"""Hub-authoritative U2 quotas (PART-U2-QUOTAS / D-084).

Hub refuses create-site over max_sites=5 and fleet 12, deploy-create over
deploys_per_day=50, add-domain over domains=5, and rate floors 60 req/min
plus deploy-create 3/min + 100/day per site. Intake allow cannot override.
Unbounded max_sites is out. Quota-abuse files budget-cap-hit:partner.
Enforcement lives in the Task 4 re-validator; do not mark live Q9 ids.
"""
import ast
import json
import pathlib

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import override_settings
from django.utils import timezone

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
VECTORS_PATH = REPO / "conformance" / "fixtures" / "partner-signature-vectors.json"
DECISIONS_PATH = REPO / "DECISIONS.md"
VERIFY_PATH = REPO / "core" / "partner_verify.py"
TEMPLATE_REF = "partner-t1-static"
FORBIDDEN_MARKS = {"PART-Q9-T2-CONTAINER", "PART-Q9-T3-LIVE-PATH"}
SECRET_NEEDLES = (
    "whsec_",
    "BEGIN PRIVATE",
    "BEGIN OPENSSH PRIVATE",
    "hubk_",
)
RATE_HEADERS = (
    "X-RateLimit-Limit",
    "X-RateLimit-Remaining",
    "X-RateLimit-Reset",
)


def _vectors():
    return json.loads(VECTORS_PATH.read_text(encoding="utf-8"))


def _partner(slug, **kwargs):
    from core.models import Partner

    kwargs.setdefault("name", slug)
    return Partner.objects.create(slug=slug, **kwargs)


def _signed_partner(slug, **kwargs):
    vectors = _vectors()
    kwargs.setdefault("pubkey_current", vectors["public_key_raw_b64"])
    return _partner(slug, **kwargs), vectors


def _plain_site(name, *, domain=""):
    from core.models import Project, Site

    project = Project.objects.create(name=name, slug=name)
    return Site.objects.create(
        project=project,
        name=name,
        exposure=Site.Exposure.MESH_ONLY,
        domain=domain,
    )


def _bind_sites(partner, n, *, domain=False):
    from core.models import PartnerSite

    sites = []
    for i in range(n):
        host = f"{partner.slug}-{i}.apps.invalid" if domain else ""
        site = _plain_site(f"{partner.slug}-s{i}", domain=host)
        PartnerSite.objects.create(
            partner=partner, site=site, tenant_ref=f"tenant-{i}",
        )
        sites.append(site)
    return sites


def _zone(slug):
    from core.models import NetworkZone

    return NetworkZone.objects.create(name=slug, slug=slug)


def _target(zone, host):
    from core.models import Target

    return Target.objects.create(
        zone=zone, host=host, kind="aws_ec2", status=Target.Status.READY,
    )


def _job(partner, *, tenant_ref="t-new", extra=None):
    payload = {
        "tenant_ref": tenant_ref,
        "subdomain": tenant_ref,
        "template_ref": TEMPLATE_REF,
    }
    if extra:
        payload.update(extra)
    return {
        "id": f"job-{partner.slug}-{tenant_ref}",
        "type": "partner-job",
        "action": "site.create",
        "method": "POST",
        "path": "/partner/v1/sites",
        "body": json.dumps(payload),
        "payload": payload,
        "headers": {},
    }


def _raw_pubkey_b64(private):
    import base64

    from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat

    raw = private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)
    return base64.b64encode(raw).decode("ascii")


def _sign_headers(private, method, path, body, *, now, nonce):
    import base64

    from core.partner_verify import canonical_string

    ts = str(int(now.timestamp()) if hasattr(now, "timestamp") else int(now))
    message = canonical_string(method, path, body, ts, nonce).encode("ascii")
    return {
        "X-Partner-Timestamp": ts,
        "X-Partner-Nonce": nonce,
        "X-Partner-Key-Id": "hubk_test_fixture",
        "X-Partner-Signature": base64.b64encode(private.sign(message)).decode("ascii"),
    }


def _signed_deploy_create_job(partner, private, site, *, tenant_ref, now, nonce):
    """Intake-shaped POST .../deployments, not POST /partner/v1/sites."""
    payload = {
        "tenant_ref": tenant_ref,
        "subdomain": tenant_ref,
        "template_ref": TEMPLATE_REF,
    }
    path = f"/partner/v1/sites/{site.pk}/deployments"
    body = json.dumps(payload)
    return {
        "id": f"job-{partner.slug}-dc-{tenant_ref}",
        "type": "partner-job",
        "action": "deployment.create",
        "method": "POST",
        "path": path,
        "body": body,
        "payload": payload,
        "headers": _sign_headers(
            private, "POST", path, body, now=now, nonce=nonce,
        ),
    }


def _plant_nonces(partner, n, *, now):
    from core.models import PartnerReplayNonce

    rows = [
        PartnerReplayNonce(partner=partner, nonce=f"rl-{partner.pk}-{i:04d}", seen_at=now)
        for i in range(n)
    ]
    PartnerReplayNonce.objects.bulk_create(rows)
    PartnerReplayNonce.objects.filter(partner=partner).update(seen_at=now)


def _plant_deploys(site, n, *, created_at):
    from deploys.models import Deployment, Manifest

    for i in range(n):
        last = site.manifests.order_by("-version").values_list("version", flat=True).first()
        version = (last or 0) + 1
        manifest = Manifest.objects.create(site=site, version=version, body={"n": i})
        Manifest.objects.filter(pk=manifest.pk).update(created_at=created_at)
        Deployment.objects.create(manifest=manifest)


def _assert_rate_headers(headers, *, limit):
    for name in RATE_HEADERS:
        assert name in headers, f"missing {name}"
    assert str(headers["X-RateLimit-Limit"]) == str(limit)
    remaining = int(headers["X-RateLimit-Remaining"])
    assert remaining >= 0
    assert int(headers["X-RateLimit-Reset"]) > 0


def _finding_blobs():
    from core.models import AuditEvent, CheckRun, Finding

    blobs = []
    for row in Finding.objects.all():
        blobs.extend([
            row.title, row.body, row.fix_action, row.entity,
            row.fingerprint, row.severity, row.source_engine,
        ])
    for event in AuditEvent.objects.all():
        blobs.extend([event.action, event.detail, event.object_type, event.object_id])
    for run in CheckRun.objects.all():
        blobs.extend([run.kind, run.status, str(run.results)])
    return json.dumps(blobs, default=str)


def _assert_no_secrets(blob):
    lower = blob.lower()
    for needle in SECRET_NEEDLES:
        assert needle.lower() not in lower, f"secret {needle!r} leaked into quota surfaces"


def _assert_no_live_marks():
    tree = ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if not (isinstance(func, ast.Attribute) and func.attr == "req"):
            continue
        if not node.args:
            continue
        arg0 = node.args[0]
        if isinstance(arg0, ast.Constant) and arg0.value in FORBIDDEN_MARKS:
            found.append(arg0.value)
    assert found == [], f"T1 quota tests must not mark live Q9 ids: {found}"


@pytest.mark.req("PART-U2-QUOTAS")
def test_max_sites_default_5():
    """Partner.max_sites defaults to 5 and the fifth site is still allowed.

    What would make this fail: a different default, null (unbounded), or the
    Hub treating the fifth site as already over cap. Rate-limit headers must
    ride an under-cap Hub re-verify so intake copies cannot be the only source.
    """
    from core.models import Partner, PartnerSite
    from core.partner_jobs import materialize
    from core.partner_verify import reverify

    _assert_no_live_marks()
    assert Partner._meta.get_field("max_sites").default == 5
    assert Partner._meta.get_field("max_sites").null is False
    partner, vectors = _signed_partner("q-max5")
    partner.refresh_from_db()
    assert partner.max_sites == 5
    row = Partner.objects.filter(pk=partner.pk).values("max_sites").get()
    assert row["max_sites"] == 5

    case = vectors["cases"]["valid"]
    verified = reverify(
        partner, case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    assert verified.ok is True
    _assert_rate_headers(verified.headers, limit=60)

    zone = _zone("q-max5-zone")
    box = _target(zone, "q-max5.lan")
    partner.destination_order = [box.pk]
    partner.save(update_fields=["destination_order"])
    _bind_sites(partner, 4)
    with override_settings(PARTNER_API_ENABLED=True):
        result = materialize(partner, _job(partner, tenant_ref="tenant-4"))
    assert result is not None
    assert PartnerSite.objects.filter(partner=partner).count() == 5


@pytest.mark.req("PART-U2-QUOTAS")
@override_settings(PARTNER_API_ENABLED=True)
def test_sixth_site_refuses():
    """A sixth PartnerSite over default max_sites=5 refuses at Hub create-site.

    What would make this fail: counting only in-memory partner.max_sites,
    skipping the re-validator, or materialize creating site 6 after reverify
    already said no.
    """
    from core.models import PartnerSite
    from core.partner_jobs import PartnerRefuse, materialize
    from core.partner_verify import evaluate_quotas, reverify

    partner, vectors = _signed_partner("q-sixth")
    zone = _zone("q-sixth-zone")
    box = _target(zone, "q-sixth.lan")
    partner.destination_order = [box.pk]
    partner.save(update_fields=["destination_order"])
    _bind_sites(partner, partner.max_sites)
    assert PartnerSite.objects.filter(partner=partner).count() == 5

    case = vectors["cases"]["quota-exceeded"]
    verified = reverify(
        partner, case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    assert verified.ok is False
    assert verified.reason == "quota"
    assert verified.status == 403
    _assert_rate_headers(verified.headers, limit=60)

    decision = evaluate_quotas(
        partner, "POST", "/partner/v1/sites",
        now=vectors["now"], body=case["body"],
    )
    assert decision.refused is True
    assert decision.reason == "quota"

    with pytest.raises(PartnerRefuse) as exc:
        materialize(partner, _job(partner, tenant_ref="t-quota"))
    assert exc.value.reason == "quota"
    assert PartnerSite.objects.filter(partner=partner).count() == 5
    assert not PartnerSite.objects.filter(partner=partner, tenant_ref="t-quota").exists()


@pytest.mark.req("PART-U2-QUOTAS")
@override_settings(PARTNER_API_ENABLED=True)
def test_signed_deploy_create_at_max_sites_does_not_create_site_6():
    """A signed deploy-create with a new tenant_ref must not mint site 6.

    evaluate_quotas applies max_sites/fleet only on POST /partner/v1/sites, but
    materialize/_create inserts a PartnerSite for any new or default tenant_ref.
    What would make this fail: path-gated evaluate_quotas so POST
    /partner/v1/sites/{id}/deployments at 5 sites creates PartnerSite 6.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from core.models import PartnerSite
    from core.partner_jobs import PartnerNotFound, PartnerRefuse, materialize
    from core.partner_verify import reverify
    from monitor.intake_poll import FakeIntakeClient, poll

    private = Ed25519PrivateKey.generate()
    partner = _partner("q-dc-sixth", pubkey_current=_raw_pubkey_b64(private))
    zone = _zone("q-dc-sixth-zone")
    box = _target(zone, "q-dc-sixth.lan")
    partner.destination_order = [box.pk]
    partner.save(update_fields=["destination_order"])
    sites = _bind_sites(partner, partner.max_sites)
    assert PartnerSite.objects.filter(partner=partner).count() == 5

    now = timezone.now()
    job = _signed_deploy_create_job(
        partner, private, sites[0],
        tenant_ref="t-sneak-6", now=now, nonce="n-dc-sixth-0001aaaaaaaaaaaaaa",
    )
    assert job["action"] == "deployment.create"
    assert job["path"] != "/partner/v1/sites"
    assert job["path"].endswith("/deployments")

    verified = reverify(
        partner, job["method"], job["path"], job["body"], job["headers"],
        now=now, remember_nonce=False, persist_idempotency=False,
    )
    assert verified.status != 401

    try:
        materialize(partner, job, now=now)
    except (PartnerRefuse, PartnerNotFound):
        pass
    assert PartnerSite.objects.filter(partner=partner).count() == 5
    assert not PartnerSite.objects.filter(
        partner=partner, tenant_ref="t-sneak-6",
    ).exists()

    client = FakeIntakeClient(items=[dict(job)])
    poll(client=client, now=now, jitter=0, sleep=lambda _s: None)
    assert PartnerSite.objects.filter(partner=partner).count() == 5
    assert not PartnerSite.objects.filter(
        partner=partner, tenant_ref="t-sneak-6",
    ).exists()


@pytest.mark.req("PART-U2-QUOTAS")
@override_settings(PARTNER_API_ENABLED=True, PARTNER_FLEET_MAX_SITES=12)
def test_fleet_cap_12_refuses():
    """The thirteenth fleet PartnerSite refuses even when this partner is under max_sites.

    What would make this fail: a per-partner-only cap, a default other than 12,
    or trusting an in-memory max_sites bump to overflow the 30-node map bar.
    """
    from core.models import PartnerSite
    from core.partner_jobs import PartnerRefuse, materialize
    from core.partner_verify import evaluate_quotas

    zone = _zone("q-fleet-zone")
    box = _target(zone, "q-fleet.lan")
    a = _partner("q-fleet-a", max_sites=10, destination_order=[box.pk])
    b = _partner("q-fleet-b", max_sites=10, destination_order=[box.pk])
    c = _partner("q-fleet-c", max_sites=10, destination_order=[box.pk])
    _bind_sites(a, 6)
    _bind_sites(b, 6)
    assert PartnerSite.objects.count() == 12

    decision = evaluate_quotas(
        c, "POST", "/partner/v1/sites",
        body=json.dumps({"tenant_ref": "fleet-13"}),
    )
    assert decision.refused is True
    assert decision.reason == "quota"

    with pytest.raises(PartnerRefuse) as exc:
        materialize(c, _job(c, tenant_ref="fleet-13"))
    assert exc.value.reason == "quota"
    assert PartnerSite.objects.count() == 12


@pytest.mark.req("PART-U2-QUOTAS")
@override_settings(PARTNER_API_ENABLED=True, PARTNER_FLEET_MAX_SITES=12)
def test_signed_deploy_create_at_fleet_cap_does_not_create_site_13():
    """A signed deploy-create with a new tenant_ref must not mint fleet site 13.

    Same insert hole as max_sites: path-gated caps on POST /sites, but
    materialize mints a PartnerSite for a new tenant_ref on deploy-create.
    What would make this fail: partner C under its own max_sites minting
    through POST .../deployments after A+B already hold 12 rows.
    """
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    from core.models import PartnerSite
    from core.partner_jobs import PartnerNotFound, PartnerRefuse, materialize

    zone = _zone("q-dc-fleet-zone")
    box = _target(zone, "q-dc-fleet.lan")
    a = _partner("q-dc-fleet-a", max_sites=10, destination_order=[box.pk])
    b = _partner("q-dc-fleet-b", max_sites=10, destination_order=[box.pk])
    private = Ed25519PrivateKey.generate()
    c = _partner(
        "q-dc-fleet-c", max_sites=10, destination_order=[box.pk],
        pubkey_current=_raw_pubkey_b64(private),
    )
    _bind_sites(a, 6)
    sites_b = _bind_sites(b, 6)
    assert PartnerSite.objects.count() == 12

    now = timezone.now()
    job = _signed_deploy_create_job(
        c, private, sites_b[0],
        tenant_ref="fleet-dc-13", now=now, nonce="n-dc-fleet-0001aaaaaaaaaaaaa",
    )
    assert job["path"] != "/partner/v1/sites"
    try:
        materialize(c, job, now=now)
    except (PartnerRefuse, PartnerNotFound):
        pass
    assert PartnerSite.objects.count() == 12
    assert not PartnerSite.objects.filter(tenant_ref="fleet-dc-13").exists()


@pytest.mark.req("PART-U2-QUOTAS")
def test_deploys_per_day_default_50():
    """Partner.deploys_per_day defaults to 50; the 51st Hub deploy-create refuses.

    What would make this fail: a different default, counting calendar-day
    deploys as unlimited, or gating only the 3/min floor so 51 slow deploys pass.
    """
    from datetime import timedelta

    from core.models import Partner
    from core.partner_verify import evaluate_quotas

    assert Partner._meta.get_field("deploys_per_day").default == 50
    partner = _partner("q-dpd")
    partner.refresh_from_db()
    assert partner.deploys_per_day == 50
    row = Partner.objects.filter(pk=partner.pk).values("deploys_per_day").get()
    assert row["deploys_per_day"] == 50

    sites = _bind_sites(partner, 1)
    now = timezone.now()
    earlier = now - timedelta(hours=2)
    _plant_deploys(sites[0], 50, created_at=earlier)
    path = f"/partner/v1/sites/{sites[0].pk}/deployments"
    decision = evaluate_quotas(partner, "POST", path, now=now)
    assert decision.refused is True
    assert decision.reason == "quota"
    assert decision.status == 403


@pytest.mark.req("PART-U2-QUOTAS")
def test_domains_default_5():
    """Partner.domains defaults to 5; a sixth Hub add-domain refuses.

    What would make this fail: a different default, treating extra hostnames as
    free, or coupling the check to max_sites so a partner with room for sites
    can still mint unbounded domains.
    """
    from core.models import Partner
    from core.partner_verify import evaluate_quotas

    assert Partner._meta.get_field("domains").default == 5
    partner = _partner("q-dom", max_sites=10)
    partner.refresh_from_db()
    assert partner.domains == 5
    row = Partner.objects.filter(pk=partner.pk).values("domains").get()
    assert row["domains"] == 5

    sites = _bind_sites(partner, 5, domain=True)
    path = f"/partner/v1/sites/{sites[0].pk}/domains"
    body = json.dumps({"hostname": "sixth.apps.invalid"})
    decision = evaluate_quotas(partner, "POST", path, now=timezone.now(), body=body)
    assert decision.refused is True
    assert decision.reason == "quota"
    assert decision.status == 403


@pytest.mark.req("PART-U2-QUOTAS")
@override_settings(PARTNER_API_ENABLED=True)
def test_hub_refuses_even_if_intake_says_allow():
    """Intake authenticating a create-site cannot override Hub quota refuse.

    What would make this fail: trusting intake's allow, or an in-memory
    max_sites=999 (unsaved) letting Partner.objects.filter(pk).values be ignored
    so the sixth site materializes.
    """
    import base64

    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

    from core.models import PartnerSite
    from core.partner_jobs import PartnerRefuse, materialize
    from core.partner_verify import reverify
    from intake.verify import verify as intake_verify
    from monitor.intake_poll import FakeIntakeClient, poll

    partner, vectors = _signed_partner("q-hub-wins")
    zone = _zone("q-hub-wins-zone")
    box = _target(zone, "q-hub-wins.lan")
    partner.destination_order = [box.pk]
    partner.save(update_fields=["destination_order"])
    _bind_sites(partner, partner.max_sites)
    partner.max_sites = 999
    assert partner.max_sites == 999

    case = vectors["cases"]["quota-exceeded"]
    raw = base64.b64decode(vectors["public_key_raw_b64"].encode("ascii"), validate=True)
    keys = {vectors["key_id"]: Ed25519PublicKey.from_public_bytes(raw)}
    intake_verify(
        case["method"], case["path"], case["body"], case["headers"],
        keys, now=vectors["now"],
    )
    verified = reverify(
        partner, case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    assert verified.ok is False
    assert verified.reason == "quota"

    job = {
        "id": "job-hub-wins",
        "type": "partner-job",
        "action": "site.create",
        "method": case["method"],
        "path": case["path"],
        "body": case["body"],
        "headers": dict(case["headers"]),
        "payload": json.loads(case["body"]),
    }
    client = FakeIntakeClient(items=[job])
    with override_settings(INTAKE_URL="http://intake.test"):
        poll(client=client, now=vectors["now"], jitter=0, sleep=lambda _s: None)
    assert PartnerSite.objects.filter(partner=partner).count() == 5
    assert not PartnerSite.objects.filter(
        partner=partner, tenant_ref="t-quota",
    ).exists()
    with pytest.raises(PartnerRefuse):
        materialize(partner, _job(partner, tenant_ref="t-quota"))


@pytest.mark.req("PART-U2-QUOTAS")
def test_unbounded_max_sites_refused():
    """null / 0-as-infinite max_sites refuses at clean() and create.

    What would make this fail: treating 0 as unlimited, allowing null, or
    skipping full_clean so only a later Hub count overflows the map bar.
    """
    from core.models import Partner

    zero = Partner(slug="q-unb-0", name="q-unb-0", max_sites=0)
    with pytest.raises(ValidationError):
        zero.full_clean()
    none = Partner(slug="q-unb-n", name="q-unb-n")
    none.max_sites = None
    with pytest.raises(ValidationError):
        none.full_clean()
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Partner.objects.create(slug="q-unb-c0", name="q-unb-c0", max_sites=0)
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Partner.objects.create(slug="q-unb-cn", name="q-unb-cn", max_sites=None)
    assert not Partner.objects.filter(slug__startswith="q-unb-").exists()


@pytest.mark.req("PART-U2-QUOTAS")
def test_quota_abuse_files_budget_cap_hit_partner():
    """Quota-abuse files existing P1 fingerprint budget-cap-hit:partner (refs, never secrets).

    What would make this fail: inventing a new kind, defaulting fingerprint to
    budget-cap-hit:partner:{pk}, or putting hubk_/whsec_/PEM in the Finding.
    """
    from core.models import Finding
    from core.partner_verify import evaluate_quotas, reverify

    partner, vectors = _signed_partner("q-abuse")
    _bind_sites(partner, partner.max_sites)
    case = vectors["cases"]["quota-exceeded"]
    reverify(
        partner, case["method"], case["path"], case["body"], case["headers"],
        now=vectors["now"],
    )
    evaluate_quotas(
        partner, case["method"], case["path"],
        now=vectors["now"], body=case["body"],
    )
    row = Finding.objects.get(fingerprint="budget-cap-hit:partner")
    assert row.severity == "p1"
    assert row.fingerprint == "budget-cap-hit:partner"
    blob = _finding_blobs()
    _assert_no_secrets(blob)
    refs = f"{row.body}{row.entity}{row.fix_action}{row.title}"
    assert str(partner.pk) in refs or partner.slug in refs


@pytest.mark.req("PART-U2-QUOTAS")
def test_rate_limit_60_and_deploy_create_3_per_min():
    """General 60 req/min and deploy-create 3/min + 100/day per site, with X-RateLimit-*.

    What would make this fail: no Hub counter (intake-only), a 61st general
    request passing, a 4th deploy-create in the same minute passing, skipping
    the 101st per-site day cap, or omitting X-RateLimit-Limit/Remaining/Reset.
    """
    from datetime import timedelta

    from core.partner_verify import evaluate_quotas

    now = timezone.now()
    general_partner = _partner("q-rl-g")
    _plant_nonces(general_partner, 60, now=now)
    general = evaluate_quotas(
        general_partner, "GET", "/partner/v1/deployments/1", now=now,
    )
    assert general.refused is True
    assert general.reason == "rate"
    assert general.status == 429
    _assert_rate_headers(general.headers, limit=60)
    assert int(general.headers["X-RateLimit-Remaining"]) == 0

    burst_partner = _partner("q-rl-b", deploys_per_day=500, max_sites=10)
    burst_site = _bind_sites(burst_partner, 1)[0]
    deploy_path = f"/partner/v1/sites/{burst_site.pk}/deployments"
    recent = now - timedelta(seconds=10)
    _plant_deploys(burst_site, 3, created_at=recent)
    burst = evaluate_quotas(burst_partner, "POST", deploy_path, now=now)
    assert burst.refused is True
    assert burst.reason == "rate"
    assert burst.status == 429
    _assert_rate_headers(burst.headers, limit=3)

    day_partner = _partner("q-rl-d", deploys_per_day=500, max_sites=10)
    day_site = _bind_sites(day_partner, 1)[0]
    day_path = f"/partner/v1/sites/{day_site.pk}/deployments"
    _plant_deploys(day_site, 100, created_at=now - timedelta(hours=3))
    daily = evaluate_quotas(day_partner, "POST", day_path, now=now)
    assert daily.refused is True
    assert daily.reason in {"quota", "rate"}
    assert daily.status in {403, 429}


@pytest.mark.req("PART-U2-QUOTAS")
def test_rate_429_does_not_file_budget_cap_hit_partner():
    """Rate floors refuse 429 without the quota-abuse spend-cap P1.

    What would make this fail: _refuse("rate") calling _file_quota_abuse, or
    dropping the 429 / X-RateLimit-* refuse itself.
    """
    from datetime import timedelta

    from core.models import Finding
    from core.partner_verify import evaluate_quotas

    now = timezone.now()
    general_partner = _partner("q-rl-no-p1")
    _plant_nonces(general_partner, 60, now=now)
    general = evaluate_quotas(
        general_partner, "GET", "/partner/v1/deployments/1", now=now,
    )
    assert general.refused is True
    assert general.reason == "rate"
    assert general.status == 429
    _assert_rate_headers(general.headers, limit=60)
    assert not Finding.objects.filter(fingerprint="budget-cap-hit:partner").exists()

    burst_partner = _partner("q-rl-burst-no-p1", deploys_per_day=500, max_sites=10)
    burst_site = _bind_sites(burst_partner, 1)[0]
    deploy_path = f"/partner/v1/sites/{burst_site.pk}/deployments"
    _plant_deploys(burst_site, 3, created_at=now - timedelta(seconds=10))
    burst = evaluate_quotas(burst_partner, "POST", deploy_path, now=now)
    assert burst.refused is True
    assert burst.reason == "rate"
    assert burst.status == 429
    assert not Finding.objects.filter(fingerprint="budget-cap-hit:partner").exists()


@pytest.mark.req("PART-U2-QUOTAS")
def test_d084_numbers_match_partner_field_defaults():
    """D-084 numbers are the Partner field defaults, fleet 12, and Hub rate floors.

    What would make this fail: defaults drifting from D-084, a fleet env default
    other than 12, Hub quota code that never re-reads Partner via .values(), or
    inventing a live quota id / extra token env.
    """
    from django.conf import settings

    from core import partner_verify as pv
    from core.models import Partner

    assert Partner._meta.get_field("max_sites").default == 5
    assert Partner._meta.get_field("deploys_per_day").default == 50
    assert Partner._meta.get_field("domains").default == 5
    assert int(settings.PARTNER_FLEET_MAX_SITES) == 12
    assert pv.RATE_GENERAL_PER_MIN == 60
    assert pv.RATE_DEPLOY_CREATE_PER_MIN == 3
    assert pv.RATE_DEPLOY_CREATE_PER_DAY == 100
    assert pv.DEFAULT_FLEET_MAX_SITES == 12

    d084 = DECISIONS_PATH.read_text(encoding="utf-8")
    assert "| D-084 |" in d084
    assert "`max_sites=5`" in d084
    assert "`deploys_per_day=50`" in d084
    assert "`domains=5`" in d084
    assert "`PARTNER_FLEET_MAX_SITES` default `12`" in d084
    assert "60 req/min" in d084
    assert "3/min + 100/day" in d084
    assert "`budget-cap-hit:partner`" in d084
    assert "unbounded `max_sites` is out" in d084

    src = VERIFY_PATH.read_text(encoding="utf-8")
    assert "Partner.objects.filter(pk=" in src
    assert ".values(" in src
    assert "budget-cap-hit:partner" in src
    assert "HUB_TEST_PARTNER_TOKEN" not in src
    _assert_no_live_marks()


@pytest.mark.req("ARCH-D4-IMPORT-RULE")
def test_unwired_evaluate_quotas_deploy_create_fails_loud(monkeypatch):
    """Unwired store must not fail-open as count 0 on partner deploy-create.

    What would make this fail: except Exception: day_count = 0, or a
    zeroing stand-in when _store is None.
    """
    import core.partner_deploys as port
    from core.partner_verify import evaluate_quotas
    from django.apps import apps as django_apps

    partner = _partner("q-unwired")
    monkeypatch.setattr(port, "_store", None)
    with pytest.raises(RuntimeError, match="not wired"):
        evaluate_quotas(partner, "POST", "/partner/v1/sites/x/deployments")
    django_apps.get_app_config("deploys").ready()
