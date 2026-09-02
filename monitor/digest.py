"""P3 daily digest and weekly rollup (D-037) — same Finding set the inbox shows."""
from django.conf import settings
from django.core import mail

from core.models import Finding, Workspace


def inbox_findings(*, workspace, **filters):
    """Same Finding set the inbox list shows: one workspace, then severity, -last_seen."""
    if workspace is None:
        raise TypeError("inbox_findings requires workspace")
    return Finding.objects.filter(workspace=workspace, **filters).order_by(
        "severity", "-last_seen",
    )


def build_digest(day, *, workspace=None):
    """08:00 local P3 digest. `day` is a date; Beat honours TIME_ZONE."""
    mailed = []
    collected = []
    for ws in _digest_workspaces(workspace):
        rows = list(inbox_findings(workspace=ws, severity=Finding.Severity.P3))
        collected.extend(rows)
        mailed.append(_send(
            f"[HUB P3] digest {day} ({ws.slug})",
            _render(f"P3 digest {day}", rows),
        ))
    return {"day": day, "findings": collected, "severity": Finding.Severity.P3, "sent": mailed}


def build_weekly_rollup(week, *, workspace=None):
    """Monday 08:00 local. Owner is the alert recipient; findings are the inbox."""
    mailed = []
    collected = []
    for ws in _digest_workspaces(workspace):
        rows = list(inbox_findings(workspace=ws))
        collected.extend(rows)
        mailed.append(_send(
            f"[HUB] weekly rollup {week} ({ws.slug})",
            _render(f"weekly rollup {week}", rows),
        ))
    return {
        "week": week,
        "owner": getattr(settings, "HUB_ALERT_TO", "operator"),
        "findings": collected,
        "sent": mailed,
    }


def _digest_workspaces(workspace):
    if workspace is not None:
        return [workspace]
    return list(Workspace.objects.order_by("pk"))


def _render(heading, rows):
    lines = [heading, ""]
    for row in rows:
        lines.append(f"[{row.severity}] {row.title} ({row.entity})")
    return "\n".join(lines) if len(lines) > 2 else heading + "\n\n(none)"


def _file_smtp_failure(exc, recipient):
    from core.findings import finding
    from core.models import default_workspace

    finding(
        "monitor.digest",
        "digest:smtp-failed",
        workspace=default_workspace(),
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
