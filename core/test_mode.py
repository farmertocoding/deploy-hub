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


def _csv_setting(name):
    raw = getattr(settings, name, "") or ""
    if isinstance(raw, (list, tuple)):
        return tuple(str(part).strip() for part in raw if str(part).strip())
    return tuple(part.strip() for part in str(raw).split(",") if part.strip())


def assert_test_aws(account_id, region, *, purpose=None, tags=None):
    """Quadruple-keyed AWS test-plane wall (D-066).

    Under HUB_TEST_MODE both HUB_TEST_AWS_ACCOUNT_IDS and HUB_TEST_AWS_REGIONS
    must contain the values; an empty allowlist refuses live. Outside it, a
    purpose=test tagged call refuses. Operator (non-test) calls are a no-op
    when the flag is off.
    """
    tagged_test = purpose == "test" or (tags or {}).get("purpose") == "test"
    if getattr(settings, "HUB_TEST_MODE", False):
        accounts = _csv_setting("HUB_TEST_AWS_ACCOUNT_IDS")
        regions = _csv_setting("HUB_TEST_AWS_REGIONS")
        if not accounts or not regions:
            raise TestModeError(
                "HUB_TEST_MODE empty AWS allowlist refuses live "
                f"(account={account_id!r} region={region!r})"
            )
        if str(account_id) not in accounts or str(region) not in regions:
            raise TestModeError(
                f"HUB_TEST_MODE refuses AWS account {account_id!r} "
                f"region {region!r} (off allowlist)"
            )
        return
    if tagged_test:
        raise TestModeError(
            "refusing purpose=test AWS call outside HUB_TEST_MODE"
        )
