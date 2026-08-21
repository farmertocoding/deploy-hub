"""Desired vs observed reconciler with C2 brakes and N3 staleness policy."""
from datetime import timedelta

from django.utils import timezone

from core import locks
from core.audit import audit
from core.models import AuditEvent, OperationLock, SiteInstance
from deploys.steps import ensure_start

MUTATION_BUDGET = 2
FLAP_WINDOW = timedelta(minutes=10)
FLAP_CYCLE_LIMIT = 3
BACKOFF_AFTER = 3
STALE_REASONS = frozenset({"data-stale", "feed-stale", "feed-staleness", "staleness"})
UPSTREAM_REASONS = frozenset({"upstream-down"})


def tick(site, *, transport, now=None, observe=None, jitter=0):
    """Observe one site's instances and repair drift unless a brake applies.

    ``jitter`` is accepted for Beat spreading; T1 passes 0 and it does not skip work.
    """
    del jitter  # schedule hint only — never a mutate skip (nonzero must not disable)
    now = now or timezone.now()
    used = 0
    for instance in site.instances.all():
        observed = _read_observed(instance, transport, site, observe)
        _persist_observation(instance, observed, now)
        if _braked(site, instance, observed, now):
            continue
        action = _plan(instance, observed)
        if action is None:
            _maybe_clear_failures(instance, observed)
            continue
        if used >= MUTATION_BUDGET:
            continue
        if _apply(site, instance, transport, action, now):
            used += 1
            if _cycle_count(instance, now) >= FLAP_CYCLE_LIMIT:
                _audit_once("reconcile_flap_pause", instance)
    return {"mutations": used}


def rearm(instance):
    """Manual re-arm after backoff or flap pause."""
    instance.consecutive_failures = 0
    instance.save(update_fields=["consecutive_failures"])
    audit("reconcile_rearmed", instance, source=AuditEvent.Source.RECONCILER)


def _read_observed(instance, transport, site, observe):
    if observe is not None:
        raw = observe(instance) or {}
        return {
            "state": raw.get("state") or SiteInstance.ObservedState.ABSENT,
            "reason": raw.get("reason") or "",
        }
    return {
        "state": _probe_container_state(transport, site, instance),
        "reason": "",
    }


def _persist_observation(instance, observed, now):
    state = observed["state"]
    if state not in SiteInstance.ObservedState.values:
        state = SiteInstance.ObservedState.ABSENT
    instance.observed_state = state
    instance.observed_at = now
    instance.save(update_fields=["observed_state", "observed_at"])


def _braked(site, instance, observed, now):
    if not site.reconcile_enabled:
        _audit_once("reconcile_disabled", site)
        return True
    if site.maintenance_until is not None and site.maintenance_until > now:
        return True
    reason = _reason_key(observed.get("reason"))
    if reason in STALE_REASONS:
        _audit_once("reconcile_data_stale", instance, priority="P2")
        return True
    if reason in UPSTREAM_REASONS:
        _audit_once("reconcile_upstream_down", instance, priority="P2")
        return True
    if instance.consecutive_failures >= BACKOFF_AFTER:
        _audit_once("reconcile_backoff", instance)
        return True
    if _flap_paused(instance):
        return True
    return False


def _plan(instance, observed):
    state = observed["state"]
    desired = instance.desired_state
    if state == SiteInstance.ObservedState.WARMING:
        return None
    if state == SiteInstance.ObservedState.UNHEALTHY:
        if instance.consecutive_failures >= 1:
            return None
        if desired == SiteInstance.DesiredState.RUNNING:
            return "restart"
        return None
    if desired == SiteInstance.DesiredState.RUNNING and state in {
        SiteInstance.ObservedState.ABSENT,
        SiteInstance.ObservedState.STOPPED,
    }:
        return "start"
    if desired == SiteInstance.DesiredState.STOPPED and state in {
        SiteInstance.ObservedState.RUNNING,
        SiteInstance.ObservedState.UNHEALTHY,
    }:
        return "stop"
    if desired == SiteInstance.DesiredState.ABSENT and state == SiteInstance.ObservedState.RUNNING:
        return "stop"
    return None


def _maybe_clear_failures(instance, observed):
    if (
        observed["state"] == SiteInstance.ObservedState.RUNNING
        and instance.desired_state == SiteInstance.DesiredState.RUNNING
        and instance.consecutive_failures
    ):
        instance.consecutive_failures = 0
        instance.save(update_fields=["consecutive_failures"])


def _apply(site, instance, transport, action, now):
    holder = f"reconcile:{site.pk}"
    lock = locks.acquire(
        OperationLock.Scope.SITE, site.pk, OperationLock.Kind.RECONCILE, holder,
    )
    if lock is None:
        return False
    try:
        _record(transport, "lock", ["recheck"])
        _probe_container_state(transport, site, instance)
        if not OperationLock.objects.filter(
            scope=OperationLock.Scope.SITE,
            object_id=str(site.pk),
            kind=OperationLock.Kind.RECONCILE,
            holder=holder,
        ).exists():
            return False
        desired = _desired(site, instance, transport)
        name = _container_name(desired)
        if action == "start":
            ensure_start(desired)
            instance.consecutive_failures = 0
            instance.observed_state = SiteInstance.ObservedState.RUNNING
        elif action == "stop":
            transport.run(["docker", "stop", name])
            instance.observed_state = SiteInstance.ObservedState.STOPPED
        elif action == "restart":
            transport.run(["docker", "restart", name])
            instance.consecutive_failures = instance.consecutive_failures + 1
            instance.observed_state = SiteInstance.ObservedState.UNHEALTHY
        else:
            return False
        instance.last_reconciled_at = now
        instance.save(update_fields=[
            "observed_state", "consecutive_failures", "last_reconciled_at",
        ])
        audit(
            "reconcile_repair", instance,
            source=AuditEvent.Source.RECONCILER, op=action,
        )
        return True
    except Exception:
        instance.consecutive_failures = instance.consecutive_failures + 1
        instance.save(update_fields=["consecutive_failures"])
        if instance.consecutive_failures >= BACKOFF_AFTER:
            _audit_once("reconcile_backoff", instance)
        return False
    finally:
        locks.release(
            OperationLock.Scope.SITE, site.pk, OperationLock.Kind.RECONCILE,
            holder=holder,
        )


def _desired(site, instance, transport):
    from deploys.models import Deployment

    dep = Deployment.objects.filter(manifest__site=site).order_by("-pk").first()
    body = (dep.manifest.body if dep is not None else None) or {}
    return {
        "transport": transport,
        "site": site,
        "site_slug": site.name,
        "deployment_id": dep.pk if dep is not None else instance.pk,
        "image_tag": instance.desired_image_tag or "app:recon",
        "manifest_body": body,
        "internal_port": instance.internal_port,
    }


def _container_name(desired):
    return f"site-{desired['site_slug']}-{desired['deployment_id']}"


def _probe_container_state(transport, site, instance):
    desired = _desired(site, instance, transport)
    name = _container_name(desired)
    result = transport.probe([
        "docker", "inspect", "--format", "{{.State.Running}}", name,
    ])
    if not result.ok:
        return SiteInstance.ObservedState.ABSENT
    if result.stdout.strip().lower() in {"true", "running", "1"}:
        return SiteInstance.ObservedState.RUNNING
    return SiteInstance.ObservedState.STOPPED


def _record(transport, kind, payload):
    calls = getattr(transport, "calls", None)
    if calls is not None:
        calls.append((kind, payload))


def _reason_key(reason):
    return (reason or "").strip().lower().replace("_", "-")


def _audit_once(action, obj, **detail):
    exists = AuditEvent.objects.filter(
        action=action,
        object_type=type(obj).__name__,
        object_id=str(getattr(obj, "pk", "")),
    ).exists()
    if exists:
        return None
    return audit(action, obj, source=AuditEvent.Source.RECONCILER, **detail)


def _flap_paused(instance):
    pause = (
        AuditEvent.objects.filter(
            action="reconcile_flap_pause",
            object_type="SiteInstance",
            object_id=str(instance.pk),
        )
        .order_by("-ts")
        .first()
    )
    if pause is None:
        return False
    rearmed = (
        AuditEvent.objects.filter(
            action="reconcile_rearmed",
            object_type="SiteInstance",
            object_id=str(instance.pk),
        )
        .order_by("-ts")
        .first()
    )
    if rearmed is None:
        return True
    return pause.ts >= rearmed.ts


def _cycle_count(instance, now):
    events = (
        AuditEvent.objects.filter(
            action="reconcile_repair",
            object_type="SiteInstance",
            object_id=str(instance.pk),
            ts__gte=now - FLAP_WINDOW,
        )
        .order_by("ts")
    )
    ops = [
        event.detail.get("op")
        for event in events
        if event.detail.get("op") in {"start", "stop"}
    ]
    cycles = 0
    i = 0
    while i < len(ops) - 1:
        if {ops[i], ops[i + 1]} == {"start", "stop"}:
            cycles += 1
            i += 2
        else:
            i += 1
    return cycles
