"""Settings-bind Site.dns_zone on POST /api/v1/projects/ (DNS-SITE-ZONE-BIND).

Public create binds one matching-purpose eligible zone. Zero eligible is
409 with zero Project, zero Site, zero Finding — site-dns-unbound is illegal
because an unbound public Site cannot exist (C1 / I-purpose / I-target).
"""
from pathlib import Path

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db

PROJECTS = "/api/v1/projects/"


@pytest.fixture(autouse=True)
def _allow_tmp_local_sources(tmp_path, settings):
    root = tmp_path / "sources"
    root.mkdir()
    settings.HUB_ALLOW_LOCAL_SOURCES = True
    settings.HUB_LOCAL_SOURCE_ROOT = str(root)
    return root


@pytest.fixture
def auth_client(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


def _target(*, slug="bind-target"):
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(name=slug, slug=slug)
    return Target.objects.create(
        zone=zone, kind=Target.Kind.SSH, host=f"{slug}.example.com",
    )


def _zone(name, *, purpose="prod"):
    from dns_fixtures import default_dns_zone

    return default_dns_zone(name, purpose=purpose)


def _public_body(name, **extra):
    from django.conf import settings as dj_settings

    root = Path(dj_settings.HUB_LOCAL_SOURCE_ROOT)
    local = root / name
    local.mkdir(parents=True, exist_ok=True)
    (local / "app.py").write_text("# fixture\n")
    body = {
        "name": name,
        "local_path": str(local),
        "domain": f"{name}.example.com",
        "exposure": "public",
        "proxied": True,
    }
    body.update(extra)
    return body


def _create(client, name, **extra):
    return client.post(
        PROJECTS, _public_body(name, **extra), content_type="application/json",
    )


def _counts():
    from core.models import Finding, Project, Site

    return Project.objects.count(), Site.objects.count(), Finding.objects.count()


@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_public_site_create_auto_binds_the_single_eligible_zone(auth_client):
    """Exactly one eligible zone is bound without a body dns_zone.

    What would make this fail: leaving Site.dns_zone null (illegal for public)
    or requiring the operator to re-state the only connected zone.
    """
    from core.models import Project, Site

    _target()
    zone = _zone("only.example")

    before = _counts()
    response = _create(auth_client, "bind-auto")
    assert response.status_code == 201, response.content
    project = Project.objects.get(name="bind-auto")
    site = Site.objects.get(project=project)
    assert site.dns_zone_id == zone.pk
    assert site.domain == "bind-auto.example.com"
    assert _counts() == (before[0] + 1, before[1] + 1, before[2])
    assert not Site.objects.filter(dns_zone__isnull=True).exclude(
        exposure=Site.Exposure.MESH_ONLY,
    ).exists()


@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_public_site_create_with_no_eligible_zone_is_409_and_creates_nothing(auth_client):
    """Zero eligible zones: 409, and the fleet is unchanged (C1).

    Replaces test_public_site_create_with_no_zone_files_unbound_finding_and_409.
    site-dns-unbound:{pk} cannot be filed — there is no public Site pk.

    What would make this fail: creating a Project anyway, filing a Finding
    on a row that the constraint forbids, or returning 400 for a well-formed
    body the fleet cannot satisfy.
    """
    from core.models import Finding

    _target()
    before = _counts()
    response = _create(auth_client, "bind-none")
    assert response.status_code == 409, response.content
    assert _counts() == before
    assert not Finding.objects.filter(fingerprint__startswith="site-dns-unbound").exists()


@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_public_site_create_with_several_eligible_zones_requires_dns_zone(auth_client):
    """Several eligible zones: body dns_zone is required and must be one of them (I2).

    What would make this fail: auto-binding the first zone, or 409 even when
    the operator names a member of the eligible set.
    """
    from core.models import Project, Site

    _target()
    first = _zone("alpha.example")
    second = _zone("beta.example")
    before = _counts()

    missing = _create(auth_client, "bind-several")
    assert missing.status_code == 409, missing.content
    assert _counts() == before

    response = _create(auth_client, "bind-several", dns_zone=second.pk)
    assert response.status_code == 201, response.content
    site = Site.objects.get(project=Project.objects.get(name="bind-several"))
    assert site.dns_zone_id == second.pk
    assert site.dns_zone_id != first.pk


@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_purpose_test_zone_binds_only_under_test_plane(auth_client):
    """purpose=test is eligible only under the triple key (I-purpose).

    What would make this fail: treating any test zone as bindable outside
    HUB_TEST_MODE, or refusing the same zone when the allowlist names it.
    """
    from core.models import Project, Site

    _target()
    zone = _zone("hub-test", purpose="test")

    with override_settings(HUB_TEST_MODE=False, HUB_TEST_ZONE_SLUGS=["hub-test"]):
        before = _counts()
        refused = _create(auth_client, "bind-test-off")
        assert refused.status_code == 409, refused.content
        assert _counts() == before

    with override_settings(HUB_TEST_MODE=True, HUB_TEST_ZONE_SLUGS=["hub-test"]):
        response = _create(auth_client, "bind-test-on")
        assert response.status_code == 201, response.content
        site = Site.objects.get(project=Project.objects.get(name="bind-test-on"))
        assert site.dns_zone_id == zone.pk
        assert site.dns_zone.purpose == "test"


@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_public_site_binds_purpose_prod_zone(auth_client):
    """purpose=prod is always eligible — Site has no tier field.

    What would make this fail: requiring HUB_TEST_MODE for prod, or adding
    Site.tier and gating bind on it.
    """
    from core.models import Project, Site

    _target()
    zone = _zone("prod.example", purpose="prod")
    with override_settings(HUB_TEST_MODE=False):
        response = _create(auth_client, "bind-prod")
    assert response.status_code == 201, response.content
    site = Site.objects.get(project=Project.objects.get(name="bind-prod"))
    assert site.dns_zone_id == zone.pk
    assert site.dns_zone.purpose == "prod"
    assert "tier" not in {f.name for f in Site._meta.get_fields()}


@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_requested_ineligible_zone_is_409_and_creates_nothing(auth_client):
    """A body dns_zone that is not eligible is 409, zero rows, zero Findings.

    What would make this fail: binding a purpose=test zone outside the test
    plane because the operator asked, or creating the Project before the check.
    """
    from core.models import Finding

    _target()
    _zone("eligible.example", purpose="prod")
    ineligible = _zone("lab.example", purpose="test")
    before = _counts()
    with override_settings(HUB_TEST_MODE=False):
        response = _create(auth_client, "bind-ineligible", dns_zone=ineligible.pk)
    assert response.status_code == 409, response.content
    assert _counts() == before
    assert not Finding.objects.filter(fingerprint__startswith="site-dns-unbound").exists()


@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_one_enrolled_target_auto_binds_primary_target(auth_client):
    """Exactly one Target row auto-binds Site.primary_target.

    What would make this fail: leaving primary_target null when the fleet
    has one enrolled host, so adopt later refuses a site the operator just created.
    """
    from core.models import Project, Site

    target = _target(slug="solo-host")
    _zone("solo.example")
    response = _create(auth_client, "bind-solo-target")
    assert response.status_code == 201, response.content
    site = Site.objects.get(project=Project.objects.get(name="bind-solo-target"))
    assert site.primary_target_id == target.pk


@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_several_targets_require_primary_target_in_the_body(auth_client):
    """Several Targets: body primary_target is required (I-target).

    What would make this fail: picking the first host, or 409 even when the
    operator names an enrolled Target pk.
    """
    from core.models import Project, Site

    first = _target(slug="host-a")
    second = _target(slug="host-b")
    _zone("multi-host.example")
    before = _counts()

    missing = _create(auth_client, "bind-hosts")
    assert missing.status_code == 409, missing.content
    assert _counts() == before

    response = _create(auth_client, "bind-hosts", primary_target=second.pk)
    assert response.status_code == 201, response.content
    site = Site.objects.get(project=Project.objects.get(name="bind-hosts"))
    assert site.primary_target_id == second.pk
    assert site.primary_target_id != first.pk


@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_zero_targets_is_409_and_creates_nothing(auth_client):
    """Zero enrolled Targets: 409 and neither row is created.

    What would make this fail: creating a public Site with no host so adopt
    and deploy have no implicit target to invent.
    """
    from core.models import Target

    _zone("notarget.example")
    assert Target.objects.count() == 0
    before = _counts()
    response = _create(auth_client, "bind-no-host")
    assert response.status_code == 409, response.content
    assert _counts() == before


@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_mesh_only_site_may_omit_dns_zone(auth_client):
    """mesh_only is the one exposure that may skip the DnsZone FK.

    What would make this fail: applying the public eligible-zone 409 to
    tailnet-only sites, or requiring a domain on mesh_only.
    """
    from core.models import Project, Site

    _target()
    before = _counts()
    body = _public_body("bind-mesh", exposure="mesh_only", domain="")
    response = auth_client.post(
        PROJECTS,
        body,
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    site = Site.objects.get(project=Project.objects.get(name="bind-mesh"))
    assert site.exposure == Site.Exposure.MESH_ONLY
    assert site.dns_zone_id is None
    assert _counts() == (before[0] + 1, before[1] + 1, before[2])
