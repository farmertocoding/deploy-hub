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

from core.models import Finding, default_workspace

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
    from core.models import default_workspace
    from monitor.alerts import raise_alert

    return raise_alert(
        "prod-site-hard-down",
        entity,
        fingerprint=fingerprint,
        workspace=default_workspace(),
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

    ws = default_workspace()
    raise_alert(
        "prod-site-hard-down", "site:p1", fingerprint="digest-p1",
        workspace=ws, **COPY,
    )
    raise_alert(
        "feed-data-stale", "feed:p2", fingerprint="digest-p2",
        workspace=ws, **COPY,
    )
    raise_alert(
        "advice-tier", "site:p3", fingerprint="digest-p3",
        workspace=ws, **COPY,
    )
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


def test_weekly_rollup_sends_mail_via_locmem():
    """What would make this fail: weekly rollup returning the inbox set
    without calling mail.send_mail."""
    from monitor.alerts import raise_alert
    from monitor.digest import build_weekly_rollup

    raise_alert(
        "advice-tier", "site:p3", fingerprint="rollup-send-p3",
        workspace=default_workspace(), **COPY,
    )
    mail.outbox.clear()
    week = timezone.localdate()
    result = build_weekly_rollup(week)
    assert mail.outbox, "weekly rollup must send email"
    sent = mail.outbox[-1]
    assert str(week) in sent.subject
    assert any(finding.fingerprint == "rollup-send-p3" for finding in result["findings"])
    assert COPY["title"] in sent.body


def test_digest_smtp_failure_files_a_finding_and_does_not_raise(monkeypatch):
    """What would make this fail: a swallowed SMTP error with no Finding,
    or _send raising and blocking the caller."""
    from django.core import mail as django_mail

    from monitor.digest import _send, build_weekly_rollup

    leak = "vlt_secret_must_not_appear"

    def _boom(*args, **kwargs):
        raise OSError(f"smtp down token={leak}")

    monkeypatch.setattr(django_mail, "send_mail", _boom)
    week = timezone.localdate()
    result = build_weekly_rollup(week)
    assert result["findings"] is not None
    ok = _send(f"[HUB] weekly rollup {week}", f"mailbox body {leak}")
    assert ok is False
    filed = Finding.objects.get(fingerprint="digest:smtp-failed")
    assert filed.severity == Finding.Severity.P2
    hay = f"{filed.title}\n{filed.body}\n{filed.fix_action}"
    assert leak not in hay
    assert "token=" not in hay


def test_grouped_p2_push_is_delivered_once():
    """What would make this fail: two P2s in the window producing two pushes."""
    from monitor.alerts import raise_alert
    from monitor.pager import deliver_grouped, get_pager

    ws = default_workspace()
    raise_alert(
        "feed-data-stale", "feed:a", fingerprint="stale:group-a",
        workspace=ws, **COPY,
    )
    raise_alert(
        "feed-data-stale", "feed:b", fingerprint="stale:group-b",
        workspace=ws, **COPY,
    )
    pager = get_pager()
    before = len(pager.published)
    n = deliver_grouped(window=600)
    assert n == 1
    assert len(pager.published) == before + 1


def test_beat_invokes_deliver_grouped():
    """What would make this fail: no Beat owner for the P2 flush, so pending
    P2s stay on __pushes__ until a test calls deliver_grouped by hand."""
    from monitor import tasks as monitor_tasks
    from monitor.alerts import raise_alert
    from monitor.pager import get_pager

    entry = settings.CELERY_BEAT_SCHEDULE["alert-group-p2"]
    assert entry["task"] == monitor_tasks.deliver_grouped.name
    assert float(entry["schedule"]) == 300.0
    assert entry["task"] != settings.CELERY_BEAT_SCHEDULE["probe-uptime"]["task"]

    ws = default_workspace()
    raise_alert(
        "feed-data-stale", "feed:a", fingerprint="stale:beat-a",
        workspace=ws, **COPY,
    )
    raise_alert(
        "feed-data-stale", "feed:b", fingerprint="stale:beat-b",
        workspace=ws, **COPY,
    )
    pager = get_pager()
    before = len(pager.published)
    monitor_tasks.deliver_grouped()
    assert len(pager.published) == before + 1


def test_failed_publish_does_not_start_the_hourly_clock():
    """What would make this fail: a failed first P1 stamping last_push_at so
    repeat_unacked waits a full hour before retrying."""
    from core.models import AlertDelivery, AlertState
    from monitor.alerts import repeat_unacked
    from monitor.pager import get_pager

    pager = get_pager()
    pager.fail = True
    row = _p1(fingerprint="site-down:failed-clock")
    ntfy = AlertDelivery.objects.get(finding=row, channel=AlertDelivery.Channel.NTFY)
    assert ntfy.ok is False
    state = AlertState.objects.get(fingerprint=row.fingerprint)
    assert state.last_push_at is None

    pager.fail = False
    before = len(pager.published)
    repeat_unacked(now=timezone.now() + timedelta(minutes=5))
    assert len(pager.published) == before + 1


def test_failed_grouped_flush_retries():
    """What would make this fail: group_p2 marking delivered before publish,
    so a later Beat sees an empty window after a failed flush."""
    from monitor.alerts import raise_alert
    from monitor.pager import deliver_grouped, get_pager

    ws = default_workspace()
    raise_alert(
        "feed-data-stale", "feed:a", fingerprint="stale:retry-a",
        workspace=ws, **COPY,
    )
    raise_alert(
        "feed-data-stale", "feed:b", fingerprint="stale:retry-b",
        workspace=ws, **COPY,
    )
    pager = get_pager()
    pager.fail = True
    deliver_grouped(window=600)
    failed_n = len(pager.published)
    pager.fail = False
    n = deliver_grouped(window=600)
    assert n == 1
    assert len(pager.published) == failed_n + 1
