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
    body = _render(f"weekly rollup {week}", rows)
    _send(f"[HUB] weekly rollup {week}", body)
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


def _file_smtp_failure(exc, recipient):
    from core.findings import finding

    finding(
        "monitor.digest",
        "digest:smtp-failed",
        severity=Finding.Severity.P2,
        entity="digest",
        title="Digest SMTP send failed",
        body=(
            f"SMTP send failed ({type(exc).__name__}) to {recipient}. "
            "The push path was not blocked."
        ),
        fix_action=(
            "Check HUB_SMTP_* and the mail backend; retry the digest Beat."
        ),
    )


def _send(subject, body):
    recipient = getattr(settings, "HUB_ALERT_TO", "ops@localhost")
    try:
        mail.send_mail(
            subject,
            body,
            getattr(settings, "HUB_ALERT_FROM", "hub@localhost"),
            [recipient],
            fail_silently=False,
        )
    except Exception as exc:
        # Digest mail is not the push path; a failure here must not raise.
        try:
            _file_smtp_failure(exc, recipient)
        except Exception:
            return False
        return False
    return True
