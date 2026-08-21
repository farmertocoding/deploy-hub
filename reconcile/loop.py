"""Desired vs observed reconciler with C2 brakes and N3 staleness policy."""
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from core import locks
from core.audit import audit
from core.models import AuditEvent, OperationLock, SiteInstance, Target
from deploys.steps import ensure_start

MUTATION_BUDGET = 2
GLOBAL_MUTATION_BUDGET = 3
FLAP_WINDOW = timedelta(minutes=10)
FLAP_CYCLE_LIMIT = 3
BACKOFF_AFTER = 3
COLLECT_FRESH_S = 60
STALE_REASONS = frozenset({"data-stale", "feed-stale", "feed-staleness", "staleness"})
UPSTREAM_REASONS = frozenset({"upstream-down"})
REARM_SCOPED_AUDITS = frozenset({"reconcile_flap_pause", "reconcile_backoff"})
RUNNING_DOCKER = frozenset({"running", "true", "1"})


def tick(site, *, transport, now=None, observe=None, jitter=0, budget=None, instance=None):
    """Observe one site's instances and repair drift unless a brake applies.

    ``jitter`` is accepted for Beat spreading; it does not skip work.
    ``budget`` caps mutations for this call (T1 / remaining global cap).
    """
    del jitter  # schedule hint only — never a mutate skip
    if not getattr(settings, "HUB_RECONCILE_ENABLED", True):
        _audit_once("reconcile_globally_disabled", None)
        return {"mutations": 0}
    now = now or timezone.now()
    cap = MUTATION_BUDGET if budget is None else budget
    used = 0
    qs = site.instances.all()
    if instance is not None:
        qs = qs.filter(pk=instance.pk)
    for row in qs:
        observed = _read_observed(row, transport, site, observe, now)
        _persist_observation(row, observed, now)
        if _braked(site, row, observed, now):
            continue
        action = _plan(row, observed)
        if action is None:
            _maybe_clear_failures(row, observed)
            continue
        if used >= cap:
            continue
        if _deploy_lock_held(site, row):
            continue
        if _apply(site, row, transport, action, now, observe=observe):
            used += 1
            if _cycle_count(row, now) >= FLAP_CYCLE_LIMIT:
                _audit_once("reconcile_flap_pause", row)
    return {"mutations": used}


def rearm(instance):
    """Manual re-arm after backoff or flap pause."""
    instance.consecutive_failures = 0
    instance.save(update_fields=["consecutive_failures"])
    audit("reconcile_rearmed", instance, source=AuditEvent.Source.RECONCILER)


def _read_observed(instance, transport, site, observe, now=None):
    if observe is not None:
        raw = observe(instance) or {}
        return {
            "state": raw.get("state") or SiteInstance.ObservedState.ABSENT,
            "reason": raw.get("reason") or "",
        }
    clock = now or timezone.now()
    payload = _fresh_collect_payload(instance, clock)
    if payload is not None:
        name = _container_name(_desired(site, instance, transport))
        return {
            "state": _state_from_collect(payload, name),
            "reason": _reason_from_collect(payload, name),
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
    if desired in {
        SiteInstance.DesiredState.STOPPED,
        SiteInstance.DesiredState.ABSENT,
    } and state in {
        SiteInstance.ObservedState.RUNNING,
        SiteInstance.ObservedState.UNHEALTHY,
    }:
        return "stop"
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
    return None


def _maybe_clear_failures(instance, observed):
    if (
        observed["state"] == SiteInstance.ObservedState.RUNNING
        and instance.desired_state == SiteInstance.DesiredState.RUNNING
        and instance.consecutive_failures
    ):
        instance.consecutive_failures = 0
        instance.save(update_fields=["consecutive_failures"])


def _apply(site, instance, transport, action, now, observe=None):
    holder = f"reconcile:{site.pk}"
    lock = locks.acquire(
        OperationLock.Scope.SITE, site.pk, OperationLock.Kind.RECONCILE, holder,
    )
    if lock is None:
        return False
    try:
        _record(transport, "lock", ["recheck"])
        instance.refresh_from_db()
        observed = _read_observed(instance, transport, site, observe, now)
        _persist_observation(instance, observed, now)
        if _braked(site, instance, observed, now):
            return False
        action = _plan(instance, observed)
        if action is None:
            _maybe_clear_failures(instance, observed)
            return False
        if not OperationLock.objects.filter(
            scope=OperationLock.Scope.SITE,
            object_id=str(site.pk),
            kind=OperationLock.Kind.RECONCILE,
            holder=holder,
        ).exists():
            return False
        if _deploy_lock_held(site, instance):
            return False
        desired = _desired(site, instance, transport)
        name = _container_name(desired)
        if action == "start":
            ensure_start(desired)
            instance.consecutive_failures = 0
            instance.observed_state = SiteInstance.ObservedState.RUNNING
        elif action == "stop":
            result = transport.run(["docker", "stop", name])
            if not result.ok:
                raise RuntimeError(f"docker stop failed: {result.stderr}")
            instance.observed_state = SiteInstance.ObservedState.STOPPED
        elif action == "restart":
            result = transport.run(["docker", "restart", name])
            if not result.ok:
                raise RuntimeError(f"docker restart failed: {result.stderr}")
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
        _invalidate_collect(instance.target)
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


def _deploy_lock_held(site, instance):
    if OperationLock.objects.filter(
        scope=OperationLock.Scope.SITE,
        object_id=str(site.pk),
        kind=OperationLock.Kind.DEPLOY,
    ).exists():
        return True
    target_id = getattr(instance, "target_id", None) or getattr(
        getattr(instance, "target", None), "pk", None,
    )
    if target_id is None:
        return False
    return OperationLock.objects.filter(
        scope=OperationLock.Scope.TARGET,
        object_id=str(target_id),
        kind=OperationLock.Kind.DEPLOY,
    ).exists()


def _desired(site, instance, transport):
    from deploys.models import Deployment

    dep = (
        Deployment.objects.filter(
            manifest__site=site,
            status=Deployment.Status.SUCCEEDED,
        )
        .order_by("-pk")
        .first()
    )
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


def _fresh_collect_payload(instance, now):
    target = instance.target
    if target is None:
        return None
    pk = getattr(target, "pk", None)
    if pk is not None:
        fresh = Target.objects.filter(pk=pk).only(
            "collect_payload", "collect_at",
        ).first()
        if fresh is not None:
            target = fresh
    payload = getattr(target, "collect_payload", None)
    collected_at = getattr(target, "collect_at", None)
    if not payload or collected_at is None:
        return None
    age = now - collected_at
    if age.total_seconds() > COLLECT_FRESH_S:
        return None
    return payload


def _invalidate_collect(target):
    if target is None or not getattr(target, "pk", None):
        return
    Target.objects.filter(pk=target.pk).update(collect_at=None)
    target.collect_at = None


def _health_for(payload, name):
    healthz = payload.get("healthz") or {}
    if not isinstance(healthz, dict):
        return {}
    checks = healthz.get("checks") or {}
    per = checks.get(name) if isinstance(checks, dict) else None
    if isinstance(per, dict) and ("live" in per or "ready" in per):
        return per
    return healthz


def _reason_from_collect(payload, name):
    health = _health_for(payload, name)
    if not isinstance(health, dict):
        return ""
    explicit = health.get("reason")
    if explicit:
        return str(explicit)
    checks = health.get("checks")
    if not isinstance(checks, dict):
        return ""
    upstream = checks.get("upstream")
    if isinstance(upstream, str):
        key = _reason_key(upstream)
        if key in UPSTREAM_REASONS:
            return key
    for key, val in checks.items():
        for token in (key, val):
            text = _reason_key(str(token))
            if text in STALE_REASONS:
                return text
    return ""


def _state_from_collect(payload, name):
    rows = payload.get("containers") or []
    by_name = {}
    for row in rows:
        if isinstance(row, dict) and row.get("name"):
            by_name[row["name"]] = (row.get("state") or "").strip().lower()
    if name not in by_name:
        return SiteInstance.ObservedState.ABSENT
    if by_name[name] not in RUNNING_DOCKER:
        return SiteInstance.ObservedState.STOPPED
    health = _health_for(payload, name)
    live = bool(health.get("live"))
    ready = bool(health.get("ready"))
    if live and ready:
        return SiteInstance.ObservedState.RUNNING
    if live and not ready:
        return SiteInstance.ObservedState.WARMING
    return SiteInstance.ObservedState.UNHEALTHY


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


def _last_rearm(obj):
    return (
        AuditEvent.objects.filter(
            action="reconcile_rearmed",
            object_type=type(obj).__name__,
            object_id=str(getattr(obj, "pk", "")),
        )
        .order_by("-ts")
        .first()
    )


def _audit_once(action, obj, **detail):
    object_type = type(obj).__name__ if obj is not None else ""
    object_id = str(getattr(obj, "pk", "")) if obj is not None else ""
    qs = AuditEvent.objects.filter(
        action=action,
        object_type=object_type,
        object_id=object_id,
    )
    if action in REARM_SCOPED_AUDITS:
        rearmed = _last_rearm(obj)
        if rearmed is not None:
            qs = qs.filter(ts__gt=rearmed.ts)
    if qs.exists():
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
    events = AuditEvent.objects.filter(
        action="reconcile_repair",
        object_type="SiteInstance",
        object_id=str(instance.pk),
        ts__gte=now - FLAP_WINDOW,
    )
    rearmed = _last_rearm(instance)
    if rearmed is not None:
        events = events.filter(ts__gt=rearmed.ts)
    ops = [
        event.detail.get("op")
        for event in events.order_by("ts")
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
