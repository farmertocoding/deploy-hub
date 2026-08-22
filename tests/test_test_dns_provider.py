"""T1: the test-plane DNS adapter refuses (§B9 / D-028 / HARNESS-B9-TEST-MODE).

TestDnsProvider is the Task 12 test-plane Cloudflare client — NOT the Phase 3
product adapter (D-028). These tests prove the refuse paths and never touch
the network: an autouse fixture replaces the module's urlopen with a tripwire,
so any test that reaches HTTP fails loudly instead of calling out.
"""
import inspect
import pathlib
import re

import pytest
from django.test import override_settings

from core.models import NetworkZone
from core.test_mode import TestModeError

REPO = pathlib.Path(__file__).resolve().parent.parent

TOKEN_ENV = "HUB_TEST_CF_TOKEN"
ZONE_ENV = "HUB_TEST_DNS_ZONE"
# A clearly-fake value: the T1 tests need the env var PRESENT, never valid.
DUMMY_TOKEN = "t1-dummy-not-a-credential"
TEST_ZONE_NAME = "t12.example"


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    """T1 must never open a socket: urlopen through the adapter is a failure."""
    import providers.test_dns as test_dns

    def tripwire(*args, **kwargs):
        raise AssertionError("TestDnsProvider touched the network in a T1 test")

    monkeypatch.setattr(test_dns, "urlopen", tripwire)


def _provider(monkeypatch):
    """Construct under HUB_TEST_MODE with the dummy token and test zone name."""
    from providers.test_dns import TestDnsProvider

    monkeypatch.setenv(TOKEN_ENV, DUMMY_TOKEN)
    monkeypatch.setenv(ZONE_ENV, TEST_ZONE_NAME)
    return TestDnsProvider()


@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_refuses_construct_when_not_test_mode(monkeypatch):
    """__init__ is the wall: without HUB_TEST_MODE there is no client at all.

    What would make this fail: constructing quietly and refusing only at
    mutate time, which leaves a token-holding client around for anyone.
    """
    from providers.test_dns import TestDnsProvider

    monkeypatch.setenv(TOKEN_ENV, DUMMY_TOKEN)
    monkeypatch.setenv(ZONE_ENV, TEST_ZONE_NAME)
    with override_settings(HUB_TEST_MODE=False):
        with pytest.raises(TestModeError):
            TestDnsProvider()


@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_refuses_construct_when_token_env_unset(monkeypatch):
    """No HUB_TEST_CF_TOKEN means no client: the T3 test skips the LE req —
    it never instantiates anything that could fall back to a prod credential.
    """
    from providers.test_dns import TestDnsProvider

    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.setenv(ZONE_ENV, TEST_ZONE_NAME)
    with override_settings(HUB_TEST_MODE=True):
        with pytest.raises(TestModeError):
            TestDnsProvider()


@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_refuses_non_allowlisted_zone(monkeypatch):
    """purpose=test is not enough off the allowlist, and a bare zone name that
    is not HUB_TEST_DNS_ZONE is refused before any network I/O.

    What would make this fail: checking purpose only, or walling construction
    but letting mutates through on any zone the caller hands over.
    """
    with override_settings(HUB_TEST_MODE=True, HUB_TEST_ZONE_SLUGS=["hub-test"]):
        provider = _provider(monkeypatch)
        off_allowlist = NetworkZone(name="other-test", slug="other-test", purpose="test")
        with pytest.raises(TestModeError):
            provider.upsert_record(off_allowlist, "a.t12.example", "A", ["203.0.113.10"])
        with pytest.raises(TestModeError):
            provider.delete_record(off_allowlist, "rec-1")
        with pytest.raises(TestModeError):
            provider.upsert_record("prod.example", "a.prod.example", "A", ["203.0.113.10"])


@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_refuses_prod_purpose_zone(monkeypatch):
    """An allowlisted slug with purpose=prod is refused — slug membership alone
    must never admit a prod zone (same rule test_hub_test_mode proves for the
    shared wall; this proves the adapter actually calls it).
    """
    with override_settings(HUB_TEST_MODE=True, HUB_TEST_ZONE_SLUGS=["hub-test"]):
        provider = _provider(monkeypatch)
        prod = NetworkZone(name="prod", slug="hub-test")
        assert prod.purpose == "prod"
        with pytest.raises(TestModeError):
            provider.upsert_record(prod, "a.t12.example", "A", ["203.0.113.10"])
        with pytest.raises(TestModeError):
            provider.delete_record(prod, "rec-1")
        with pytest.raises(TestModeError):
            provider.list_records(prod)


@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_allowlisted_test_zone_passes_the_wall(monkeypatch):
    """The wall admits purpose=test + allowlisted slug, and the configured zone
    name — otherwise the refuse tests above would pass with an unconditional
    raise. The configured zone itself must be allowlisted (S1), so the slugs
    list carries both. Every zone-taking method goes through the wall, by source.
    """
    import providers.test_dns as test_dns

    with override_settings(
        HUB_TEST_MODE=True, HUB_TEST_ZONE_SLUGS=["hub-test", TEST_ZONE_NAME],
    ):
        provider = _provider(monkeypatch)
        allowed = NetworkZone(name="hub-test", slug="hub-test", purpose="test")
        provider.refuse_unless_test_zone(allowed)
        provider.refuse_unless_test_zone(TEST_ZONE_NAME)
    for method in (
        test_dns.TestDnsProvider.list_records,
        test_dns.TestDnsProvider.upsert_record,
        test_dns.TestDnsProvider.delete_record,
        test_dns.TestDnsProvider.get_nameservers,
    ):
        assert "refuse_unless_test_zone" in inspect.getsource(method), method


@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_env_named_zone_off_allowlist_fails_closed(monkeypatch):
    """S1: matching HUB_TEST_DNS_ZONE is not an authorization. The configured
    zone — the one every API call actually mutates — must itself be on
    HUB_TEST_ZONE_SLUGS, and an allowlisted NetworkZone must not authorize a
    configured zone that never passed the allowlist.

    What would make this fail: refuse_unless_test_zone accepting a bare name
    merely because it equals the env var, or the NetworkZone branch skipping
    the configured-zone check so the provider mutates whatever zone the env
    var names.
    """
    with override_settings(HUB_TEST_MODE=True, HUB_TEST_ZONE_SLUGS=["hub-test"]):
        provider = _provider(monkeypatch)
        # The bare name equals HUB_TEST_DNS_ZONE — still refused: t12.example
        # is not on HUB_TEST_ZONE_SLUGS.
        with pytest.raises(TestModeError):
            provider.refuse_unless_test_zone(TEST_ZONE_NAME)
        # An allowlisted purpose=test NetworkZone must not smuggle a mutation
        # into the off-allowlist configured zone.
        allowed = NetworkZone(name="hub-test", slug="hub-test", purpose="test")
        with pytest.raises(TestModeError):
            provider.upsert_record(allowed, "a.t12.example", "A", ["203.0.113.10"])
        with pytest.raises(TestModeError):
            provider.list_records(allowed)
        # And the zone-id resolver itself fails closed before any network I/O
        # (the no_network tripwire proves nothing was called).
        with pytest.raises(TestModeError):
            provider._test_zone_id()


@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_no_import_of_test_dns_from_deploys():
    """deploys/ may never grow an edge to the test-plane adapter (D-028): the
    pipeline takes a DnsProvider as an argument, and the Phase 3 product
    adapter will be a different module.
    """
    pattern = re.compile(r"^\s*(?:import|from)\s+[^\n#]*\btest_dns\b", re.M)
    assert pattern.search("from providers import test_dns"), "detector is broken"
    assert pattern.search("import providers.test_dns"), "detector is broken"
    assert pattern.search("from providers.test_dns import TestDnsProvider"), "detector is broken"
    assert (REPO / "providers" / "test_dns.py").is_file(), (
        "providers/test_dns.py is the module this rule guards; without it the "
        "scan below is vacuously green"
    )
    offenders = [
        str(py.relative_to(REPO))
        for py in sorted((REPO / "deploys").rglob("*.py"))
        if pattern.search(py.read_text(encoding="utf-8"))
    ]
    assert offenders == [], f"deploys/ imports the test-plane DNS adapter: {offenders}"
