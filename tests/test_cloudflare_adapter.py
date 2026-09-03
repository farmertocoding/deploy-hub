"""T1: the product Cloudflare adapter over a doubled urlopen (D-034, §D5).

No test here opens a socket: FakeCloudflare replaces providers.cloudflare's
urlopen the same way tests/test_test_dns_provider.py doubles the test-plane
client. Direct CloudflareDnsProvider(...) construction is allowed ONLY in
providers/registry.py and the adapter's own tests — this file is one of them
(tests/test_dns_zone_wall.py::test_dns_provider_for_is_the_only_construction_path).
"""
import json
import logging
from urllib.error import HTTPError

import pytest

TOKEN = "t1-dummy-product-token-not-a-credential"  # nosec B105 — a test constant
ZONE_ID = "z123"
ZONE_NAME = "example.com"


class _Resp:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode()

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class FakeCloudflare:
    """urlopen double: canned JSON per (method, path); records every request."""

    def __init__(self, routes=None):
        self.routes = dict(routes or {})
        self.requests = []  # (method, path, headers, body)

    def __call__(self, request, timeout=None):
        from providers.cloudflare import API

        assert request.full_url.startswith(API), request.full_url
        path = request.full_url[len(API):]
        method = request.get_method()
        body = request.data.decode() if request.data else None
        self.requests.append((method, path, dict(request.header_items()), body))
        outcome = self.routes.get((method, path))
        if outcome is None:
            raise AssertionError(f"unrouted Cloudflare call: {method} {path}")
        if isinstance(outcome, Exception):
            raise outcome
        return _Resp(outcome)

    def methods(self):
        return [method for method, *_ in self.requests]


def record(rid, name, content, *, rtype="A", proxied=True, ttl=1):
    return {
        "id": rid, "name": name, "type": rtype,
        "content": content, "proxied": proxied, "ttl": ttl,
    }


def list_page(rows, *, page=1, total_pages=1):
    return {
        "success": True,
        "result": rows,
        "result_info": {"page": page, "total_pages": total_pages},
    }


LIST_P1 = ("GET", f"/zones/{ZONE_ID}/dns_records?per_page=100&page=1")
LIST_P2 = ("GET", f"/zones/{ZONE_ID}/dns_records?per_page=100&page=2")


def _zone():
    from core.models import DnsAccount, DnsZone

    account = DnsAccount(provider="cloudflare", label="adapter-test")
    return DnsZone(account=account, name=ZONE_NAME, provider_zone_id=ZONE_ID)


def _provider(monkeypatch, http):
    import providers.cloudflare as cloudflare

    monkeypatch.setattr(cloudflare, "urlopen", http)
    return cloudflare.CloudflareDnsProvider(_zone(), token=TOKEN)


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_upsert_is_a_diff_not_a_blind_write(monkeypatch):
    """A matching (name, rtype, content, proxied) row records zero writes.

    What would make this fail: PUTting the same content over the existing
    record on every deploy, which turns each idempotent re-run into an API
    mutation Cloudflare rate-limits and audits.
    """
    existing = record("rec1", f"app.{ZONE_NAME}", "1.2.3.4")
    http = FakeCloudflare({LIST_P1: list_page([existing])})
    provider = _provider(monkeypatch, http)
    zone = provider.zone

    rid = provider.upsert_record(zone, f"app.{ZONE_NAME}", "A", ["1.2.3.4"], proxied=True)
    assert rid == "rec1"
    assert set(http.methods()) == {"GET"}, http.requests

    http.routes[("PUT", f"/zones/{ZONE_ID}/dns_records/rec1")] = {
        "success": True, "result": record("rec1", f"app.{ZONE_NAME}", "5.6.7.8"),
    }
    rid = provider.upsert_record(zone, f"app.{ZONE_NAME}", "A", ["5.6.7.8"], proxied=True)
    assert rid == "rec1"
    assert http.methods().count("PUT") == 1
    assert "POST" not in http.methods()
    assert "DELETE" not in http.methods()


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_list_records_follows_pagination(monkeypatch):
    """Records past page one are still part of the diff set (2.5 minor).

    What would make this fail: reading only the first page, so a zone with
    >100 records diffs against a truncated view and re-creates existing rows.
    """
    http = FakeCloudflare({
        LIST_P1: list_page([record("rec1", f"a.{ZONE_NAME}", "1.1.1.1")],
                           page=1, total_pages=2),
        LIST_P2: list_page([record("rec2", f"b.{ZONE_NAME}", "2.2.2.2")],
                           page=2, total_pages=2),
    })
    provider = _provider(monkeypatch, http)

    rows = provider.list_records(provider.zone)
    assert [row["id"] for row in rows] == ["rec1", "rec2"]
    assert [req[1] for req in http.requests] == [LIST_P1[1], LIST_P2[1]]


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_token_never_appears_in_repr_logs_or_exceptions(monkeypatch, caplog):
    """The token lives in the Authorization header and nowhere else.

    What would make this fail: a repr carrying the credential, or an API
    error message interpolating the request (headers included) into the
    exception a Celery task will happily log.
    """
    http = FakeCloudflare({
        LIST_P1: {"success": False, "errors": [{"code": 10000, "message": "denied"}]},
    })
    provider = _provider(monkeypatch, http)

    assert TOKEN not in repr(provider)
    assert TOKEN not in str(provider)

    from providers.cloudflare import CloudflareApiError

    with caplog.at_level(logging.DEBUG):
        with pytest.raises(CloudflareApiError) as exc:
            provider.list_records(provider.zone)
    assert TOKEN not in str(exc.value)
    assert TOKEN not in repr(exc.value)
    assert TOKEN not in caplog.text

    # The header itself is the one sanctioned home.
    headers = http.requests[0][2]
    assert headers.get("Authorization") == f"Bearer {TOKEN}"


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_delete_absent_record_is_success(monkeypatch):
    """Deleting an already-absent record is idempotent success, like the fake.

    What would make this fail: surfacing Cloudflare's 404 as an error, which
    makes a resumed deploy step fail on work the previous attempt finished.
    """
    path = f"/zones/{ZONE_ID}/dns_records/gone"
    http = FakeCloudflare({
        ("DELETE", path): HTTPError("u", 404, "Not Found", {}, None),
    })
    provider = _provider(monkeypatch, http)

    provider.delete_record(provider.zone, "gone")  # must not raise
    assert http.methods() == ["DELETE"]

    from providers.cloudflare import CloudflareApiError

    http.routes[("DELETE", path)] = HTTPError("u", 500, "boom", {}, None)
    with pytest.raises(CloudflareApiError):
        provider.delete_record(provider.zone, "gone")


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_capabilities_declares_proxied(monkeypatch):
    """proxied is a Cloudflare capability surfaced here, not a neutral field.

    What would make this fail: an empty capabilities() — DnsZone.proxied_default
    documents itself as "surfaced by capabilities()", so the surface must exist.
    """
    provider = _provider(monkeypatch, FakeCloudflare())
    assert "proxied" in provider.capabilities()


def _header(headers, name):
    wanted = name.lower()
    for key, value in headers.items():
        if key.lower() == wanted:
            return value
    return None


ORIGIN_CA_ISSUE = ("POST", "/certificates")
ORIGIN_CA_CSR = (
    "-----BEGIN CERTIFICATE REQUEST-----\n"
    "t1-dummy-csr-not-a-credential\n"
    "-----END CERTIFICATE REQUEST-----"
)
SERVICE_KEY = (
    "v1.0-144c9defac04969c7bfad8ef-631a41d003a32d25fe878081ef365c49503f7fada6"
)


def _issuer(monkeypatch, http, *, credential=TOKEN):
    import providers.cloudflare as cloudflare

    monkeypatch.setattr(cloudflare, "urlopen", http)
    return cloudflare.CloudflareOriginCertIssuer(_zone(), origin_ca_key=credential)


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_origin_ca_issue_sends_bearer_not_service_key(monkeypatch):
    """Origin CA issue authenticates with Authorization Bearer.

    What would make this fail: sending X-Auth-User-Service-Key, which
    Cloudflare deprecated 2026-03-19 and shuts down 2026-09-30.
    """
    http = FakeCloudflare({
        ORIGIN_CA_ISSUE: {
            "success": True,
            "result": {
                "certificate": "-----BEGIN CERTIFICATE-----\nMII\n-----END CERTIFICATE-----",
                "expires_on": "2030-01-01T00:00:00+00:00",
            },
        },
    })
    issuer = _issuer(monkeypatch, http)
    result = issuer.issue(
        issuer.zone, ["app.example.com"], validity_days=7, csr=ORIGIN_CA_CSR,
    )
    assert "BEGIN CERTIFICATE" in result["certificate"]
    assert http.requests, "issue must hit POST /certificates"
    headers = http.requests[0][2]
    assert _header(headers, "Authorization") == f"Bearer {TOKEN}"
    assert _header(headers, "X-Auth-User-Service-Key") is None


def test_origin_ca_expires_on_cloudflare_utc_spelling(monkeypatch):
    """Cloudflare Origin CA returns '2014-01-01 05:20:00 +0000 UTC', not ISO-8601.

    What would make this fail: parse_datetime returning None so expires_at
    becomes now() and the next deploy reissues.
    """
    from datetime import datetime
    from datetime import timezone as dt_timezone

    import providers.cloudflare as cloudflare

    parsed = cloudflare._parse_expires("2030-01-01 05:20:00 +0000 UTC")
    assert parsed == datetime(2030, 1, 1, 5, 20, tzinfo=dt_timezone.utc)
    http = FakeCloudflare({
        ORIGIN_CA_ISSUE: {
            "success": True,
            "result": {
                "certificate": "-----BEGIN CERTIFICATE-----\nMII\n-----END CERTIFICATE-----",
                "expires_on": "2030-01-01 05:20:00 +0000 UTC",
            },
        },
    })
    issuer = _issuer(monkeypatch, http)
    result = issuer.issue(
        issuer.zone, ["app.example.com"], validity_days=7, csr=ORIGIN_CA_CSR,
    )
    assert result["expires_at"].year == 2030


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_origin_ca_refuses_service_key_before_network(monkeypatch):
    """A v1.0- Origin CA service key never reaches urlopen.

    What would make this fail: still sending X-Auth-User-Service-Key, or
    interpolating the credential into the refusal.
    """
    from providers.cloudflare import CloudflareError

    http = FakeCloudflare()
    with pytest.raises(CloudflareError) as exc:
        _issuer(monkeypatch, http, credential=SERVICE_KEY)
    assert http.requests == []
    message = str(exc.value)
    assert SERVICE_KEY not in message
    assert "Bearer" in message or "deprecated" in message.lower()


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_origin_ca_module_does_not_send_service_key_header():
    """The adapter must not still plant the deprecated header name as a header.

    What would make this fail: a quoted X-Auth-User-Service-Key assignment
    remaining in providers/cloudflare.py after the Bearer migration.
    """
    from pathlib import Path

    src = Path("providers/cloudflare.py").read_text()
    assert '"X-Auth-User-Service-Key"' not in src
    assert "'X-Auth-User-Service-Key'" not in src
