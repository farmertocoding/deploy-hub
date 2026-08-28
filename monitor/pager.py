"""deliver(finding) — minimized, scrubbed push + P1 email copy (D-036).

The push body is object · severity · duration · deep link (host aliases,
never raw IPs). Break-glass lives only in the email copy, prefixed
advisory-only. AlertDelivery records which backend delivered and whether
it succeeded. A failed email files a Finding and never blocks the push.
"""
import re

from django.conf import settings
from django.core import mail
from django.utils import timezone

from core.models import AlertDelivery, AlertState, Finding, Site, Target
from monitor.scrub import scrub

ADVISORY = "advisory only — re-read from the Findings inbox before typing"
_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")

_pager = None


def get_pager():
    global _pager
    if _pager is None:
        backend = getattr(settings, "HUB_PAGER_BACKEND", "fake")
        if backend == "ntfy":
            from providers.ntfy import NtfyPager

            _pager = NtfyPager()
        else:
            from providers.fakes import FakePager

            _pager = FakePager()
    return _pager


def reset_pager():
    global _pager
    _pager = None


def maybe_deliver(row, *, now=None):
    """First-push seam: P1 + will_push only. P2 waits for deliver_grouped."""
    if not isinstance(row, Finding):
        return None
    if row.severity != Finding.Severity.P1:
        return None
    if not getattr(row, "will_push", False):
        return None
    return deliver(row, now=now)


def deliver(finding, *, now=None, pager=None):
    now = now or timezone.now()
    pager = pager or get_pager()
    backend = getattr(settings, "HUB_PAGER_BACKEND", "fake")
    if finding.severity == Finding.Severity.P3:
        return {"ok": False, "skipped": "p3"}

    title, body, click = _minimized(finding, now)
    title, body = scrub(title), scrub(body)
    tags = ["rotating_light"] if finding.severity == Finding.Severity.P1 else ["warning"]
    push_ok = False
    push_detail = ""
    try:
        pager.publish(
            finding.severity, title, body, tags=tags, click_url=click,
        )
        push_ok = True
    except Exception as exc:
        push_detail = type(exc).__name__
    AlertDelivery.objects.create(
        finding=finding,
        channel=AlertDelivery.Channel.NTFY,
        severity=finding.severity,
        backend=backend,
        ok=push_ok,
        detail=push_detail,
    )
    if push_ok:
        _touch_last_push(finding, now)
    else:
        _release_failed_push_clock(finding)
    if finding.severity == Finding.Severity.P1:
        _email_p1(finding, backend, unacked=False)
    return {"ok": push_ok}


def deliver_grouped(*, window=600, now=None, pager=None):
    """Flush pending P2s: one publish per group_p2 batch.

    group_p2 is asked not to mark the window: a failed publish must stay
    pending so the next Beat tick retries instead of seeing an empty log.
    """
    from monitor.antinoise import group_p2, mark_p2_delivered

    now = now or timezone.now()
    pager = pager or get_pager()
    batches = group_p2(window=window, now=now, mark=False)
    n = 0
    for batch in batches:
        findings = batch.get("findings") or []
        if not findings:
            continue
        if batch.get("grouped"):
            ok = _publish_group(findings, pager=pager, now=now)
        else:
            ok = deliver(findings[0], now=now, pager=pager).get("ok")
        if ok:
            mark_p2_delivered(findings)
        n += 1
    return n


def send_unacked_email(finding, *, now=None):
    backend = getattr(settings, "HUB_PAGER_BACKEND", "fake")
    _email_p1(finding, backend, unacked=True)


def _publish_group(findings, *, pager, now):
    backend = getattr(settings, "HUB_PAGER_BACKEND", "fake")
    labels = [_object_label(row) for row in findings]
    click = f"{_public_url()}/#/findings"
    title = scrub(f"{len(findings)} P2 findings")
    body = scrub(f"{', '.join(labels)} · p2 · {click}")
    ok, detail = True, "grouped"
    try:
        pager.publish("p2", title, body, tags=["warning"], click_url=click)
    except Exception as exc:
        ok, detail = False, type(exc).__name__
    AlertDelivery.objects.create(
        finding=findings[0],
        channel=AlertDelivery.Channel.NTFY,
        severity=Finding.Severity.P2,
        backend=backend,
        ok=ok,
        detail=detail,
    )
    return ok


def _minimized(finding, now):
    obj = _object_label(finding)
    start = finding.first_seen
    minutes = max(0, int((now - start).total_seconds() // 60))
    click = f"{_public_url()}/#/findings/{finding.pk}"
    title = f"{obj} · {finding.severity} · {minutes} min"
    body = f"{obj} · {finding.severity} · {minutes} min · {click}"
    return title, body, click


def _object_label(finding):
    entity = finding.entity or ""
    kind, _, name = entity.partition(":")
    haystack = name or entity
    if not _IP.search(haystack):
        return name or entity
    ip = _IP.search(haystack).group(0)
    target = Target.objects.filter(host=ip).first()
    if target is not None:
        site = Site.objects.filter(primary_target=target).order_by("name").first()
        if site is not None:
            return site.name
        return f"host-{target.pk}"
    return kind or "host"


def _public_url():
    return getattr(settings, "HUB_PUBLIC_URL", "https://hub.local").rstrip("/")


def _touch_last_push(finding, now):
    state, _ = AlertState.objects.get_or_create(
        workspace=finding.workspace, fingerprint=finding.fingerprint,
    )
    state.last_push_at = now
    state.save(update_fields=["last_push_at"])


def _release_failed_push_clock(finding):
    """A failed publish must not start the hourly repeat clock.

    after_raise stamps last_push_at when will_push is set; that stamp is
    not a successful delivery. Leave a prior successful stamp alone so a
    failed hourly retry is still due on the next 300 s tick.
    """
    has_ok = AlertDelivery.objects.filter(
        finding=finding,
        channel=AlertDelivery.Channel.NTFY,
        ok=True,
    ).exists()
    if has_ok:
        return
    state, _ = AlertState.objects.get_or_create(
        workspace=finding.workspace, fingerprint=finding.fingerprint,
    )
    if state.last_push_at is None:
        return
    state.last_push_at = None
    state.save(update_fields=["last_push_at"])


def _email_p1(finding, backend, *, unacked):
    subject = scrub(f"[HUB P1] {finding.title}")
    if unacked:
        subject = scrub(f"[UNACKED] {subject}")
    alias = _object_label(finding)
    body = scrub(
        f"{finding.title}\n\n{finding.body}\n\n"
        f"{ADVISORY}\n\n"
        f"ssh {alias}  # docker restart — re-read from the Findings inbox before typing\n"
    )
    ok, detail = True, "[UNACKED]" if unacked else ""
    try:
        mail.send_mail(
            subject,
            body,
            getattr(settings, "HUB_ALERT_FROM", "hub@localhost"),
            [getattr(settings, "HUB_ALERT_TO", "ops@localhost")],
            fail_silently=False,
        )
    except Exception as exc:
        ok, detail = False, type(exc).__name__
        _file_email_failure(finding, exc)
    AlertDelivery.objects.create(
        finding=finding,
        channel=AlertDelivery.Channel.EMAIL,
        severity=finding.severity,
        backend=backend,
        ok=ok,
        detail=detail,
    )


def _file_email_failure(finding, exc):
    from monitor.alerts import raise_alert

    raise_alert(
        "pager-email-failed",
        finding.entity,
        fingerprint=f"pager-email-failed:{finding.pk}",
        workspace=finding.workspace,
        source_engine="monitor.pager",
        title="Alert email failed",
        body=(
            f"SMTP send failed ({type(exc).__name__}) for finding "
            f"{finding.pk}. The push path was not blocked."
        ),
        fix_action=(
            "Check HUB_SMTP_* and the mail backend; re-send from the "
            "Findings inbox."
        ),
    )
