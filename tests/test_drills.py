"""Beat drill job bodies: short Hub-down, reaper, honest restore stub."""
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from core.models import CheckRun
from monitor.drills import (
    find_missed,
    run_hub_down_drill,
    run_reaper_drill,
    run_restore_clean_drill,
)

pytestmark = [pytest.mark.django_db]

WAIVER_24H = "REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven"
DAY = 86400


@pytest.mark.req("REL-P2-DRILL-STUB")
@pytest.mark.req("HARNESS-DRILLS-BEAT")
def test_hub_down_stub_writes_checkrun_succeeded_when_site_serves():
    """Hub-down probe writes succeeded when the site still answers.

    What would make this fail: skipping the CheckRun, treating a serving site
    as failed, or stopping the pytest process because stop_hub was not injected.
    """
    events = []

    def stop_hub():
        events.append("stop")

    def start_hub():
        events.append("start")

    def site_prober():
        events.append("probe")
        return True

    run = run_hub_down_drill(
        duration_s=60,
        site_prober=site_prober,
        stop_hub=stop_hub,
        start_hub=start_hub,
    )

    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.kind == CheckRun.Kind.HUB_DOWN
    assert stored.status == CheckRun.Status.SUCCEEDED
    assert stored.results["schema_version"] == 1
    assert stored.results["duration_s"] == 60
    assert events == ["stop", "probe", "start"]


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_hub_down_does_not_claim_24h():
    """Recorded duration stays under a day and no 24h success flag is set.

    What would make this fail: writing duration_s >= 86400, setting a 24h
    success key, or deleting the REL-P2 24h waiver line.
    """
    from pathlib import Path

    run = run_hub_down_drill(
        duration_s=1800,
        site_prober=lambda: True,
        stop_hub=lambda: None,
        start_hub=lambda: None,
    )

    assert run.results["schema_version"] == 1
    assert run.results["duration_s"] == 1800
    assert run.results["duration_s"] < DAY
    flag_keys = [
        key
        for key in run.results
        if "24h" in str(key).lower() or "24_h" in str(key).lower()
    ]
    assert flag_keys == []
    assert run.results.get("success_24h") is None
    assert run.results.get("ok_24h") is None

    waivers = (Path(__file__).resolve().parent.parent / "WAIVERS.md").read_text(
        encoding="utf-8"
    )
    assert WAIVER_24H in waivers


@pytest.mark.req("HARNESS-DRILLS-BEAT")
def test_missed_monthly_hub_down_is_detected():
    """A month-old scheduled hub_down with no terminal row is missed.

    What would make this fail: find_missed ignoring hub_down, or treating a
    past monthly due as covered without a succeeded/failed run.
    """
    from monitor.drills import record_run

    now = timezone.now()
    record_run("hub_down", "scheduled", due_at=now - timedelta(days=31))

    assert find_missed(now) == ["hub_down"]


@pytest.mark.req("HARNESS-REAPER-TEST-PLANE")
def test_reaper_drill_removes_planted_orphan_prefix():
    """Weekly reaper drill deletes only the planted hub-t3-orphan-* name.

    What would make this fail: leaving the planted orphan, deleting a name
    outside the prefix, or skipping the reaper CheckRun.
    """
    planted = "hub-t3-orphan-weekly"
    deleted = []

    run = run_reaper_drill(
        list_fn=lambda: [planted, "primary", "something-else"],
        delete_fn=deleted.append,
        planted_name=planted,
    )

    assert planted in deleted
    assert "primary" not in deleted
    assert "something-else" not in deleted
    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.kind == CheckRun.Kind.REAPER
    assert stored.status == CheckRun.Status.SUCCEEDED
    assert stored.results["schema_version"] == 1


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_restore_drill_is_honest_stub_not_green_fiction():
    """Restore CheckRun is a recorded stub, not a fake restore success.

    What would make this fail: omitting stub=true, inventing a restore payload,
    or claiming the Phase 2.5 body already ran.
    """
    run = run_restore_clean_drill()

    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.kind == CheckRun.Kind.RESTORE_CLEAN
    assert stored.status == CheckRun.Status.SUCCEEDED
    assert stored.results["schema_version"] == 1
    assert stored.results["stub"] is True
    assert stored.results["reason"] == "Phase 2.5 body deferred"
    assert "restored" not in stored.results
    assert stored.results.get("restore_ok") is not True
    assert stored.results.get("green") is not True


@pytest.mark.req("HARNESS-DRILLS-BEAT")
def test_beat_schedule_lists_three_drills():
    """Monthly hub-down, weekly reaper, monthly restore stub are on Beat.

    What would make this fail: missing a key, using crontab instead of seconds,
    sending drills off queue probes, or monthly hub-down not passing 1800s.
    """
    from monitor import tasks as monitor_tasks

    hub = settings.CELERY_BEAT_SCHEDULE["drill-hub-down-monthly"]
    reaper = settings.CELERY_BEAT_SCHEDULE["drill-reaper-weekly"]
    restore = settings.CELERY_BEAT_SCHEDULE["drill-restore-monthly"]

    assert hub["task"] == monitor_tasks.run_hub_down_drill.name
    assert reaper["task"] == monitor_tasks.run_reaper_drill.name
    assert restore["task"] == monitor_tasks.run_restore_clean_drill.name
    assert float(hub["schedule"]) == 30 * DAY
    assert float(reaper["schedule"]) == 7 * DAY
    assert float(restore["schedule"]) == 30 * DAY
    assert hub.get("kwargs", {}).get("duration_s") == 1800
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "probes"
