"""dns_provider_for is the wall (D-033/D-034/D-046): fail-closed, synchronous.

Construction refuses BEFORE the client exists: Bearer-only credential shape,
active-token verify, and the pinned one-zone probe (`GET /zones?per_page=50`)
that must return exactly the expected provider_zone_id — verify alone cannot
prove scope (D-046). Test-zone construction stays triple-keyed: HUB_TEST_MODE
+ purpose=test + HUB_TEST_ZONE_SLUGS. urlopen is doubled; nothing here opens
a socket.
"""
import ast
import pathlib

import pytest
from django.test import override_settings
from test_cloudflare_adapter import FakeCloudflare

REPO = pathlib.Path(__file__).resolve().parent.parent

TOKEN = "t1-wall-dummy-token-not-a-credential"  # nosec B105 — a test constant
VERIFY = ("GET", "/user/tokens/verify")
PROBE = ("GET", "/zones?per_page=50")

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _fresh_scope_cache():
    import providers.registry as registry

    registry.reset_scope_cache()
    yield
    registry.reset_scope_cache()


def _zone(*, name="wall.example", zone_id="zid-wall", purpose="prod",
          token=TOKEN, label="wall-acct"):
    from core.models import DnsAccount, DnsZone
    from vault import service as vault_service

    account = DnsAccount.objects.create(provider="cloudflare", label=label)
    ref = f"dnsacct-{account.pk}"
    vault_service.put(
        kind="api_token", owner_type="dns_account", owner_id=ref,
        plaintext=token.encode(),
    )
    account.dns_token_ref = ref
    account.save(update_fields=["dns_token_ref"])
    return DnsZone.objects.create(
        account=account, name=name, provider_zone_id=zone_id, purpose=purpose,
    )


def _routes(zone, *, status="active", zones=None):
    result = [{"id": zone.provider_zone_id, "name": zone.name}] if zones is None else zones
    return {
        VERIFY: {"success": True, "result": {"id": "tok-1", "status": status}},
        PROBE: {"success": True, "result": result},
    }


def _http(monkeypatch, routes):
    import providers.cloudflare as cloudflare

    http = FakeCloudflare(routes)
    monkeypatch.setattr(cloudflare, "urlopen", http)
    return http


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_global_api_key_header_shape_is_refused_before_any_request(monkeypatch):
    """An X-Auth-Key/X-Auth-Email credential never reaches the wire (D-046).

    What would make this fail: sending the Global API Key to verify and
    letting Cloudflare's answer decide — the refusal must be by shape,
    before any request.
    """
    import json

    from providers.registry import ScopeError, dns_provider_for

    global_key = json.dumps({"X-Auth-Key": "abc123", "X-Auth-Email": "op@example.com"})
    zone = _zone(token=global_key)
    http = _http(monkeypatch, _routes(zone))

    with pytest.raises(ScopeError):
        dns_provider_for(zone)
    assert http.requests == []


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_inactive_token_refuses_construction(monkeypatch):
    """verify must return success + status=active or there is no client.

    What would make this fail: skipping the status field, so a disabled or
    expired token constructs a client that fails later, mid-deploy.
    """
    from providers.registry import ScopeError, dns_provider_for

    zone = _zone()
    http = _http(monkeypatch, _routes(zone, status="disabled"))

    with pytest.raises(ScopeError):
        dns_provider_for(zone)
    assert [req[1] for req in http.requests] == [VERIFY[1]]


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_two_zone_probe_result_refuses_construction(monkeypatch):
    """Excess access is refused at construction, not reported tomorrow.

    What would make this fail: only checking that the expected zone is IN the
    probe result — a two-zone token is over-scoped even when one id matches
    (D-034: the daily audit is defense-in-depth, not the enforcement).
    """
    from providers.registry import ScopeError, dns_provider_for

    zone = _zone()
    http = _http(monkeypatch, _routes(zone, zones=[
        {"id": zone.provider_zone_id, "name": zone.name},
        {"id": "zid-other", "name": "other.example"},
    ]))

    with pytest.raises(ScopeError):
        dns_provider_for(zone)
    assert [req[1] for req in http.requests] == [VERIFY[1], PROBE[1]]


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_zone_id_mismatch_refuses_construction(monkeypatch):
    """Exactly one zone with the WRONG id is still a refusal.

    What would make this fail: counting the result and never comparing ids,
    so a single-zone token for someone else's zone passes the wall.
    """
    from providers.registry import ScopeError, dns_provider_for

    zone = _zone()
    _http(monkeypatch, _routes(zone, zones=[{"id": "zid-wrong", "name": zone.name}]))

    with pytest.raises(ScopeError):
        dns_provider_for(zone)


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_verification_failure_fails_closed_and_files_a_finding(monkeypatch):
    """A refused construction is visible: a Finding row, not just a raise.

    What would make this fail: raising without persisting anything, so the
    operator learns about a broken token only from a failed deploy traceback.
    """
    from core.models import Finding
    from providers.registry import ScopeError, dns_provider_for

    zone = _zone()
    _http(monkeypatch, _routes(zone, zones=[
        {"id": zone.provider_zone_id, "name": zone.name},
        {"id": "zid-extra", "name": "extra.example"},
    ]))

    with pytest.raises(ScopeError):
        dns_provider_for(zone)

    finding = Finding.objects.get(source_engine="dns_scope")
    assert finding.state == Finding.State.OPEN
    assert zone.name in finding.fingerprint
    assert TOKEN not in finding.body

    # Refusing again updates last_seen on the same fingerprint, no second row.
    with pytest.raises(ScopeError):
        dns_provider_for(zone)
    assert Finding.objects.filter(source_engine="dns_scope").count() == 1


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_verified_scope_is_cached_and_reverified_after_ttl(monkeypatch):
    """One verification per (token_ref, zone) per TTL; expiry fails closed.

    What would make this fail: verifying on every construction (a probe per
    deploy step), caching forever, or serving the cache after the TTL when
    the re-verify now refuses.
    """
    from providers.registry import ScopeError, dns_provider_for

    zone = _zone()
    http = _http(monkeypatch, _routes(zone))
    clock = {"t": 1000.0}

    def now():
        return clock["t"]

    dns_provider_for(zone, now=now)
    assert len(http.requests) == 2  # verify + probe

    dns_provider_for(zone, now=now)
    assert len(http.requests) == 2  # cached inside the TTL

    clock["t"] += 899.0
    dns_provider_for(zone, now=now)
    assert len(http.requests) == 2  # still inside the 15-min window

    clock["t"] += 2.0
    dns_provider_for(zone, now=now)
    assert len(http.requests) == 4  # expired: re-verified

    clock["t"] += 901.0
    http.routes[PROBE] = {"success": True, "result": [
        {"id": zone.provider_zone_id, "name": zone.name},
        {"id": "zid-crept-in", "name": "crept.example"},
    ]}
    with pytest.raises(ScopeError):
        dns_provider_for(zone, now=now)  # expiry fails closed, never stale-serves


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_test_mode_requires_all_three_keys(monkeypatch):
    """HUB_TEST_MODE + purpose=test + allowlist — drop any one and it refuses.

    What would make this fail: any pair being enough, e.g. allowlisting a
    prod-purpose zone under HUB_TEST_MODE, or a test-purpose zone building a
    client in prod mode.
    """
    from core.test_mode import TestModeError
    from providers.cloudflare import CloudflareDnsProvider
    from providers.registry import ScopeError, dns_provider_for

    allow = ["hub-test.example"]

    # All three keys: constructs.
    zone = _zone(name="hub-test.example", zone_id="zid-t", purpose="test", label="a1")
    _http(monkeypatch, _routes(zone))
    with override_settings(HUB_TEST_MODE=True, HUB_TEST_ZONE_SLUGS=allow):
        provider = dns_provider_for(zone)
    assert isinstance(provider, CloudflareDnsProvider)

    # Drop HUB_TEST_MODE: a purpose=test zone is refused outright.
    with override_settings(HUB_TEST_MODE=False):
        with pytest.raises(ScopeError):
            dns_provider_for(zone)

    # Drop purpose=test: refused under HUB_TEST_MODE even though allowlisted.
    prod_zone = _zone(name="hub-test.example2", zone_id="zid-p", purpose="prod",
                      label="a2")
    _http(monkeypatch, _routes(prod_zone))
    with override_settings(HUB_TEST_MODE=True,
                           HUB_TEST_ZONE_SLUGS=allow + ["hub-test.example2"]):
        with pytest.raises(TestModeError):
            dns_provider_for(prod_zone)

    # Drop the allowlist entry: purpose=test alone is refused.
    rogue = _zone(name="rogue.example", zone_id="zid-r", purpose="test", label="a3")
    _http(monkeypatch, _routes(rogue))
    with override_settings(HUB_TEST_MODE=True, HUB_TEST_ZONE_SLUGS=allow):
        with pytest.raises(TestModeError):
            dns_provider_for(rogue)


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_prod_mode_refuses_test_purpose_zone(monkeypatch):
    """Outside HUB_TEST_MODE a purpose=test zone never builds a client.

    What would make this fail: the purpose wall living only under
    HUB_TEST_MODE, so prod code paths could drive the test zone's records.
    """
    from providers.registry import ScopeError, dns_provider_for

    zone = _zone(name="testy.example", zone_id="zid-ty", purpose="test")
    http = _http(monkeypatch, _routes(zone))
    with override_settings(HUB_TEST_MODE=False):
        with pytest.raises(ScopeError):
            dns_provider_for(zone)
    assert http.requests == []  # refused before any network I/O


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_dns_provider_for_is_the_only_construction_path():
    """AST scan: no CloudflareDnsProvider(...) call outside the registry and
    the adapter's own tests (D-033).

    What would make this fail: a task or view constructing the client
    directly, skipping the synchronous scope enforcement.
    """
    allowed = {
        "providers/registry.py",
        "tests/test_cloudflare_adapter.py",
        "tests/test_dns_zone_wall.py",
    }
    skip_dirs = {".git", ".venv", ".venv-scaffold", ".worktrees", "node_modules",
                 "frontend", "mutants", "staticfiles", "__pycache__"}
    offenders = []
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO)
        if set(rel.parts) & skip_dirs or str(rel) in allowed:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = getattr(func, "id", None) or getattr(func, "attr", None)
                if name == "CloudflareDnsProvider":
                    offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], offenders

    # And the detector is not vacuous: the registry itself does construct it.
    registry_src = (REPO / "providers" / "registry.py").read_text(encoding="utf-8")
    assert "CloudflareDnsProvider(" in registry_src


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_single_zone_allowlist_namespace(monkeypatch):
    """HUB_TEST_DNS_ZONE authorizes nothing anywhere in the tree (D-033).

    The env var survives only inside the legacy test-plane module (Task 18
    retires it) where S1 already walls it behind HUB_TEST_ZONE_SLUGS. What
    would make this fail: the product wall (core/test_mode.py, providers/
    registry.py, providers/cloudflare.py, deploys/) reading the retired
    namespace, or the env var admitting a zone the allowlist never named.
    """
    legacy_only = {
        "providers/test_dns.py",
        "tests/test_t3_https.py",
        "tests/test_test_dns_provider.py",
        "tests/test_dns_zone_wall.py",  # this test names it to ban it
    }
    skip_dirs = {".git", ".venv", ".venv-scaffold", ".worktrees", "node_modules",
                 "frontend", "mutants", "staticfiles", "__pycache__"}
    offenders = []
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO)
        if set(rel.parts) & skip_dirs or str(rel) in legacy_only:
            continue
        if "HUB_TEST_DNS_ZONE" in path.read_text(encoding="utf-8"):
            offenders.append(str(rel))
    assert offenders == [], offenders

    # Functionally: naming a zone in the env var is not an authorization.
    from core.test_mode import TestModeError
    from providers.registry import dns_provider_for

    rogue = _zone(name="envnamed.example", zone_id="zid-env", purpose="test")
    http = _http(monkeypatch, _routes(rogue))
    monkeypatch.setenv("HUB_TEST_DNS_ZONE", "envnamed.example")
    with override_settings(HUB_TEST_MODE=True, HUB_TEST_ZONE_SLUGS=["hub-test"]):
        with pytest.raises(TestModeError):
            dns_provider_for(rogue)
    assert http.requests == []
