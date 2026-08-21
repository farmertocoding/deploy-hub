"""CheckRun writers and the missed-drill query. Job bodies are Task 13."""
from django.db.models import Q
from django.utils import timezone

from core.models import CheckRun

RESULTS_SCHEMA_VERSION = 1
_TERMINAL = (CheckRun.Status.SUCCEEDED, CheckRun.Status.FAILED)


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
