"""§F3 first-run checklist is derived fleet state (UX-F3-FIRST-RUN-CHECKLIST).

GET /api/v1/first-run/ reads Target / DnsAccount / origin_ca_key_ref / Project
/ Site. It does not open a topic: seq is the findings counter. mesh_only first
site skips Cloudflare connect and Origin-CA plant. A proxied public Site keeps
Home owned until plant. site-dns-unbound is illegal — this test never creates
an unbound public Site.
"""
import pytest

from core.models import DnsAccount, Project, Site

pytestmark = [pytest.mark.django_db, pytest.mark.req("UX-F3-FIRST-RUN-CHECKLIST")]

FIRST_RUN = "/api/v1/first-run/"


@pytest.fixture
def auth_client(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


def _target(*, slug="f3-target"):
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(name=slug, slug=slug)
    return Target.objects.create(
        zone=zone, kind=Target.Kind.SSH, host=f"{slug}.example.com",
    )


def _items(body):
    return {row["id"]: row for row in body["data"]["items"]}


def _get(client):
    response = client.get(FIRST_RUN)
    assert response.status_code == 200, response.content
    body = response.json()
    assert "seq" in body and "data" in body
    return body


def test_checklist_derives_from_target_zone_plant_and_project(auth_client):
    """owns_home flips only as Target, zone, plant, and Project appear.

    What would make this fail: a dedicated checklist topic, treating plant as
    done before origin_ca_key_ref, or creating a public Site with no DnsZone.
    """
    from core.findings import findings_seq
    from realtime.authorize import ALLOWED_PREFIXES

    assert not any("checklist" in p or "first-run" in p or "first_run" in p
                   for p in ALLOWED_PREFIXES)

    empty = _get(auth_client)
    assert empty["seq"] == findings_seq()
    assert empty["data"]["owns_home"] is True
    items = _items(empty)
    assert items["enroll_target"] == {
        "id": "enroll_target", "applicable": True, "done": False,
    }
    assert items["connect_cloudflare"]["applicable"] is True
    assert items["connect_cloudflare"]["done"] is False
    assert items["plant_origin_ca"]["applicable"] is False
    assert items["add_project"]["done"] is False
    assert Site.objects.filter(dns_zone__isnull=True).exclude(
        exposure=Site.Exposure.MESH_ONLY,
    ).count() == 0

    target = _target()
    after_target = _get(auth_client)
    assert _items(after_target)["enroll_target"]["done"] is True
    assert after_target["data"]["owns_home"] is True

    from dns_fixtures import default_dns_zone

    zone = default_dns_zone("f3.example")
    after_zone = _get(auth_client)
    assert _items(after_zone)["connect_cloudflare"]["done"] is True
    assert _items(after_zone)["plant_origin_ca"]["applicable"] is False
    assert after_zone["data"]["owns_home"] is True

    project = Project.objects.create(
        name="f3-pub", slug="f3-pub", source_kind=Project.Source.LOCAL_PATH,
        local_path="/tmp/f3-pub",
    )
    Site.objects.create(
        project=project, name="f3-pub", domain="app.f3.example",
        exposure=Site.Exposure.PUBLIC, proxied=True, dns_zone=zone,
        primary_target=target,
    )
    after_project = _get(auth_client)
    plant = _items(after_project)["plant_origin_ca"]
    assert _items(after_project)["add_project"]["done"] is True
    assert plant["applicable"] is True
    assert plant["done"] is False
    assert after_project["data"]["owns_home"] is True
    assert not Site.objects.filter(
        exposure=Site.Exposure.PUBLIC, dns_zone__isnull=True,
    ).exists()

    account = DnsAccount.objects.get(label="test-fixture")
    account.origin_ca_key_ref = "planted-ref-not-a-key"
    account.save(update_fields=["origin_ca_key_ref"])
    done = _get(auth_client)
    assert _items(done)["plant_origin_ca"]["done"] is True
    assert done["data"]["owns_home"] is False
    assert done["seq"] == findings_seq()


def test_mesh_only_skips_cf_items(auth_client):
    """A mesh_only first site does not require Cloudflare or Origin-CA plant.

    What would make this fail: blocking first-run on connect/plant for a
    tailnet-only first deploy, or requiring a DnsZone on mesh_only.
    """
    from core.models import Target

    target = _target(slug="f3-mesh")
    project = Project.objects.create(
        name="f3-mesh", slug="f3-mesh", source_kind=Project.Source.LOCAL_PATH,
        local_path="/tmp/f3-mesh",
    )
    site = Site.objects.create(
        project=project, name="f3-mesh", exposure=Site.Exposure.MESH_ONLY,
        primary_target=target,
    )
    assert site.dns_zone_id is None
    assert DnsAccount.objects.count() == 0
    assert Target.objects.count() == 1

    body = _get(auth_client)
    items = _items(body)
    assert items["enroll_target"]["done"] is True
    assert items["add_project"]["done"] is True
    assert items["connect_cloudflare"]["applicable"] is False
    assert items["plant_origin_ca"]["applicable"] is False
    assert body["data"]["owns_home"] is False
