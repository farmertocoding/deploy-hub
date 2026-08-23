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

from .base import DnsProvider, EdgeProtection, OriginCertIssuer

API = "https://api.cloudflare.com/client/v4"

# The pinned SEC-B5 observation endpoints (D-046). These literals live HERE
# and nowhere else: providers/registry.py (construction) and
# monitor/token_audit.py (the daily audit) both consume observe_token, so the
# enforcement and the audit that backs it up cannot drift into two spellings
# — tests/test_cf_token_audit.py scans both consumers for a re-spelling.
TOKEN_VERIFY_PATH = "/user/tokens/verify"  # nosec B105 — API path, not a password
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


def zone_set_size(probe):
    """The token's zone-set size from a GET /zones probe body (D-046).

    When result_info.total_count is present, that integer is the set size —
    a one-row page is not one zone (a later per_page=1 must not construct
    an over-scoped token). When total_count is absent, fall back to
    len(result), today's rule, so probe bodies that omit result_info still
    construct when they contain exactly one row.
    """
    info = probe.get("result_info") or {}
    if not isinstance(info, dict):
        info = {}
    if "total_count" in info and info["total_count"] is not None:
        return int(info["total_count"])
    return len(probe.get("result") or [])


def observe_token(token, *, timeout=20):
    """The one spelling of SEC-B5's pinned token observation (D-046).

    verify proves liveness (it returns no policy set, so it can never prove
    scope); the zone-set probe proves reach. Returns
    ``{"status": <verify result.status>, "zones": [{"id", "name"}, ...],
    "zone_count": <set size>}``. ``zone_count`` is the set-size fact
    ``zone_set_size`` reads from the probe — ``result_info.total_count``
    when present, else ``len(result)``. A one-row page is never returned
    as "one zone" when that fact is not 1.

    The probe is skipped when verify already failed the token — a dead
    credential's reach is not worth a second request, and the construction
    wall's tests pin that an inactive token sends exactly one request.

    Read-only, GETs only, and safe by construction: the token is shape-refused
    here (refuse_global_api_key), so no consumer can put a Global API Key on
    the wire by handing this helper a raw vault value. Judgment stays with the
    callers: the registry refuses construction on anything but exactly the one
    expected zone; the daily audit files Findings on drift against the
    declared zone rows. Both judges must use ``zone_count``, not page length.
    """
    token = refuse_global_api_key(token)
    verify = api_request(token, "GET", TOKEN_VERIFY_PATH, timeout=timeout)
    status = (verify.get("result") or {}).get("status")
    if status != "active":
        return {"status": status, "zones": [], "zone_count": 0}
    probe = api_request(token, "GET", ZONE_PROBE_PATH, timeout=timeout)
    rows = [
        {"id": row.get("id"), "name": row.get("name")}
        for row in probe.get("result") or []
    ]
    count = zone_set_size(probe)
    # Do not return a one-row page as "one zone" when the set is not 1.
    zones = [] if count != 1 and len(rows) == 1 else rows
    return {"status": status, "zones": zones, "zone_count": count}


def origin_ca_request(origin_ca_key, method, path, payload=None, *, timeout=20):
    """One Origin CA call. The service key goes into X-Auth-User-Service-Key
    and nowhere else — never Bearer, never logs, never error text."""
    if isinstance(origin_ca_key, (bytes, bytearray)):
        origin_ca_key = origin_ca_key.decode()
    request = Request(
        API + path,
        data=None if payload is None else json.dumps(payload).encode(),
        headers={
            "X-Auth-User-Service-Key": origin_ca_key,
            "Content-Type": "application/json",
        },
        method=method,
    )
    # nosec justification: scheme is pinned to the https:// API constant.
    try:
        with urlopen(request, timeout=timeout) as response:  # nosec B310
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        raise CloudflareApiError(
            f"cloudflare Origin CA {method} {path} failed: HTTP {error.code}",
            status=error.code,
        ) from None
    if not body.get("success", False):
        raise CloudflareApiError(
            f"cloudflare Origin CA {method} {path} failed: {body.get('errors')}"
        )
    return body


def verify_token(token_ref, *, timeout=20):
    """Resolve a DnsAccount vault ref and observe it (Task 2's audit entry).

    The ref is loaded through the registry's vault seam (never a raw value in
    a signature the caller might log), then observed through observe_token,
    which shape-refuses pre-network itself. No mutation anywhere.
    """
    from .registry import _load_token

    _, raw = _load_token(token_ref)
    return observe_token(raw, timeout=timeout)


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
        # capabilities()" — this set is that surface. custom_hostname is
        # D-079: create/status/TXT live on this object, not a second client.
        return {"proxied", "custom_hostname"}

    def create_custom_hostname(self, hostname):
        from .custom_hostname import (
            normalize_custom_hostname,
            refuse_partner_base_collision,
        )

        host = str(hostname or "").rstrip(".").lower()
        refuse_partner_base_collision(host)
        zone_id = self._zone_id(self.zone)
        body = self._api(
            "POST",
            f"/zones/{zone_id}/custom_hostnames",
            {"hostname": host, "ssl": {"method": "txt", "type": "dv"}},
        )
        return normalize_custom_hostname(body.get("result") or {"hostname": host})

    def _custom_hostname_row(self, hostname):
        host = str(hostname or "").rstrip(".").lower()
        zone_id = self._zone_id(self.zone)
        query = urlencode({"hostname": host})
        body = self._api("GET", f"/zones/{zone_id}/custom_hostnames?{query}")
        rows = body.get("result") or []
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows:
            if str(row.get("hostname") or "").rstrip(".").lower() == host:
                return row
        raise CloudflareError(f"custom hostname {host!r} not found")

    def custom_hostname_status(self, hostname):
        return str(self._custom_hostname_row(hostname).get("status") or "").lower()

    def custom_hostname_txt(self, hostname):
        from .custom_hostname import ownership_from_record

        return ownership_from_record(self._custom_hostname_row(hostname))

    def serve_custom_hostname(self, hostname):
        from .custom_hostname import caddy_route_for

        return caddy_route_for(self, hostname)

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


class CloudflareOriginCertIssuer(OriginCertIssuer):
    """Origin CA client. The Hub sends a CSR; the private key never leaves."""

    def __init__(self, zone, *, origin_ca_key, timeout=20):
        self.zone = zone
        self._origin_ca_key = origin_ca_key
        self.timeout = timeout

    def __repr__(self):
        return f"<CloudflareOriginCertIssuer zone={self.zone.name!r}>"

    __str__ = __repr__

    def issue(self, zone, hostnames, *, validity_days, csr):
        if zone is not None and zone is not self.zone:
            same_row = (
                getattr(zone, "pk", None) is not None
                and getattr(zone, "pk", None) == self.zone.pk
            )
            if not same_row:
                raise CloudflareError(
                    f"this issuer is bound to zone {self.zone.name!r}; "
                    f"refusing a call for a different zone"
                )
        csr_text = csr.decode() if isinstance(csr, (bytes, bytearray)) else csr
        body = origin_ca_request(
            self._origin_ca_key,
            "POST",
            "/certificates",
            {
                "hostnames": list(hostnames),
                "requested_validity": int(validity_days),
                "request_type": "origin-ecc",
                "csr": csr_text,
            },
            timeout=self.timeout,
        )
        result = body.get("result") or {}
        return {
            "certificate": result["certificate"],
            "expires_at": _parse_expires(result.get("expires_on")),
        }


class CloudflareEdge(EdgeProtection):
    """Cloudflare edge client bound to one verified DnsZone (D-057).

    Constructed ONLY by providers.registry.edge_protection_for. The token
    appears in the Authorization header and nowhere else.
    """

    def __init__(self, zone, *, token, timeout=20, on_auth_error=None):
        self.zone = zone
        self._token = refuse_global_api_key(token)
        self.timeout = timeout
        self._on_auth_error = on_auth_error
        self.security_level = {}
        self.banned = []

    def __repr__(self):
        return f"<CloudflareEdge zone={self.zone.name!r}>"

    __str__ = __repr__

    def set_security_level(self, zone, level):
        current = self._get_security_level(zone)
        if current == level:
            return
        zone_id = self._zone_id(zone)
        self._api(
            "PATCH", f"/zones/{zone_id}/settings/security_level", {"value": level},
        )
        self.security_level[zone] = level

    def ban_ip(self, zone, ip, *, note=""):
        if not ip or self._ip_banned(zone, ip):
            return
        zone_id = self._zone_id(zone)
        self._api(
            "POST",
            f"/zones/{zone_id}/firewall/access_rules/rules",
            {
                "mode": "block",
                "configuration": {"target": "ip", "value": ip},
                "notes": note or "attack-playbook",
            },
        )
        self.banned.append((zone, ip, note))

    def purge_cache(self, zone):
        zone_id = self._zone_id(zone)
        self._api("POST", f"/zones/{zone_id}/purge_cache", {"purge_everything": True})

    def _get_security_level(self, zone):
        cached = self.security_level.get(zone)
        if cached is not None:
            return cached
        zone_id = self._zone_id(zone)
        body = self._api("GET", f"/zones/{zone_id}/settings/security_level")
        value = (body.get("result") or {}).get("value")
        if value:
            self.security_level[zone] = value
        return value

    def _ip_banned(self, zone, ip):
        if any(item[0] == zone and item[1] == ip for item in self.banned):
            return True
        zone_id = self._zone_id(zone)
        page = 1
        while True:
            query = urlencode({"per_page": 100, "page": page})
            body = self._api(
                "GET", f"/zones/{zone_id}/firewall/access_rules/rules?{query}",
            )
            for row in body.get("result") or []:
                cfg = row.get("configuration") or {}
                if (
                    cfg.get("target") == "ip"
                    and cfg.get("value") == ip
                    and row.get("mode") == "block"
                ):
                    self.banned.append((zone, ip, row.get("notes") or ""))
                    return True
            info = body.get("result_info") or {}
            if page >= int(info.get("total_pages") or 1):
                break
            page += 1
        return False

    def _zone_id(self, zone):
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


def _parse_expires(raw):
    from django.utils import timezone
    from django.utils.dateparse import parse_datetime

    if raw is None:
        return timezone.now()
    if hasattr(raw, "year"):
        return raw
    parsed = parse_datetime(str(raw).replace(" +0000", "+00:00"))
    if parsed is None:
        return timezone.now()
    if timezone.is_naive(parsed):
        parsed = timezone.make_aware(parsed, timezone.utc)
    return parsed
