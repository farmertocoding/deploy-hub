"""Nightly retention janitor — the pinned §C7 numbers, as batched DELETEs.

HostMetric raw 14 d / hourly 1 y · UptimeEvent 90 d / daily forever ·
TrafficStat minute 48 h / hour 90 d / day forever · deploy logs gzipped
after 30 d · AuditEvent forever. No partitioning, no TimescaleDB.
"""
import gzip
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.utils import timezone

# Pinned plan-addendum-2026-07-30.md §C7. None = keep forever.
HORIZONS = {
    "HostMetric": {
        "raw": timedelta(days=14),
        "hourly": timedelta(days=365),
    },
    "UptimeEvent": {
        "raw": timedelta(days=90),
        "daily": None,
    },
    "TrafficStat": {
        "minute": timedelta(hours=48),
        "hour": timedelta(days=90),
        "day": None,
    },
    "deploy_logs": timedelta(days=30),
    "AuditEvent": None,
}

NEVER_DELETE = frozenset({"AuditEvent"})
UPTIME_DAILY_KIND = "daily"
BATCH_SIZE = 500


def sweep(*, now=None, batch_size=None, log_dir=None):
    """Idempotent nightly pass. Batched DELETEs; AuditEvent is never touched."""
    clock = now or timezone.now()
    size = BATCH_SIZE if batch_size is None else batch_size
    archive = _log_dir(log_dir)
    return {
        "HostMetric": _sweep_host_metric(clock, size),
        "UptimeEvent": _sweep_uptime(clock, size),
        "TrafficStat": _sweep_traffic(clock, size),
        "deploy_logs": _gzip_deploy_logs(clock, size, archive),
        "AuditEvent": {"deleted": 0, "batches": 0},
    }


def _log_dir(log_dir):
    if log_dir is not None:
        return Path(log_dir)
    configured = getattr(settings, "HUB_DEPLOY_LOG_DIR", None)
    if configured:
        return Path(configured)
    return Path(settings.BASE_DIR) / "var" / "deploy-logs"


def _delete_batched(qs, batch_size):
    model = qs.model
    if model.__name__ in NEVER_DELETE:
        raise RuntimeError(f"{model.__name__} is never deleted")
    deleted = 0
    batches = 0
    while True:
        ids = list(qs.values_list("pk", flat=True)[:batch_size])
        if not ids:
            break
        model.objects.filter(pk__in=ids).delete()
        deleted += len(ids)
        batches += 1
    return {"deleted": deleted, "batches": batches}


def _sweep_host_metric(_now, _batch_size):
    """HostMetric was named in §C7 but never landed as a table (Task 1).

    The horizon stays pinned so a later model cannot pick a different number.
    No schema is invented here — batched DELETEs begin when the table exists.
    """
    return {"deleted": 0, "batches": 0}


def _sweep_uptime(now, batch_size):
    from core.models import UptimeEvent

    horizon = HORIZONS["UptimeEvent"]["raw"]
    return _delete_batched(
        UptimeEvent.objects.filter(at__lt=now - horizon).exclude(
            kind=UPTIME_DAILY_KIND,
        ),
        batch_size,
    )


def _sweep_traffic(now, batch_size):
    from core.models import TrafficStat

    deleted = 0
    batches = 0
    for grain, horizon in HORIZONS["TrafficStat"].items():
        if horizon is None:
            continue
        stats = _delete_batched(
            TrafficStat.objects.filter(
                granularity=grain,
                bucket_start__lt=now - horizon,
            ),
            batch_size,
        )
        deleted += stats["deleted"]
        batches += stats["batches"]
    return {"deleted": deleted, "batches": batches}


def _gzip_deploy_logs(now, batch_size, log_dir):
    from deploys.models import DeploymentStep

    horizon = HORIZONS["deploy_logs"]
    qs = (
        DeploymentStep.objects.filter(finished__lt=now - horizon)
        .exclude(log_text="")
        .order_by("pk")
    )
    gzipped = 0
    batches = 0
    while True:
        steps = list(qs[:batch_size])
        if not steps:
            break
        batches += 1
        for step in steps:
            _archive_step(step, log_dir)
            gzipped += 1
    return {"gzipped": gzipped, "batches": batches}


def _archive_step(step, log_dir):
    log_dir.mkdir(parents=True, exist_ok=True)
    path = log_dir / f"deploy-{step.deployment_id}-step-{step.seq}.log.gz"
    with gzip.open(path, "wb") as fh:
        fh.write(step.log_text.encode("utf-8"))
    artifacts = dict(step.artifacts or {})
    artifacts["log_gzip"] = str(path)
    step.log_text = ""
    step.artifacts = artifacts
    step.save(update_fields=["log_text", "artifacts"])
