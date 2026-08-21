"""HUB_TEST_MODE credential wall (§B9 / HARNESS-B9-TEST-MODE)."""
from pathlib import Path

import pytest
from django.conf import settings
from django.test import override_settings

from core.models import NetworkZone, Target

REPO = Path(__file__).resolve().parent.parent

PROD_VAULT_NEEDLES = (
    "HUB_VAULT_KEYFILE",
    "HUB_VAULT_KEK_BACKEND",
    "/etc/deploy-hub/vault.key",
)


def _zone(*, name, slug, purpose=None):
    kwargs = {"name": name, "slug": slug}
    if purpose is not None:
        kwargs["purpose"] = purpose
    return NetworkZone.objects.create(**kwargs)


def _target_in(zone):
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref="vault-b9",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


@pytest.mark.django_db
@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_prod_zone_refused_when_test_mode():
    """Default purpose is prod; HUB_TEST_MODE must refuse even an allowlisted slug.

    What would make this fail: treating slug membership as enough, or defaulting
    existing rows to test so the wall is opt-out.
    """
    from core.test_mode import TestModeError, assert_test_zone

    zone = _zone(name="prod", slug="hub-test")
    assert zone.purpose == "prod"
    with override_settings(HUB_TEST_MODE=True):
        with pytest.raises(TestModeError):
            assert_test_zone(zone)


@pytest.mark.django_db
@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_test_zone_off_allowlist_refused():
    """purpose=test is not enough if the slug is outside HUB_TEST_ZONE_SLUGS.

    What would make this fail: checking purpose only and ignoring the allowlist.
    """
    from core.test_mode import TestModeError, assert_test_zone

    zone = _zone(name="other-test", slug="other-test", purpose="test")
    with override_settings(HUB_TEST_MODE=True, HUB_TEST_ZONE_SLUGS=["hub-test"]):
        with pytest.raises(TestModeError):
            assert_test_zone(zone)


@pytest.mark.django_db
@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_test_zone_on_allowlist_allowed():
    """purpose=test and an allowlisted slug is the only combination the wall admits.

    What would make this fail: refusing hub-test under HUB_TEST_MODE, or requiring
    a second flag after the zone already matches.
    """
    from core.test_mode import assert_test_zone

    zone = _zone(name="hub-test", slug="hub-test", purpose="test")
    with override_settings(HUB_TEST_MODE=True, HUB_TEST_ZONE_SLUGS=["hub-test"]):
        assert_test_zone(zone)


@pytest.mark.django_db
@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_execute_does_not_mutate_after_refuse():
    """execute must raise TestModeError before any Transport run/put.

    What would make this fail: calling ensure_* (or otherwise mutating) and then
    raising, so the wall is only a log line after the deploy has started.
    """
    from pipeline_fakes import PipelineTransport, fixture_body, queued_deployment

    from core.test_mode import TestModeError
    from deploys.pipeline import execute
    from providers.fakes import FakeDnsProvider

    _site, deployment = queued_deployment("b9-exec", body=fixture_body("b9-exec"))
    transport = PipelineTransport()
    with override_settings(HUB_TEST_MODE=True):
        with pytest.raises(TestModeError):
            execute(deployment.pk, transport=transport, dns=FakeDnsProvider())
    assert transport.mutating_calls() == []


@pytest.mark.django_db
@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_provision_does_not_mutate_after_refuse():
    """provision_host must raise TestModeError with mutating_calls still empty.

    What would make this fail: probing then importing catalog / writing crontab
    on a prod-purpose zone because the wall ran after the first mutate.
    """
    from core.test_mode import TestModeError
    from core.transport import FakeTransport
    from provision.service import provision_host

    target = _target_in(_zone(name="prod-prov", slug="prod-prov"))
    transport = FakeTransport()
    with override_settings(HUB_TEST_MODE=True):
        with pytest.raises(TestModeError):
            provision_host(target, transport)
    assert transport.mutating_calls() == []


@pytest.mark.django_db
@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_test_mode_false_does_not_raise_on_prod_zone():
    """Operator path: flag off means a prod zone is not a TestModeError.

    What would make this fail: raising whenever purpose is prod, including when
    HUB_TEST_MODE is the prod default False.
    """
    from core.test_mode import assert_test_zone

    assert settings.HUB_TEST_MODE is False
    zone = _zone(name="ops-prod", slug="ops-prod")
    assert zone.purpose == "prod"
    with override_settings(HUB_TEST_MODE=False):
        assert_test_zone(zone)


@pytest.mark.req("HARNESS-B9-TEST-MODE")
def test_no_prod_vault_env_names_in_harness_modules():
    """tests/harness and providers/test_dns.py must not name prod vault material.

    Absent files are a pass — Task 12 owns the test-plane DNS adapter. What would
    make this fail: a harness module that mentions HUB_VAULT_KEYFILE or the
    prod keyfile default path.
    """
    roots = (REPO / "tests" / "harness", REPO / "providers" / "test_dns.py")
    hits = []
    for root in roots:
        if not root.exists():
            continue
        files = [root] if root.is_file() else sorted(p for p in root.rglob("*") if p.is_file())
        for path in files:
            text = path.read_text(encoding="utf-8")
            for needle in PROD_VAULT_NEEDLES:
                if needle in text:
                    hits.append(f"{path.relative_to(REPO)}:{needle}")
    assert hits == []
