"""Collector persist of HostMetric (C3 / D-094).

Schema tests live in test_host_metric.py. These pin Hub-clock insert, mapping,
coercion, skip-when-missing, and persist isolation. Unmarked (C11).
"""
import json
from datetime import UTC, datetime

import pytest

from core.transport import CommandResult, FakeTransport

pytestmark = pytest.mark.django_db


def _target(slug="hm-persist"):
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(name=slug, slug=slug)
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host=f"{slug}.example",
        ssh_user="deploy",
        ssh_key_ref="vault-owner-1",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )

HUB_NOW = datetime(2026, 8, 24, 12, 0, tzinfo=UTC)
PAYLOAD_TS = "1999-01-01T00:00:00+00:00"
_MISSING = object()


def _payload(target, metrics=_MISSING, *, ts=PAYLOAD_TS):
    body = {
        "schema_version": 1,
        "target_id": getattr(target, "pk", None),
        "ts": ts,
        "containers": [],
        "log_chunk": {
            "file": "/var/log/caddy/access.log",
            "inode": 1,
            "offset": 0,
            "bytes": "RAW-LOG-SHOULD-NOT-AUDIT",
        },
        "clock": ts,
        "healthz": {"live": True, "ready": True, "checks": {}},
        "networks": [],
    }
    if metrics is not _MISSING:
        body["metrics"] = metrics
    return body


def _ok_metrics(**overrides):
    metrics = {
        "load1": 2.25,
        "mem_pct": 90.5,
        "disk_pct": 41.0,
        "cores": 4,
        "cpu": 99.0,
    }
    metrics.update(overrides)
    return metrics


class _StdoutTransport(FakeTransport):
    def __init__(self, stdout):
        super().__init__()
        self._stdout = stdout

    def probe(self, argv, *, timeout=60):
        self.calls.append(("probe", list(argv)))
        return CommandResult(argv, stdout=self._stdout)


def test_persist_collect_writes_host_metric_from_payload_metrics():
    """_persist_collect maps mem_pct/disk_pct/load1/cores; ts is the Hub now kwarg.

    What would make this fail: leaving HostMetric empty after a collect save,
    copying payload["ts"] onto the row, mapping cpu from the payload, or
    inventing ram/disk/load/cores from the wrong keys.
    """
    from core.models import HostMetric
    from monitor.collector import _persist_collect

    target = _target("hm-write")
    _persist_collect(target, _payload(target, _ok_metrics()), now=HUB_NOW)
    target.refresh_from_db()
    assert target.collect_payload is not None

    row = HostMetric.objects.get(target=target)
    assert row.ts == HUB_NOW
    assert row.ts.isoformat() != PAYLOAD_TS
    assert row.cpu is None
    assert row.ram == 90.5
    assert row.disk == 41.0
    assert row.load == 2.25
    assert row.cores == 4


def test_persist_skips_when_metrics_missing():
    """No metrics object (or a non-dict) must not insert a row of invented zeros.

    What would make this fail: defaulting ram/disk/load/cores to 0 when metrics
    is absent, a list, or a string, so a hole looks like a cold sample.
    """
    from core.models import HostMetric
    from monitor.collector import _persist_collect
    from monitor.host_metrics import persist_sample

    target = _target("hm-skip")
    persist_sample(target, _payload(target), now=HUB_NOW)
    persist_sample(target, _payload(target, metrics=["not", "a", "dict"]), now=HUB_NOW)
    persist_sample(target, _payload(target, metrics="hot"), now=HUB_NOW)
    persist_sample(target, _payload(target, metrics=None), now=HUB_NOW)
    _persist_collect(target, _payload(target), now=HUB_NOW)

    assert HostMetric.objects.filter(target=target).count() == 0
    assert not HostMetric.objects.filter(ram=0, disk=0, load=0).exists()


def test_persist_coerces_non_finite_and_out_of_range_to_none():
    """Bad mem_pct/disk_pct/load1/cores store None on that axis and do not raise.

    What would make this fail: mem_pct='hot' / inf / 101 raising, writing 0, or
    skipping the whole row so a partial sample punches a hole in the streak.
    """
    from core.models import HostMetric
    from monitor.host_metrics import persist_sample

    target = _target("hm-coerce")

    persist_sample(
        target,
        _payload(target, _ok_metrics(mem_pct="hot")),
        now=HUB_NOW,
    )
    hot = HostMetric.objects.get()
    assert hot.ram is None
    assert hot.disk == 41.0
    assert hot.load == 2.25
    assert hot.cores == 4
    assert hot.cpu is None

    HostMetric.objects.all().delete()
    persist_sample(
        target,
        _payload(
            target,
            _ok_metrics(
                mem_pct=float("inf"),
                disk_pct=float("nan"),
                load1=float("-inf"),
            ),
        ),
        now=HUB_NOW,
    )
    inf = HostMetric.objects.get()
    assert inf.ram is None
    assert inf.disk is None
    assert inf.load is None
    assert inf.cores == 4

    HostMetric.objects.all().delete()
    persist_sample(
        target,
        _payload(target, _ok_metrics(mem_pct=101, disk_pct=-1, cores="4")),
        now=HUB_NOW,
    )
    oob = HostMetric.objects.get()
    assert oob.ram is None
    assert oob.disk is None
    assert oob.load == 2.25
    assert oob.cores is None


def test_persist_failure_does_not_fail_collect(monkeypatch):
    """persist_sample raising must not fail collect; collect_payload still saves.

    What would make this fail: letting the insert raise out of collect() so
    traffic ingest never runs, rolling back collect_payload, or stuffing the
    raw payload into AuditEvent.detail instead of the error type.
    """
    from core.models import AuditEvent, HostMetric
    from monitor.collector import _persist_collect, collect
    from monitor.host_metrics import persist_sample

    def boom(*args, **kwargs):
        raise RuntimeError("db down")

    monkeypatch.setattr("monitor.host_metrics.persist_sample", boom)
    assert persist_sample is not boom

    target = _target("hm-iso")
    payload = _payload(target, _ok_metrics())
    _persist_collect(target, payload, now=HUB_NOW)
    target.refresh_from_db()
    assert target.collect_payload is not None
    assert "RAW-LOG-SHOULD-NOT-AUDIT" not in json.dumps(target.collect_payload)
    assert HostMetric.objects.count() == 0

    events = list(AuditEvent.objects.all())
    assert events
    for event in events:
        assert event.detail.get("error") == "RuntimeError"
        dumped = json.dumps(event.detail)
        assert "db down" not in dumped
        assert "RAW-LOG-SHOULD-NOT-AUDIT" not in dumped
        assert "mem_pct" not in dumped
        assert "90.5" not in dumped
        assert payload["ts"] not in dumped

    stdout = json.dumps(_payload(target, _ok_metrics(mem_pct=66.6)))
    returned = collect(
        target, _StdoutTransport(stdout), now=HUB_NOW, sleep=lambda _s: None,
    )
    assert returned["metrics"]["mem_pct"] == 66.6
    target.refresh_from_db()
    assert target.collect_payload is not None
    assert target.collect_payload["metrics"]["mem_pct"] == 66.6
    assert HostMetric.objects.count() == 0


def test_collect_once_metrics_includes_cores():
    """On-target _metrics reports cores from os.cpu_count().

    What would make this fail: omitting cores so load>cores cannot be evaluated,
    or inventing a constant that is not the host's cpu_count.
    """
    import os

    from monitor.collect_once import _metrics

    metrics = _metrics()
    assert "cores" in metrics
    assert metrics["cores"] == os.cpu_count()
