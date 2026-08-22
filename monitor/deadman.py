"""Dead-man ping + canary rule (Task 8 — alert-protocol §5, D-039,
MON-DEADMAN-EXTERNAL).

The ping fires ONLY after a probe cycle completed every target (§C7): it is
the external receiver's proof that scheduler + broker + worker + probe ran
end-to-end this minute, so a partial or crashed cycle must stay silent and
let the receiver's missed-ping alarm fire. The receiver URL is a vault
secret resolved by ref — settings, logs, task args and Finding bodies never
carry it. A failed or unreachable POST files its own Finding (panel r2): a
watcher that cannot be reached is exactly the silence the switch exists to
break, and the misconfigured-URL failure mode must never be permanent quiet.
The receiver's registration itself is a Task 19 demo artifact.
"""
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from django.conf import settings
from django.utils import timezone

from core.audit import audit
from core.models import Finding

DEADMAN_TIMEOUT_S = 10
CANARY_TIMEOUT_S = 10

# One stable fingerprint: minutely repeats update last_seen on ONE row —
# deduped, never one Finding per minute.
DEADMAN_FINDING_FINGERPRINT = "deadman:post-failed"


def http_post_default(url, *, timeout=DEADMAN_TIMEOUT_S):
    """Default POST seam: empty body, bounded timeout, returns the status."""
    request = Request(url, data=b"", method="POST")
    # nosec justification: the URL comes from the operator-stored vault
    # secret, scheme pinned https at registration; never caller input.
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            return response.status
    except HTTPError as error:
        return error.code


def _resolve_receiver_url():
    """Vault ref → receiver URL (the Target.ssh_key_ref pattern; newest row
    wins so rotation takes effect immediately). None when unconfigured."""
    from vault import service as vault_service
    from vault.models import Secret

    secret = (
        Secret.objects.filter(
            kind=Secret.Kind.API_TOKEN,
            owner_type="deadman",
            owner_id=settings.HUB_DEADMAN_URL_REF,
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if secret is None:
        return None
    return vault_service.get(secret, reason="dead-man ping").decode().strip()


def _file_finding(*, source_engine, severity, entity, title, body,
                  fix_action, fingerprint):
    """File through the Finding primitive Task 4's service layer wraps.

    SEAM (named in the task report): when Task 4's core.findings.finding()
    merges, this body becomes the one line
    `return finding(source_engine, fingerprint, severity=..., ...)`.
    """
    row = Finding.objects.filter(fingerprint=fingerprint).first()
    if row is not None:
        row.last_seen = timezone.now()
        row.save(update_fields=["last_seen"])
        return row
    row = Finding.objects.create(
        source_engine=source_engine,
        severity=severity,
        entity=entity,
        title=title,
        body=body,
        fix_action=fix_action,
        fingerprint=fingerprint,
    )
    audit("finding-filed", row, source="system", severity="warning",
          fingerprint=fingerprint)
    return row


def _file_deadman_finding(reason):
    return _file_finding(
        source_engine="monitor.deadman",
        severity=Finding.Severity.P2,
        entity="hub:deadman",
        title="Dead-man POST failed — the watcher cannot hear the Hub",
        body=(
            f"The after-cycle dead-man POST did not reach its receiver "
            f"({reason}). Until it does, the external missed-ping alarm is "
            f"the only thing standing behind a dead Hub — and a "
            f"misconfigured receiver URL would otherwise be permanent "
            f"silence (alert-protocol §5)."
        ),
        fix_action=(
            f"Check the vault secret under ref "
            f"{settings.HUB_DEADMAN_URL_REF!r} (owner_type=deadman) and the "
            f"receiver's registration artifact in the phase-3 demo record."
        ),
        fingerprint=DEADMAN_FINDING_FINGERPRINT,
    )


def ping(*, http_post=None, now=None):
    """POST the receiver once. Every failure mode files the deduped Finding:
    missing vault secret, non-2xx, unreachable. The URL never enters logs,
    audit detail, task args or the Finding text."""
    post = http_post or http_post_default
    url = _resolve_receiver_url()
    if url is None:
        _file_deadman_finding("no vault secret under the configured ref")
        return {"pinged": False, "ok": False, "reason": "unconfigured"}
    try:
        status = post(url, timeout=DEADMAN_TIMEOUT_S)
        ok = status is not None and 200 <= int(status) < 300
    except OSError as exc:
        status, ok = None, False
        reason = f"unreachable ({type(exc).__name__})"
    else:
        reason = f"HTTP {status}"
    if ok:
        audit("deadman-ping", source="system")
        return {"pinged": True, "ok": True}
    _file_deadman_finding(reason)
    audit("deadman-ping-failed", source="system", severity="warning",
          status=status or 0)
    return {"pinged": True, "ok": False}


def ping_after_cycle(cycle, *, http_post=None, now=None):
    """The §C7 gate: ping only when the cycle completed EVERY target. A DOWN
    site is a completed probe; an incomplete cycle stays silent so the
    receiver's missed-ping alarm fires."""
    if not isinstance(cycle, dict) or cycle.get("completed") is not True:
        return {"pinged": False, "ok": False, "reason": "cycle-incomplete"}
    return ping(http_post=http_post, now=now)


def canary_ok(*, http_get=None):
    """Probe the known-good external endpoint (§5.3). Bounded timeout;
    any response counts — the question is egress, not the endpoint's mood."""
    from monitor.uptime import http_probe

    get = http_get or http_probe
    try:
        status = get(settings.HUB_CANARY_URL, host=None,
                     timeout=CANARY_TIMEOUT_S)
    except OSError:
        return False
    return status is not None and 200 <= int(status) < 500


def declare_mass_outage(candidates, *, http_get=None):
    """The canary rule PRECEDES the declaration: probe the canary first, and
    if the Hub itself is blind, collapse N would-be site-down pages into one
    'Hub egress degraded' P2 naming what it swallowed."""
    if not canary_ok(http_get=http_get):
        suppressed = [str(entity) for entity in candidates]
        return [{
            "kind": "hub-egress-degraded",
            "severity": "p2",
            "entity": "hub",
            "title": f"Hub egress degraded — canary unreachable "
                     f"({len(suppressed)} site alerts suppressed)",
            "suppressed": suppressed,
        }]
    return [
        {
            "kind": "site-down",
            "severity": "p1",
            "entity": str(entity),
            "title": f"{entity} down",
        }
        for entity in candidates
    ]
