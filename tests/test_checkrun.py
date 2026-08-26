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
    # Phase 3 schema wave (Task 1): the daily token-scope audit and the
    # cert-expiry check get their CheckRun kinds with the rest of the schema.
    "cf_token_scope",
    "cert_expiry",
    # Phase 3b Task 1: adopt progress reuses CheckRun (Python choices; no
    # CheckRun migration). site_id lives in results, not an FK.
    "adopt",
    # Phase 4 Task 1: Python-only kinds (D-056). 0011 does not AlterField
    # CheckRun. BACKUP results are a closed key set; the others are not.
    "ssh_rotate",
    "backup",
    "attack_playbook",
    "tailscale_devices",
    # Phase 5 Task 1: Python-only kinds (D-072). 0012 does not AlterField
    # CheckRun. IAM daily audit and the cloud reaper write these kinds.
    "aws_iam_scope",
    "aws_reaper",
    # Phase 5.5 Task 1: Python-only kinds (D-076). 0013 does not AlterField
    # CheckRun. Partner reaper and intake poller write these kinds.
    "partner_reaper",
    "intake_poll",
    # Phase 7.4 Task 1: Python-only kind (D-137). 0015 stays closed.
    "hub_dns01",
}

_BACKUP_RESULT_KEYS = frozenset(
    {"schema_version", "unit_id", "site_id", "bytes", "digest", "stored_at"}
)


def _backup_results(**overrides):
    payload = {
        "schema_version": 1,
        "unit_id": 1,
        "site_id": 1,
        "bytes": 128,
        "digest": "a" * 64,
        "stored_at": "2026-08-23T00:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def test_checkrun_statuses_match_pinned_enums():
    """Status and kind are the pinned sets, neither a subset nor a superset.

    What would make this fail: renaming skipped, dropping pager, or adding a
    kind no design note asked for.
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


def test_checkrun_kind_backup_closed_schema():
    """kind=backup results keys are exactly the C7 set; bytes is an int size.

    What would make this fail: accepting the default {schema_version} payload,
    storing bytes as a string, or allowing extra keys that later become a
    ciphertext / key home.
    """
    from core.models import CheckRun

    with pytest.raises(ValidationError) as exc:
        CheckRun.objects.create(
            kind=CheckRun.Kind.BACKUP,
            status=CheckRun.Status.SUCCEEDED,
            results={"schema_version": 1},
        )
    assert "results" in exc.value.message_dict

    missing_bytes = _backup_results()
    del missing_bytes["bytes"]
    with pytest.raises(ValidationError) as exc:
        CheckRun.objects.create(
            kind=CheckRun.Kind.BACKUP,
            status=CheckRun.Status.SUCCEEDED,
            results=missing_bytes,
        )
    assert "results" in exc.value.message_dict

    with pytest.raises(ValidationError) as exc:
        CheckRun.objects.create(
            kind=CheckRun.Kind.BACKUP,
            status=CheckRun.Status.SUCCEEDED,
            results=_backup_results(token="must-not-persist"),
        )
    assert "results" in exc.value.message_dict

    with pytest.raises(ValidationError) as exc:
        CheckRun.objects.create(
            kind=CheckRun.Kind.BACKUP,
            status=CheckRun.Status.SUCCEEDED,
            results=_backup_results(bytes="128"),
        )
    assert "results" in exc.value.message_dict

    with pytest.raises(ValidationError) as exc:
        CheckRun.objects.create(
            kind=CheckRun.Kind.BACKUP,
            status=CheckRun.Status.SUCCEEDED,
            results=_backup_results(bytes=True),
        )
    assert "results" in exc.value.message_dict

    run = CheckRun.objects.create(
        kind=CheckRun.Kind.BACKUP,
        status=CheckRun.Status.SUCCEEDED,
        results=_backup_results(bytes=4096, unit_id=9, site_id=4),
    )
    run.refresh_from_db()
    assert set(run.results) == _BACKUP_RESULT_KEYS
    assert run.results["bytes"] == 4096
    assert type(run.results["bytes"]) is int
    assert run.results["unit_id"] == 9
    assert run.results["site_id"] == 4


def test_checkrun_kinds_ssh_rotate_attack_tailscale_exist():
    """Phase 4 kinds persist on the existing CheckRun table (Python choices).

    What would make this fail: omitting a named kind so a later task invents a
    second schema wave, or adding a Site FK that every drill would have to fill.
    """
    from core.models import CheckRun, Site

    assert CheckRun.Kind.SSH_ROTATE == "ssh_rotate"
    assert CheckRun.Kind.BACKUP == "backup"
    assert CheckRun.Kind.ATTACK_PLAYBOOK == "attack_playbook"
    assert CheckRun.Kind.TAILSCALE_DEVICES == "tailscale_devices"
    assert not any(field.name == "site" for field in CheckRun._meta.fields)
    assert Site not in {
        getattr(field, "related_model", None) for field in CheckRun._meta.fields
    }

    for kind in (
        CheckRun.Kind.SSH_ROTATE,
        CheckRun.Kind.ATTACK_PLAYBOOK,
        CheckRun.Kind.TAILSCALE_DEVICES,
    ):
        run = CheckRun.objects.create(
            kind=kind,
            status=CheckRun.Status.SUCCEEDED,
            results={"schema_version": 1},
        )
        run.refresh_from_db()
        assert run.kind == kind

