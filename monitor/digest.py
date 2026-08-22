"""P3 daily digest and weekly rollup (D-037) — same Finding set the inbox shows."""
from django.conf import settings
from django.core import mail

from core.models import Finding


def inbox_findings(**filters):
    """Same Finding set the inbox list shows: filter + severity, -last_seen."""
    return Finding.objects.filter(**filters).order_by("severity", "-last_seen")


def build_digest(day):
    """08:00 local P3 digest. `day` is a date; Beat honours TIME_ZONE."""
    rows = list(inbox_findings(severity=Finding.Severity.P3))
    body = _render(f"P3 digest {day}", rows)
    _send(f"[HUB P3] digest {day}", body)
    return {"day": day, "findings": rows, "severity": Finding.Severity.P3}


def build_weekly_rollup(week):
    """Monday 08:00 local. Owner is the alert recipient; findings are the inbox."""
    rows = list(inbox_findings())
    return {
        "week": week,
        "owner": getattr(settings, "HUB_ALERT_TO", "operator"),
        "findings": rows,
    }


def _render(heading, rows):
    lines = [heading, ""]
    for row in rows:
        lines.append(f"[{row.severity}] {row.title} ({row.entity})")
    return "\n".join(lines) if len(lines) > 2 else heading + "\n\n(none)"


def _send(subject, body):
    try:
        mail.send_mail(
            subject,
            body,
            getattr(settings, "HUB_ALERT_FROM", "hub@localhost"),
            [getattr(settings, "HUB_ALERT_TO", "ops@localhost")],
            fail_silently=False,
        )
    except Exception:
        # Digest mail is not the push path; a failure here must not raise.
        return False
    return True
