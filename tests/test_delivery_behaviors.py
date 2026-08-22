"""Named delivery owners (D-037, ALERT-DELIVERY-BEHAVIORS).

Every severity-table behaviour has a module and a Beat entry. The repeat
scan is not piggybacked on probe-uptime.
"""
from __future__ import annotations

from datetime import timedelta

import pytest
from django.conf import settings
from django.core import mail
from django.utils import timezone

from core.models import Finding

pytestmark = [pytest.mark.django_db, pytest.mark.req("ALERT-DELIVERY-BEHAVIORS")]

COPY = dict(
    title="alert title",
    body="why this matters to the operator",
    fix_action="do the named fix",
)


@pytest.fixture(autouse=True)
def _reset_pager():
    from monitor.pager import reset_pager

    reset_pager()
    yield
    reset_pager()


def _p1(*, fingerprint, entity="site:repeat"):
    from monitor.alerts import raise_alert

    return raise_alert(
        "prod-site-hard-down",
        entity,
        fingerprint=fingerprint,
        **COPY,
    )


def test_unacked_p1_repeats_hourly_on_its_own_beat_entry():
    """What would make this fail: no Beat owner, a schedule other than 300 s,
    or skipping the hourly re-push of an open unacked P1."""
    from celery.schedules import crontab
    from django.conf import settings as dj

    from monitor import tasks as monitor_tasks
    from monitor.alerts import repeat_unacked
    from monitor.pager import get_pager

    entry = dj.CELERY_BEAT_SCHEDULE["alert-repeat-unacked"]
    assert entry["task"] == monitor_tasks.repeat_unacked.name
    assert float(entry["schedule"]) == 300.0
    assert not isinstance(entry["schedule"], crontab)

    row = _p1(fingerprint="site-down:hourly-repeat")
    pager = get_pager()
    first = len(pager.published)
    deliver_now = timezone.now()
    repeat_unacked(now=deliver_now + timedelta(minutes=30))
    assert len(pager.published) == first
    repeat_unacked(now=deliver_now + timedelta(hours=1))
    assert len(pager.published) == first + 1
    row.refresh_from_db()
    assert row.state == Finding.State.OPEN


def test_repeat_does_not_depend_on_the_probe_cycle_running():
    """What would make this fail: piggybacking repeats on probe-uptime so a
    stalled probe cycle silences the hourly page."""
    import ast
    import pathlib

    from monitor import tasks as monitor_tasks
    from monitor.alerts import repeat_unacked
    from monitor.pager import get_pager

    beat = settings.CELERY_BEAT_SCHEDULE
    assert beat["alert-repeat-unacked"]["task"] != beat["probe-uptime"]["task"]
    assert beat["alert-repeat-unacked"]["task"] == monitor_tasks.repeat_unacked.name
    assert beat["probe-uptime"]["task"] == monitor_tasks.probe_uptime.name

    src = (pathlib.Path(__file__).resolve().parent.parent / "monitor" / "alerts.py")
    tree = ast.parse(src.read_text(encoding="utf-8"))
    called = {
        getattr(node.func, "id", None) or getattr(node.func, "attr", None)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    assert "probe_cycle" not in called
    assert "probe_uptime" not in called

    _p1(fingerprint="site-down:no-probe")
    n = len(get_pager().published)
    repeat_unacked(now=timezone.now() + timedelta(hours=1))
    assert len(get_pager().published) == n + 1


def test_unacked_24h_sends_the_unacked_email():
    """What would make this fail: a 24 h open P1 with no [UNACKED] email."""
    from core.models import AlertState
    from monitor.alerts import repeat_unacked

    row = _p1(fingerprint="site-down:unacked-24h")
    opened = timezone.now() - timedelta(hours=24, minutes=1)
    Finding.objects.filter(pk=row.pk).update(first_seen=opened)
    state = AlertState.objects.get(fingerprint=row.fingerprint)
    state.opened_at = opened
    state.last_push_at = timezone.now()
    state.save(update_fields=["opened_at", "last_push_at"])
    mail.outbox.clear()
    repeat_unacked(now=timezone.now())
    assert mail.outbox, "24 h unacked must send email"
    assert any("[UNACKED]" in (msg.subject + msg.body) for msg in mail.outbox)


def test_daily_digest_runs_at_0800_local_and_contains_only_p3():
    """What would make this fail: a digest that is not 08:00 local, or that
    includes a P1/P2."""
    from celery.schedules import crontab

    from monitor import tasks as monitor_tasks
    from monitor.alerts import raise_alert
    from monitor.digest import build_digest

    entry = settings.CELERY_BEAT_SCHEDULE["digest-daily"]
    assert entry["task"] == monitor_tasks.build_digest.name
    schedule = entry["schedule"]
    assert isinstance(schedule, crontab)
    assert schedule.hour == {8}
    assert schedule.minute == {0}
    assert settings.CELERY_TIMEZONE == settings.TIME_ZONE

    raise_alert("prod-site-hard-down", "site:p1", fingerprint="digest-p1", **COPY)
    raise_alert("feed-data-stale", "feed:p2", fingerprint="digest-p2", **COPY)
    raise_alert("advice-tier", "site:p3", fingerprint="digest-p3", **COPY)
    result = build_digest(timezone.localdate())
    severities = {finding.severity for finding in result["findings"]}
    assert severities <= {Finding.Severity.P3, "p3"}
    assert any(finding.fingerprint == "digest-p3" for finding in result["findings"])
    assert all(finding.fingerprint != "digest-p1" for finding in result["findings"])
    assert all(finding.fingerprint != "digest-p2" for finding in result["findings"])


def test_weekly_rollup_has_an_owner_and_a_beat_entry():
    """What would make this fail: a weekly rollup with no owner, or no Beat
    entry honouring Monday 08:00 local."""
    from celery.schedules import crontab

    from monitor import tasks as monitor_tasks
    from monitor.digest import build_weekly_rollup

    entry = settings.CELERY_BEAT_SCHEDULE["digest-weekly"]
    assert entry["task"] == monitor_tasks.build_weekly_rollup.name
    schedule = entry["schedule"]
    assert isinstance(schedule, crontab)
    assert schedule.hour == {8}
    assert schedule.minute == {0}
    assert 1 in schedule.day_of_week  # Monday (cron: 0=Sunday)
    result = build_weekly_rollup(timezone.localdate())
    assert result["owner"]
    assert result["findings"] is not None


def test_grouped_p2_push_is_delivered_once():
    """What would make this fail: two P2s in the window producing two pushes."""
    from monitor.alerts import raise_alert
    from monitor.pager import deliver_grouped, get_pager

    raise_alert("feed-data-stale", "feed:a", fingerprint="stale:group-a", **COPY)
    raise_alert("feed-data-stale", "feed:b", fingerprint="stale:group-b", **COPY)
    pager = get_pager()
    before = len(pager.published)
    n = deliver_grouped(window=600)
    assert n == 1
    assert len(pager.published) == before + 1
