"""Partner isolation + template-only refuse (PART-ISOLATION / PART-TEMPLATES).

Isolation is Partner + PartnerSite + dedicated destination Targets. No Site.tier,
Site.partner_id, or Target.tier. Hub host, non-partner co-host, empty
destination_order, overflow, and own-server without tunnel refuse. Validated
jobs become ordinary Deployments only when PARTNER_API_ENABLED. Do not import
intake from these Hub modules.
"""
import ast
import json
import pathlib
import re

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
HUB_URL = "https://hub.example.test"
HUB_HOST = "hub.example.test"
TEMPLATE_REF = "partner-t1-static"
DIGEST_PATH = REPO / "conformance" / "fixtures" / "partner-t1-template.digest"
VECTORS_PATH = REPO / "conformance" / "fixtures" / "partner-signature-vectors.json"
SOURCE_DIR = REPO / "images" / "partner-t1-static"
DECOY_PUBKEY_B64 = "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA="
INTAKE_IMPORT_RE = re.compile(r"^\s*(?:from|import)\s+intake\b", re.M)
HUB_MODULES = (
    REPO / "core" / "partner_jobs.py",
    REPO / "core" / "partner_templates.py",
    REPO / "monitor" / "intake_poll.py",
    REPO / "scaling" / "attack_gate.py",
)


def _zone(slug):
    from core.models import NetworkZone

    return NetworkZone.objects.create(name=slug, slug=slug)


def _target(zone, host, *, kind="aws_ec2", tunnel=None):
    from core.models import Target

    kwargs = {
        "zone": zone,
        "host": host,
        "kind": kind,
        "status": Target.Status.READY,
    }
    if tunnel is True:
        kwargs["collect_payload"] = {"tunnel": True}
    elif tunnel is False:
        kwargs["collect_payload"] = {"tunnel": False}
    return Target.objects.create(**kwargs)


def _partner(slug, targets=None, **kwargs):
    from core.models import Partner

    kwargs.setdefault("name", slug)
    if targets is not None:
        kwargs["destination_order"] = [t.pk for t in targets]
    return Partner.objects.create(slug=slug, **kwargs)


def _plain_site(name, target=None):
    from core.models import Project, Site

    project = Project.objects.create(name=name, slug=name)
    return Site.objects.create(
        project=project,
        name=name,
        exposure=Site.Exposure.MESH_ONLY,
        primary_target=target,
        domain=f"{name}.example.test",
    )


def _job(partner, *, tenant_ref="t1", subdomain="acme", extra=None, job_id=None):
    payload = {
        "tenant_ref": tenant_ref,
        "subdomain": subdomain,
        "template_ref": TEMPLATE_REF,
    }
    if extra:
        payload.update(extra)
    return {
        "id": job_id or f"job-{partner.slug}-{tenant_ref}",
        "type": "partner-job",
        "action": "site.create",
        "partner_pk": partner.pk,
        "method": "POST",
        "path": "/partner/v1/sites",
        "body": json.dumps(payload),
        "payload": payload,
        "headers": {},
    }


def _vectors():
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def _intake_shaped_job(vectors, *, job_id):
    """Mesh outbox shape from intake/app.py _outbox_job: no partner_pk."""
    case = vectors["cases"]["valid"]
    payload = json.loads(case["body"])
    payload.setdefault("template_ref", TEMPLATE_REF)
    return {
        "id": job_id,
        "type": "partner-job",
        "action": "site.create",
        "method": case["method"],
        "path": case["path"],
        "body": case["body"],
        "headers": dict(case["headers"]),
        "payload": payload,
    }


def _assert_no_intake_import(path):
    src = path.read_text(encoding="utf-8")
    assert INTAKE_IMPORT_RE.search(src) is None
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] != "intake"
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] != "intake"


@pytest.mark.req("PART-ISOLATION")
def test_partner_a_404s_on_partner_b_ids():
    """Partner A looking up B's site or deployment id is 404, never 403.

    What would make this fail: a queryset that is not filtered on Partner, or
    returning 403 which confirms the id exists in another tenant.
    """
    from core.partner_jobs import (
        PartnerNotFound,
        get_partner_deployment,
        get_partner_site,
        partner_sites_qs,
    )

    from deploys.models import Deployment, Manifest

    zone = _zone("idor-zone")
    target_a = _target(zone, "a.lan")
    target_b = _target(zone, "b.lan")
    partner_a = _partner("idor-a", [target_a])
    partner_b = _partner("idor-b", [target_b])
    site_b = _plain_site("idor-b-site", target_b)
    from core.models import PartnerSite

    PartnerSite.objects.create(
        partner=partner_b, site=site_b, tenant_ref="tenant-b",
    )
    manifest = Manifest.objects.create(site=site_b, version=1, body={})
    dep_b = Deployment.objects.create(manifest=manifest)

    assert site_b not in list(partner_sites_qs(partner_a))
    with pytest.raises(PartnerNotFound) as site_exc:
        get_partner_site(partner_a, site_b.pk)
    assert site_exc.value.status == 404
    assert site_exc.value.status != 403
    with pytest.raises(PartnerNotFound) as dep_exc:
        get_partner_deployment(partner_a, dep_b.pk)
    assert dep_exc.value.status == 404
    assert dep_exc.value.status != 403
    missing = get_partner_site
    with pytest.raises(PartnerNotFound) as missing_exc:
        missing(partner_a, 0)
    assert missing_exc.value.status == 404


@pytest.mark.req("PART-ISOLATION")
def test_no_site_tier_column():
    """Isolation is PartnerSite membership, not Site.tier (D-053 / D-078).

    What would make this fail: a Site.tier column so partner-ness is a Site
    attribute instead of the PartnerSite binding.
    """
    from core.models import Site

    assert "tier" not in {f.name for f in Site._meta.get_fields()}


@pytest.mark.req("PART-ISOLATION")
def test_no_site_partner_id_and_no_target_tier():
    """No Site.partner_id and no Target.tier; partner-tier is destination_order.

    What would make this fail: denormalizing Partner onto Site or a Target.tier
    column that later tasks would have to keep in sync with destination_order.
    """
    from core.models import Site, Target

    site_names = {f.name for f in Site._meta.get_fields()}
    assert "partner_id" not in site_names
    assert "partner" not in site_names
    assert "tier" not in {f.name for f in Target._meta.get_fields()}


@pytest.mark.req("PART-ISOLATION")
@override_settings(HUB_PUBLIC_URL=HUB_URL, PARTNER_API_ENABLED=True)
def test_hub_host_refuses():
    """A destination whose host is the topology r1 Hub hostname refuses.

    What would make this fail: treating the Hub box as just another ranked
    target so a partner site lands on the control plane.
    """
    from core.partner_jobs import PartnerRefuse, materialize

    from deploys.models import Deployment

    zone = _zone("hub-host-zone")
    hub = _target(zone, HUB_HOST)
    partner = _partner("hub-host-p", [hub])
    with pytest.raises(PartnerRefuse) as exc:
        materialize(partner, _job(partner, tenant_ref="hub-t"))
    assert exc.value.reason == "hub-host"
    assert Deployment.objects.count() == 0
    _assert_no_intake_import(REPO / "core" / "partner_jobs.py")


@pytest.mark.req("PART-ISOLATION")
@override_settings(PARTNER_API_ENABLED=True, HUB_PUBLIC_URL=HUB_URL)
def test_non_partner_cohost_refuses():
    """A Target that already hosts a non-PartnerSite refuses this partner.

    What would make this fail: co-hosting a partner site with Joseph prod, or
    accepting a partner-base domain that already belongs to a non-partner Site.
    """
    from core.partner_jobs import PartnerRefuse, materialize

    from deploys.models import Deployment

    zone = _zone("cohost-zone")
    box = _target(zone, "cohost.lan")
    partner = _partner("cohost-p", [box])
    _plain_site("prod-shop", box)
    with pytest.raises(PartnerRefuse) as exc:
        materialize(partner, _job(partner, tenant_ref="cohost-t"))
    assert exc.value.reason == "non-partner-cohost"
    assert Deployment.objects.count() == 0

    clean_zone = _zone("base-zone")
    clean = _target(clean_zone, "base.lan")
    partner2 = _partner("base-p", [clean])
    taken = _plain_site("joseph-prod")
    taken.domain = "apps.example.test"
    taken.save(update_fields=["domain"])
    with pytest.raises(PartnerRefuse) as base_exc:
        materialize(
            partner2,
            _job(
                partner2,
                tenant_ref="base-t",
                extra={"domain": "apps.example.test"},
            ),
        )
    assert base_exc.value.reason == "partner-base"


@pytest.mark.req("PART-ISOLATION")
@override_settings(PARTNER_API_ENABLED=True)
def test_empty_destination_order_refuses_create():
    """Empty destination_order refuses create-site; there is no implicit Hub dest.

    What would make this fail: falling back to any ready Target, including the
    Hub host, when the operator has not ranked destinations.
    """
    from core.partner_jobs import PartnerRefuse, materialize

    from deploys.models import Deployment

    zone = _zone("empty-dest-zone")
    _target(zone, "unused.lan")
    partner = _partner("empty-dest-p", [])
    assert partner.destination_order == []
    with pytest.raises(PartnerRefuse) as exc:
        materialize(partner, _job(partner, tenant_ref="empty-t"))
    assert exc.value.reason == "empty-destination-order"
    assert Deployment.objects.count() == 0


@pytest.mark.req("PART-ISOLATION")
def test_overflow_scale_refuses_partner_site():
    """Partner overflow refuses even when the attack playbook is not engaged.

    What would make this fail: only refuse_if_attack gating scale, so a partner
    site scales on quiet traffic; or removing refuse_if_attack.
    """
    from scaling.attack_gate import (
        PartnerOverflowRefuse,
        refuse_if_attack,
        refuse_if_partner_overflow,
    )

    zone = _zone("overflow-zone")
    box = _target(zone, "overflow.lan")
    partner = _partner("overflow-p", [box])
    site = _plain_site("overflow-site", box)
    from core.models import PartnerSite

    PartnerSite.objects.create(
        partner=partner, site=site, tenant_ref="overflow-t",
    )
    quiet = _plain_site("overflow-quiet")
    assert refuse_if_attack(quiet) is None
    with pytest.raises(PartnerOverflowRefuse):
        refuse_if_partner_overflow(site)
    with pytest.raises(PartnerOverflowRefuse):
        refuse_if_attack(site)
    src = (REPO / "scaling" / "attack_gate.py").read_text(encoding="utf-8")
    assert "def refuse_if_attack(" in src


@pytest.mark.req("PART-ISOLATION")
@override_settings(PARTNER_API_ENABLED=True)
def test_own_server_without_tunnel_refuses():
    """kind=ssh destination refuses unless collect_payload['tunnel'] is True.

    What would make this fail: ranking an own-server target without Tunnel so
    a partner origin is reachable on the operator's residential IP.
    """
    from core.partner_jobs import PartnerRefuse, materialize

    from core.models import Finding
    from deploys.models import Deployment

    zone = _zone("ssh-zone")
    box = _target(zone, "own.lan", kind="ssh", tunnel=False)
    partner = _partner("ssh-p", [box])
    with pytest.raises(PartnerRefuse) as exc:
        materialize(partner, _job(partner, tenant_ref="ssh-t"))
    assert exc.value.reason == "tunnel-required"
    assert Deployment.objects.count() == 0
    assert Finding.objects.filter(
        fingerprint=f"partner-tunnel-required:{box.pk}",
    ).exists()

    tunneled = _target(zone, "tun.lan", kind="ssh", tunnel=True)
    partner2 = _partner("ssh-tun-p", [tunneled])
    result = materialize(partner2, _job(partner2, tenant_ref="ssh-ok"))
    assert result is not None
    assert result.deployment.pk
    assert result.site.partner_site.partner_id == partner2.pk


@pytest.mark.req("PART-TEMPLATES")
@override_settings(PARTNER_API_ENABLED=True)
def test_dockerfile_or_git_source_refuses():
    """Partner Dockerfile, build step, git-as-source, and jobs_image refuse.

    What would make this fail: honoring a partner-supplied Dockerfile or git URL
    so unconstrained code lands on a partner-tier target.
    """
    from core.partner_jobs import PartnerRefuse, materialize

    from deploys.models import Deployment

    zone = _zone("src-zone")
    box = _target(zone, "src.lan")
    partner = _partner("src-p", [box])
    cases = (
        {"dockerfile": "FROM nginx"},
        {"Dockerfile": "FROM alpine"},
        {"build": True},
        {"jobs_image": "jobs:latest"},
        {"git_url": "https://github.com/o/r.git"},
        {"source_kind": "git"},
    )
    for extra in cases:
        with pytest.raises(PartnerRefuse) as exc:
            materialize(
                partner,
                _job(partner, tenant_ref=f"src-{next(iter(extra))}", extra=extra),
            )
        assert exc.value.reason in {
            "dockerfile", "build", "jobs_image", "git-source",
        }
    assert Deployment.objects.count() == 0


@pytest.mark.req("PART-TEMPLATES")
@override_settings(PARTNER_API_ENABLED=True)
def test_unconstrained_image_refuses():
    """An image that is not the digest-pinned fixture refuses.

    What would make this fail: accepting nginx:latest or a tag without the
    pinned digest so a partner picks any Hub-pullable image.
    """
    from core.partner_jobs import PartnerRefuse, materialize

    from deploys.models import Deployment

    zone = _zone("img-zone")
    box = _target(zone, "img.lan")
    partner = _partner("img-p", [box])
    for extra in (
        {"image": "nginx:latest"},
        {"image": "alpine"},
        {"image_digest": "sha256:" + "ab" * 32},
        {"template_ref": "not-the-fixture"},
    ):
        with pytest.raises(PartnerRefuse) as exc:
            materialize(
                partner,
                _job(
                    partner,
                    tenant_ref=f"img-{hash(json.dumps(extra, sort_keys=True))}",
                    extra=extra,
                ),
            )
        assert exc.value.reason == "unconstrained-image"
    assert Deployment.objects.count() == 0


@pytest.mark.req("PART-TEMPLATES")
@override_settings(PARTNER_API_ENABLED=True)
def test_digest_pinned_fixture_template_deploys():
    """The digest-pinned images/partner-t1-static fixture becomes a Deployment.

    What would make this fail: requiring a partner Dockerfile, skipping the
    digest file, or creating a Site without a PartnerSite binding.
    """
    from core.partner_jobs import materialize
    from core.partner_templates import FIXTURE_DIGEST
    from core.partner_templates import TEMPLATE_REF as REF

    from core.models import PartnerSite
    from core.transport import FakeTransport
    from deploys.models import Deployment
    from providers.fakes import FakeImageRegistry

    assert SOURCE_DIR.is_dir()
    assert (SOURCE_DIR / "Dockerfile").is_file()
    assert DIGEST_PATH.is_file()
    pin = DIGEST_PATH.read_text(encoding="utf-8").strip()
    assert pin.startswith("sha256:")
    assert FIXTURE_DIGEST == pin
    assert REF == TEMPLATE_REF

    zone = _zone("pin-zone")
    box = _target(zone, "pin.lan")
    partner = _partner("pin-p", [box])
    registry = FakeImageRegistry()
    transport = FakeTransport()
    result = materialize(
        partner,
        _job(partner, tenant_ref="pin-t"),
        transport=transport,
        registry=registry,
    )
    assert result is not None
    assert result.deployment.status == Deployment.Status.QUEUED
    assert result.partner_site.partner_id == partner.pk
    assert result.site.primary_target_id == box.pk
    assert PartnerSite.objects.filter(
        partner=partner, site=result.site, tenant_ref="pin-t",
    ).exists()
    assert result.manifest.body.get("image_digest") == pin
    assert result.site.project.git_url == ""
    assert result.site.project.source_kind != result.site.project.Source.GIT
    assert pin in registry.images
    _assert_no_intake_import(REPO / "core" / "partner_templates.py")


@pytest.mark.req("PART-TEMPLATES")
@override_settings(PARTNER_API_ENABLED=True)
def test_template_is_not_applied_catalog_entry():
    """The fixture is images/ + digest file, not catalog/ AppliedCatalogEntry.

    What would make this fail: applying a catalog entry to ship the template,
    or growing a PartnerTemplate table.
    """
    from core.partner_jobs import materialize
    from core.partner_templates import SOURCE_DIR as SRC
    from django.apps import apps

    from catalog.models import AppliedCatalogEntry

    zone = _zone("cat-zone")
    box = _target(zone, "cat.lan")
    partner = _partner("cat-p", [box])
    before = AppliedCatalogEntry.objects.count()
    materialize(partner, _job(partner, tenant_ref="cat-t"))
    assert AppliedCatalogEntry.objects.count() == before
    assert SRC == SOURCE_DIR
    assert "catalog" not in SRC.parts
    src = (REPO / "core" / "partner_templates.py").read_text(encoding="utf-8")
    assert "AppliedCatalogEntry" not in src
    imports = set()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.add(node.module.split(".")[0])
    assert "catalog" not in imports
    from core import models as core_models

    assert not hasattr(core_models, "PartnerTemplate")
    assert "PartnerTemplate" not in {m.__name__ for m in apps.get_models()}
    from catalog.entries import CATALOG

    ids = {entry.id for entry in CATALOG}
    assert TEMPLATE_REF not in ids
    assert all("partner-t1" not in entry.id for entry in CATALOG)


def test_flag_off_does_not_create_deployment():
    """PARTNER_API_ENABLED default False leaves jobs un-materialized.

    What would make this fail: creating a Deployment on the default-off flag
    so a T1 poll of Fake intake becomes a live partner site; or acking the
    outbox job so Task 7 enable finds nothing to apply.
    """
    from core.partner_jobs import materialize
    from django.conf import settings

    from deploys.models import Deployment
    from monitor.intake_poll import FakeIntakeClient, poll

    assert settings.PARTNER_API_ENABLED is False
    vectors = _vectors()
    zone = _zone("flag-zone")
    box = _target(zone, "flag.lan")
    partner = _partner(
        "flag-p", [box], pubkey_current=vectors["public_key_raw_b64"],
    )
    job = _intake_shaped_job(vectors, job_id="job-flag-t")
    assert "partner_pk" not in job
    assert "partner_id" not in job
    with override_settings(PARTNER_API_ENABLED=False):
        assert materialize(partner, job) is None
        client = FakeIntakeClient(items=[job])
        poll(
            client=client, now=vectors["now"], jitter=0, sleep=lambda _s: None,
        )
    assert Deployment.objects.count() == 0
    assert client.acked == []
    assert client.items == [job]
    with override_settings(PARTNER_API_ENABLED=True):
        poll(
            client=client, now=vectors["now"], jitter=0, sleep=lambda _s: None,
        )
    assert Deployment.objects.count() == 1
    assert client.acked == [job["id"]]
    assert client.items == []


@pytest.mark.req("PART-ISOLATION")
@override_settings(PARTNER_API_ENABLED=True)
def test_intake_shaped_job_without_partner_pk_materializes():
    """A job with method/path/body/headers and no partner_pk still materializes.

    What would make this fail: binding Partner from planted partner_pk so
    production-shaped intake outbox rows skip reverify and never become a
    Deployment, or applying the decoy Partner whose key does not verify.
    """
    from core.models import PartnerSite
    from deploys.models import Deployment
    from monitor.intake_poll import FakeIntakeClient, poll

    vectors = _vectors()
    zone = _zone("bind-zone")
    box = _target(zone, "bind.lan")
    decoy = _partner("bind-decoy", [], pubkey_current=DECOY_PUBKEY_B64)
    partner = _partner(
        "bind-p", [box], pubkey_current=vectors["public_key_raw_b64"],
    )
    job = _intake_shaped_job(vectors, job_id="job-bind-t")
    assert "partner_pk" not in job
    assert "partner_id" not in job
    assert job["headers"].get("X-Partner-Key-Id")
    client = FakeIntakeClient(items=[job])
    poll(
        client=client, now=vectors["now"], jitter=0, sleep=lambda _s: None,
    )
    assert Deployment.objects.count() == 1
    dep = Deployment.objects.select_related("manifest__site").get()
    binding = PartnerSite.objects.get(site=dep.manifest.site)
    assert binding.partner_id == partner.pk
    assert binding.partner_id != decoy.pk
    assert client.acked == [job["id"]]
    assert client.items == []
    src = (REPO / "monitor" / "intake_poll.py").read_text(encoding="utf-8")
    assert 'job.get("partner_pk")' not in src
    assert 'job.get("partner_id")' not in src


@pytest.mark.req("PART-ISOLATION")
@override_settings(PARTNER_API_ENABLED=True)
def test_materialize_run_twice_zero_mutating_calls():
    """Second materialize of the same job records zero mutating calls (D6).

    What would make this fail: a second docker load / registry push, or a
    second Deployment row for the same partner-job id.
    """
    from core.partner_jobs import materialize

    from core.transport import FakeTransport
    from deploys.models import Deployment
    from providers.fakes import FakeImageRegistry

    zone = _zone("twice-zone")
    box = _target(zone, "twice.lan")
    partner = _partner("twice-p", [box])
    job = _job(partner, tenant_ref="twice-t", job_id="job-twice-1")
    transport = FakeTransport()
    registry = FakeImageRegistry()
    first = materialize(
        partner, job, transport=transport, registry=registry,
    )
    assert first.deployment.pk
    t_n = len(transport.mutating_calls())
    r_n = len(registry.mutating_calls())
    assert r_n >= 1 or t_n >= 1
    second = materialize(
        partner, job, transport=transport, registry=registry,
    )
    assert second.deployment.pk == first.deployment.pk
    assert Deployment.objects.count() == 1
    assert transport.mutating_calls()[t_n:] == []
    assert registry.mutating_calls()[r_n:] == []
    for path in HUB_MODULES:
        if path.is_file():
            _assert_no_intake_import(path)
