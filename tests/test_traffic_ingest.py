"""Minute TrafficStat rows from the collector's log chunk (MON-TRAFFIC-INGEST, §C4)."""
import json
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from core.models import NetworkZone, Project, Site, Target, TrafficStat

pytestmark = pytest.mark.django_db

M1 = datetime(2026, 8, 22, 10, 0, tzinfo=UTC)
M2 = datetime(2026, 8, 22, 10, 1, tzinfo=UTC)


def _line(status, *, host, size=100, ip="203.0.113.7", at=M1, second=5):
    return json.dumps({
        "ts": at.timestamp() + second,
        "status": status,
        "size": size,
        "request": {"host": host, "remote_ip": ip, "uri": "/x"},
    })


def _world(slug, domains=("alpha.example.com",)):
    from dns_fixtures import default_dns_zone

    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    zone = NetworkZone.objects.create(name="lan", slug=f"lan-{slug}")
    target = Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref=f"vault-{slug}",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )
    sites = [
        Site.objects.create(
            project=project, name=f"{slug}-{i}", domain=domain,
            primary_target=target, dns_zone=default_dns_zone(),
        )
        for i, domain in enumerate(domains)
    ]
    return target, sites


def _payload(target, lines, *, ts="2026-08-22T10:01:30Z", offset=4096, metrics=None):
    return {
        "schema_version": 1,
        "target_id": target.pk,
        "ts": ts,
        "metrics": metrics or {},
        "containers": [],
        "log_chunk": {
            "file": "/var/log/caddy/access.log",
            "inode": 777,
            "offset": offset,
            "bytes": "\n".join(lines) + "\n" if lines else "",
        },
        "clock": ts,
        "healthz": {"live": True, "ready": True, "checks": {}},
    }


@pytest.mark.req("MON-TRAFFIC-INGEST")
def test_minute_rows_aggregate_status_counts():
    """Lines land as per-site minute rows: requests, bytes, counts by status.

    What would make this fail: one row per line, collapsing minutes together,
    or mixing two sites' traffic into one row.
    """
    from monitor.traffic import ingest

    target, (alpha, beta) = _world(
        "agg", domains=("alpha.example.com", "beta.example.com"))
    lines = [
        _line(200, host="alpha.example.com", size=100, second=1),
        _line(200, host="alpha.example.com", size=100, second=2),
        _line(200, host="alpha.example.com", size=100, second=3),
        _line(404, host="alpha.example.com", size=50, second=4),
        _line(200, host="beta.example.com", size=70, second=5),
        _line(200, host="beta.example.com", size=70, second=6),
        _line(500, host="alpha.example.com", size=10, at=M2, second=1),
    ]
    result = ingest(target, _payload(target, lines))
    assert result["ok"] is True

    a1 = TrafficStat.objects.get(site=alpha, bucket_start=M1)
    assert a1.granularity == TrafficStat.Granularity.MINUTE
    assert a1.requests == 4
    assert a1.bytes == 350
    assert a1.status_counts == {"200": 3, "404": 1}
    assert a1.sampled is False

    b1 = TrafficStat.objects.get(site=beta, bucket_start=M1)
    assert b1.requests == 2
    assert b1.bytes == 140
    assert b1.status_counts == {"200": 2}

    a2 = TrafficStat.objects.get(site=alpha, bucket_start=M2)
    assert a2.requests == 1
    assert a2.status_counts == {"500": 1}


@pytest.mark.req("MON-TRAFFIC-INGEST")
def test_malformed_log_line_is_counted_not_fatal():
    """Garbage lines are a counter, never an exception; valid lines still land.

    What would make this fail: json.loads raising out of ingest, or malformed
    lines silently vanishing with no accounting.
    """
    from monitor.traffic import ingest

    target, (site,) = _world("mal", domains=("alpha.example.com",))
    lines = [
        "this is not json",
        _line(200, host="alpha.example.com"),
        "[1, 2, 3]",  # json, but not a log record
    ]
    result = ingest(target, _payload(target, lines))
    assert result["ok"] is True
    assert result["malformed"] == 2

    row = TrafficStat.objects.get(site=site)
    assert row.requests == 1
    assert row.status_counts == {"200": 1}


@pytest.mark.req("MON-TRAFFIC-INGEST")
def test_ingest_publishes_to_the_site_traffic_topic(monkeypatch):
    """Ingest publishes site.{id}.traffic (+ host.{id}.metrics); both authorize.

    What would make this fail: rows landing with no event so the dashboard
    polls blind, raw log content riding the event, or the topic table refusing
    the new prefixes.
    """
    import monitor.traffic as traffic_mod
    from monitor.traffic import ingest
    from realtime.authorize import authorize_topic

    target, (site,) = _world("pub", domains=("alpha.example.com",))
    published = []
    monkeypatch.setattr(
        traffic_mod, "publish", lambda topic, event, **kw: published.append((topic, event)))

    lines = [_line(200, host="alpha.example.com"), _line(404, host="alpha.example.com")]
    ingest(target, _payload(target, lines, metrics={"load1": 0.7, "mem_pct": 41.0}))

    topics = [t for t, _e in published]
    assert f"site.{site.pk}.traffic" in topics
    assert f"host.{target.pk}.metrics" in topics

    traffic_event = next(e for t, e in published if t == f"site.{site.pk}.traffic")
    assert traffic_event["requests"] == 2
    assert traffic_event["status_counts"] == {"200": 1, "404": 1}
    blob = json.dumps(published)
    assert "/x" not in blob and "203.0.113.7" not in blob  # aggregates only

    user = SimpleNamespace(is_authenticated=True)
    assert authorize_topic(user, f"site.{site.pk}.traffic")
    assert authorize_topic(user, f"host.{target.pk}.metrics")
    assert not authorize_topic(SimpleNamespace(is_authenticated=False),
                               f"host.{target.pk}.metrics")


@pytest.mark.req("MON-TRAFFIC-INGEST")
def test_ready_wires_core_events_through_realtime_publish(monkeypatch):
    """RealtimeConfig.ready() routes core.events through realtime.publish, live.

    What would make this fail: a second module-level publisher slot the
    registration misses, a ready() that stops registering, or a port that
    silently no-ops when unwired instead of failing loud (boot-order bug).
    """
    from django.apps import apps as django_apps

    import core.events as events
    import realtime.publish as rt

    monkeypatch.setattr(events, "_stream", None)
    with pytest.raises(RuntimeError, match="not wired"):
        events.publish("demo.wiring.log", {"n": 0})
    with pytest.raises(RuntimeError, match="not wired"):
        events.current_seq("demo.wiring.log")

    django_apps.get_app_config("realtime").ready()
    assert events._stream == (rt.publish, rt.current_seq)  # the real seam, unpatched

    before = rt.current_seq("demo.wiring.log")
    seq = events.publish("demo.wiring.log", {"n": 1})
    assert seq == before + 1
    assert events.current_seq("demo.wiring.log") == seq == rt.current_seq("demo.wiring.log")

    # ONE slot serves both consumers: findings_seq reads through the same port.
    from core.findings import FINDINGS_TOPIC, findings_seq

    assert findings_seq() == rt.current_seq(FINDINGS_TOPIC)
