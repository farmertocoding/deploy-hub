"""H10: T3 CF harness must not rewrite HUB_TEST_ZONE_SLUGS from the token."""
import pytest

pytestmark = pytest.mark.django_db


def test_allowlist_zone_does_not_append_unlisted_names(settings):
    """Mismatch skips; it does not append the observed Cloudflare zone name.

    What would make this fail: _allowlist_zone adding whatever observe_token
    returned onto HUB_TEST_ZONE_SLUGS so a one-zone production token is
    labelled purpose=test and mutated.
    """
    from tests.harness.cf_zone import _allowlist_zone

    settings.HUB_TEST_ZONE_SLUGS = ["hub-test"]
    with pytest.raises((pytest.skip.Exception, RuntimeError)):
        _allowlist_zone("prod.example.test")
    assert list(settings.HUB_TEST_ZONE_SLUGS) == ["hub-test"]
