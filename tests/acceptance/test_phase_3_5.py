"""Phase 3.5 acceptance — each test transcribes one design-note §4 clause.

`check.py --phase 3.5 --exclude-tier t2 --exclude-tier t3` is the 3b gate.
T1 fakes only: FakeDnsProvider, AdoptTransport, Hub-local plant files.
Do not require a live CF token. Do not invent a test-zone token env.
Do not mark TLS-B2-HUB-DNS01-UNPROXIED or the full-text SEC-B2 id.

Every T1 body asserts the same properties an existing named proof asserts
(transcription, not fiction); each docstring names its source test.
The demo record must describe those proofs, not a fictional live run.
"""
from pathlib import Path

import pytest
import yaml

REPO = Path(__file__).resolve().parent.parent.parent
DEMO = REPO / "conformance" / "demos" / "phase-3.5.md"
WAIVER_24H = "REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven"
FULL_TEXT_SEC_B2 = "SEC-B2-NO-DNS-TOKENS-ON-TARGETS"
DNS01_ID = "TLS-B2-HUB-DNS01-UNPROXIED"
LE_STAGING = "HARNESS-T3-LE-STAGING"
ADOPT_IDS = ("PROV-J7-COMPOSE-AWARE-ADOPT", "PROV-E6-ADOPT-TEMP-SUBDOMAIN")
NAMED = (
    "test_public_site_binds_dns_zone",
    "test_public_site_create_with_no_eligible_zone_creates_nothing",
    "test_origin_ca_is_planted_from_a_hub_file_not_a_paste",
    "test_f3_checklist_owns_home_until_done",
    "test_compose_plan_is_one_v5_site",
    "test_temp_subdomain_on_site_zone_cleans_up",
    "test_flip_refuses_before_verify",
    "test_live_site_stays_up_until_flip",
    "test_registered_volume_survives_decommission_without_docker_volume_rm",
    "test_rel_p2_24h_still_not_claimed",
    "test_hub_central_dns01_still_not_due",
)

pytestmark = [pytest.mark.acceptance(phase=3.5)]


def _waivers():
    return (REPO / "WAIVERS.md").read_text(encoding="utf-8")


def _demo():
    assert DEMO.is_file() and DEMO.stat().st_size > 0, (
        "conformance/demos/phase-3.5.md must exist — P3B-ADOPT-DEMO is verify: demo"
    )
    text = DEMO.read_text(encoding="utf-8")
    assert text.strip(), "a whitespace-only demo is not a record"
    return text


def _registry():
    data = yaml.safe_load(
        (REPO / "conformance" / "requirements.yaml").read_text(encoding="utf-8"))
    return {r["id"]: r for r in data["requirements"]}


def _waiver_lines(fingerprint):
    prefix = f"WAIVED: {fingerprint} "
    return [line for line in _waivers().splitlines() if line.startswith(prefix)]


def _assert_honest_t1_demo():
    """A non-empty stub must not verify P3B-ADOPT-DEMO (Task 0 F)."""
    record = _demo()
    lower = record.lower()
    for name in NAMED:
        assert name in record, f"demo must name the acceptance nodeid {name}"
    assert "FakeDnsProvider" in record
    assert "AdoptTransport" in record or "T1" in record
    assert "t1" in lower
    assert "live cloudflare" not in lower or "no live" in lower or "not a live" in lower
    assert "hub-down" not in lower or "not claimed" in lower or "still not" in lower
    assert "24 h hub-down" not in lower and "24h hub-down" not in lower
    assert WAIVER_24H in record
    assert DNS01_ID in record
    assert "phase 4" in lower
    assert LE_STAGING in record
    for rid in ADOPT_IDS:
        assert rid in record
        assert "RETIRED" in record
    assert "HUB_TEST_" + "DNS_ZONE" not in record
    assert "stub" not in lower
    assert "todo" not in lower
    return record


# ── named clauses ───────────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_public_site_binds_dns_zone(client, django_user_model):
    """POST /api/v1/projects/ binds Site.dns_zone and primary_target.

    Transcribes tests/test_site_dns_bind.py::
    test_public_site_create_auto_binds_the_single_eligible_zone and
    ::test_one_enrolled_target_auto_binds_primary_target. No unbound Finding
    — an unbound public Site cannot exist.
    """
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from test_site_dns_bind import _create, _target, _zone

    from core.models import Finding, Project, Site

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)

    target = _target()
    zone = _zone("p35-bind.example")
    response = _create(client, "p35-bind")
    assert response.status_code == 201, response.content
    site = Site.objects.get(project=Project.objects.get(name="p35-bind"))
    assert site.dns_zone_id == zone.pk
    assert site.primary_target_id == target.pk
    assert not Site.objects.filter(dns_zone__isnull=True).exclude(
        exposure=Site.Exposure.MESH_ONLY,
    ).exists()
    assert not Finding.objects.filter(fingerprint__startswith="site-dns-unbound").exists()


@pytest.mark.django_db
@pytest.mark.req("DNS-SITE-ZONE-BIND")
def test_public_site_create_with_no_eligible_zone_creates_nothing(client, django_user_model):
    """Zero eligible zones: 409 and zero Project, Site, Finding rows (C1).

    Transcribes tests/test_site_dns_bind.py::
    test_public_site_create_with_no_eligible_zone_is_409_and_creates_nothing.
    """
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from test_site_dns_bind import _counts, _create, _target

    from core.models import Finding

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)

    _target()
    before = _counts()
    response = _create(client, "p35-none")
    assert response.status_code == 409, response.content
    assert _counts() == before
    assert not Finding.objects.filter(fingerprint__startswith="site-dns-unbound").exists()


@pytest.mark.django_db
@pytest.mark.req("TLS-B2-ORIGIN-CA-PLANT")
def test_origin_ca_is_planted_from_a_hub_file_not_a_paste(
        client, django_user_model, tmp_path, monkeypatch):
    """Plant is body {path} only. Connect stays DNS-token only.

    Transcribes tests/test_origin_ca_plant.py::
    test_plant_from_allowlisted_0600_file_sets_origin_ca_key_ref,
    ::test_plant_request_and_response_contain_no_key_bytes, and
    ::test_connect_endpoint_still_does_not_accept_an_origin_ca_key.
    """
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from test_cloudflare_adapter import FakeCloudflare
    from test_origin_ca_plant import (
        CONNECT,
        KEY_BYTES,
        PROBE,
        TOKEN,
        VERIFY,
        _account,
        _allowlisted_file,
        _plant,
        _plant_url,
    )

    import providers.cloudflare as cloudflare
    from core.models import DnsAccount, Finding
    from vault import service as vault_service
    from vault.models import Secret

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)

    account = _account(label="p35-plant")
    path = _allowlisted_file(tmp_path, monkeypatch)
    marker = KEY_BYTES.decode()
    stuffed = client.post(
        _plant_url(account),
        {"path": str(path), "origin_ca_key": marker},
        content_type="application/json",
    )
    assert stuffed.status_code == 400
    assert marker not in stuffed.content.decode()
    account.refresh_from_db()
    assert account.origin_ca_key_ref == ""

    response = _plant(client, account, path)
    assert response.status_code == 200, response.content
    assert response.json()["planted"] is True
    assert marker not in response.content.decode()
    account.refresh_from_db()
    secret = Secret.objects.get(
        kind=Secret.Kind.API_TOKEN,
        owner_type="dns_account",
        owner_id=account.origin_ca_key_ref,
    )
    assert vault_service.get(secret, reason="p35-plant") == KEY_BYTES
    assert not any(
        marker in ((row.body or "") + (row.title or "") + (row.fix_action or ""))
        for row in Finding.objects.all()
    )

    http = FakeCloudflare({
        VERIFY: {"success": True, "result": {"id": "tok", "status": "active"}},
        PROBE: {"success": True, "result": [{"id": "zid-p35", "name": "p35.example"}]},
    })
    monkeypatch.setattr(cloudflare, "urlopen", http)
    connect = client.post(
        CONNECT,
        {"token": TOKEN, "origin_ca_key": marker},
        content_type="application/json",
    )
    assert connect.status_code == 201, connect.content
    assert marker not in connect.content.decode()
    connected = DnsAccount.objects.exclude(pk=account.pk).get()
    assert connected.dns_token_ref
    assert connected.origin_ca_key_ref == ""


@pytest.mark.django_db
@pytest.mark.req("UX-F3-FIRST-RUN-CHECKLIST")
def test_f3_checklist_owns_home_until_done(client, django_user_model):
    """GET /api/v1/first-run/ owns Home until target, connect/plant, project.

    Transcribes tests/test_first_run_checklist.py::
    test_checklist_derives_from_target_zone_plant_and_project and
    frontend/tests/checklist.test.ts::checklist_owns_home_until_items_are_done.
    Topic stays findings.
    """
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from test_first_run_checklist import _get, _items, _target

    from core.findings import findings_seq
    from core.models import DnsAccount, Project, Site
    from realtime.authorize import ALLOWED_PREFIXES

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)

    assert not any("checklist" in p or "first-run" in p or "first_run" in p
                   for p in ALLOWED_PREFIXES)

    empty = _get(client)
    assert empty["seq"] == findings_seq()
    assert empty["data"]["owns_home"] is True
    assert _items(empty)["enroll_target"]["done"] is False

    target = _target(slug="p35-f3")
    from dns_fixtures import default_dns_zone

    zone = default_dns_zone("p35-f3.example")
    project = Project.objects.create(
        name="p35-f3", slug="p35-f3", source_kind=Project.Source.LOCAL_PATH,
        local_path="/tmp/p35-f3",
    )
    Site.objects.create(
        project=project, name="p35-f3", domain="app.p35-f3.example",
        exposure=Site.Exposure.PUBLIC, proxied=True, dns_zone=zone,
        primary_target=target,
    )
    mid = _get(client)
    assert mid["data"]["owns_home"] is True
    assert _items(mid)["add_project"]["done"] is True
    assert _items(mid)["plant_origin_ca"]["applicable"] is True
    assert _items(mid)["plant_origin_ca"]["done"] is False

    account = DnsAccount.objects.get(label="test-fixture")
    account.origin_ca_key_ref = "p35-planted-ref-not-a-key"
    account.save(update_fields=["origin_ca_key_ref"])
    done = _get(client)
    assert _items(done)["plant_origin_ca"]["done"] is True
    assert done["data"]["owns_home"] is False

    home = (REPO / "frontend" / "src" / "screens" / "Home.jsx").read_text(
        encoding="utf-8")
    assert "if (progress?.owns_home)" in home
    assert "ChecklistCard" in home
    assert 'events.subscribe("findings"' in home or 'subscribe("findings"' in home


@pytest.mark.django_db
@pytest.mark.req("PROV-J7-COMPOSE-AWARE-ADOPT")
def test_compose_plan_is_one_v5_site():
    """The three fixture stacks classify to one V5 Site; two publics refuse.

    Transcribes tests/test_adopt_compose.py::
    test_worker_beat_and_oneshot_migrate_are_classified,
    ::test_site_owned_edge_container_is_recorded_as_a_decision_on_the_site,
    ::test_single_container_stack_still_produces_one_manifest, and
    ::test_two_public_services_refuse_with_a_finding.
    """
    from test_adopt_compose import FIXTURES, _project_from_fixture

    from core.models import Site
    from deploys.models import Manifest
    from provision.adopt import adoption_plan, classify_services, read_compose

    roles = classify_services(read_compose(FIXTURES / "web-worker-beat-migrate"))
    assert roles["web"] == "web"
    assert roles["worker"] == "worker"
    assert roles["beat-scheduler"] == "beat"
    assert roles["one-shot migrate"] == "migrate"

    _project, caddy_site = _project_from_fixture("web-site-caddy", "p35-caddy")
    caddy_plan = adoption_plan(caddy_site.project)
    caddy_site.refresh_from_db()
    assert caddy_site.edge_owner == Site.EdgeOwner.SITE_CADDY
    assert caddy_plan.refused is False

    _web, web_site = _project_from_fixture("web-only", "p35-web")
    web_plan = adoption_plan(web_site.project)
    assert web_plan.manifest["components"]["service"]["name"] == "web"
    assert web_plan.manifest["components"]["jobs"] == []
    assert Manifest.objects.filter(site=web_site).count() == 0
    web_site.refresh_from_db()
    assert web_site.edge_owner == Site.EdgeOwner.HOST_CADDY

    _two, two_site = _project_from_fixture("two-public", "p35-two")
    two_plan = adoption_plan(two_site.project)
    assert two_plan.refused is True
    assert two_plan.manifest is None
    assert Manifest.objects.filter(site=two_site).count() == 0


@pytest.mark.django_db
@pytest.mark.req("PROV-E6-ADOPT-TEMP-SUBDOMAIN")
def test_temp_subdomain_on_site_zone_cleans_up():
    """Temp {slug}-adopt-{8hex}.{zone} upserts on Site.dns_zone; cleanup deletes it.

    Transcribes tests/test_adopt_flow.py::
    test_temp_name_is_slug_adopt_token_hex_4_on_site_dns_zone and
    ::test_abandoned_flip_cleans_up_its_temp_subdomain. FakeDnsProvider only.
    """
    from test_adopt_flow import (
        TEMP_NAME_RE,
        AdoptTransport,
        _checkrun,
        _desired,
        _prod_values,
        _site,
    )

    from core.models import DnsRecord, DnsZone
    from deploys.adopt_flow import cleanup, ensure_temp_dns
    from providers.fakes import FakeDnsProvider

    site, deployment = _site("p35-temp")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    before = set(DnsZone.objects.values_list("pk", "name"))
    ensure_temp_dns(desired)
    assert set(DnsZone.objects.values_list("pk", "name")) == before
    temp = _checkrun(site).results["temp_name"]
    assert TEMP_NAME_RE.match(temp)
    assert temp.endswith(f".{site.dns_zone.name}")
    assert len(temp.split("-adopt-")[1].split(".")[0]) == 8
    upserts = [call for call in dns.calls if call[0] == "upsert_record"]
    assert upserts and upserts[0][1] is site.dns_zone
    cleanup(desired)
    assert not any(rec["name"] == temp for rec in dns.list_records(site.dns_zone))
    assert not DnsRecord.objects.filter(site=site, name=temp).exists()
    assert _prod_values(dns, site.dns_zone, site.domain) == ["198.51.100.1"]


@pytest.mark.django_db
@pytest.mark.req("PROV-E6-ADOPT-TEMP-SUBDOMAIN")
def test_flip_refuses_before_verify():
    """Flip is gated on verify for this image tag, not on temp DNS existing.

    Transcribes tests/test_adopt_flow.py::test_dns_flip_refuses_before_verification.
    """
    from test_adopt_flow import AdoptTransport, _desired, _prod_values, _site

    from core.models import DnsRecord
    from deploys.adopt_flow import AdoptRefused, ensure_flip, ensure_temp_dns
    from providers.fakes import FakeDnsProvider

    site, deployment = _site("p35-flip")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    ensure_temp_dns(desired)
    with pytest.raises(AdoptRefused):
        ensure_flip(desired)
    assert _prod_values(dns, site.dns_zone, site.domain) == ["198.51.100.1"]
    assert DnsRecord.objects.get(site=site, name=site.domain).value == "198.51.100.1"
    assert transport.containers[desired["old_container"]] == "running"


@pytest.mark.django_db
@pytest.mark.req("PROV-E6-ADOPT-TEMP-SUBDOMAIN")
def test_live_site_stays_up_until_flip():
    """Old container is not stopped during temp deploy or verify (QE I3).

    Transcribes tests/test_adopt_flow.py::test_live_site_stays_up_until_flip.
    """
    from test_adopt_flow import AdoptTransport, _desired, _site

    from deploys.adopt_flow import ensure_flip, ensure_temp_dns, ensure_verify
    from providers.fakes import FakeDnsProvider

    site, deployment = _site("p35-stay")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    desired = _desired(site, deployment, transport, dns)
    old = desired["old_container"]
    ensure_temp_dns(desired)
    ensure_verify(desired)
    assert transport.containers[old] == "running"
    stops = [
        payload for kind, payload in transport.calls
        if kind == "run" and isinstance(payload, list)
        and payload[:2] == ["docker", "stop"] and old in payload
    ]
    assert stops == []
    ensure_flip(desired)
    assert transport.containers[old] == "running"


@pytest.mark.django_db
@pytest.mark.req("PROV-J7-COMPOSE-AWARE-ADOPT")
@pytest.mark.req("PROV-E6-ADOPT-TEMP-SUBDOMAIN")
def test_registered_volume_survives_decommission_without_docker_volume_rm():
    """Decommission never `docker volume rm` a registered SiteVolume name (M1).

    Transcribes tests/test_adopt_flow.py::
    test_decommission_never_docker_volume_rm_a_registered_name.
    """
    from test_adopt_flow import (
        AdoptTransport,
        _desired,
        _site,
        _volume_rm_argvs,
    )

    from core.models import SiteVolume
    from deploys.adopt_flow import adopt_flow
    from providers.fakes import FakeDnsProvider

    site, deployment = _site("p35-vol")
    transport = AdoptTransport()
    dns = FakeDnsProvider()
    adopt_flow(_desired(site, deployment, transport, dns))
    registered = set(SiteVolume.objects.filter(site=site).values_list("name", flat=True))
    assert {"pgdata", "media"} <= registered
    for argv in _volume_rm_argvs(transport):
        joined = " ".join(str(part) for part in argv)
        for name in registered:
            assert name not in joined
    assert transport.volumes >= {"pgdata", "media"}


def test_rel_p2_24h_still_not_claimed():
    """REL-P2 24 h stays waived. This record is T1 fakes, not a Hub-down.

    Transcribes tests/test_drills.py::test_hub_down_still_refuses_to_claim_24h
    (D-042) and pins the 3.5 demo as the honest outstanding line.
    """
    waivers = _waivers()
    assert WAIVER_24H in waivers
    line = next(row for row in waivers.splitlines() if WAIVER_24H in row)
    assert line.startswith("WAIVED:")
    assert "calendar" in line.lower() or "24 h" in line.lower() or "24h" in line.lower()

    rel_p2 = _registry()["REL-P2-HUB-DOWN-SITES-UP"]
    assert rel_p2["phase"] == 2
    assert rel_p2["verify"] == "demo"

    record = _assert_honest_t1_demo()
    assert WAIVER_24H in record
    assert "not this phase" in record.lower() or "still not claimed" in record.lower()
    assert "D-042" in record


def test_hub_central_dns01_still_not_due():
    """Hub-central DNS-01 stays phase 4. SEC-B2 clause waiver and LE line stay.

    Transcribes tests/test_certs_phase_pin.py and tests/test_conformance_gate.py::
    test_tls_b2_hub_dns01_stays_phase_4. Leftover Task 8 still owns
    HARNESS-T3-LE-STAGING — 3b neither freezes nor retires it.
    """
    import check
    from test_certs_phase_pin import _unproxied_class_docstring, _unproxied_fix_action

    reg = _registry()
    assert reg[DNS01_ID]["phase"] == 4
    markers = check.collect_markers(REPO)
    assert DNS01_ID not in markers
    assert FULL_TEXT_SEC_B2 not in markers

    sec = _waiver_lines(FULL_TEXT_SEC_B2)
    assert sec, f"{FULL_TEXT_SEC_B2} must stay waived — DNS-01 is unbuilt"
    assert "DNS-01" in sec[0] or "Hub-central" in sec[0]
    assert DNS01_ID in sec[0]

    le = _waiver_lines(LE_STAGING)
    assert le, f"{LE_STAGING} must stay — leftover Task 8 owns that line"
    assert "no-test-zone-credentials" in le[0]

    for rid in ADOPT_IDS:
        assert not _waiver_lines(rid), (
            f"{rid} must be retired — Tasks 4+6+7 marked T1 tests are green"
        )
        assert "RETIRED" in _waivers() and rid in _waivers()

    doc = _unproxied_class_docstring()
    assert "phase 4" in doc.lower()
    assert "3b" not in doc.lower()
    fix = _unproxied_fix_action()
    assert "phase 4" in fix.lower()

    record = _assert_honest_t1_demo()
    assert DNS01_ID in record
    assert LE_STAGING in record
    assert "not due" in record.lower() or "phase 4" in record.lower()
