"""MON-UPTIME-EVENTS: transitions, not samples — and no second SSH session (§C3).

The probe cycle reaches every site over HTTP through an injectable seam (the
poller's ls_remote pattern): public sites by domain, mesh_only sites
Hub→tailnet against the target host. It never constructs a Transport, so the
one-collector-session-per-minute budget (REL-C3) survives Task 8.
"""
import pytest

from core.models import UptimeEvent

pytestmark = pytest.mark.django_db


class RecordingGet:
    """Injectable HTTP seam: returns a status per URL, records every call."""

    def __init__(self, status=200, per_url=None):
        self.status = status
        self.per_url = per_url or {}
        self.calls = []

    def __call__(self, url, *, host=None, timeout=None):
        self.calls.append({"url": url, "host": host, "timeout": timeout})
        outcome = self.per_url.get(url, self.status)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def _count_transport_constructions(monkeypatch):
    """Patch SshTransport.__init__ to count sessions the cycle opens (must be 0)."""
    import core.ssh

    counter = {"n": 0}
    original = core.ssh.SshTransport.__init__

    def counting_init(self, *args, **kwargs):
        counter["n"] += 1
        return original(self, *args, **kwargs)

    monkeypatch.setattr(core.ssh.SshTransport, "__init__", counting_init)
    return counter


def test_transition_writes_one_event_not_one_per_probe():
    from uptime_fixtures import make_site

    from monitor.uptime import probe_cycle

    site = make_site("blog")
    get = RecordingGet(status=200)
    for _ in range(3):
        cycle = probe_cycle(http_get=get)
        assert cycle["completed"] is True
    entity = f"site:{site.name}"
    assert UptimeEvent.objects.filter(entity=entity).count() == 1
    assert UptimeEvent.objects.get(entity=entity).state == "up"

    # The state flip writes exactly one more event, again independent of
    # how many probes observe it.
    get.status = 503
    for _ in range(3):
        probe_cycle(http_get=get)
    events = list(UptimeEvent.objects.filter(entity=entity).order_by("at", "pk"))
    assert [event.state for event in events] == ["up", "down"]


def test_mesh_only_site_is_probed_over_http_not_a_new_ssh_session(monkeypatch):
    from uptime_fixtures import make_site

    from monitor.uptime import probe_cycle

    site = make_site("scan", exposure="mesh_only", host="scan.tailnet.example")
    sessions = _count_transport_constructions(monkeypatch)
    get = RecordingGet(status=200)

    cycle = probe_cycle(http_get=get)

    assert cycle["completed"] is True
    assert sessions["n"] == 0, "the probe cycle opened an SSH session (§C3)"
    assert len(get.calls) == 1
    assert get.calls[0]["url"] == f"http://scan.tailnet.example{site.liveness_path}"
    assert get.calls[0]["timeout"] is not None, "probe timeout must be bounded"


def test_ws_site_card_metric_is_last_tick_age_and_connections():
    from uptime_fixtures import make_site

    from monitor.uptime import probe_cycle, ws_card_metric

    payload = {
        "healthz": {
            "live": True,
            "ready": True,
            "checks": {
                "site-scanner-7": {
                    "live": True,
                    "ready": True,
                    "checks": {"last_tick_age_s": 4, "connections": 12},
                },
            },
        },
    }
    site = make_site("scanner", exposure="mesh_only", ws_payload=payload)
    cycle = probe_cycle(http_get=RecordingGet(status=200))
    row = next(r for r in cycle["results"] if r["entity"] == f"site:{site.name}")
    assert row["ws_metric"] == {"last_tick_age_s": 4, "connections": 12}

    # The rendering rule (§O3) is a function of the /healthz payload the
    # collector already fetched — no tick data means no ws card metric.
    assert ws_card_metric({"live": True, "ready": True, "checks": {}}) is None


def test_overlapping_cycle_is_a_recorded_skip():
    from uptime_fixtures import make_site

    from core import locks
    from core.models import AuditEvent
    from monitor.deadman import ping_after_cycle
    from monitor.uptime import CYCLE_LOCK, probe_cycle

    make_site("blog3")
    # Another worker holds the cycle guard (a slow fleet still probing).
    assert locks.acquire(*CYCLE_LOCK, "another-worker") is not None
    get = RecordingGet(status=200)

    cycle = probe_cycle(http_get=get)

    # Skip-and-record, never a stacked concurrent run.
    assert cycle["skipped"] is True
    assert cycle["completed"] is False
    assert get.calls == []
    assert AuditEvent.objects.filter(action="uptime-cycle-skipped").exists()

    # And a skipped cycle proved nothing, so it must not dead-man ping.
    post_calls = []
    outcome = ping_after_cycle(
        cycle, http_post=lambda url, *, timeout=None: post_calls.append(url) or 200,
    )
    assert outcome["pinged"] is False
    assert post_calls == []

    # Once the holder releases, the next cycle runs normally.
    locks.release(*CYCLE_LOCK, holder="another-worker")
    cycle = probe_cycle(http_get=get)
    assert cycle["completed"] is True and cycle["n"] == 1


def test_probe_cycle_records_zero_mutating_transport_calls(monkeypatch):
    from uptime_fixtures import make_site

    from monitor.uptime import probe_cycle

    make_site("blog2")
    make_site("scan2", exposure="mesh_only")
    sessions = _count_transport_constructions(monkeypatch)

    cycle = probe_cycle(http_get=RecordingGet(status=200))

    assert cycle["completed"] is True and cycle["n"] == 2
    assert sessions["n"] == 0

    # Belt and braces: the module never touches a Transport at all — no
    # import of core.ssh, no put()/run() call sites.
    import inspect

    import monitor.uptime as module

    source = inspect.getsource(module)
    assert "core.ssh" not in source
    assert "transport" not in source.lower()
