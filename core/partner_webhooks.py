"""Hub-side Standard Webhooks signer and T1 Fake sink (§7 C7).

Delivery is Hub egress only. Intake never imports this module. ``whsec_`` is
vaulted Hub-side (``Secret.Kind.WEBHOOK_SECRET``) and never appears in
AuditEvent.detail. Re-resolve and re-run B10 on every send.
"""
import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from math import floor
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from django.utils import timezone as dj_timezone

from core.validators import validate_webhook_url

MAX_ATTEMPTS = 5
RETRY_WINDOW = timedelta(hours=24)

_delivered = set()  # (partner.pk, webhook-id)
_failures = {}  # partner.pk -> [datetime, ...]


class WebhookDeliveryError(RuntimeError):
    """A webhook POST failed. Never carries the signing secret."""


def reset_delivery_state():
    """Drop in-process attempt / idempotency maps. Tests and process start."""
    _delivered.clear()
    _failures.clear()


def webhook_sink_for(sink=None):
    """T1 default is the in-process Fake. Live HTTP is opt-in."""
    if sink is not None:
        return sink
    return FakeWebhookSink()


def sign_standard_webhook(secret, msg_id, timestamp, payload):
    """HMAC-SHA256 over ``id.timestamp.payload``; ``whsec_`` prefix (exact)."""
    if isinstance(secret, (bytes, bytearray)):
        secret = bytes(secret).decode()
    raw = secret
    if raw.startswith("whsec_"):
        raw = raw[len("whsec_"):]
    key = base64.b64decode(raw + "==")
    if isinstance(timestamp, datetime):
        ts = timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        ts_str = str(floor(ts.timestamp()))
    else:
        ts_str = str(int(timestamp))
    data = payload.decode() if isinstance(payload, (bytes, bytearray)) else payload
    to_sign = f"{msg_id}.{ts_str}.{data}".encode()
    signature = base64.b64encode(hmac.new(key, to_sign, hashlib.sha256).digest())
    return {
        "webhook-id": msg_id,
        "webhook-timestamp": ts_str,
        "webhook-signature": f"v1,{signature.decode('ascii')}",
    }


class FakeWebhookSink:
    """In-process sink. No socket, no live POST. Tests inject this."""

    _MUTATING = {"post"}

    def __init__(self):
        self.calls = []
        self.deliveries = []
        self.fail = False

    def mutating_calls(self):
        return [call for call in self.calls if call[0] in self._MUTATING]

    def post(self, url, headers, body):
        payload = body if isinstance(body, (bytes, bytearray)) else str(body).encode()
        self.calls.append(("post", url, dict(headers), payload))
        if self.fail:
            raise WebhookDeliveryError("fake sink failed")
        self.deliveries.append({
            "url": url,
            "headers": {str(key).lower(): value for key, value in headers.items()},
            "body": payload.decode(),
        })
        return {"status": "delivered"}


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise WebhookDeliveryError(f"webhook redirect refused ({code})")


class HttpWebhookSink:
    """Real Hub egress. Redirects off; Location is never followed."""

    def post(self, url, headers, body):
        payload = body if isinstance(body, (bytes, bytearray)) else str(body).encode()
        request = Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", **headers},
            method="POST",
        )
        opener = build_opener(_NoRedirect)
        try:
            # nosec B310 — scheme is https-only via validate_webhook_url
            # immediately before this call; redirects are refused above.
            with opener.open(request, timeout=20) as response:  # nosec B310
                return {"status": "delivered", "code": getattr(response, "status", 200)}
        except HTTPError as error:
            raise WebhookDeliveryError(
                f"webhook POST failed: HTTP {error.code}"
            ) from None


def _now(now):
    return now if now is not None else dj_timezone.now()


def _is_disabled(partner):
    from core.models import Finding

    return Finding.objects.filter(
        fingerprint=f"hub-egress-degraded:partner:{partner.pk}",
        state=Finding.State.OPEN,
    ).exists()


def _prune_failures(partner_pk, now):
    window_start = now - RETRY_WINDOW
    rows = [stamp for stamp in _failures.get(partner_pk, []) if stamp >= window_start]
    _failures[partner_pk] = rows
    return rows


def _file_egress_degraded(partner):
    from monitor.alerts import raise_alert

    entity = f"partner:{partner.pk}"
    raise_alert(
        "hub-egress-degraded",
        entity,
        fingerprint=f"hub-egress-degraded:partner:{partner.pk}",
        source_engine="partner_webhooks",
        title="Partner webhook delivery disabled",
        body="Hub egress to the partner webhook URL failed 5 times in 24 hours",
        fix_action="Repair the partner webhook endpoint, then retry delivery",
    )


def _record_failure(partner, now):
    rows = _prune_failures(partner.pk, now)
    rows.append(now)
    _failures[partner.pk] = rows
    if len(rows) >= MAX_ATTEMPTS:
        _file_egress_degraded(partner)


def _load_webhook_secret(partner):
    from vault import service as vault_service
    from vault.models import Secret

    secret = (
        Secret.objects.filter(
            kind=Secret.Kind.WEBHOOK_SECRET,
            owner_type="partner",
            owner_id=str(partner.pk),
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if secret is None:
        raise WebhookDeliveryError("no webhook secret in the vault")
    return vault_service.get(secret, reason="partner webhook sign")


def _payload_and_id(event):
    if isinstance(event, (bytes, bytearray)):
        body = bytes(event).decode()
        return body, None
    if isinstance(event, str):
        return event, None
    body = json.dumps(event, separators=(",", ":"), sort_keys=True)
    return body, event.get("id")


def deliver_partner_webhook(partner, event, *, sink=None, now=None):
    """Sign and POST one event. Re-reads webhook_url and re-runs B10 every time."""
    now = _now(now)
    sink = webhook_sink_for(sink)
    if getattr(partner, "pk", None) is not None:
        partner.refresh_from_db()
    if _is_disabled(partner):
        return {"status": "disabled"}

    body, msg_id = _payload_and_id(event)
    msg_id = msg_id or f"msg_{partner.pk}_{floor(now.timestamp())}"
    key = (partner.pk, msg_id)
    if key in _delivered:
        return {"status": "skipped"}

    url = (partner.webhook_url or "").strip()
    if not url:
        return {"status": "skipped"}
    validate_webhook_url(url, resolve=True)

    secret = _load_webhook_secret(partner)
    headers = sign_standard_webhook(secret, msg_id, now, body)
    try:
        sink.post(url, headers, body.encode())
    except WebhookDeliveryError:
        _record_failure(partner, now)
        raise
    _delivered.add(key)
    return {"status": "delivered"}
