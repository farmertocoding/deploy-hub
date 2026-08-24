"""Propose-mode scale-out evaluator (C5–C8). Never provisions."""
from datetime import timedelta

from django.utils import timezone

from core import locks
from core.audit import audit
from core.findings import resolve
from core.models import Finding, HostMetric, OperationLock, Site
from monitor.alerts import raise_alert
from scaling.attack_gate import AttackRefuse, PartnerOverflowRefuse, refuse_if_attack
from scaling.constants import (
    FIX_ACTION,
    OVERFLOW_HOURLY_USD,
    OVERFLOW_SIZE,
    TITLE,
    WINDOW_S,
)
from scaling.pressure import _overflow_axis, sustained_pressure

CYCLE_LOCK = ("target", "evaluate-scale-proposals", "collect")
CYCLE_HOLDER = "evaluate-scale-proposals"
CYCLE_LOCK_STALE_S = 300
KIND = "scale-out-proposal"
SOURCE = "scaling.evaluator"


def evaluate_site(site, *, now=None):
    """Call refuse_if_attack first; file only to open; never provision."""
    try:
        refuse_if_attack(site)
    except (AttackRefuse, PartnerOverflowRefuse):
        _retract(site)
        return None
    try:
        return _evaluate_eligible(site, now=now)
    except (AttackRefuse, PartnerOverflowRefuse):
        _retract(site)
        return None
    except Exception:
        return None


def evaluate_all(*, now=None):
    lock = _acquire_cycle_lock()
    if lock is None:
        audit(
            "scale-evaluate-skipped",
            source="system",
            severity="warning",
            reason="cycle-lock-held",
        )
        return None
    clock = now or timezone.now()
    try:
        for site in Site.objects.order_by("pk"):
            try:
                evaluate_site(site, now=clock)
            except Exception as exc:
                audit(
                    "scale-evaluate-failed",
                    site,
                    source="celery",
                    error=type(exc).__name__,
                )
                continue
    finally:
        locks.release(*CYCLE_LOCK, holder=CYCLE_HOLDER)
    return None


def _evaluate_eligible(site, *, now):
    clock = now or timezone.now()
    if (
        not site.primary_target_id
        or site.scale_ready is not True
        or site.exposure == Site.Exposure.MESH_ONLY
    ):
        _retract(site)
        return None
    samples = _samples(site, clock)
    if not sustained_pressure(samples, now=clock):
        _retract(site)
        return None
    fingerprint = f"{KIND}:{site.pk}"
    existing = Finding.objects.filter(fingerprint=fingerprint).first()
    if existing is not None and existing.state in {
        Finding.State.OPEN,
        Finding.State.ACKED,
        Finding.State.ACCEPTED,
    }:
        return existing
    axis = _overflow_axis(samples, now=clock) or "ram"
    entity = f"site:{site.domain or site.name}"
    body = (
        f"{site.name} has sustained {axis} pressure. "
        f"Overflow estimate {OVERFLOW_HOURLY_USD} USD/hour on {OVERFLOW_SIZE}. "
        "propose-mode does not launch."
    )
    return raise_alert(
        KIND,
        entity,
        fingerprint=fingerprint,
        title=TITLE,
        body=body,
        fix_action=FIX_ACTION,
        source_engine=SOURCE,
    )


def _samples(site, clock):
    rows = HostMetric.objects.filter(
        target_id=site.primary_target_id,
        ts__gte=clock - timedelta(seconds=WINDOW_S),
        ts__lte=clock,
    )
    return [
        {
            "ram": row.ram,
            "disk": row.disk,
            "load": row.load,
            "cores": row.cores,
            "ts": row.ts,
        }
        for row in rows
    ]


def _retract(site):
    row = Finding.objects.filter(fingerprint=f"{KIND}:{site.pk}").first()
    if row is not None and row.state in {
        Finding.State.OPEN,
        Finding.State.ACKED,
    }:
        resolve(row, source="system")


def _acquire_cycle_lock():
    lock = locks.acquire(*CYCLE_LOCK, CYCLE_HOLDER)
    if lock is not None:
        return lock
    scope, object_id, kind = CYCLE_LOCK
    cutoff = timezone.now() - timedelta(seconds=CYCLE_LOCK_STALE_S)
    stale, _ = OperationLock.objects.filter(
        scope=scope,
        object_id=object_id,
        kind=kind,
        heartbeat_at__lt=cutoff,
    ).delete()
    if not stale:
        return None
    audit(
        "scale-evaluate-lock-broken",
        source="system",
        severity="warning",
        stale_after_s=CYCLE_LOCK_STALE_S,
    )
    return locks.acquire(*CYCLE_LOCK, CYCLE_HOLDER)
