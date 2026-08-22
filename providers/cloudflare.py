"""Product Cloudflare DNS adapter (§D5, D-034) — the client the pipeline and
the credentialed T3 leg both drive.

Constructed ONLY by providers.registry.dns_provider_for, which enforces scope
synchronously before this class exists (Bearer-only, active-token verify, the
pinned one-zone probe — D-046); tests/test_dns_zone_wall.py AST-scans for any
other construction site. The client is bound to exactly one DnsZone and
refuses calls that name a different one.

The token appears in the Authorization header and nowhere else: not in repr,
not in logs (this module logs nothing), not in exception text.
"""
import json
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from .base import DnsProvider

API = "https://api.cloudflare.com/client/v4"

# The pinned SEC-B5 observation endpoints (D-046). These literals live HERE
# and nowhere else: providers/registry.py (construction) and
# monitor/token_audit.py (the daily audit) both consume observe_token, so the
# enforcement and the audit that backs it up cannot drift into two spellings
# — tests/test_cf_token_audit.py scans both consumers for a re-spelling.
TOKEN_VERIFY_PATH = "/user/tokens/verify"
ZONE_PROBE_PATH = "/zones?per_page=50"

# Header names whose presence marks the legacy Global API Key credential
# shape, refused outright before any request (D-046 / SEC-B5).
_GLOBAL_KEY_MARKERS = {"x-auth-key", "x-auth-email", "api_key", "email"}


class CloudflareError(RuntimeError):
    """A Cloudflare call failed. Never carries the token."""


class CloudflareApiError(CloudflareError):
    def __init__(self, message, *, status=None):
        super().__init__(message)
        self.status = status


def refuse_global_api_key(credential):
    """Bearer only: return the token string or refuse the credential.

    A mapping — or a JSON document that parses to one — is the
    X-Auth-Key/X-Auth-Email Global API Key header shape and is refused
    before any request is built (D-046).
    """
    if isinstance(credential, (bytes, bytearray)):
        credential = credential.decode()
    if isinstance(credential, dict):
        raise CloudflareError(
            "refused: credential has the Global API Key header shape "
            "(X-Auth-Key/X-Auth-Email) — only a scoped Bearer token is accepted"
        )
    text = str(credential).strip()
    try:
        parsed = json.loads(text)
    except ValueError:
        parsed = None
    if isinstance(parsed, dict):
        keys = {str(key).lower() for key in parsed}
        shape = "Global API Key" if keys & _GLOBAL_KEY_MARKERS else "structured"
        raise CloudflareError(
            f"refused: credential is a {shape} document, not a Bearer token"
        )
    if not text:
        raise CloudflareError("refused: empty credential")
    return text


def api_request(token, method, path, payload=None, *, timeout=20):
    """One Cloudflare v4 call. The token goes into the Authorization header
    and nowhere else — never into logs, task args, or error messages."""
    request = Request(
        API + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method=method,
    )
    # nosec justification: the scheme is pinned — every URL is API + path
    # where API is the https:// Cloudflare constant above; no caller input
    # can change the scheme to file:/ or custom.
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise CloudflareApiError(
            f"cloudflare API {method} {path} failed: HTTP {error.code}",
            status=error.code,
        ) from None
    if not body.get("success", False):
        raise CloudflareApiError(
            f"cloudflare API {method} {path} failed: {body.get('errors')}"
        )
    return body


def observe_token(token, *, timeout=20):
    """The one spelling of SEC-B5's pinned token observation (D-046).

    verify proves liveness (it returns no policy set, so it can never prove
    scope); the zone-set probe proves reach. Returns
    ``{"status": <verify result.status>, "zones": [{"id", "name"}, ...]}``.
    The probe is skipped when verify already failed the token — a dead
    credential's reach is not worth a second request, and the construction
    wall's tests pin that an inactive token sends exactly one request.

    Read-only, GETs only. Judgment stays with the callers: the registry
    refuses construction on anything but exactly the one expected zone; the
    daily audit files Findings on drift against the declared zone rows.
    """
    verify = api_request(token, "GET", TOKEN_VERIFY_PATH, timeout=timeout)
    status = (verify.get("result") or {}).get("status")
    if status != "active":
        return {"status": status, "zones": []}
    probe = api_request(token, "GET", ZONE_PROBE_PATH, timeout=timeout)
    zones = [
        {"id": row.get("id"), "name": row.get("name")}
        for row in probe.get("result") or []
    ]
    return {"status": status, "zones": zones}


def verify_token(token_ref, *, timeout=20):
    """Resolve a DnsAccount vault ref and observe it (Task 2's audit entry).

    The ref is loaded through the registry's vault seam (never a raw value in
    a signature the caller might log), refused pre-network on a Global-API-Key
    shape, then observed through observe_token. No mutation anywhere.
    """
    from .registry import _load_token

    _, raw = _load_token(token_ref)
    return observe_token(refuse_global_api_key(raw), timeout=timeout)


class CloudflareDnsProvider(DnsProvider):
    """Cloudflare client bound to one verified DnsZone."""

    def __init__(self, zone, *, token, timeout=20, on_auth_error=None):
        self.zone = zone
        self._token = refuse_global_api_key(token)
        self.timeout = timeout
        # Registry hook: a 401/403 mid-use drops the cached scope verification
        # so the next construction re-verifies rather than trusting the cache.
        self._on_auth_error = on_auth_error

    def __repr__(self):
        return f"<CloudflareDnsProvider zone={self.zone.name!r}>"

    __str__ = __repr__

    def list_records(self, zone):
        """All records in the zone, following list pagination (2.5 minor)."""
        zone_id = self._zone_id(zone)
        page, rows = 1, []
        while True:
            query = urlencode({"per_page": 100, "page": page})
            body = self._api("GET", f"/zones/{zone_id}/dns_records?{query}")
            rows.extend(body["result"])
            info = body.get("result_info") or {}
            if page >= int(info.get("total_pages") or 1):
                break
            page += 1
        return [
            {
                "id": row["id"],
                "name": row["name"],
                "rtype": row["type"],
                "values": [row["content"]],
                "proxied": row.get("proxied", False),
                "ttl": row.get("ttl"),
            }
            for row in rows
        ]

    def upsert_record(self, zone, name, rtype, values, *, proxied=False, ttl=None):
        """A diff, not a blind write: rows already matching (content, proxied,
        ttl) are left untouched; changed rows are PUT, missing rows POSTed,
        stale extras DELETEd. Cloudflare stores one content per record, so a
        multi-value upsert is one record per value. Returns the first record
        id; callers treat it as opaque.
        """
        zone_id = self._zone_id(zone)
        current = [
            rec for rec in self.list_records(zone)
            if rec["name"] == name and rec["rtype"] == rtype
        ]
        # ttl=1 is Cloudflare's spelling of "automatic".
        wanted_ttl = int(ttl or 1)
        record_id = None
        for index, value in enumerate(values):
            if index < len(current):
                row = current[index]
                if (
                    row["values"] == [value]
                    and row["proxied"] == bool(proxied)
                    and int(row.get("ttl") or 1) == wanted_ttl
                ):
                    record_id = record_id or row["id"]
                    continue
            payload = {
                "type": rtype,
                "name": name,
                "content": value,
                "proxied": bool(proxied),
                "ttl": wanted_ttl,
            }
            if index < len(current):
                result = self._api(
                    "PUT",
                    f"/zones/{zone_id}/dns_records/{current[index]['id']}",
                    payload,
                )
            else:
                result = self._api("POST", f"/zones/{zone_id}/dns_records", payload)
            record_id = record_id or result["result"]["id"]
        for stale in current[len(values):]:
            self.delete_record(zone, stale["id"])
        return record_id

    def delete_record(self, zone, record_id):
        zone_id = self._zone_id(zone)
        try:
            self._api("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
        except CloudflareApiError as error:
            if error.status != 404:  # absent == success, like the fake
                raise

    def get_nameservers(self, domain):
        body = self._api("GET", f"/zones/{self.zone.provider_zone_id}")
        return list(body["result"].get("name_servers") or [])

    def capabilities(self):
        # DnsZone.proxied_default documents itself as "surfaced by
        # capabilities()" — this set is that surface.
        return {"proxied"}

    def _zone_id(self, zone):
        """The client exists for exactly one zone; a different one refuses."""
        if zone is not None and zone is not self.zone:
            same_row = (
                getattr(zone, "pk", None) is not None
                and getattr(zone, "pk", None) == self.zone.pk
            )
            if not same_row:
                raise CloudflareError(
                    f"this client is bound to zone {self.zone.name!r}; "
                    f"refusing a call for a different zone"
                )
        return self.zone.provider_zone_id

    def _api(self, method, path, payload=None):
        try:
            return api_request(
                self._token, method, path, payload, timeout=self.timeout,
            )
        except CloudflareApiError as error:
            if error.status in (401, 403) and self._on_auth_error is not None:
                self._on_auth_error()
            raise
