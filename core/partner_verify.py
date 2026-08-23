"""Hub-authoritative Ed25519 re-verifier (design-note §7 C4).

Does not import intake. Consumes the shared vector file independently.
Nonce cache TTL 10 min; Idempotency-Key 24 h; 5-minute timestamp window.
"""
import base64
import hashlib
import json
import time
from pathlib import Path

from vault.ssh import verify_ed25519

WINDOW_S = 300
NONCE_TTL_S = 600
IDEMPOTENCY_TTL_S = 86400
VECTORS_PATH = (
    Path(__file__).resolve().parent.parent
    / "conformance"
    / "fixtures"
    / "partner-signature-vectors.json"
)


class SignatureRejected(Exception):
    status = 401


class ReplayRejected(Exception):
    status = 409


class VerifyResult:
    def __init__(self, ok, status=202, response=None, reason="", nonce=""):
        self.ok = ok
        self.status = status
        self.response = {} if response is None else response
        self.reason = reason
        self.nonce = nonce


def load_shared_vectors():
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def canonical_string(method, path, body, timestamp, nonce):
    if not isinstance(body, (bytes, bytearray)):
        body = b"" if body is None else str(body).encode("utf-8")
    digest = hashlib.sha256(bytes(body)).hexdigest()
    return f"{method}\n{path}\n{digest}\n{timestamp}\n{nonce}"


def _unix(now):
    if now is None:
        return int(time.time())
    if hasattr(now, "timestamp"):
        return int(now.timestamp())
    return int(now)


def _as_bytes(body):
    if body is None:
        return b""
    if isinstance(body, (bytes, bytearray)):
        return bytes(body)
    return str(body).encode("utf-8")


def _header(headers, name):
    if not headers:
        return ""
    if name in headers:
        return str(headers.get(name) or "").strip()
    wanted = name.lower()
    for key, value in headers.items():
        if str(key).lower() == wanted:
            return str(value or "").strip()
    return ""


def _load_pubkey(blob):
    raw = (blob or "").strip()
    if not raw:
        return None
    try:
        data = base64.b64decode(raw.encode("ascii"), validate=True)
    except (ValueError, TypeError):
        return None
    if len(data) != 32:
        return None
    return data


def _params_hash(method, path, body):
    material = f"{method}\n{path}\n".encode("utf-8") + _as_bytes(body)
    return hashlib.sha256(material).hexdigest()


def _clock(now):
    from django.utils import timezone

    if now is not None and hasattr(now, "year"):
        return now
    return timezone.now()


def _file_replay(partner):
    from monitor.alerts import raise_alert

    raise_alert(
        "partner-replay",
        f"partner:{partner.pk}",
        fingerprint=f"partner-replay:{partner.pk}",
        source_engine="core.partner_verify",
        title="Partner request replayed",
        body=(
            "A signed partner request reused a nonce the Hub already accepted. "
            "The Hub rejected it; intake forwarding does not override this."
        ),
        fix_action="Rotate the partner key if this was not an operator retry.",
    )


def _verify_signature(partner, method, path, body, headers, now):
    ts = _header(headers, "X-Partner-Timestamp")
    nonce = _header(headers, "X-Partner-Nonce")
    sig_b64 = _header(headers, "X-Partner-Signature")
    if not (ts and nonce and sig_b64):
        raise SignatureRejected("missing signature headers")
    try:
        ts_i = int(ts)
    except (TypeError, ValueError):
        raise SignatureRejected("invalid timestamp") from None
    if abs(_unix(now) - ts_i) > WINDOW_S:
        raise SignatureRejected("expired")
    try:
        signature = base64.b64decode(sig_b64.encode("ascii"), validate=True)
        message = canonical_string(method, path, body, ts, nonce).encode("ascii")
    except (ValueError, TypeError):
        raise SignatureRejected("invalid signature") from None
    keys = []
    for blob in (partner.pubkey_current, partner.pubkey_previous):
        key = _load_pubkey(blob)
        if key is not None:
            keys.append(key)
    if not keys:
        raise SignatureRejected("no partner public key")
    for key in keys:
        if verify_ed25519(key, signature, message):
            return nonce
    raise SignatureRejected("invalid signature")


def _remember_nonce(partner, nonce, now, *, persist=True):
    from datetime import timedelta

    from django.db import IntegrityError, transaction

    from core.models import PartnerReplayNonce

    clock = _clock(now)
    cutoff = clock - timedelta(seconds=NONCE_TTL_S)
    PartnerReplayNonce.objects.filter(partner=partner, seen_at__lt=cutoff).delete()
    if not persist:
        if PartnerReplayNonce.objects.filter(partner=partner, nonce=nonce).exists():
            _file_replay(partner)
            raise ReplayRejected("replayed nonce")
        return
    try:
        with transaction.atomic():
            PartnerReplayNonce.objects.create(partner=partner, nonce=nonce)
    except IntegrityError:
        _file_replay(partner)
        raise ReplayRejected("replayed nonce") from None


def _quota_refuse(partner, method, path):
    from django.conf import settings

    from core.models import PartnerSite

    if str(method).upper() != "POST":
        return False
    if str(path).rstrip("/") != "/partner/v1/sites":
        return False
    if partner.partner_sites.count() >= int(partner.max_sites):
        return True
    fleet_cap = int(getattr(settings, "PARTNER_FLEET_MAX_SITES", 12) or 12)
    return PartnerSite.objects.count() >= fleet_cap


def _idempotency_cached(partner, idem_key, params, now, nonce=""):
    """Return a live stored response, a 422 mismatch, or None if absent/expired.

    A match is ok only for 2xx so a cached quota 403 is not treated as accepted.
    """
    from datetime import timedelta

    from core.models import PartnerIdempotencyKey

    existing = PartnerIdempotencyKey.objects.filter(
        partner=partner, key=idem_key,
    ).first()
    if existing is None:
        return None
    cutoff = _clock(now) - timedelta(seconds=IDEMPOTENCY_TTL_S)
    created = existing.created_at
    if created is not None and created < cutoff:
        existing.delete()
        return None
    if existing.params_hash != params:
        return VerifyResult(
            False, status=422, reason="idempotency", nonce=nonce,
        )
    return VerifyResult(
        existing.status_code < 400,
        status=existing.status_code,
        response=existing.response,
        reason="idempotency-match",
        nonce=nonce,
    )


def _store_idempotency(partner, idem_key, params, result):
    from django.db import IntegrityError, transaction

    from core.models import PartnerIdempotencyKey

    if not idem_key:
        return
    try:
        with transaction.atomic():
            PartnerIdempotencyKey.objects.create(
                partner=partner,
                key=idem_key,
                params_hash=params,
                status_code=result.status,
                response=result.response,
            )
    except IntegrityError:
        return


def reverify(
    partner, method, path, body, headers, *, now=None,
    remember_nonce=True, persist_idempotency=True,
):
    """Re-verify a signed partner request against Partner pubkey slots.

    `remember_nonce=False` still rejects an already-consumed nonce
    (replay) but does not insert. `persist_idempotency=False` still
    returns a live matching/mismatching row but does not insert. The
    poller persists both after materialize+ack so operator-fixable
    refuses do not spend the nonce or cache a quota 403 as ok=True.
    """
    nonce = _verify_signature(partner, method, path, body, headers, now)
    # Replay is Hub-authoritative even when the request also carries a
    # matching Idempotency-Key (byte-for-byte replay ≠ Stripe retry).
    _remember_nonce(partner, nonce, now, persist=remember_nonce)
    idem_key = _header(headers, "Idempotency-Key")
    params = _params_hash(method, path, body)

    if idem_key:
        cached = _idempotency_cached(
            partner, idem_key, params, now, nonce=nonce,
        )
        if cached is not None:
            return cached

    if _quota_refuse(partner, method, path):
        result = VerifyResult(
            False, status=403, response={}, reason="quota", nonce=nonce,
        )
    else:
        result = VerifyResult(
            True, status=202, response={"accepted": True}, nonce=nonce,
        )

    if idem_key and persist_idempotency:
        _store_idempotency(partner, idem_key, params, result)
    return result
