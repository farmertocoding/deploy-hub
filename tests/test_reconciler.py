"""Reconciler converges desired vs observed; C2 brakes refuse to fight the operator."""
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone
from pipeline_fakes import PipelineTransport

from core.models import AuditEvent, NetworkZone, Project, Site, SiteInstance, Target
from core.transport import CommandResult, RecordingTransport

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
    if hasattr(transport, "mutating_calls"):
        return transport.mutating_calls()
    return [c for c in transport.calls if c[0] in ("run", "put")]


def _start_stop_runs(transport):
    found = []
    for kind, argv in _mutating(transport):
        if kind != "run" or not argv or argv[0] != "docker":
            continue
        if argv[1] in {"run", "start", "stop", "restart"}:
            found.append(argv)
    return found


class FailStartTransport(PipelineTransport):
    """docker run/start fail so three convergences trip backoff."""

    def run(self, argv, *, timeout=60):
        argv = list(argv)
        if argv[:2] in (["docker", "run"], ["docker", "start"]):
            self.calls.append(("run", argv))
            return CommandResult(argv, exit_code=1, stderr="cannot start")
        return super().run(argv, timeout=timeout)


@pytest.mark.req("REL-P1-RECONCILER")
def test_drift_container_converged():
    """desired running + observed absent → ensure_start, then observed running.

    What would make this fail: skipping ensure_start, using transport.run for inspect,
    or leaving observed_state absent after a successful docker run.
    """
    from reconcile.loop import tick
    from reconcile.tasks import tick_all

    site, inst, transport = _world("drift")
    tick(site, transport=transport, jitter=0)

    inst.refresh_from_db()
    assert inst.observed_state == SiteInstance.ObservedState.RUNNING
    runs = _start_stop_runs(transport)
    assert any(argv[1] in {"run", "start"} for argv in runs)
    beat = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert tick_all.name in beat
    schedule = next(
        entry["schedule"]
        for entry in settings.CELERY_BEAT_SCHEDULE.values()
        if entry["task"] == tick_all.name
    )
    assert 60 <= float(schedule) <= 120
    assert settings.CELERY_TASK_ROUTES["reconcile.*"]["queue"] == "probes"


@pytest.mark.req("REL-P1-RECONCILER")
def test_noop_on_converged_zero_mutating_calls():
    """Already matching desired/observed records zero run/put on the second tick.

    What would make this fail: calling docker run every tick, or treating probe as mutate.
    """
    from reconcile.loop import tick

    site, inst, transport = _world("noop")
    tick(site, transport=transport, jitter=0)
    inst.refresh_from_db()
    assert inst.observed_state == SiteInstance.ObservedState.RUNNING
    transport.calls.clear()
    tick(site, transport=transport, jitter=0)
    assert _mutating(transport) == []


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_maintenance_until_does_not_mutate():
    """maintenance_until in the future still observes, and never docker run/put.

    What would make this fail: acting during the window, or skipping the observe probe.
    """
    from reconcile.loop import tick

    now = timezone.now()
    site, inst, transport = _world("maint")
    site.maintenance_until = now + timedelta(hours=1)
    site.save(update_fields=["maintenance_until"])
    tick(site, transport=transport, now=now, jitter=0)
    assert _mutating(transport) == []
    assert any(kind == "probe" for kind, _payload in transport.calls)
    inst.refresh_from_db()
    assert inst.observed_state == SiteInstance.ObservedState.ABSENT


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_backoff_after_three_failures():
    """Three failed convergences: one AuditEvent, then no mutate until rearm.

    What would make this fail: looping docker run forever, alerting every tick, or
    rearm leaving consecutive_failures set.
    """
    from reconcile.loop import rearm, tick

    site, inst, transport = _world("backoff")
    transport = FailStartTransport()
    for _ in range(3):
        tick(site, transport=transport, jitter=0)
    inst.refresh_from_db()
    assert inst.consecutive_failures >= 3
    alerts = AuditEvent.objects.filter(action="reconcile_backoff")
    assert alerts.count() == 1
    after_three = list(_mutating(transport))
    tick(site, transport=transport, jitter=0)
    assert _mutating(transport) == after_three
    rearm(inst)
    inst.refresh_from_db()
    assert inst.consecutive_failures == 0
    tick(site, transport=transport, jitter=0)
    assert len(_mutating(transport)) > len(after_three)


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_flap_pauses():
    """Three start/stop cycles in the flap window pause further mutations and audit.

    What would make this fail: chasing an oscillating desired_state forever, or
    pausing without an AuditEvent.
    """
    from reconcile.loop import tick

    now = timezone.now()
    site, inst, transport = _world("flap")
    for _ in range(3):
        inst.desired_state = SiteInstance.DesiredState.RUNNING
        inst.save(update_fields=["desired_state"])
        tick(site, transport=transport, now=now, jitter=0)
        inst.desired_state = SiteInstance.DesiredState.STOPPED
        inst.save(update_fields=["desired_state"])
        tick(site, transport=transport, now=now, jitter=0)
    assert AuditEvent.objects.filter(action="reconcile_flap_pause").exists()
    paused_at = list(_mutating(transport))
    inst.desired_state = SiteInstance.DesiredState.RUNNING
    inst.save(update_fields=["desired_state"])
    tick(site, transport=transport, now=now, jitter=0)
    assert _mutating(transport) == paused_at


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_kill_switch_stops_mutations():
    """reconcile_enabled=False observes no docker run and audits once across ticks.

    What would make this fail: ignoring the flag, or writing a new AuditEvent every tick.
    """
    from reconcile.loop import tick

    site, _inst, transport = _world("kill")
    site.reconcile_enabled = False
    site.save(update_fields=["reconcile_enabled"])
    tick(site, transport=transport, jitter=0)
    tick(site, transport=transport, jitter=0)
    assert _mutating(transport) == []
    assert AuditEvent.objects.filter(action="reconcile_disabled").count() == 1


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_reprobe_before_mutate():
    """Last resource probe is after the lock re-check and before the repairing run.

    What would make this fail: acting on the first observation, or running before
    the re-probe / lock re-check. Call log order is the proof.
    """
    from reconcile.loop import tick

    site, _inst, inner = _world("reprobe")
    transport = RecordingTransport(inner)
    tick(site, transport=transport, jitter=0)
    kinds = [kind for kind, _payload in transport.calls]
    run_idx = next(
        i for i, (kind, argv) in enumerate(transport.calls)
        if kind == "run" and argv and argv[0] == "docker"
        and argv[1] in {"run", "start"}
    )
    probe_idx = max(
        i for i, (kind, argv) in enumerate(transport.calls[:run_idx])
        if kind == "probe" and argv and argv[0] == "docker"
    )
    lock_idx = max(i for i, kind in enumerate(kinds[:probe_idx + 1]) if kind == "lock")
    assert lock_idx < probe_idx < run_idx
