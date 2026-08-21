"""HUB_TEST_MODE credential wall (§B9)."""
from django.conf import settings


class TestModeError(Exception):
    """Raised when HUB_TEST_MODE refuses a non-test or off-allowlist zone."""


def assert_test_zone(zone):
    """Refuse unless the zone is purpose=test and its slug is allowlisted.

    No-op when HUB_TEST_MODE is off so the operator path stays intact.
    """
    if not getattr(settings, "HUB_TEST_MODE", False):
        return
    slugs = getattr(settings, "HUB_TEST_ZONE_SLUGS", ("hub-test",))
    if zone.purpose != "test" or zone.slug not in slugs:
        raise TestModeError(
            f"HUB_TEST_MODE refuses zone {zone.slug!r} (purpose={zone.purpose!r})"
        )
