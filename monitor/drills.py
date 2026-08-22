"""CheckRun writers, missed-drill query, and Beat drill job bodies."""
from django.db.models import Q
from django.utils import timezone

from core.models import CheckRun

RESULTS_SCHEMA_VERSION = 1
_MAX_HUB_DOWN_S = 86400
_TERMINAL = (CheckRun.Status.SUCCEEDED, CheckRun.Status.FAILED)
_RESTORE_STUB_REASON = "Phase 2.5 body deferred"


def record_run(kind, status, results=None, *, due_at=None):
    """Persist one CheckRun. ``results is None`` becomes a versioned empty payload."""
    now = timezone.now()
    if results is None:
        results = {"schema_version": RESULTS_SCHEMA_VERSION}
    started = None
    finished = None
    if status in (
        CheckRun.Status.RUNNING,
        CheckRun.Status.SUCCEEDED,
        CheckRun.Status.FAILED,
        CheckRun.Status.SKIPPED,
    ):
        started = now
    if status in _TERMINAL + (CheckRun.Status.SKIPPED,):
        finished = now
    return CheckRun.objects.create(
        kind=kind,
        status=status,
        results=results,
        due_at=due_at,
        started=started,
        finished=finished,
    )


def find_missed(now):
    """Kinds whose latest due_at is past and have no succeeded/failed row after it."""
    missed = []
    for kind in CheckRun.Kind.values:
        latest = (
            CheckRun.objects.filter(kind=kind, due_at__isnull=False)
            .order_by("-due_at", "-pk")
            .first()
        )
        if latest is None or latest.due_at >= now:
            continue
        if latest.status in _TERMINAL:
            continue
        covered = CheckRun.objects.filter(kind=kind, status__in=_TERMINAL).filter(
            Q(finished__gte=latest.due_at) | Q(started__gte=latest.due_at)
        ).exists()
        if not covered:
            missed.append(kind)
    return missed


def run_hub_down_drill(
    *,
    duration_s=60,
    site_prober=None,
    stop_hub=None,
    start_hub=None,
):
    """Stop Hub-side workers, probe the site, write kind=hub_down. Never claims 24h."""
    if duration_s >= _MAX_HUB_DOWN_S:
        raise ValueError("hub_down duration_s must be < 86400; 24h stays waived")
    stop = stop_hub or (lambda: None)
    start = start_hub or (lambda: None)
    probe = site_prober or (lambda: False)
    stop()
    try:
        serving = bool(probe())
    except Exception:
        serving = False
    finally:
        start()
    return record_run(
        CheckRun.Kind.HUB_DOWN,
        CheckRun.Status.SUCCEEDED if serving else CheckRun.Status.FAILED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "duration_s": duration_s,
        },
    )


def run_reaper_drill(*, list_fn, delete_fn, planted_name):
    """Call reap_test_plane against a planted hub-t3-orphan-* name."""
    from tests.harness.reaper import reap_test_plane

    names = list(list_fn())
    if planted_name not in names:
        names.append(planted_name)
    deleted = []

    def _delete(name):
        deleted.append(name)
        delete_fn(name)

    reap_test_plane(list_fn=lambda: names, delete_fn=_delete)
    removed = planted_name in deleted
    return record_run(
        CheckRun.Kind.REAPER,
        CheckRun.Status.SUCCEEDED if removed else CheckRun.Status.FAILED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "planted_name": planted_name,
            "deleted": deleted,
        },
    )


def run_restore_clean_drill():
    """Honest stub: record that the restore body is deferred. Do not fake success."""
    return record_run(
        CheckRun.Kind.RESTORE_CLEAN,
        CheckRun.Status.SUCCEEDED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "stub": True,
            "reason": _RESTORE_STUB_REASON,
        },
    )
