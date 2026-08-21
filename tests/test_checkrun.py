"""CheckRun rows plus the missed-drill detector (HARNESS-DRILLS-BEAT)."""
from datetime import timedelta

import pytest
from django.conf import settings
from django.core.exceptions import ValidationError
from django.utils import timezone

pytestmark = [pytest.mark.django_db, pytest.mark.req("HARNESS-DRILLS-BEAT")]

PINNED_STATUSES = {
    "scheduled",
    "running",
    "succeeded",
    "failed",
    "skipped",
}

PINNED_KINDS = {
    "hub_down",
    "restore_clean",
    "reaper",
    "pager",
}


def test_checkrun_statuses_match_pinned_enums():
    """Status and kind are the pinned Phase 2.5 sets, neither a subset nor a superset.

    What would make this fail: renaming skipped, dropping pager, or adding a
    fifth-wave kind before Task 13 asks for one.
    """
    from core.models import CheckRun

    assert set(CheckRun.Status.values) == PINNED_STATUSES
    assert set(CheckRun.Kind.values) == PINNED_KINDS


def test_results_require_schema_version():
    """Unversioned results JSON is refused; a schema_version key is enough to persist.

    What would make this fail: accepting {}, or storing results that cannot be
    diffed across runs because the shape has no version.
    """
    from core.models import CheckRun

    with pytest.raises(ValidationError):
        CheckRun.objects.create(
            kind=CheckRun.Kind.PAGER,
            status=CheckRun.Status.SUCCEEDED,
            results={"ok": True},
        )

    run = CheckRun.objects.create(
        kind=CheckRun.Kind.PAGER,
        status=CheckRun.Status.SUCCEEDED,
        results={"schema_version": 1, "ok": True},
    )
    run.refresh_from_db()
    assert run.results["schema_version"] == 1


def test_missed_due_run_is_detected():
    """A past due_at with no succeeded/failed row after that due is a missed kind.

    What would make this fail: ignoring due_at, or treating scheduled/skipped as
    a completion so a silent skip never shows up.
    """
    from monitor.drills import find_missed, record_run

    now = timezone.now()
    record_run("hub_down", "scheduled", due_at=now - timedelta(hours=1))

    assert find_missed(now) == ["hub_down"]


def test_fresh_succeeded_run_is_not_missed():
    """A succeeded row after the latest due covers that kind.

    What would make this fail: treating every past due_at as missed even after
    record_run wrote succeeded, or requiring ntfy before the kind is cleared.
    """
    from monitor.drills import find_missed, record_run

    now = timezone.now()
    record_run("hub_down", "scheduled", due_at=now - timedelta(hours=1))
    record_run("hub_down", "succeeded")

    assert find_missed(now) == []


def test_skipped_status_is_still_a_written_row():
    """Skip is a persisted CheckRun, not a missing row.

    What would make this fail: record_run(skipped) returning None or writing
    nothing, so a skipped drill is indistinguishable from one that never ran.
    """
    from core.models import CheckRun
    from monitor.drills import record_run

    run = record_run("reaper", "skipped")

    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.status == CheckRun.Status.SKIPPED
    assert stored.kind == CheckRun.Kind.REAPER
    assert stored.results["schema_version"] == 1


def test_missed_drill_writes_audit_event():
    """detect_missed_drills audits each missed kind as warning; Beat is hourly.

    What would make this fail: a log-only miss, ntfy instead of AuditEvent, or
    the detector missing from CELERY_BEAT_SCHEDULE / queue probes.
    """
    from core.models import AuditEvent
    from monitor.drills import record_run
    from monitor.tasks import detect_missed_drills

    now = timezone.now()
    record_run("restore_clean", "scheduled", due_at=now - timedelta(days=1))

    detect_missed_drills(now=now)

    event = AuditEvent.objects.get(action="drill-missed")
    assert event.severity == AuditEvent.Severity.WARNING
    assert event.detail["kind"] == "restore_clean"

    beat = settings.CELERY_BEAT_SCHEDULE["detect-missed-drills"]
    assert beat["task"] == detect_missed_drills.name
    assert float(beat["schedule"]) == 3600.0
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "probes"
