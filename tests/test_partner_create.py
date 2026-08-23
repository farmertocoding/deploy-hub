"""Settings Partners tab + T1 partner.create (UX-P55-PARTNERS / §7 C8).

partner.create is T1 (touch + type-the-name; confirm_name = slug). POST 201
returns hubk_* + whsec_ once; GET / list never echo them; Fake / empty
INTAKE_URL / post-create never paints Connected. NAV stays six. Kill-switch
chrome waits for Task 7.
"""
from __future__ import annotations

import inspect
import json
import logging
import os
import pathlib
import re
import time

import pytest
from django.contrib.auth.models import User
from django.test import override_settings

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
CREATE_URL = "/api/v1/partners/"
SLUG = "fixture-partner"


def _frontend(*parts):
    return (REPO / "frontend").joinpath(*parts).read_text(encoding="utf-8")


def _settings_jsx():
    return _frontend("src", "screens", "Settings.jsx")


def _nav_ids():
    text = _frontend("src", "Chrome.jsx")
    block = text.split("export const NAV = [", 1)[1].split("];", 1)[0]
    return re.findall(r'id:\s*"([^"]+)"', block)


def _settings_tab_ids():
    text = _settings_jsx()
    block = text.split("export const SETTINGS_TABS = [", 1)[1].split("];", 1)[0]
    return re.findall(r'id:\s*"([^"]+)"', block)


def _without_single_instance(text):
    return re.sub(r"single-instance", "", text, flags=re.I)


def _make_cred(user, name="passkey"):
    from django_otp_webauthn.models import WebAuthnCredential

    return WebAuthnCredential.objects.create(
        user=user,
        name=name,
        confirmed=True,
        credential_id=os.urandom(16),
        public_key=os.urandom(32),
        aaguid="00000000-0000-0000-0000-000000000000",
        transports=["usb"],
    )


def _login(client, user, password="a-long-dev-password"):
    client.force_login(user)
    session = client.session
    session["_hub_last_activity"] = time.time()
    session.save()


def _patch_webauthn(monkeypatch):
    from django_otp_webauthn.models import WebAuthnCredential

    class FakeHelper:
        def __init__(self, request):
            self.request = request

        def authenticate_begin(self, user=None, require_user_verification=True):
            return (
                {"challenge": "YXV0aGNoYWxs", "rpId": "localhost"},
                {"challenge": "YXV0aGNoYWxs"},
            )

        def authenticate_complete(self, user, state, data):
            qs = WebAuthnCredential.objects.filter(confirmed=True)
            if user is not None:
                qs = qs.filter(user=user)
            return qs.first()

    monkeypatch.setattr(
        WebAuthnCredential,
        "get_webauthn_helper",
        classmethod(lambda cls, request: FakeHelper(request)),
    )


def _touch(client, monkeypatch):
    _patch_webauthn(monkeypatch)
    assert client.post("/api/auth/webauthn/authentication/begin/").status_code == 200
    touch = client.post(
        "/api/auth/webauthn/touch/",
        data=json.dumps({"id": "cred-1", "response": {}}),
        content_type="application/json",
    )
    assert touch.status_code == 200, touch.content


def _t1_user(client):
    user = User.objects.create_user("joseph", password="a-long-dev-password")
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")
    _login(client, user)
    return user


def _create_body(*, slug=SLUG, confirm_name=None, name=None):
    return {
        "slug": slug,
        "name": name or slug,
        "confirm_name": slug if confirm_name is None else confirm_name,
    }


def _post_create(client, **kwargs):
    return client.post(
        CREATE_URL,
        data=json.dumps(_create_body(**kwargs)),
        content_type="application/json",
    )


def _blob(obj):
    return json.dumps(obj, default=str)


def _hubk_prefix(hubk):
    if hubk.startswith("hubk_test_"):
        return "hubk_test_"
    if hubk.startswith("hubk_live_"):
        return "hubk_live_"
    return None


# ── T1 HTTP ──────────────────────────────────────────────────────────────────


@pytest.mark.req("UX-P55-PARTNERS")
def test_partner_create_is_t1():
    """partner.create is T1 Create partner: RequireRecentTouch HTTP, type-the-name.

    What would make this fail: a T2/T3 row, hanging the view off /api/auth/,
    a Connect-paste label, cost on the partner T1 overlay, or leaving T1_HTTP
    unregistered so the standing T1 pin 404s the wrong slug.
    """
    from django.urls import resolve

    from core.actions import ACTION_TIERS
    from core.partner_views import PartnerListCreateView
    from core.permissions import RequireRecentTouch
    from tests.test_webauthn_t1 import T1_HTTP

    row = next(r for r in ACTION_TIERS if r["id"] == "partner.create")
    assert row["tier"] == "T1"
    assert row["label"] == "Create partner"
    assert "instance" not in row["label"].lower()
    assert "connect" not in row["label"].lower()

    template = T1_HTTP["partner.create"]
    assert template == CREATE_URL
    match = resolve(template)
    view_cls = getattr(match.func, "cls", None)
    assert view_cls is PartnerListCreateView
    assert RequireRecentTouch in view_cls.permission_classes
    source = inspect.getsource(PartnerListCreateView)
    assert "PartnerCreateSerializer" in source
    assert "request.data.get" not in source
    assert "confirm_name" in source

    core_urls = (REPO / "core" / "urls.py").read_text(encoding="utf-8")
    assert "partners/" not in core_urls

    tiers = _frontend("src", "Tiers.jsx")
    assert 'row.id === "partner.create"' in tiers or "partner.create" in tiers


@pytest.mark.req("UX-P55-PARTNERS")
def test_partner_create_refuses_without_recent_touch(client):
    """Two passkeys are not enough: no recent WebAuthn touch → 403, no Partner.

    What would make this fail: create running on a stolen session that never
    touched a security key.
    """
    from core.models import Partner

    _t1_user(client)
    response = _post_create(client)
    assert response.status_code == 403, response.content
    assert "touch" in response.json()["detail"].lower()
    assert not Partner.objects.filter(slug=SLUG).exists()
    assert "hardware_touch_at" not in client.session


@pytest.mark.req("UX-P55-PARTNERS")
def test_partner_create_requires_type_the_name(client, monkeypatch):
    """Hardware touch without typing the intended slug still refuses.

    What would make this fail: confirm_name ignored so any string creates.
    """
    from core.models import Partner

    _t1_user(client)
    _touch(client, monkeypatch)

    wrong = _post_create(client, confirm_name="wrong-slug")
    assert wrong.status_code == 400, wrong.content
    assert not Partner.objects.filter(slug=SLUG).exists()

    ok = _post_create(client, confirm_name=SLUG)
    assert ok.status_code == 201, ok.content
    assert Partner.objects.filter(slug=SLUG).exists()


@pytest.mark.req("UX-P55-PARTNERS")
def test_totp_does_not_satisfy_partner_create(client):
    """A TOTP login of a two-passkey operator still cannot satisfy T1.

    What would make this fail: TOTP writing hardware_touch_at, or create
    treating an OTP session as a recent touch.
    """
    from django_otp.oath import TOTP
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import Partner

    user = User.objects.create_user("joseph", password="a-long-dev-password")
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    code = format(totp.token(), "06d")

    login = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph",
            "password": "a-long-dev-password",
            "otp_code": code,
        }),
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    assert "hardware_touch_at" not in client.session

    response = _post_create(client)
    assert response.status_code == 403
    assert "hardware_touch_at" not in client.session
    assert not Partner.objects.filter(slug=SLUG).exists()


@pytest.mark.req("UX-P55-PARTNERS")
def test_create_201_returns_hubk_and_whsec_once(client, monkeypatch):
    """201 returns hubk_test_/hubk_live_ + whsec_ once; they are not persisted.

    What would make this fail: minting without returning the prefixes, vaulting
    the Ed25519 private key, or a second GET that still carries them.
    """
    from core.models import Partner
    from vault.models import Secret
    from vault.service import get as vault_get

    _t1_user(client)
    _touch(client, monkeypatch)

    with override_settings(HUB_TEST_MODE=True):
        created = _post_create(client)
    assert created.status_code == 201, created.content
    body = created.json()
    hubk = body.get("hubk") or ""
    whsec = body.get("whsec") or ""
    assert hubk.startswith("hubk_test_"), hubk[:12]
    assert whsec.startswith("whsec_"), whsec[:8]
    partner = Partner.objects.get(slug=SLUG)
    assert partner.pubkey_current
    assert hubk not in partner.pubkey_current
    assert "hubk_" not in partner.pubkey_current
    assert not any("private" in f.name for f in Partner._meta.get_fields())

    secret = Secret.objects.get(
        kind=Secret.Kind.WEBHOOK_SECRET,
        owner_type="partner",
        owner_id=str(partner.pk),
    )
    stored = vault_get(secret).decode()
    assert stored == whsec

    listed = client.get(CREATE_URL)
    assert listed.status_code == 200, listed.content
    dumped = _blob(listed.json())
    assert "hubk_" not in dumped
    assert "whsec_" not in dumped


@pytest.mark.req("UX-P55-PARTNERS")
def test_get_never_echoes_hubk_or_whsec(client, monkeypatch):
    """GET list and GET detail never echo hubk_ or whsec_.

    What would make this fail: a ModelSerializer that dumps the 201 fields,
    or intake status copy that reprints minted material.
    """
    _t1_user(client)
    _touch(client, monkeypatch)
    created = _post_create(client)
    assert created.status_code == 201, created.content
    pk = created.json()["id"]
    hubk = created.json()["hubk"]
    whsec = created.json()["whsec"]

    listed = client.get(CREATE_URL)
    assert listed.status_code == 200
    listed_blob = _blob(listed.json())
    assert hubk not in listed_blob
    assert whsec not in listed_blob
    assert "hubk_" not in listed_blob
    assert "whsec_" not in listed_blob
    assert not re.search(r"\bConnected\b", listed_blob)

    detail = client.get(f"{CREATE_URL}{pk}/")
    assert detail.status_code == 200, detail.content
    detail_blob = _blob(detail.json())
    assert hubk not in detail_blob
    assert whsec not in detail_blob
    assert "hubk_" not in detail_blob
    assert "whsec_" not in detail_blob


@pytest.mark.req("UX-P55-PARTNERS")
def test_create_does_not_put_hubk_or_whsec_in_audit_or_logs(client, monkeypatch, caplog):
    """AuditEvent.detail / logs never contain hubk_, whsec_, PEM, or raw key bytes.

    What would make this fail: audit(**request.data), logging the 201 body, or
    stuffing the private key into Finding/CheckRun detail.
    """
    from core.models import AuditEvent, CheckRun, Finding

    _t1_user(client)
    _touch(client, monkeypatch)
    with caplog.at_level(logging.DEBUG):
        created = _post_create(client)
    assert created.status_code == 201, created.content
    hubk = created.json()["hubk"]
    whsec = created.json()["whsec"]

    audit_blob = _blob(list(AuditEvent.objects.values("action", "detail", "object_id")))
    assert "hubk_" not in audit_blob
    assert "whsec_" not in audit_blob
    assert hubk not in audit_blob
    assert whsec not in audit_blob
    assert "BEGIN" not in audit_blob
    assert hubk not in caplog.text
    assert whsec not in caplog.text
    assert "hubk_" not in caplog.text
    assert "whsec_" not in caplog.text

    findings_blob = _blob(list(Finding.objects.values("title", "body")))
    assert "hubk_" not in findings_blob
    assert "whsec_" not in findings_blob
    checks_blob = _blob(list(CheckRun.objects.values("results")))
    assert "hubk_" not in checks_blob
    assert "whsec_" not in checks_blob


@pytest.mark.req("UX-P55-PARTNERS")
def test_private_key_is_not_a_partner_column_and_not_vaulted(client, monkeypatch):
    """Ed25519 private key is not a Partner column and is never vaulted.

    What would make this fail: a private_key field, vault.put of hubk_*, or
    storing PEM next to the public slots.
    """
    from core.models import Partner
    from vault.models import Secret
    from vault.service import get as vault_get

    names = {f.name for f in Partner._meta.get_fields()}
    assert "private_key" not in names
    assert not any("private" in n for n in names)

    _t1_user(client)
    _touch(client, monkeypatch)
    created = _post_create(client)
    assert created.status_code == 201, created.content
    hubk = created.json()["hubk"]
    partner = Partner.objects.get(slug=SLUG)
    dumped = _blob(list(Partner.objects.filter(pk=partner.pk).values()))
    assert hubk not in dumped
    assert "hubk_" not in dumped
    assert "BEGIN" not in dumped
    assert partner.pubkey_current
    assert hubk not in partner.pubkey_current

    for secret in Secret.objects.all():
        plaintext = vault_get(secret)
        assert b"hubk_" not in plaintext
        assert hubk.encode() not in plaintext
        assert b"BEGIN" not in plaintext


# ── Settings / NAV / copy / F8 ───────────────────────────────────────────────


@pytest.mark.req("UX-P55-PARTNERS")
def test_settings_is_create_partner_not_connect():
    """Settings Partners tab is Create partner, not Connect.

    What would make this fail: an AWS/CF paste form, a Connect button on the
    Partners tab, or a second Intake console.
    """
    settings_src = _settings_jsx()
    assert '{ id: "partners", label: "Partners" }' in settings_src
    assert "Create partner" in settings_src
    partners_block = settings_src.split("export function PartnersPanel")[1].split(
        "export function", 1
    )[0]
    assert "Create partner" in partners_block
    assert not re.search(r"\bConnect\b", partners_block)
    assert "INTAKE_URL" in partners_block or "Fake" in partners_block
    assert "ActionButton" in settings_src
    assert 'tierFor("partner.create")' in settings_src


@pytest.mark.req("UX-P55-PARTNERS")
def test_settings_unconfigured_is_degraded_not_connected(client):
    """Empty / unconfigured Partners tab is degraded Fake, never Connected.

    What would make this fail: painting Connected on empty INTAKE_URL, or
    omitting the Fake name.
    """
    _t1_user(client)
    response = client.get(CREATE_URL)
    assert response.status_code == 200, response.content
    body = response.json()
    dumped = _blob(body)
    assert not re.search(r"\bConnected\b", dumped)
    intake = body["intake"]
    assert intake["status"] == "degraded"
    assert intake["mode"] == "fake"
    assert intake["configured"] is False
    assert body["partners"] == []

    partners_block = _settings_jsx().split("export function PartnersPanel")[1].split(
        "export function", 1
    )[0]
    assert "degraded" in partners_block
    assert "Fake" in partners_block
    assert not re.search(r"\\bConnected\\b", partners_block)
    assert not re.search(r"\bConnected\b", partners_block)


@pytest.mark.req("UX-P55-PARTNERS")
def test_settings_post_create_fake_or_empty_intake_never_connected(client, monkeypatch):
    """Post-create with Fake / empty INTAKE_URL still never paints Connected.

    What would make this fail: flipping a connected flag after 201, or GET
    growing a Connected status once a Partner row exists.
    """
    _t1_user(client)
    _touch(client, monkeypatch)
    created = _post_create(client)
    assert created.status_code == 201, created.content
    listed = client.get(CREATE_URL)
    assert listed.status_code == 200
    body = listed.json()
    dumped = _blob(body)
    assert not re.search(r"\bConnected\b", dumped)
    assert body["intake"]["status"] in {"degraded", "error"}
    assert body["intake"]["mode"] == "fake"
    assert len(body["partners"]) == 1
    row = body["partners"][0]
    assert row["slug"] == SLUG
    assert row.get("destination_order") == []
    assert "hubk" not in row
    assert "whsec" not in row

    partners_block = _settings_jsx().split("export function PartnersPanel")[1]
    assert "partner-site create will refuse" in partners_block
    assert "dedicated cloud first" in partners_block


@pytest.mark.req("UX-P55-PARTNERS")
def test_nav_still_six():
    """NAV stays the six object-centric items; Partners is a Settings tab.

    What would make this fail: a 7th NAV id, or Partners as a top-level page.
    """
    ids = _nav_ids()
    assert ids == ["home", "sites", "targets", "deploys", "findings", "settings"]
    assert "partners" not in ids
    chrome = _frontend("src", "Chrome.jsx")
    assert "PHONE_SCOPE" in chrome
    assert "partners" not in chrome.split("export const PHONE_SCOPE")[1].split("\n", 1)[0]


@pytest.mark.req("UX-P55-PARTNERS")
def test_checklist_has_no_connect_partner():
    """Do not add connect_partner to checklist.ITEM_IDS.

    What would make this fail: treating partner mint as a first-run Connect.
    """
    from core.checklist import ITEM_IDS

    assert "connect_partner" not in ITEM_IDS
    src = (REPO / "core" / "checklist.py").read_text(encoding="utf-8")
    assert "connect_partner" not in src
    frontend = _frontend("src", "checklist.js")
    assert "connect_partner" not in frontend


@pytest.mark.req("UX-P55-PARTNERS")
def test_settings_tabs_partners_after_aws():
    """SETTINGS_TABS = security, cloudflare, aws, partners, developer, vault.

    What would make this fail: Partners before AWS, or replacing Developer.
    """
    assert _settings_tab_ids() == [
        "security", "cloudflare", "aws", "partners", "developer", "vault",
    ]


@pytest.mark.req("UX-P55-PARTNERS")
def test_copy_does_not_say_instance():
    """Partner copy never says instance except the existing single-instance token.

    What would make this fail: calling a partner site an instance, or a T1
    label that still says instance.
    """
    from core.actions import ACTION_TIERS

    row = next(r for r in ACTION_TIERS if r["id"] == "partner.create")
    assert not re.search(r"\binstance\b", row["label"], re.I)

    for rel in (
        ("src", "screens", "Settings.jsx"),
        ("tests", "settings-partners.test.ts"),
        ("src", "screens", "Sites.jsx"),
    ):
        text = _without_single_instance(_frontend(*rel))
        if rel[-1] == "Sites.jsx":
            # Partner-tab additions: badge + filter must not say instance.
            assert "isPartnerSite" in _frontend(*rel)
        assert not re.search(r"\binstance\b", text, re.I), rel


@pytest.mark.req("UX-P55-PARTNERS")
def test_settings_partners_has_no_99_9_uptime_sla():
    """SLA copy on Settings Partners is response-time, never 99.9% / uptime SLA.

    What would make this fail: borrowing a three-nines uptime sentence.
    """
    partners_block = _settings_jsx().split("export function PartnersPanel")[1].split(
        "export function", 1
    )[0]
    assert not re.search(r"99\.9%|uptime SLA", partners_block, re.I)
    assert "response-time" in partners_block


@pytest.mark.req("UX-P55-PARTNERS")
def test_sites_all_mine_partner_filter_and_partner_badge():
    """Sites All/Mine/Partner filter + partner badge is symbol + words.

    What would make this fail: a colour-only badge, Site.tier=partner, or
    no Partner filter.
    """
    src = _frontend("src", "screens", "Sites.jsx")
    assert "All" in src and "Mine" in src and "Partner" in src
    assert "PartnerBadge" in src
    assert "isPartnerSite" in src
    assert "◆ partner" in src or "partner" in src.lower()
    findings = _frontend("src", "screens", "Findings.jsx")
    assert 'aria-label="Filter by entity"' in findings
    assert "partner:" in _frontend("tests", "settings-partners.test.ts")


@pytest.mark.req("UX-P55-PARTNERS")
def test_hide_adopt_and_job_create_on_partner_site_detail():
    """Partner site detail hides adopt and job-create.

    What would make this fail: AdoptPlan / Create job still mounting when
    site.partner is set.
    """
    src = _frontend("src", "screens", "Sites.jsx")
    assert "isPartnerSite" in src
    assert "AdoptPlan" in src
    assert "Create job" in src
    assert "jobCreateVisible" in src or "Create job" in src
    tests = _frontend("tests", "settings-partners.test.ts")
    assert "Start adopt" in tests or "Adopt plan" in tests
    assert "Create job" in tests


@pytest.mark.req("UX-P55-PARTNERS")
def test_f8_seed_is_partnersite_never_site_tier_partner():
    """F8 seed is PartnerSite-bound, never Site.tier=partner, never a named partner.

    What would make this fail: tier: partner on a Site, a committed-partner
    name, or omitting partner-intake-empty/error/degraded from REQUIRED_STATE_IDS.
    """
    seed = json.loads((REPO / "simulation" / "seed_v1.json").read_text(encoding="utf-8"))
    dumped = json.dumps(seed)
    assert '"tier": "partner"' not in dumped
    assert "tier: partner" not in dumped
    ids = [row["id"] for row in seed["states"]]
    for required in (
        "partner-intake-empty",
        "partner-intake-error",
        "partner-intake-degraded",
        "partner-site",
    ):
        assert required in ids, required
    partner_states = [row for row in seed["states"] if row["id"].startswith("partner")]
    assert partner_states
    for row in seed.get("sites", []):
        assert row.get("tier") != "partner"
    sim_tests = _frontend("tests", "simulation-states.test.ts")
    assert "partner-intake-empty" in sim_tests
    assert "partner-intake-error" in sim_tests
    assert "partner-intake-degraded" in sim_tests
    assert "partner-site" in sim_tests
    assert "REQUIRED_STATE_IDS" in sim_tests
    lowered = dumped.lower()
    assert "acme corp" not in lowered
    assert "fixture-partner" in dumped
    assert "partner-intake-unreachable" in dumped
    assert "partner:fixture-partner" in dumped
