"""Beat drill job bodies: short Hub-down, reaper, honest restore stub."""
import ast
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings
from django.utils import timezone

from core.models import CheckRun
from monitor.drills import (
    find_missed,
    run_hub_down_drill,
    run_reaper_drill,
    run_restore_clean_drill,
)

REPO = Path(__file__).resolve().parent.parent
PRODUCT_DRILL_MODULES = (
    "monitor/tasks.py",
    "monitor/drills.py",
    "monitor/reaper.py",
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
    assert stored.status == CheckRun.Status.SKIPPED
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
    pager = settings.CELERY_BEAT_SCHEDULE["drill-pager-monthly"]

    assert hub["task"] == monitor_tasks.run_hub_down_drill.name
    assert reaper["task"] == monitor_tasks.run_reaper_drill.name
    assert restore["task"] == monitor_tasks.run_restore_clean_drill.name
    assert pager["task"] == monitor_tasks.run_pager_drill.name
    assert float(hub["schedule"]) == 30 * DAY
    assert float(reaper["schedule"]) == 7 * DAY
    assert float(restore["schedule"]) == 30 * DAY
    assert float(pager["schedule"]) == 30 * DAY
    assert hub.get("kwargs", {}).get("duration_s") == 1800
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "probes"


@pytest.mark.req("HARNESS-DRILLS-BEAT")
def test_product_drill_modules_do_not_import_tests():
    """Beat/product drill path must not import the tests package.

    What would make this fail: monitor.tasks / drills / reaper importing
    tests.harness so a probes worker runs Multipass on the Hub host.
    """
    for rel in PRODUCT_DRILL_MODULES:
        path = REPO / rel
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        imported = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.append(node.module)
        offenders = [
            name
            for name in imported
            if name == "tests" or name.startswith("tests.")
        ]
        assert not offenders, f"{rel} imports {offenders}"
        assert "tests.harness" not in source


@pytest.mark.req("REL-P2-DRILL-STUB")
@pytest.mark.req("HARNESS-DRILLS-BEAT")
def test_beat_hub_down_without_prober_is_skipped_not_failed():
    """Unconfigured monthly Hub-down is skipped/stub, not a fake FAILED.

    What would make this fail: default site_prober returning False so Beat
    writes failed without stopping workers or GET-ing a site.
    """
    from monitor.tasks import run_hub_down_drill as beat_hub_down

    result = beat_hub_down()
    stored = CheckRun.objects.get(
        kind=CheckRun.Kind.HUB_DOWN, status=CheckRun.Status.SKIPPED,
    )
    assert stored.status != CheckRun.Status.FAILED
    assert stored.results["schema_version"] == 1
    assert "eligible" in stored.results["reason"]
    assert stored.results["duration_s"] == 1800
    assert stored.results["duration_s"] < DAY
    assert result["status"] == CheckRun.Status.SKIPPED


@pytest.mark.req("HARNESS-REAPER-TEST-PLANE")
def test_beat_reaper_skips_when_not_test_plane():
    """Weekly reaper on a non-test Hub writes skipped, and does not crash.

    What would make this fail: importing tests.harness or calling Multipass
    on the crown-jewel host when HUB_TEST_MODE is off.
    """
    from monitor.tasks import run_reaper_drill as beat_reaper

    with override_settings(HUB_TEST_MODE=False):
        result = beat_reaper()

    stored = CheckRun.objects.get(
        kind=CheckRun.Kind.REAPER, status=CheckRun.Status.SKIPPED,
    )
    assert stored.status == CheckRun.Status.SKIPPED
    assert stored.results["schema_version"] == 1
    assert stored.results["stub"] is True
    assert result["status"] == CheckRun.Status.SKIPPED


@pytest.mark.req("REL-P2-DRILL-STUB")
@pytest.mark.req("HARNESS-DRILLS-BEAT")
def test_hub_down_uses_a_real_external_prober_by_default(monkeypatch):
    """Default hub-down prober is an external HTTP GET of a live site.

    What would make this fail: calling a Hub-internal URL, skipping the
    GET when a READY site exists, or requiring the caller to inject a prober.
    """
    from uptime_fixtures import make_site

    site = make_site("blog", domain="blog.example.com")
    calls = []

    class _Resp:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(request, timeout=None):
        calls.append(
            {
                "url": request.full_url,
                "method": request.get_method(),
                "timeout": timeout,
            }
        )
        return _Resp()

    monkeypatch.setattr("monitor.uptime.urlopen", fake_urlopen)

    run = run_hub_down_drill(duration_s=60)

    assert calls, "default prober must issue an HTTP GET"
    assert calls[0]["url"] == f"https://{site.domain}/healthz"
    assert calls[0]["method"] == "GET"
    assert "localhost" not in calls[0]["url"]
    assert "127.0.0.1" not in calls[0]["url"]
    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.kind == CheckRun.Kind.HUB_DOWN
    assert stored.status == CheckRun.Status.SUCCEEDED


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_no_eligible_site_is_skipped_with_a_reason_and_a_p2_finding():
    """No live site is a named SKIPPED outcome plus a P2 Finding.

    What would make this fail: crashing, writing SUCCEEDED, or staying
    silent (no Finding) on an empty fleet.
    """
    from core.models import Finding

    run = run_hub_down_drill(duration_s=60)

    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.status == CheckRun.Status.SKIPPED
    assert stored.status != CheckRun.Status.SUCCEEDED
    assert "eligible" in stored.results["reason"]
    row = Finding.objects.get(fingerprint="drill-missed:hub_down:no-eligible-site")
    assert row.severity == Finding.Severity.P2


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_nightly_exits_zero_on_a_host_with_no_live_site():
    """A siteless hub-down SKIPPED is nightly-green (exit 0).

    What would make this fail: treating SKIPPED as a non-zero nightly
    exit, or crashing before a CheckRun is written.
    """
    from monitor.drills import nightly_exit_code

    run = run_hub_down_drill(duration_s=60)
    assert run.status == CheckRun.Status.SKIPPED
    assert nightly_exit_code(run) == 0


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_missing_prober_with_a_live_site_is_a_configuration_error():
    """site_prober=None is illegal when a READY site exists.

    What would make this fail: silently skipping, inventing a fake
    prober, or returning SUCCEEDED without an HTTP GET.
    """
    from uptime_fixtures import make_site

    from monitor.drills import DrillConfigurationError

    make_site("blog", domain="blog.example.com")
    with pytest.raises(DrillConfigurationError, match="site_prober"):
        run_hub_down_drill(duration_s=60, site_prober=None)


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_restore_stub_status_is_skipped_not_succeeded():
    """The restore body is deferred: SKIPPED, never a fake SUCCEEDED (M1).

    What would make this fail: writing succeeded so a stub looks like a
    restore that ran.
    """
    run = run_restore_clean_drill()
    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.status == CheckRun.Status.SKIPPED
    assert stored.status != CheckRun.Status.SUCCEEDED
    assert stored.results["reason"] == "Phase 2.5 body deferred"


@pytest.mark.req("HARNESS-DRILLS-BEAT")
@pytest.mark.req("ALERT-PAGER-DRILL")
def test_beat_seeds_due_at_for_every_drill_kind():
    """Each drill Beat job writes/refreshes a scheduled CheckRun with due_at.

    What would make this fail: running the body without a scheduled row,
    omitting pager, or leaving due_at null so find_missed stays inert.
    """
    from django.utils import timezone

    from monitor.tasks import run_hub_down_drill as beat_hub
    from monitor.tasks import run_pager_drill as beat_pager
    from monitor.tasks import run_reaper_drill as beat_reaper
    from monitor.tasks import run_restore_clean_drill as beat_restore

    with override_settings(HUB_TEST_MODE=False):
        beat_hub()
        beat_reaper()
        beat_restore()
        beat_pager()

    now = timezone.now()
    for kind in (
        CheckRun.Kind.HUB_DOWN,
        CheckRun.Kind.REAPER,
        CheckRun.Kind.RESTORE_CLEAN,
        CheckRun.Kind.PAGER,
    ):
        scheduled = CheckRun.objects.get(kind=kind, status=CheckRun.Status.SCHEDULED)
        assert scheduled.due_at is not None
        assert scheduled.due_at > now


@pytest.mark.req("HARNESS-DRILLS-BEAT")
@pytest.mark.req("ALERT-PAGER-DRILL")
def test_find_missed_fires_on_a_seeded_overdue_row():
    """A Beat-seeded scheduled row is visible to find_missed once overdue.

    What would make this fail: seed writing no due_at, or find_missed
    ignoring a past scheduled pager row.
    """
    from monitor.drills import seed_due_at

    now = timezone.now()
    seed_due_at(CheckRun.Kind.PAGER, period_s=30 * DAY, now=now - timedelta(days=31))

    assert find_missed(now) == ["pager"]


@pytest.mark.req("ALERT-PAGER-DRILL")
def test_pager_drill_records_which_backend_delivered(monkeypatch):
    """A real-backend pager drill records results.backend and SUCCEEDED.

    What would make this fail: omitting backend, treating FakePager as
    success, or skipping deliver() so nobody can see which backend ran.
    """
    from monitor.drills import run_pager_drill
    from monitor.pager import reset_pager

    published = []

    class _RecordingPager:
        def publish(self, severity, title, body, *, tags, click_url, **_kwargs):
            published.append(
                {"severity": severity, "title": title, "body": body}
            )

    monkeypatch.setattr("monitor.pager.get_pager", lambda: _RecordingPager())
    reset_pager()
    with override_settings(HUB_PAGER_BACKEND="ntfy"):
        reset_pager()
        run = run_pager_drill()

    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.kind == CheckRun.Kind.PAGER
    assert stored.status == CheckRun.Status.SUCCEEDED
    assert stored.results["backend"] == "ntfy"
    assert published, "synthetic P1 must go through deliver()"
    from core.models import Finding

    period = timezone.localtime(timezone.now()).strftime("%Y-%m")
    filed = Finding.objects.get(fingerprint=f"pager-drill:{period}")
    assert filed.title == "TEST — ack me"
    assert filed.severity == Finding.Severity.P1


@pytest.mark.req("ALERT-PAGER-DRILL")
def test_fake_backend_pager_drill_is_skipped_not_succeeded():
    """Fake backend is SKIPPED with backend: fake — it paged nobody.

    What would make this fail: writing SUCCEEDED for FakePager, or
    omitting backend so a silent skip looks like a real page.
    """
    from monitor.drills import run_pager_drill

    assert settings.HUB_PAGER_BACKEND == "fake"
    run = run_pager_drill()
    stored = CheckRun.objects.get(pk=run.pk)
    assert stored.status == CheckRun.Status.SKIPPED
    assert stored.status != CheckRun.Status.SUCCEEDED
    assert stored.results["backend"] == "fake"


@pytest.mark.req("ALERT-PAGER-DRILL")
def test_missed_pager_drill_alerts_like_a_down_site():
    """A missed pager CheckRun files a P1 Finding, never silence.

    What would make this fail: detect_missed only auditing pager, or
    classifying a missed pager drill as anything quieter than a down site.
    """
    from core.models import Finding
    from monitor.drills import record_run
    from monitor.tasks import detect_missed_drills

    now = timezone.now()
    record_run("pager", "scheduled", due_at=now - timedelta(days=31))
    detect_missed_drills(now=now)

    row = Finding.objects.get(fingerprint="drill-missed:pager")
    assert row.severity == Finding.Severity.P1


class _RecordingPager:
    """Injectable pager for ALERT-PAGER-DRILL. fail=True raises after record."""

    def __init__(self):
        self.published = []
        self.fail = False

    def publish(self, severity, title, body, *, tags, click_url, **_kwargs):
        self.published.append({"severity": severity, "title": title, "body": body})
        if self.fail:
            raise RuntimeError("ntfy down")


@pytest.mark.req("ALERT-PAGER-DRILL")
def test_historical_fake_ok_does_not_succeed_a_failed_ntfy_run(monkeypatch):
    """Months of FakePager ok=True must not make a failed ntfy run SUCCEEDED.

    What would make this fail: unbounded AlertDelivery.ok.exists() treating
    a prior fake-backend row as this run's real delivery.
    """
    from monitor.drills import run_pager_drill
    from monitor.pager import reset_pager

    assert settings.HUB_PAGER_BACKEND == "fake"
    fake_run = run_pager_drill()
    assert fake_run.status == CheckRun.Status.SKIPPED

    pager = _RecordingPager()
    pager.fail = True
    monkeypatch.setattr("monitor.pager.get_pager", lambda: pager)
    reset_pager()
    with override_settings(HUB_PAGER_BACKEND="ntfy"):
        reset_pager()
        run = run_pager_drill()

    assert run.status != CheckRun.Status.SUCCEEDED
    assert run.results["backend"] == "ntfy"


@pytest.mark.req("ALERT-PAGER-DRILL")
def test_later_ntfy_failure_is_not_succeeded_from_an_earlier_ok(monkeypatch):
    """A later ntfy fail must not inherit SUCCEEDED from this finding's past ok.

    What would make this fail: judging the CheckRun on any historical NTFY
    ok=True instead of this call's delivery.
    """
    from monitor.drills import run_pager_drill
    from monitor.pager import reset_pager

    pager = _RecordingPager()
    monkeypatch.setattr("monitor.pager.get_pager", lambda: pager)
    reset_pager()
    with override_settings(HUB_PAGER_BACKEND="ntfy"):
        reset_pager()
        first = run_pager_drill()
        assert first.status == CheckRun.Status.SUCCEEDED
        pager.fail = True
        second = run_pager_drill()

    assert second.status != CheckRun.Status.SUCCEEDED
    assert second.results["backend"] == "ntfy"


@pytest.mark.req("ALERT-PAGER-DRILL")
def test_acked_finding_without_this_run_push_is_not_succeeded(monkeypatch):
    """Ack must not let the next run SUCCEEDED without paging this month.

    What would make this fail: stable fingerprint + finding() leaving ACKED
    + maybe_deliver skip + historical ok.exists() still writing SUCCEEDED.
    """
    from core.findings import ack
    from core.models import Finding
    from monitor.drills import run_pager_drill
    from monitor.pager import reset_pager

    pager = _RecordingPager()
    monkeypatch.setattr("monitor.pager.get_pager", lambda: pager)
    reset_pager()
    with override_settings(HUB_PAGER_BACKEND="ntfy"):
        reset_pager()
        first = run_pager_drill()
        assert first.status == CheckRun.Status.SUCCEEDED
        filed = Finding.objects.get(title="TEST — ack me")
        ack(filed)
        before = len(pager.published)
        second = run_pager_drill()

    assert second.status != CheckRun.Status.SUCCEEDED
    assert len(pager.published) == before


@pytest.mark.req("ALERT-PAGER-DRILL")
def test_next_month_pager_drill_pages_after_last_month_ack(monkeypatch):
    """A new YYYY-MM fingerprint must still page after last month was acked.

    What would make this fail: one stable fingerprint so ack + maybe_deliver
    skip the next month's synthetic P1.
    """
    from core.findings import ack
    from core.models import Finding
    from monitor.drills import run_pager_drill
    from monitor.pager import reset_pager

    pager = _RecordingPager()
    monkeypatch.setattr("monitor.pager.get_pager", lambda: pager)
    reset_pager()
    january = timezone.now().replace(year=2026, month=1, day=15)
    february = timezone.now().replace(year=2026, month=2, day=15)
    with override_settings(HUB_PAGER_BACKEND="ntfy"):
        reset_pager()
        first = run_pager_drill(now=january)
        assert first.status == CheckRun.Status.SUCCEEDED
        ack(Finding.objects.get(fingerprint="pager-drill:2026-01"))
        before = len(pager.published)
        second = run_pager_drill(now=february)

    assert second.status == CheckRun.Status.SUCCEEDED
    assert len(pager.published) > before
    assert Finding.objects.filter(fingerprint="pager-drill:2026-02").exists()


@pytest.mark.req("REL-P2-DRILL-STUB")
def test_hub_down_still_refuses_to_claim_24h():
    """24h stays a dated calendar item; the short form must not claim it.

    What would make this fail: accepting duration_s >= 86400, writing a
    24h success flag, dropping the waiver, or amending it to claim 24h.
    """
    with pytest.raises(ValueError, match="86400"):
        run_hub_down_drill(
            duration_s=DAY,
            site_prober=lambda: True,
            stop_hub=lambda: None,
            start_hub=lambda: None,
        )

    waivers = (Path(__file__).resolve().parent.parent / "WAIVERS.md").read_text(
        encoding="utf-8"
    )
    assert WAIVER_24H in waivers
    line = next(row for row in waivers.splitlines() if WAIVER_24H in row)
    assert "prober" in line.lower()
    assert "real" in line.lower()
    assert "calendar" in line.lower()
    assert "24h" in line.lower() or "24 h" in line.lower()
