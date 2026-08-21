"""Staleness is P2 at most and never a reconciler restart (ALERT-N3)."""
import pytest
from pipeline_fakes import PipelineTransport

from core.models import AuditEvent, NetworkZone, Project, Site, SiteInstance, Target

pytestmark = pytest.mark.django_db


def _world(slug):
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
    site = Site.objects.create(
        project=project, name=slug, primary_target=target, reconcile_enabled=True,
    )
    inst = SiteInstance.objects.create(
        site=site,
        target=target,
        desired_image_tag="app:recon",
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.ABSENT,
        internal_port=20000,
    )
    return site, inst, PipelineTransport()


def _mutating(transport):
    return [c for c in transport.calls if c[0] in ("run", "put")]


def _restart_runs(transport):
    found = []
    for kind, argv in _mutating(transport):
        if kind != "run" or not argv or argv[0] != "docker":
            continue
        if argv[1] in {"restart", "stop", "kill"}:
            found.append(argv)
    return found


def _bring_up(site, transport):
    from reconcile.loop import tick

    tick(site, transport=transport, jitter=0)
    transport.calls.clear()


@pytest.mark.req("ALERT-N3-STALENESS-NEVER-RESTARTS")
def test_data_stale_does_not_restart():
    """Feed data-staleness audits P2 and must not docker restart/stop.

    What would make this fail: treating data_stale as unhealthy liveness, or
    skipping the P2 audit.
    """
    from reconcile.loop import tick

    site, inst, transport = _world("stale")
    _bring_up(site, transport)

    tick(
        site,
        transport=transport,
        observe=lambda _i: {"state": "running", "reason": "data_stale"},
        jitter=0,
    )
    assert _restart_runs(transport) == []
    assert _mutating(transport) == []
    event = AuditEvent.objects.get(action="reconcile_data_stale")
    assert event.detail.get("priority") == "P2"
    inst.refresh_from_db()
    assert inst.observed_state == SiteInstance.ObservedState.RUNNING


@pytest.mark.req("ALERT-N3-STALENESS-NEVER-RESTARTS")
def test_upstream_down_never_restarts():
    """upstream-down is never a restart, even when desired is running.

    What would make this fail: docker restart because the feed reported down.
    """
    from reconcile.loop import tick

    site, _inst, transport = _world("upstream")
    _bring_up(site, transport)

    tick(
        site,
        transport=transport,
        observe=lambda _i: {"state": "running", "reason": "upstream-down"},
        jitter=0,
    )
    assert _restart_runs(transport) == []
    assert _mutating(transport) == []


@pytest.mark.req("ALERT-N3-STALENESS-NEVER-RESTARTS")
def test_unhealthy_live_restarts_once():
    """Live process failing checks restarts once, then backs off.

    What would make this fail: crashloop restart every tick, or skipping the first
    restart; warming must not share this path.
    """
    from reconcile.loop import tick

    site, inst, transport = _world("unhealthy")
    _bring_up(site, transport)

    def observe_unhealthy(_i):
        return {"state": "unhealthy", "reason": "checks_failing"}

    tick(site, transport=transport, observe=observe_unhealthy, jitter=0)
    assert len(_restart_runs(transport)) == 1
    tick(site, transport=transport, observe=observe_unhealthy, jitter=0)
    assert len(_restart_runs(transport)) == 1

    transport.calls.clear()
    tick(
        site,
        transport=transport,
        observe=lambda _i: {"state": "warming", "reason": "warmup"},
        jitter=0,
    )
    assert _restart_runs(transport) == []
    assert _mutating(transport) == []
    inst.refresh_from_db()
    assert inst.observed_state == SiteInstance.ObservedState.WARMING
