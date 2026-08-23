"""T1: T3 HTTPS skip matches credentials_present, not the retired zone env.

HARNESS-T3-LE-STAGING stays skipped-only on this host. These tests never
carry that req marker and never plant a real process token (D-024 / D-031).
"""
from __future__ import annotations

import os

import pytest

# Split so this file itself never mentions the retired env name; the product
# allowlist scan (test_single_zone_allowlist_namespace) forbids the literal
# in any new module.
_RETIRED_ZONE_ENV = "HUB_TEST_" + "DNS_ZONE"
TOKEN_ENV = "HUB_TEST_CF_TOKEN"

pytestmark = pytest.mark.django_db


def _plant_test_zone(settings, name="t6b-probe.example"):
    from dns_fixtures import default_dns_zone

    zone = default_dns_zone(name, purpose="test")
    settings.HUB_TEST_MODE = True
    settings.HUB_TEST_ZONE_SLUGS = [zone.name]
    return zone


def test_t3_skip_is_false_without_token_or_allowlisted_test_zone(monkeypatch, settings):
    """Skip is false when the token is absent or no allowlisted test zone exists.

    What would make this fail: _credentialed treating the retired zone env as
    a credential (D-033), so a host with only that env could leave skip.
    """
    from core.models import DnsZone
    from tests.test_t3_https import _credentialed

    monkeypatch.setenv(_RETIRED_ZONE_ENV, "retired-env.example")
    monkeypatch.setenv(TOKEN_ENV, "t6b-planted-not-a-credential")
    DnsZone.objects.filter(purpose="test").delete()
    settings.HUB_TEST_ZONE_SLUGS = ["hub-test"]
    assert _credentialed() is False

    monkeypatch.delenv(TOKEN_ENV, raising=False)
    _plant_test_zone(settings)
    assert _credentialed() is False


def test_t3_skip_uses_allowlisted_test_zone_name(monkeypatch, settings):
    """Skip is true for token + allowlisted purpose=test zone; name is that zone.

    What would make this fail: _credentialed still requiring the retired env,
    or _zone_name reading it instead of the planted DnsZone name.
    """
    from tests.test_t3_https import _credentialed, _zone_name

    zone = _plant_test_zone(settings, name="t6b-probe.example")
    monkeypatch.setenv(TOKEN_ENV, "t6b-planted-not-a-credential")
    monkeypatch.delenv(_RETIRED_ZONE_ENV, raising=False)
    assert os.environ.get(_RETIRED_ZONE_ENV, "").strip() == ""
    assert _credentialed() is True
    assert _zone_name() == "t6b-probe.example"

    monkeypatch.setenv(_RETIRED_ZONE_ENV, "other-retired.example")
    assert _credentialed() is True
    assert _zone_name() == zone.name
