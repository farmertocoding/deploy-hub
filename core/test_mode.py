"""HUB_TEST_MODE credential wall (§B9)."""
from django.conf import settings


class TestModeError(Exception):
    """Raised when HUB_TEST_MODE refuses a non-test or off-allowlist zone."""


def assert_test_zone(zone):
    """Refuse unless the zone is purpose=test and allowlisted (D-033).

    HUB_TEST_ZONE_SLUGS is the single allowlist: it names NetworkZone slugs
    AND DnsZone names — the retired test-DNS-zone env namespace authorizes
    nothing. No-op when HUB_TEST_MODE is off so the operator path stays intact.
    """
    if not getattr(settings, "HUB_TEST_MODE", False):
        return
    slugs = getattr(settings, "HUB_TEST_ZONE_SLUGS", ("hub-test",))
    ident = getattr(zone, "slug", None) or getattr(zone, "name", None)
    if zone.purpose != "test" or ident not in slugs:
        raise TestModeError(
            f"HUB_TEST_MODE refuses zone {ident!r} (purpose={zone.purpose!r})"
        )
