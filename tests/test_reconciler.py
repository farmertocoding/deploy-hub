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
    from dns_fixtures import default_dns_zone

    site = Site.objects.create(
        project=project, name=slug, primary_target=target, reconcile_enabled=True,
        dns_zone=default_dns_zone(),
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
    for _ in range(2):
        tick(site, transport=transport, jitter=0)
    inst.refresh_from_db()
    assert inst.consecutive_failures >= 3
    assert AuditEvent.objects.filter(action="reconcile_backoff").count() == 2


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


def _oscillate(site, inst, transport, now, cycles):
    from reconcile.loop import tick

    for _ in range(cycles):
        inst.desired_state = SiteInstance.DesiredState.RUNNING
        inst.save(update_fields=["desired_state"])
        tick(site, transport=transport, now=now, jitter=0)
        inst.desired_state = SiteInstance.DesiredState.STOPPED
        inst.save(update_fields=["desired_state"])
        tick(site, transport=transport, now=now, jitter=0)


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_flap_pauses_again_after_rearm():
    """rearm must not permanently disable flap: three new cycles pause and audit again.

    What would make this fail: _audit_once refusing a second flap_pause, or
    _flap_paused staying false because pause.ts < rearm.ts with no new row.
    """
    from reconcile.loop import rearm, tick

    now = timezone.now()
    site, inst, transport = _world("flap-rearm")
    _oscillate(site, inst, transport, now, 3)
    assert AuditEvent.objects.filter(action="reconcile_flap_pause").count() == 1
    rearm(inst)
    inst.desired_state = SiteInstance.DesiredState.RUNNING
    inst.save(update_fields=["desired_state"])
    after_rearm = list(_mutating(transport))
    tick(site, transport=transport, now=now, jitter=0)
    assert len(_mutating(transport)) > len(after_rearm)
    _oscillate(site, inst, transport, now, 2)
    assert AuditEvent.objects.filter(action="reconcile_flap_pause").count() == 1
    _oscillate(site, inst, transport, now, 1)
    assert AuditEvent.objects.filter(action="reconcile_flap_pause").count() == 2
    paused_at = list(_mutating(transport))
    inst.desired_state = SiteInstance.DesiredState.RUNNING
    inst.save(update_fields=["desired_state"])
    tick(site, transport=transport, now=now, jitter=0)
    assert _mutating(transport) == paused_at


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_reprobe_skips_when_locked_observe_converged():
    """First observe unhealthy, locked re-observe running → no docker restart.

    What would make this fail: applying the original action after the re-probe
    discarded the new observation.
    """
    from reconcile.loop import tick

    site, inst, transport = _world("reprobe-skip")
    inst.desired_state = SiteInstance.DesiredState.RUNNING
    inst.observed_state = SiteInstance.ObservedState.RUNNING
    inst.save(update_fields=["desired_state", "observed_state"])
    seen = []

    def observe(_i):
        if not seen:
            seen.append("unhealthy")
            return {"state": "unhealthy", "reason": "checks_failing"}
        seen.append("running")
        return {"state": "running", "reason": ""}

    tick(site, transport=transport, observe=observe, jitter=0)
    assert [argv[1] for argv in _start_stop_runs(transport)] == []
    assert seen == ["unhealthy", "running"]
    inst.refresh_from_db()
    assert inst.observed_state == SiteInstance.ObservedState.RUNNING


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_desired_stop_unhealthy_still_stops():
    """desired stopped + observed unhealthy must docker stop, not skip or restart.

    What would make this fail: the unhealthy branch returning None before stop.
    """
    from reconcile.loop import tick

    site, inst, transport = _world("stop-unhealthy")
    tick(site, transport=transport, jitter=0)
    transport.calls.clear()
    inst.desired_state = SiteInstance.DesiredState.STOPPED
    inst.save(update_fields=["desired_state"])
    tick(
        site,
        transport=transport,
        observe=lambda _i: {"state": "unhealthy", "reason": "checks_failing"},
        jitter=0,
    )
    stops = [argv for argv in _start_stop_runs(transport) if argv[1] == "stop"]
    restarts = [argv for argv in _start_stop_runs(transport) if argv[1] == "restart"]
    assert stops
    assert restarts == []
    inst.refresh_from_db()
    assert inst.observed_state == SiteInstance.ObservedState.STOPPED


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_failed_docker_stop_does_not_mark_stopped():
    """A failed docker stop must not persist observed_state=stopped.

    What would make this fail: treating any transport.run as success.
    """
    from reconcile.loop import tick

    class FailStopTransport(PipelineTransport):
        def run(self, argv, *, timeout=60):
            argv = list(argv)
            if argv[:2] == ["docker", "stop"]:
                self.calls.append(("run", argv))
                return CommandResult(argv, exit_code=1, stderr="cannot stop")
            return super().run(argv, timeout=timeout)

    site, inst, _unused = _world("fail-stop")
    transport = FailStopTransport()
    tick(site, transport=transport, jitter=0)
    inst.refresh_from_db()
    assert inst.observed_state == SiteInstance.ObservedState.RUNNING
    inst.desired_state = SiteInstance.DesiredState.STOPPED
    inst.save(update_fields=["desired_state"])
    tick(site, transport=transport, jitter=0)
    inst.refresh_from_db()
    assert inst.observed_state != SiteInstance.ObservedState.STOPPED
    assert any(
        kind == "run" and argv[:2] == ["docker", "stop"]
        for kind, argv in _mutating(transport)
    )


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_tick_all_global_budget_uses_instance_target():
    """A global budget leaves remaining instances for the next Beat; transport is per instance.

    What would make this fail: iterating only primary_target, or mutating the
    whole fleet in one tick_all.
    """
    from reconcile.tasks import tick_all

    _site_a, inst_a, t_a = _world("gb-a")
    _site_b, inst_b, t_b = _world("gb-b")
    _site_a.primary_target = None
    _site_a.save(update_fields=["primary_target"])
    transports = {inst_a.target_id: t_a, inst_b.target_id: t_b}

    tick_all.run(budget=1, transport_for=lambda target: transports[target.pk])

    inst_a.refresh_from_db()
    inst_b.refresh_from_db()
    running = sum(
        inst.observed_state == SiteInstance.ObservedState.RUNNING
        for inst in (inst_a, inst_b)
    )
    assert running == 1


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_tick_all_fail_open_continues_fleet():
    """One instance raising must not abort the rest of the Beat pass.

    What would make this fail: an uncaught SshTransport error stopping tick_all.
    """
    from reconcile.tasks import tick_all

    _site_a, inst_a, _t_a = _world("fo-a")
    _site_b, inst_b, t_b = _world("fo-b")

    def transport_for(target):
        if target.pk == inst_a.target_id:
            raise RuntimeError("ssh fail")
        return t_b

    tick_all.run(budget=2, transport_for=transport_for)
    inst_b.refresh_from_db()
    assert inst_b.observed_state == SiteInstance.ObservedState.RUNNING


def _inspect_argvs(transport):
    found = []
    for kind, argv in transport.calls:
        if kind != "probe" or not argv:
            continue
        if argv[:2] == ["docker", "inspect"]:
            found.append(argv)
    return found


@pytest.mark.req("REL-P1-RECONCILER")
def test_tick_uses_fresh_collector_json_not_inspect():
    """One target, two instances: a fresh collect payload drives unhealthy/warming
    and the following tick must not docker inspect.

    What would make this fail: production _probe_container_state always
    inspecting Running, or opening a second inspect SSH the same minute while
    the collector JSON is ≤60s old.
    """
    import json

    from django.utils import timezone
    from test_collector import CollectorTransport, _noop

    from monitor.collector import collect
    from reconcile.loop import tick

    project = Project.objects.create(name="fleet", slug="p-fleet")
    zone = NetworkZone.objects.create(name="lan", slug="lan-fleet")
    target = Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref="vault-fleet",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )
    from dns_fixtures import default_dns_zone

    site_warm = Site.objects.create(
        project=project, name="warm", primary_target=target, reconcile_enabled=True,
        dns_zone=default_dns_zone(),
    )
    site_sick = Site.objects.create(
        project=project, name="sick", primary_target=target, reconcile_enabled=True,
        dns_zone=default_dns_zone(),
    )
    inst_warm = SiteInstance.objects.create(
        site=site_warm,
        target=target,
        desired_image_tag="app:recon",
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.ABSENT,
        internal_port=20000,
    )
    inst_sick = SiteInstance.objects.create(
        site=site_sick,
        target=target,
        desired_image_tag="app:recon",
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.ABSENT,
        consecutive_failures=1,
        internal_port=20001,
    )
    warm_name = f"site-warm-{inst_warm.pk}"
    sick_name = f"site-sick-{inst_sick.pk}"
    payload = {
        "schema_version": 1,
        "target_id": target.pk,
        "ts": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "metrics": {"load1": 0.1, "mem_pct": 1.0, "disk_pct": 1.0},
        "containers": [
            {"name": warm_name, "state": "running"},
            {"name": sick_name, "state": "running"},
        ],
        "log_chunk": {
            "file": "/var/log/caddy/access.log",
            "inode": 1,
            "offset": 10,
            "bytes": "",
        },
        "clock": timezone.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "healthz": {
            "live": True,
            "ready": True,
            "checks": {
                warm_name: {"live": True, "ready": False, "checks": {}},
                sick_name: {"live": False, "ready": False, "checks": {}},
            },
        },
    }
    transport = CollectorTransport(stdout=json.dumps(payload))
    collect(target, transport, sleep=_noop)
    transport.calls.clear()

    tick(site_warm, transport=transport, jitter=0)
    tick(site_sick, transport=transport, jitter=0)
    inst_warm.refresh_from_db()
    inst_sick.refresh_from_db()
    assert inst_warm.observed_state == SiteInstance.ObservedState.WARMING
    assert inst_sick.observed_state == SiteInstance.ObservedState.UNHEALTHY
    assert _inspect_argvs(transport) == []
    assert _mutating(transport) == []


@pytest.mark.req("REL-C2-RECONCILER-BRAKES")
def test_global_kill_switch_stops_mutations():
    """HUB_RECONCILE_ENABLED=False is a fleet brake even when sites stay enabled.

    What would make this fail: checking only per-site reconcile_enabled, or
    writing a new AuditEvent every tick.
    """
    from django.test import override_settings

    from reconcile.loop import tick

    site, _inst, transport = _world("gkill")
    assert site.reconcile_enabled is True
    with override_settings(HUB_RECONCILE_ENABLED=False):
        tick(site, transport=transport, jitter=0)
        tick(site, transport=transport, jitter=0)
    assert _mutating(transport) == []
    assert AuditEvent.objects.filter(action="reconcile_globally_disabled").count() == 1
