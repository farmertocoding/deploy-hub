"""Test-plane Cloudflare DNS client (§B9 / D-028 / HARNESS-T3-LE-STAGING).

NOT the Phase 3 product adapter (D-028): this module exists so the
credential-gated T3 HTTPS test can drive ONE Cloudflare test zone, and
nothing else. The zone name comes from HUB_TEST_DNS_ZONE and the zone-scoped
token from HUB_TEST_CF_TOKEN — never a prod token name. Construction refuses
outside HUB_TEST_MODE or without the token, so no code path ever holds a
client that could reach a prod zone; every zone-taking call re-walls before
any network I/O. deploys/ must never import this module
(tests/test_test_dns_provider.py::test_no_import_of_test_dns_from_deploys).
"""
import json
import os
from urllib.error import HTTPError
from urllib.parse import quote
from urllib.request import Request, urlopen

from django.conf import settings

from core.test_mode import TestModeError, assert_test_zone

from .base import DnsProvider

API = "https://api.cloudflare.com/client/v4"
TOKEN_ENV = "HUB_TEST_CF_TOKEN"
ZONE_ENV = "HUB_TEST_DNS_ZONE"


class TestDnsProvider(DnsProvider):
    """Cloudflare client for the allowlisted test zone only."""

    def __init__(self, *, timeout=20):
        if not getattr(settings, "HUB_TEST_MODE", False):
            raise TestModeError("TestDnsProvider constructs only under HUB_TEST_MODE")
        token = os.environ.get(TOKEN_ENV, "").strip()
        if not token:
            raise TestModeError(
                f"TestDnsProvider requires {TOKEN_ENV}; without it the T3 test "
                "skips the LE req — it never falls back to another credential"
            )
        self._token = token
        self.zone_name = os.environ.get(ZONE_ENV, "").strip()
        self.timeout = timeout
        self._zone_id = None

    def refuse_unless_test_zone(self, zone):
        """The §B9 wall, applied per call and before any network I/O.

        A NetworkZone goes through assert_test_zone (purpose=test AND slug on
        HUB_TEST_ZONE_SLUGS); a bare zone name must equal HUB_TEST_DNS_ZONE.
        """
        if not getattr(settings, "HUB_TEST_MODE", False):
            raise TestModeError("TestDnsProvider refuses every call outside HUB_TEST_MODE")
        if hasattr(zone, "purpose") and hasattr(zone, "slug"):
            assert_test_zone(zone)
            return
        if not self.zone_name or str(zone) != self.zone_name:
            raise TestModeError(
                f"test-plane DNS refuses zone {zone!r}; the allowlist is "
                f"[{self.zone_name!r}] ({ZONE_ENV})"
            )

    def list_records(self, zone):
        self.refuse_unless_test_zone(zone)
        zone_id = self._test_zone_id()
        rows = self._api("GET", f"/zones/{zone_id}/dns_records?per_page=500")["result"]
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
        """PUT over the existing (name, rtype) rows, POST the rest, DELETE stale.

        Cloudflare stores one content per record, so a multi-value upsert
        becomes one record per value. Returns the first record id, like the
        fake — callers treat it as opaque.
        """
        self.refuse_unless_test_zone(zone)
        zone_id = self._test_zone_id()
        current = [
            rec for rec in self.list_records(zone)
            if rec["name"] == name and rec["rtype"] == rtype
        ]
        record_id = None
        for index, value in enumerate(values):
            payload = {
                "type": rtype,
                "name": name,
                "content": value,
                "proxied": bool(proxied),
                # ttl=1 is Cloudflare's spelling of "automatic".
                "ttl": int(ttl or 1),
            }
            if index < len(current):
                result = self._api(
                    "PUT",
                    f"/zones/{zone_id}/dns_records/{current[index]['id']}",
                    payload,
                )
            else:
                result = self._api("POST", f"/zones/{zone_id}/dns_records", payload)
            if record_id is None:
                record_id = result["result"]["id"]
        for stale in current[len(values):]:
            self._api("DELETE", f"/zones/{zone_id}/dns_records/{stale['id']}")
        return record_id

    def delete_record(self, zone, record_id):
        self.refuse_unless_test_zone(zone)
        zone_id = self._test_zone_id()
        try:
            self._api("DELETE", f"/zones/{zone_id}/dns_records/{record_id}")
        except HTTPError as error:
            if error.code != 404:  # absent == success, like the fake and the reaper
                raise

    def get_nameservers(self, domain):
        self.refuse_unless_test_zone(domain)
        zone_id = self._test_zone_id()
        result = self._api("GET", f"/zones/{zone_id}")["result"]
        return list(result.get("name_servers") or [])

    def capabilities(self):
        return {"proxied"}

    def _test_zone_id(self):
        """Resolve HUB_TEST_DNS_ZONE by name, once. Never any other zone."""
        if self._zone_id:
            return self._zone_id
        if not self.zone_name:
            raise TestModeError(f"{ZONE_ENV} is unset; there is no test zone to talk to")
        found = self._api("GET", f"/zones?name={quote(self.zone_name)}")["result"]
        if not found:
            raise TestModeError(
                f"Cloudflare has no zone named {self.zone_name!r} for this token"
            )
        self._zone_id = found[0]["id"]
        return self._zone_id

    def _api(self, method, path, payload=None):
        """One Cloudflare v4 call. The token goes into the Authorization header
        and nowhere else — never into logs, task args, or error messages."""
        request = Request(
            API + path,
            data=None if payload is None else json.dumps(payload).encode(),
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
            },
            method=method,
        )
        with urlopen(request, timeout=self.timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
        if not body.get("success", False):
            raise RuntimeError(
                f"cloudflare test-zone API {method} {path} failed: {body.get('errors')}"
            )
        return body
