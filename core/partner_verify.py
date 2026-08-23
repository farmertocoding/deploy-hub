"""Hub-authoritative Ed25519 re-verifier (design-note §7 C4).

Does not import intake. Consumes the shared vector file independently.
Nonce cache TTL 10 min; Idempotency-Key 24 h; 5-minute timestamp window.
U2 quotas re-read Partner via .values() so intake allow cannot override.
"""
import base64
import hashlib
import json
import re
import time
from datetime import datetime, timedelta
from datetime import timezone as dt_tz
from pathlib import Path

from vault.ssh import verify_ed25519

WINDOW_S = 300
NONCE_TTL_S = 600
IDEMPOTENCY_TTL_S = 86400
RATE_GENERAL_PER_MIN = 60
RATE_DEPLOY_CREATE_PER_MIN = 3
RATE_DEPLOY_CREATE_PER_DAY = 100
DEFAULT_FLEET_MAX_SITES = 12
VECTORS_PATH = (
    Path(__file__).resolve().parent.parent
    / "conformance"
    / "fixtures"
    / "partner-signature-vectors.json"
)
_SITES_PATH = re.compile(r"^/partner/v1/sites/?$")
_DEPLOY_PATH = re.compile(r"^/partner/v1/sites/([^/]+)/deployments/?$")
_DOMAIN_PATH = re.compile(r"^/partner/v1/sites/([^/]+)/domains/?$")


class SignatureRejected(Exception):
    status = 401


class ReplayRejected(Exception):
    status = 409


class VerifyResult:
    def __init__(self, ok, status=202, response=None, reason="", nonce="", headers=None):
        self.ok = ok
        self.status = status
        self.response = {} if response is None else response
        self.reason = reason
        self.nonce = nonce
        self.headers = {} if headers is None else headers


class QuotaDecision:
    def __init__(self, refused, reason="", status=403, headers=None):
        self.refused = refused
        self.reason = reason
        self.status = status
        self.headers = {} if headers is None else headers


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


def _as_dt(now):
    from django.utils import timezone

    if now is None:
        return timezone.now()
    if hasattr(now, "year"):
        return now
    return datetime.fromtimestamp(int(now), tz=dt_tz.utc)


def _json_object(body):
    if isinstance(body, dict):
        return body
    if body in (None, "", b""):
        return {}
    if isinstance(body, (bytes, bytearray)):
        body = body.decode("utf-8")
    try:
        parsed = json.loads(body)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _rate_headers(limit, used, reset_unix):
    remaining = max(0, int(limit) - int(used))
    return {
        "X-RateLimit-Limit": str(int(limit)),
        "X-RateLimit-Remaining": str(remaining),
        "X-RateLimit-Reset": str(int(reset_unix)),
    }


def _partner_quota_row(partner_pk):
    from core.models import Partner

    return (
        Partner.objects.filter(pk=partner_pk)
        .values("max_sites", "deploys_per_day", "domains")
        .first()
    )


def _file_quota_abuse(partner, reason):
    from monitor.alerts import raise_alert

    pk = partner.pk
    slug = getattr(partner, "slug", "") or ""
    raise_alert(
        "budget-cap-hit",
        "partner",
        fingerprint="budget-cap-hit:partner",
        source_engine="core.partner_verify",
        title="Partner quota cap hit",
        body=(
            f"Partner {pk} ({slug}) exceeded a Hub-authoritative U2 quota "
            f"({reason}). Intake allow does not override this refuse."
        ),
        fix_action=(
            "Reduce partner usage or raise the finite quota on this Partner; "
            "unbounded max_sites is out."
        ),
    )


def _resolve_partner_site(partner, token):
    from core.models import PartnerSite

    qs = PartnerSite.objects.filter(partner=partner)
    if str(token).isdigit():
        row = qs.filter(site_id=int(token)).select_related("site").first()
        if row is not None:
            return row.site
    row = qs.filter(tenant_ref=str(token)).select_related("site").first()
    return None if row is None else row.site


def _general_rate_used(partner, nonce, minute_start):
    from core.models import PartnerReplayNonce

    qs = PartnerReplayNonce.objects.filter(
        partner=partner, seen_at__gte=minute_start,
    )
    if nonce:
        qs = qs.exclude(nonce=nonce)
    return qs.count()


def evaluate_quotas(partner, method, path, *, now=None, body=None, nonce=""):
    """Hub-authoritative U2 quotas. Re-reads Partner via .values(); intake cannot override."""
    from django.conf import settings

    from core.models import PartnerSite, Site
    from deploys.models import Deployment

    clock = _as_dt(now)
    minute_start = clock - timedelta(seconds=60)
    day_start = clock - timedelta(days=1)
    reset_unix = int(clock.timestamp()) + 60
    method = str(method or "").upper()
    path = str(path or "")
    general_used = _general_rate_used(partner, nonce, minute_start)
    general_headers = _rate_headers(
        RATE_GENERAL_PER_MIN, general_used, reset_unix,
    )

    def _refuse(reason, status, headers):
        _file_quota_abuse(partner, reason)
        return QuotaDecision(
            True, reason=reason, status=status, headers=headers,
        )

    if general_used >= RATE_GENERAL_PER_MIN:
        return _refuse("rate", 429, _rate_headers(
            RATE_GENERAL_PER_MIN, general_used, reset_unix,
        ))

    row = _partner_quota_row(partner.pk)
    if row is None:
        return _refuse("quota", 403, general_headers)
    max_sites = int(row["max_sites"] or 0)
    deploys_per_day = int(row["deploys_per_day"] or 0)
    domains = int(row["domains"] or 0)
    if min(max_sites, deploys_per_day, domains) < 1:
        return _refuse("quota", 403, general_headers)

    payload = _json_object(body)
    if method == "POST" and _SITES_PATH.match(path):
        tenant_ref = str(payload.get("tenant_ref") or "").strip()
        existing = False
        if tenant_ref:
            existing = PartnerSite.objects.filter(
                partner=partner, tenant_ref=tenant_ref,
            ).exists()
        if not existing:
            if PartnerSite.objects.filter(partner=partner).count() >= max_sites:
                return _refuse("quota", 403, general_headers)
            fleet_cap = int(
                getattr(settings, "PARTNER_FLEET_MAX_SITES", DEFAULT_FLEET_MAX_SITES)
                or DEFAULT_FLEET_MAX_SITES
            )
            if PartnerSite.objects.count() >= fleet_cap:
                return _refuse("quota", 403, general_headers)

    deploy_match = _DEPLOY_PATH.match(path)
    if method == "POST" and deploy_match:
        day_count = Deployment.objects.filter(
            manifest__site__partner_site__partner=partner,
            manifest__created_at__gte=day_start,
        ).count()
        if day_count >= deploys_per_day:
            return _refuse("quota", 403, general_headers)
        site = _resolve_partner_site(partner, deploy_match.group(1))
        if site is not None:
            per_min = Deployment.objects.filter(
                manifest__site=site,
                manifest__created_at__gte=minute_start,
            ).count()
            deploy_headers = _rate_headers(
                RATE_DEPLOY_CREATE_PER_MIN, per_min, reset_unix,
            )
            if per_min >= RATE_DEPLOY_CREATE_PER_MIN:
                return _refuse("rate", 429, deploy_headers)
            per_day = Deployment.objects.filter(
                manifest__site=site,
                manifest__created_at__gte=day_start,
            ).count()
            if per_day >= RATE_DEPLOY_CREATE_PER_DAY:
                return _refuse("rate", 429, _rate_headers(
                    RATE_DEPLOY_CREATE_PER_DAY, per_day, reset_unix,
                ))
            return QuotaDecision(False, headers=deploy_headers)

    domain_match = _DOMAIN_PATH.match(path)
    if method == "POST" and domain_match:
        names = {
            (name or "").casefold()
            for name in Site.objects.filter(partner_site__partner=partner)
            .exclude(domain="")
            .values_list("domain", flat=True)
        }
        extra = str(
            payload.get("hostname") or payload.get("domain") or "",
        ).strip().casefold()
        if extra and extra not in names and len(names) >= domains:
            return _refuse("quota", 403, general_headers)

    return QuotaDecision(False, headers=general_headers)


def _quota_refuse(partner, method, path, *, now=None, body=None, nonce=""):
    return evaluate_quotas(
        partner, method, path, now=now, body=body, nonce=nonce,
    ).refused


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

    decision = evaluate_quotas(
        partner, method, path, now=now, body=body, nonce=nonce,
    )
    if decision.refused:
        result = VerifyResult(
            False, status=decision.status, response={},
            reason=decision.reason, nonce=nonce, headers=decision.headers,
        )
    else:
        result = VerifyResult(
            True, status=202, response={"accepted": True}, nonce=nonce,
            headers=decision.headers,
        )

    if idem_key and persist_idempotency:
        _store_idempotency(partner, idem_key, params, result)
    return result
