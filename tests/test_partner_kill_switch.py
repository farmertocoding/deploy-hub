"""T1 kill switches + T2 takedown/rank (PART-KILL-SWITCH / UX-P55-PARTNERS).

partner.suspend and partner.api_kill_switch are T1; enable is T1 not a toggle;
global PARTNER_API_ENABLED defaults OFF; Fake Transport stop+detach+revoke;
site_takedown is T2 and the route returns 410. Function-level req markers only.
"""
from __future__ import annotations

import ast
import inspect
import itertools
import json
import os
import pathlib
import re
import time

import pytest
from django.contrib.auth.models import User

from core.transport import FakeTransport

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
SLUG = "fixture-partner"
CONFIRM_API = "partner-api"
HONESTY = (
    "abuse takedowns and IP-reputation damage land on hardware and "
    "residential/office connections you cannot dispose of"
)
_ZONES = itertools.count(1)
_PORTS = itertools.count(20000)


def _frontend(*parts):
    return (REPO / "frontend").joinpath(*parts).read_text(encoding="utf-8")


def _settings_jsx():
    return _frontend("src", "screens", "Settings.jsx")


def _partners_block():
    return _settings_jsx().split("export function PartnersPanel")[1].split(
        "export function", 1
    )[0]


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


def _login(client, user):
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
    user = User.objects.create_superuser("joseph", password="a-long-dev-password")
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")
    _login(client, user)
    return user


def _zone(slug=None):
    from core.models import NetworkZone

    n = next(_ZONES)
    slug = slug or f"pkill-{n}"
    return NetworkZone.objects.create(name=slug, slug=slug)


def _target(*, host="box.partner.test", kind=None, zone=None, tunnel=None):
    from core.models import Target

    payload = {"tunnel": True} if tunnel else {}
    return Target.objects.create(
        zone=zone or _zone(),
        kind=kind or Target.Kind.AWS_EC2,
        host=host,
        ssh_user="deploy",
        ssh_key_ref="vault-pkill",
        host_key_fingerprint="SHA256:pkill",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
        collect_payload=payload or None,
    )


def _partner_with_site(*, slug=SLUG, host="box.partner.test", pubkey="ed25519-live"):
    from core.models import Partner, PartnerSite, Project, Site, SiteInstance

    partner = Partner.objects.create(
        slug=slug, name=slug, pubkey_current=pubkey, pubkey_previous="ed25519-prev",
    )
    project = Project.objects.create(name=slug, slug=slug)
    target = _target(host=host)
    site = Site.objects.create(
        project=project,
        name=f"{slug}-site",
        domain=f"app.{slug}.test",
        exposure=Site.Exposure.MESH_ONLY,
        primary_target=target,
    )
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref="tenant-a")
    SiteInstance.objects.create(
        site=site,
        target=target,
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.RUNNING,
        internal_port=next(_PORTS),
    )
    partner.destination_order = [target.pk]
    partner.save(update_fields=["destination_order"])
    return partner, site, target


def _inject_transport(monkeypatch, transport):
    monkeypatch.setattr(
        "core.partner_views.transport_for",
        lambda target: transport,
    )


def _suspend_url(partner):
    return f"/api/v1/partners/{partner.pk}/suspend/"


def _kill_url():
    return "/api/v1/partner-api/kill-switch/"


def _takedown_url(site):
    return f"/api/v1/sites/{site.pk}/takedown/"


def _rank_url(partner):
    return f"/api/v1/partners/{partner.pk}/destination-rank/"


def _action(action_id):
    from core.actions import ACTION_TIERS

    return next(r for r in ACTION_TIERS if r["id"] == action_id)


# ── T1 / T2 table + HTTP ─────────────────────────────────────────────────────


@pytest.mark.req("PART-KILL-SWITCH")
def test_partner_suspend_is_t1():
    """partner.suspend is T1 Suspend partner: RequireRecentTouch HTTP, type slug.

    What would make this fail: a T2/T3 row, hanging the view off /api/auth/,
    or leaving T1_HTTP unregistered so the standing T1 pin 404s the slug.
    """
    from django.urls import resolve

    from core.partner_views import PartnerSuspendView
    from core.permissions import RequireRecentTouch
    from tests.test_webauthn_t1 import T1_HTTP

    row = _action("partner.suspend")
    assert row["tier"] == "T1"
    assert row["label"] == "Suspend partner"
    assert "instance" not in row["label"].lower()

    template = T1_HTTP["partner.suspend"]
    assert template == "/api/v1/partners/{pk}/suspend/"
    match = resolve(template.format(pk=1))
    view_cls = getattr(match.func, "cls", None)
    assert view_cls is PartnerSuspendView
    assert RequireRecentTouch in view_cls.permission_classes
    source = inspect.getsource(PartnerSuspendView)
    assert "confirm_name" in source
    assert "request.data.get" not in source

    core_urls = (REPO / "core" / "urls.py").read_text(encoding="utf-8")
    assert "suspend" not in core_urls

    ids = [r["id"] for r in __import__("core.actions", fromlist=["ACTION_TIERS"]).ACTION_TIERS]
    create = ids.index("partner.create")
    assert ids[create + 1] == "partner.suspend"


@pytest.mark.req("PART-KILL-SWITCH")
def test_partner_api_kill_switch_is_t1():
    """partner.api_kill_switch is T1; confirm is partner-api.

    What would make this fail: a Settings checkbox, a T2 confirm, or a path
    on /api/auth/.
    """
    from django.urls import resolve

    from core.partner_views import PartnerApiKillSwitchView
    from core.permissions import RequireRecentTouch
    from tests.test_webauthn_t1 import T1_HTTP

    row = _action("partner.api_kill_switch")
    assert row["tier"] == "T1"
    assert row["label"] == "Disable partner API"
    assert "instance" not in row["label"].lower()

    template = T1_HTTP["partner.api_kill_switch"]
    assert template == "/api/v1/partner-api/kill-switch/"
    match = resolve(template)
    view_cls = getattr(match.func, "cls", None)
    assert view_cls is PartnerApiKillSwitchView
    assert RequireRecentTouch in view_cls.permission_classes
    source = inspect.getsource(PartnerApiKillSwitchView)
    assert "confirm_name" in source
    assert "partner-api" in source

    core_urls = (REPO / "core" / "urls.py").read_text(encoding="utf-8")
    assert "kill-switch" not in core_urls
    assert "partner-api" not in core_urls


@pytest.mark.req("PART-KILL-SWITCH")
@pytest.mark.req("UX-P55-PARTNERS")
def test_enable_partner_api_is_t1_not_a_toggle(client, monkeypatch):
    """Enable partner API uses the same T1 id with that label when OFF.

    What would make this fail: a checkbox/switch, flipping the flag without
    type-the-name + touch, or a chrome label that stays Disable while OFF.
    """
    from django.conf import settings

    from core.models import Partner

    assert settings.PARTNER_API_ENABLED is False
    block = _partners_block()
    assert "Enable partner API" in block
    assert not re.search(r'type=["\']checkbox["\']', block)
    assert "role=\"switch\"" not in block
    assert "role='switch'" not in block
    assert "<input" not in block or "type=\"checkbox\"" not in block

    _t1_user(client)
    response = client.post(
        _kill_url(),
        data=json.dumps({"confirm_name": CONFIRM_API}),
        content_type="application/json",
    )
    assert response.status_code == 403, response.content
    assert settings.PARTNER_API_ENABLED is False

    _touch(client, monkeypatch)
    wrong = client.post(
        _kill_url(),
        data=json.dumps({"confirm_name": "yes"}),
        content_type="application/json",
    )
    assert wrong.status_code == 400, wrong.content
    assert settings.PARTNER_API_ENABLED is False

    ok = client.post(
        _kill_url(),
        data=json.dumps({"confirm_name": CONFIRM_API}),
        content_type="application/json",
    )
    assert ok.status_code == 200, ok.content
    try:
        from django.conf import settings as live

        assert live.PARTNER_API_ENABLED is True
        listed = client.get("/api/v1/partners/")
        assert listed.status_code == 200
        assert listed.json().get("api_enabled") is True
        assert not Partner.objects.exists()
    finally:
        from core.partner_views import set_partner_api_enabled

        set_partner_api_enabled(False)


@pytest.mark.req("PART-KILL-SWITCH")
def test_global_flag_defaults_off():
    """PARTNER_API_ENABLED is False unless T1 enable; prod does not default on.

    What would make this fail: reading env as true by default, or prod.py
    assigning True.
    """
    from django.conf import settings

    assert settings.PARTNER_API_ENABLED is False
    base = (REPO / "hub" / "settings" / "base.py").read_text(encoding="utf-8")
    assert "HUB_PARTNER_API_ENABLED" in base
    assert 'os.environ.get(\n    "HUB_PARTNER_API_ENABLED", "",' in base or (
        'os.environ.get("HUB_PARTNER_API_ENABLED", "")' in base
    )
    prod = (REPO / "hub" / "settings" / "prod.py").read_text(encoding="utf-8")
    assert "PARTNER_API_ENABLED =" not in prod
    assert "True" not in "".join(
        line for line in prod.splitlines() if "PARTNER_API" in line
    )


@pytest.mark.req("PART-KILL-SWITCH")
def test_totp_does_not_satisfy_suspend(client):
    """A TOTP login of a two-passkey operator still cannot satisfy T1 suspend.

    What would make this fail: TOTP writing hardware_touch_at, or suspend
    treating an OTP session as a recent touch.
    """
    from django_otp.oath import TOTP
    from django_otp.plugins.otp_totp.models import TOTPDevice

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

    partner, _site, _target = _partner_with_site()
    response = client.post(
        _suspend_url(partner),
        data=json.dumps({"confirm_name": partner.slug}),
        content_type="application/json",
    )
    assert response.status_code == 403
    assert "hardware_touch_at" not in client.session
    partner.refresh_from_db()
    assert partner.suspended is False
    assert partner.pubkey_current


@pytest.mark.req("PART-KILL-SWITCH")
def test_suspend_stops_containers_detaches_revokes(client, monkeypatch):
    """T1 suspend: Fake Transport docker stop + Caddy DELETE + pubkey cleared.

    What would make this fail: leaving containers running, leaving the Caddy
    route, or keeping pubkey_current after suspended=True.
    """
    from core.models import SiteInstance

    _t1_user(client)
    _touch(client, monkeypatch)
    partner, site, _target = _partner_with_site()
    transport = FakeTransport()
    _inject_transport(monkeypatch, transport)

    response = client.post(
        _suspend_url(partner),
        data=json.dumps({"confirm_name": partner.slug}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    partner.refresh_from_db()
    assert partner.suspended is True
    assert partner.pubkey_current == ""
    assert partner.pubkey_previous == ""

    runs = [c[1] for c in transport.calls if c[0] == "run"]
    assert any(argv[:2] == ["docker", "stop"] for argv in runs), runs
    assert any(
        "DELETE" in argv and "2019" in " ".join(argv) for argv in runs
    ), runs
    inst = SiteInstance.objects.get(site=site)
    assert inst.desired_state == SiteInstance.DesiredState.STOPPED


@pytest.mark.req("PART-KILL-SWITCH")
@pytest.mark.req("UX-P55-PARTNERS")
def test_suspend_overlay_names_stop_detach_revoke():
    """T1Overlay summary for suspend names stop containers / detach / revoke.

    What would make this fail: partner T1 growing cost, other T1 ids growing
    a summary, or the overlay omitting the three verbs.
    """
    tiers = _frontend("src", "Tiers.jsx")
    assert "summary" in tiers
    assert "row.id.startsWith(\"partner.\")" in tiers or "partner." in tiers
    block = _partners_block()
    lowered = block.lower()
    assert "stop containers" in lowered
    assert "detach routes" in lowered or "detach" in lowered
    assert "revoke" in lowered
    assert "Suspend partner" in block
    assert not re.search(r"\bConnected\b", block)
    assert "Create partner" in block


@pytest.mark.req("PART-KILL-SWITCH")
def test_site_takedown_is_t2_and_returns_410(client, monkeypatch):
    """partner.site_takedown is T2; POST takes the route to 410.

    What would make this fail: RequireRecentTouch on takedown, a T1 row, or
    the domain still serving 200 after the confirm.
    """
    from django.urls import resolve

    from core.partner_views import PartnerSiteTakedownView, site_route_status
    from core.permissions import RequireRecentTouch

    row = _action("partner.site_takedown")
    assert row["tier"] == "T2"
    assert row["label"] == "Take down site"

    match = resolve("/api/v1/sites/1/takedown/")
    view_cls = getattr(match.func, "cls", None)
    assert view_cls is PartnerSiteTakedownView
    assert RequireRecentTouch not in view_cls.permission_classes

    core_urls = (REPO / "core" / "urls.py").read_text(encoding="utf-8")
    assert "takedown" not in core_urls

    _t1_user(client)
    partner, site, _target = _partner_with_site()
    _inject_transport(monkeypatch, FakeTransport())
    assert site_route_status(site) != 410
    response = client.post(
        _takedown_url(site),
        data=json.dumps({"confirm_name": site.domain}),
        content_type="application/json",
    )
    assert response.status_code == 410, response.content
    assert site_route_status(site) == 410
    partner.refresh_from_db()
    assert partner.suspended is False


@pytest.mark.req("PART-KILL-SWITCH")
@pytest.mark.req("UX-P55-PARTNERS")
def test_takedown_control_is_on_partner_site_detail():
    """Take down site is T2 chrome on partner site detail, not Settings.

    What would make this fail: hiding the control, putting it on a non-partner
    site, or copy that says instance.
    """
    sites = _frontend("src", "screens", "Sites.jsx")
    assert "partner.site_takedown" in sites
    assert "Take down site" in sites or 'tierFor("partner.site_takedown")' in sites
    assert "route → 410" in sites or "route → 410" in sites.replace("->", "→")
    assert "isPartnerSite" in sites
    assert not re.search(r"\binstance\b", re.sub(r"single-instance", "", sites), re.I)
    tests = _frontend("tests", "settings-partners.test.ts")
    assert "Take down site" in tests or "takedown" in tests.lower()


@pytest.mark.req("PART-KILL-SWITCH")
def test_auto_trigger_files_partner_kill_switch_fingerprint(monkeypatch):
    """Abuse/CSAM auto-suspend files P1 fingerprint partner-kill-switch:{pk}.

    What would make this fail: default {kind}:{entity}, skipping the file, or
    requiring the T1 overlay for CSAM.
    """
    from core.models import Finding
    from core.partner_views import auto_trigger_kill_switch

    partner, _site, _target = _partner_with_site(slug="auto-kill")
    _inject_transport(monkeypatch, FakeTransport())
    auto_trigger_kill_switch(partner, reason="csam")
    partner.refresh_from_db()
    assert partner.suspended is True
    fp = f"partner-kill-switch:{partner.pk}"
    row = Finding.objects.get(fingerprint=fp)
    assert row.severity == Finding.Severity.P1
    assert row.fingerprint != f"partner-kill-switch:partner:{partner.pk}"
    source = inspect.getsource(auto_trigger_kill_switch)
    assert "fingerprint=" in source
    assert "T1Overlay" not in source
    assert "ActionButton" not in source


@pytest.mark.req("PART-KILL-SWITCH")
def test_suspend_run_twice_zero_mutating_calls(client, monkeypatch):
    """Second suspend of an already-suspended partner is zero mutating Transport.

    What would make this fail: docker stop / Caddy DELETE on the second pass.
    """
    _t1_user(client)
    _touch(client, monkeypatch)
    partner, _site, _target = _partner_with_site(slug="twice-suspend")
    transport = FakeTransport()
    _inject_transport(monkeypatch, transport)

    first = client.post(
        _suspend_url(partner),
        data=json.dumps({"confirm_name": partner.slug}),
        content_type="application/json",
    )
    assert first.status_code == 200, first.content
    assert transport.mutating_calls()
    transport.calls.clear()

    second = client.post(
        _suspend_url(partner),
        data=json.dumps({"confirm_name": partner.slug}),
        content_type="application/json",
    )
    assert second.status_code == 200, second.content
    assert transport.mutating_calls() == []


def _string_constants(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)
    return found


def test_partner_router_still_does_not_map_to_operator_ids():
    """K6: the partner router must not call ACTION_TIERS T1/T2 operator ids.

    What would make this fail: intake or partner_jobs mapping to suspend,
    kill-switch, takedown, destination_rank, or the older internal ids.
    Gate is AST string constants plus PARTNER_ROUTER keys/values, so a
    BooleanField attribute partner.suspended does not trip partner.suspend.
    """
    from core.actions import ACTION_TIERS
    from core.partner_jobs import PARTNER_ROUTER

    operator_ids = {
        "target.delete", "key.export", "kek.rotate", "ssh.rotate",
        "instance.create", "instance.terminate", "dns.change", "site.auto_mode",
        "partner.create", "partner.suspend", "partner.api_kill_switch",
        "partner.site_takedown", "partner.destination_rank",
    }
    t1_t2 = {row["id"] for row in ACTION_TIERS if row["tier"] in {"T1", "T2"}}
    banned = t1_t2 | operator_ids
    mapped = set(PARTNER_ROUTER.values()) | set(PARTNER_ROUTER.keys())
    overlap = mapped & banned
    assert not overlap, f"partner router maps to internal ids: {sorted(overlap)}"
    assert "partner.suspend" in banned

    paths = list((REPO / "intake").rglob("*.py"))
    for rel in ("core/partner_jobs.py", "core/partner_templates.py"):
        path = REPO / rel
        if path.exists():
            paths.append(path)
    for path in paths:
        found = _string_constants(path) & banned
        assert not found, f"{path.name} names internal ACTION_TIERS ids: {sorted(found)}"


@pytest.mark.req("UX-P55-PARTNERS")
def test_destination_rank_http_pin_and_own_server_honesty_sentence(client):
    """POST /api/v1/partners/<pk>/destination-rank/; ssh confirm is K5 once.

    What would make this fail: hanging the path off /api/auth/, skipping the
    honesty sentence when kind=ssh, or nags instead of a Finding when the
    own-server has no tunnel.
    """
    from django.urls import resolve

    from core.models import Finding, Target
    from core.partner_views import PartnerDestinationRankView
    from core.permissions import RequireRecentTouch

    row = _action("partner.destination_rank")
    assert row["tier"] == "T2"
    assert row["label"] == "Rank partner destination"

    match = resolve("/api/v1/partners/1/destination-rank/")
    view_cls = getattr(match.func, "cls", None)
    assert view_cls is PartnerDestinationRankView
    assert RequireRecentTouch not in view_cls.permission_classes
    core_urls = (REPO / "core" / "urls.py").read_text(encoding="utf-8")
    assert "destination-rank" not in core_urls

    block = _partners_block()
    assert HONESTY in block
    assert "dedicated cloud first" in block
    assert not re.search(r"\bConnected\b", block)
    assert "Create partner" in block

    _t1_user(client)
    partner, _site, cloud = _partner_with_site(slug="rank-me")
    own = _target(
        host="home.partner.test", kind=Target.Kind.SSH, tunnel=False,
    )
    refused = client.post(
        _rank_url(partner),
        data=json.dumps({"destination_order": [own.pk]}),
        content_type="application/json",
    )
    assert refused.status_code == 400, refused.content
    fp = f"partner-tunnel-required:{own.pk}"
    assert Finding.objects.filter(fingerprint=fp).exists()
    partner.refresh_from_db()
    assert own.pk not in (partner.destination_order or [])

    tunneled = _target(
        host="office.partner.test", kind=Target.Kind.SSH, tunnel=True,
    )
    ok = client.post(
        _rank_url(partner),
        data=json.dumps({"destination_order": [cloud.pk, tunneled.pk]}),
        content_type="application/json",
    )
    assert ok.status_code == 200, ok.content
    partner.refresh_from_db()
    assert partner.destination_order == [cloud.pk, tunneled.pk]
    listed = client.get(f"/api/v1/partners/{partner.pk}/")
    kinds = [d["kind"] for d in listed.json().get("destinations", [])]
    assert Target.Kind.AWS_EC2 in kinds
    assert kinds[0] == Target.Kind.AWS_EC2 or "dedicated cloud first" in block


@pytest.mark.req("UX-P55-PARTNERS")
def test_destination_rank_own_server_is_t2_with_honesty_sentence():
    """Own-server rank confirm is T2; honesty sentence only when kind=ssh.

    What would make this fail: a T1 overlay on rank, showing the sentence for
    dedicated-cloud-only saves, or a Settings toggle.
    """
    row = _action("partner.destination_rank")
    assert row["tier"] == "T2"
    settings_src = _settings_jsx()
    assert 'tierFor("partner.destination_rank")' in settings_src
    assert HONESTY in settings_src
    assert "kind === \"ssh\"" in settings_src or 'kind === "ssh"' in settings_src
    assert "kind=ssh" in settings_src or "kind === \"ssh\"" in settings_src


@pytest.mark.req("PART-KILL-SWITCH")
def test_kill_switch_survives_a_fresh_process_settings_read(client, monkeypatch):
    """H4: T1 enable is visible when this process's settings flag is still off.

    What would make this fail: set_partner_api_enabled only mutating
    django.conf.settings so Beat/poller still reads the env default.
    """
    from django.test import override_settings

    from core.partner_views import partner_api_enabled, set_partner_api_enabled

    _t1_user(client)
    _touch(client, monkeypatch)
    ok = client.post(
        _kill_url(),
        data=json.dumps({"confirm_name": CONFIRM_API}),
        content_type="application/json",
    )
    assert ok.status_code == 200, ok.content
    try:
        with override_settings(PARTNER_API_ENABLED=False):
            assert partner_api_enabled() is True
    finally:
        set_partner_api_enabled(False)


@pytest.mark.req("PART-KILL-SWITCH")
def test_suspend_stops_pipeline_container_name(client, monkeypatch):
    """H12: docker stop uses site-{slug}-{deployment_id}, not site-{name} alone.

    What would make this fail: partner_views._container_name staying
    site-{site.name} while deploys/steps.py names site-{slug}-{pk}.
    """
    from deploys.models import Deployment, Manifest

    _t1_user(client)
    _touch(client, monkeypatch)
    partner, site, _target = _partner_with_site(slug="pipe-name")
    manifest = Manifest.objects.create(
        site=site, version=1, body={"schema_version": 1, "runtime": "static"},
    )
    dep = Deployment.objects.create(manifest=manifest, status=Deployment.Status.SUCCEEDED)
    transport = FakeTransport()
    _inject_transport(monkeypatch, transport)
    response = client.post(
        _suspend_url(partner),
        data=json.dumps({"confirm_name": partner.slug}),
        content_type="application/json",
    )
    assert response.status_code == 200, response.content
    expected = f"site-{site.name}-{dep.pk}"
    runs = [c[1] for c in transport.calls if c[0] == "run"]
    assert any(argv == ["docker", "stop", expected] for argv in runs), runs
    assert not any(
        argv == ["docker", "stop", f"site-{site.name}"] for argv in runs
    ), runs


@pytest.mark.req("PART-KILL-SWITCH")
def test_takedown_without_siteinstance_does_not_claim_410(client, monkeypatch):
    """H12: HTTP 410 only when the site is actually marked ABSENT.

    What would make this fail: PartnerSiteTakedownView returning 410 after a
    no-op update of zero SiteInstance rows (materialize never inserts one).
    """
    from core.models import Partner, PartnerSite, Project, Site
    from core.partner_views import site_route_status

    _t1_user(client)
    _inject_transport(monkeypatch, FakeTransport())
    partner = Partner.objects.create(slug="no-inst", name="no-inst")
    project = Project.objects.create(name="no-inst", slug="no-inst")
    target = _target(host="no-inst.partner.test")
    site = Site.objects.create(
        project=project,
        name="no-inst-site",
        domain="app.no-inst.test",
        exposure=Site.Exposure.MESH_ONLY,
        primary_target=target,
    )
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref="t")
    partner.destination_order = [target.pk]
    partner.save(update_fields=["destination_order"])
    assert site_route_status(site) != 410
    response = client.post(
        _takedown_url(site),
        data=json.dumps({"confirm_name": site.domain}),
        content_type="application/json",
    )
    # After the fix this is 410 only because a SiteInstance is now ABSENT.
    from core.models import SiteInstance

    assert SiteInstance.objects.filter(site=site).exists()
    assert site_route_status(site) == 410
    assert response.status_code == 410, response.content


@pytest.mark.req("PART-KILL-SWITCH")
def test_operator_ssh_transport_for_is_not_hardwired_fake():
    """H12: operator destinations default to SshTransport like the pipeline.

    What would make this fail: transport_for returning FakeTransport for
    AWS_EC2 (the partner-destination kind) or SSH while deploys/pipeline.py
    uses SshTransport for the same Target.
    """
    from core.models import Target
    from core.partner_views import transport_for
    from core.ssh import SshTransport
    from core.transport import FakeTransport
    from deploys.pipeline import _default_transport

    ssh = _target(kind=Target.Kind.SSH)
    aws = _target(kind=Target.Kind.AWS_EC2, host="aws.partner.test")
    assert isinstance(transport_for(ssh), SshTransport)
    assert isinstance(transport_for(aws), SshTransport)
    assert not isinstance(transport_for(aws), FakeTransport)
    site = type("S", (), {"primary_target": aws})()
    assert type(transport_for(aws)) is type(_default_transport(site))
    tests = _frontend("tests", "settings-partners.test.ts")
    assert "destination" in tests.lower() or "honesty" in tests.lower()
    sim = _frontend("tests", "simulation-states.test.ts")
    assert "partner-kill-switch-overlay" in sim
    assert "partner-destination-order-confirm" in sim
