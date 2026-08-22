"""raise_alert — classify, fingerprint, file through finding() (D-037/D-038).

after_raise is the one hand-off seam. monitor.antinoise installs its hook
over this name at import / AppConfig.ready(). observe(fingerprint, ok) is
the probe-level hysteresis API and is not called from here.
"""
from core.findings import finding
from monitor.alert_rules import classify


def after_raise(row):
    """Identity until monitor.antinoise replaces this with its hook."""
    return row


def _handoff(row):
    result = after_raise(row)
    row = row if result is None else result
    from monitor.pager import maybe_deliver

    maybe_deliver(row)
    return row


def repeat_unacked(*, now=None):
    """Re-push open unacked P1s hourly; 24 h still-open → [UNACKED] email.

    Own Beat entry (`alert-repeat-unacked`, 300 s). Not piggybacked on
    probe-uptime: a stalled probe cycle must not silence a repeat.
    """
    from datetime import timedelta

    from django.utils import timezone

    from core.models import AlertDelivery, AlertState, Finding
    from monitor.pager import deliver, send_unacked_email

    now = now or timezone.now()
    pushed = emailed = 0
    for row in Finding.objects.filter(
        severity=Finding.Severity.P1, state=Finding.State.OPEN,
    ):
        state, _ = AlertState.objects.get_or_create(fingerprint=row.fingerprint)
        due = (
            state.last_push_at is None
            or now - state.last_push_at >= timedelta(hours=1)
        )
        if due:
            row.will_push = True
            deliver(row, now=now)
            pushed += 1
        opened = state.opened_at or row.first_seen
        already = AlertDelivery.objects.filter(
            finding=row,
            channel=AlertDelivery.Channel.EMAIL,
            detail__icontains="UNACKED",
        ).exists()
        if not already and now - opened >= timedelta(hours=24):
            send_unacked_email(row, now=now)
            emailed += 1
    return {"ok": True, "pushed": pushed, "unacked_email": emailed}


def raise_alert(kind, entity, **facts):
    """classify → stable fingerprint → finding() → after_raise.

    ``fingerprint`` and ``source_engine`` may be passed in facts; the default
    fingerprint is ``{kind}:{entity}``. title/body/fix_action ride facts
    into finding() (§6.6). Remaining facts are classify() inputs only.
    """
    severity = classify(kind, **facts)
    fingerprint = facts.get("fingerprint") or f"{kind}:{entity}"
    source_engine = facts.get("source_engine", "monitor.alerts")
    row = finding(
        source_engine,
        fingerprint,
        severity=severity,
        entity=entity,
        title=facts.get("title", ""),
        body=facts.get("body", ""),
        fix_action=facts.get("fix_action", ""),
    )
    return _handoff(row)
