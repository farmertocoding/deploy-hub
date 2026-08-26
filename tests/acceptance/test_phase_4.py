"""Phase 4 acceptance — each test transcribes one design-note §4 clause.

`check.py --phase 4 --exclude-tier t2 --exclude-tier t3` is the phase-4 gate.
T1 fakes only: FakeHelper, FakeEdgeProtection, RotateTransport, FakeTailscale,
FakeKms, moto on providers/kms.py. Do not require a live CF/KMS/S3/YubiKey.
Do not invent a test-zone token env. Do not add Playwright. Do not mark
TLS-B2-HUB-DNS01-UNPROXIED or the full-text SEC-B2 id.

Every T1 body asserts the same properties an existing named proof asserts
(transcription, not fiction); each docstring names its source test.
The demo record must describe those proofs, not a fictional live run.
"""
import json
from pathlib import Path

import pytest
import yaml
from django.conf import settings
from django.test import override_settings

REPO = Path(__file__).resolve().parent.parent.parent
DEMO = REPO / "conformance" / "demos" / "phase-4.md"
WAIVER_24H = "REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven"
FULL_TEXT_SEC_B2 = "SEC-B2-NO-DNS-TOKENS-ON-TARGETS"
DNS01_ID = "TLS-B2-HUB-DNS01-UNPROXIED"
LE_STAGING = "HARNESS-T3-LE-STAGING"
TAILSCALE_ID = "SEC-B8-TAILSCALE-DEVICE-POLL"
NAMED = (
    "test_webauthn_security_key_and_phone_passkey_totp_fallback",
    "test_t1_target_delete_and_ssh_rotate_need_touch_and_name",
    "test_totp_only_session_refused_with_add_a_passkey",
    "test_t3_rollback_is_one_click_and_never_step_up_gated",
    "test_idle_timeout_kills_stolen_session_past_30_min",
    "test_declared_drill_tree_blocks_until_wizard_accept",
    "test_attack_playbook_fake_edge_and_never_scale",
    "test_topology_r1_r5_findings",
    "test_ssh_rotate_dual_key_run_twice",
    "test_backup_list_test_now_command_block_and_p1",
    "test_alerts_topic_unauthorized",
    "test_compose_parse_redis_unpublished_requirepass_json",
    "test_exhaust_gate_greps_captured_output",
    "test_tailscale_skip_unless_or_fake_unknown_device",
    "test_kms_kek_moto_refuse_cache_keyfile",
    "test_audit_hash_chain_local_never_blocks_on_s3",
    "test_rel_p2_24h_still_not_claimed",
    "test_hub_central_dns01_stays_first_slip",
    "test_conformance_4_excludes_t2_t3",
)

pytestmark = [pytest.mark.acceptance(phase=4)]


def _waivers():
    return (REPO / "WAIVERS.md").read_text(encoding="utf-8")


def _demo():
    assert DEMO.is_file() and DEMO.stat().st_size > 0, (
        "conformance/demos/phase-4.md must exist — P4-SECURITY-DEMO is verify: demo"
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
    """A non-empty stub must not verify P4-SECURITY-DEMO (Task 0)."""
    record = _demo()
    lower = record.lower()
    for name in NAMED:
        assert name in record, f"demo must name the acceptance nodeid {name}"
    assert "FakeEdgeProtection" in record
    assert "FakeTailscale" in record
    assert "FakeKms" in record or "moto" in lower
    assert "RotateTransport" in record or "FakeTransport" in record
    assert "t1" in lower
    assert "live cloudflare" not in lower or "no live" in lower or "not a live" in lower
    assert "live aws" not in lower or "no live" in lower or "not a live" in lower
    assert "yubikey kek" not in lower or "slip" in lower
    assert "playwright" not in lower or "slip" in lower
    assert "hub-down" not in lower or "not claimed" in lower or "still not" in lower
    assert "24 h hub-down" not in lower and "24h hub-down" not in lower
    assert WAIVER_24H in record
    assert DNS01_ID in record
    assert TAILSCALE_ID in record
    assert "skip-unless" in lower or "skip unless" in lower
    assert "HUB_TEST_" + "DNS_ZONE" not in record
    assert "HUB_TEST_" + "CF_TOKEN" not in record
    assert "stub" not in lower
    assert "todo" not in lower
    assert "conformance-4" in lower
    assert "--exclude-tier t2" in record and "--exclude-tier t3" in record
    return record


def _touch(client):
    assert client.post("/api/auth/webauthn/authentication/begin/").status_code == 200
    touch = client.post(
        "/api/auth/webauthn/touch/",
        data=json.dumps({"id": "cred-1", "response": {}}),
        content_type="application/json",
    )
    assert touch.status_code == 200, touch.content
    assert client.session.get("hardware_touch_at")


# ── named clauses ───────────────────────────────────────────────────────────


@pytest.mark.django_db
@pytest.mark.req("SEC-A2-WEBAUTHN-PHASE4")
def test_webauthn_security_key_and_phone_passkey_totp_fallback(client, monkeypatch):
    """Enroll a security key and a phone passkey; TOTP remains a login fallback.

    Transcribes tests/test_webauthn_t1.py::test_webauthn_enroll_and_confirm,
    ::test_second_passkey_enrolls, and
    ::test_login_accepts_webauthn_or_totp_or_recovery. FakeHelper only.
    """
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from django_otp_webauthn.models import WebAuthnCredential
    from test_webauthn_t1 import _current_code, _login_password, _patch_webauthn_helper

    from core.models import RecoveryCode

    _patch_webauthn_helper(monkeypatch)
    password = "a-long-dev-password"
    user = User.objects.create_user("joseph", password=password)
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    _login_password(client, user)

    assert client.post("/api/auth/webauthn/registration/begin/").status_code == 200
    first = client.post(
        "/api/auth/webauthn/registration/complete/",
        data=json.dumps({"name": "yubikey", "id": "cred-1"}),
        content_type="application/json",
    )
    assert first.status_code == 200, first.content
    codes = first.json().get("recovery_codes")
    assert codes and len(codes) == 8
    assert WebAuthnCredential.objects.filter(user=user, confirmed=True).count() == 1
    assert RecoveryCode.objects.filter(user=user).count() == 8
    assert "hardware_touch_at" not in client.session

    assert client.post("/api/auth/webauthn/registration/begin/").status_code == 200
    second = client.post(
        "/api/auth/webauthn/registration/complete/",
        data=json.dumps({"name": "phone", "id": "phone"}),
        content_type="application/json",
    )
    assert second.status_code == 200, second.content
    assert WebAuthnCredential.objects.filter(user=user, confirmed=True).count() == 2

    client.post("/api/auth/logout/")
    totp_login = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph", "password": password,
            "otp_code": _current_code(device),
        }),
        content_type="application/json",
    )
    assert totp_login.status_code == 200, totp_login.content
    assert "hardware_touch_at" not in client.session
    client.post("/api/auth/logout/")

    recovery_login = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph", "password": password,
            "otp_code": codes[0],
        }),
        content_type="application/json",
    )
    assert recovery_login.status_code == 200, recovery_login.content
    client.post("/api/auth/logout/")

    begin = client.post(
        "/api/auth/webauthn/login/begin/",
        data=json.dumps({"username": "joseph"}),
        content_type="application/json",
    )
    assert begin.status_code == 200, begin.content
    webauthn_login = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph", "password": password,
            "webauthn": {"id": "cred-1", "response": {}},
        }),
        content_type="application/json",
    )
    assert webauthn_login.status_code == 200, webauthn_login.content
    assert "hardware_touch_at" not in client.session


@pytest.mark.django_db
@pytest.mark.req("SEC-F5-T1-HARDWARE-TOUCH")
def test_t1_target_delete_and_ssh_rotate_need_touch_and_name(client, monkeypatch):
    """T1 target.delete / ssh.rotate refuse without WebAuthn touch and without
    type-the-name; after touch+name they run and audit. TOTP never writes
    hardware_touch_at.

    Transcribes tests/test_webauthn_t1.py::
    test_t1_target_delete_refuses_without_recent_touch,
    ::test_t1_requires_type_the_name,
    ::test_t1_totp_does_not_write_hardware_touch_at,
    ::test_t1_action_ids_are_require_recent_touch_or_404 and
    tests/test_ssh_rotate.py::test_ssh_rotate_is_t1.
    """
    import inspect

    from django.contrib.auth.models import User
    from django.urls import resolve
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from test_webauthn_t1 import (
        T1_HTTP,
        _current_code,
        _delete_url,
        _login_password,
        _make_cred,
        _make_target,
        _patch_webauthn_helper,
    )

    from core.actions import ACTION_TIERS
    from core.models import AuditEvent, Target
    from core.permissions import RequireRecentTouch
    from core.views import SshRotateView

    _patch_webauthn_helper(monkeypatch)
    monkeypatch.setattr(
        "provision.ssh_rotate.rotate_ssh",
        lambda *args, **kwargs: {"status": "rotated"},
    )
    user = User.objects.create_user("joseph", password="a-long-dev-password")
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")
    delete_target = _make_target("box-1.example.com")
    rotate_target = _make_target("box-2.example.com")
    rotate_url = T1_HTTP["ssh.rotate"].format(pk=rotate_target.pk)

    totp_login = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph",
            "password": "a-long-dev-password",
            "otp_code": _current_code(device),
        }),
        content_type="application/json",
    )
    assert totp_login.status_code == 200, totp_login.content
    assert "hardware_touch_at" not in client.session
    totp_delete = client.post(
        _delete_url(delete_target),
        data=json.dumps({"confirm_name": delete_target.host}),
        content_type="application/json",
    )
    assert totp_delete.status_code == 403
    assert "hardware_touch_at" not in client.session
    client.post("/api/auth/logout/")

    _login_password(client, user)
    for url, host in (
        (_delete_url(delete_target), delete_target.host),
        (rotate_url, rotate_target.host),
    ):
        refused = client.post(
            url, data=json.dumps({"confirm_name": host}),
            content_type="application/json",
        )
        assert refused.status_code == 403, refused.content
        assert "touch" in refused.json()["detail"].lower()
    assert Target.objects.filter(pk=delete_target.pk).exists()

    _touch(client)
    for url in (_delete_url(delete_target), rotate_url):
        wrong = client.post(
            url, data=json.dumps({"confirm_name": "wrong-host"}),
            content_type="application/json",
        )
        assert wrong.status_code == 400, wrong.content
    assert Target.objects.filter(pk=delete_target.pk).exists()

    deleted = client.post(
        _delete_url(delete_target),
        data=json.dumps({"confirm_name": "box-1.example.com"}),
        content_type="application/json",
    )
    assert deleted.status_code == 204, deleted.content
    assert not Target.objects.filter(pk=delete_target.pk).exists()
    assert AuditEvent.objects.filter(action="target.delete").exists()

    rotated = client.post(
        rotate_url,
        data=json.dumps({"confirm_name": "box-2.example.com"}),
        content_type="application/json",
    )
    assert rotated.status_code == 204, rotated.content
    assert AuditEvent.objects.filter(action="ssh.rotate").exists()

    t1_ids = [row["id"] for row in ACTION_TIERS if row["tier"] == "T1"]
    assert "target.delete" in t1_ids and "ssh.rotate" in t1_ids
    row = next(r for r in ACTION_TIERS if r["id"] == "ssh.rotate")
    assert row["tier"] == "T1"
    match = resolve(T1_HTTP["ssh.rotate"].format(pk=1))
    assert getattr(match.func, "cls", None) is SshRotateView
    assert RequireRecentTouch in SshRotateView.permission_classes
    source = inspect.getsource(SshRotateView)
    assert "SshRotateSerializer" in source
    assert "confirm_name" in source


@pytest.mark.django_db
@pytest.mark.req("SEC-F5-T1-HARDWARE-TOUCH")
def test_totp_only_session_refused_with_add_a_passkey(client, monkeypatch):
    """TOTP-only (and a single passkey) keep T1 refused with “add a passkey”.

    Transcribes tests/test_webauthn_t1.py::
    test_t1_refused_until_two_webauthn_credentials.
    """
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from test_webauthn_t1 import (
        _delete_url,
        _login_password,
        _make_cred,
        _make_target,
        _patch_webauthn_helper,
    )

    from core.models import Target

    _patch_webauthn_helper(monkeypatch)
    user = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    target = _make_target()
    _login_password(client, user)

    totp_only = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert totp_only.status_code == 403
    assert "passkey" in totp_only.json()["detail"].lower()

    _make_cred(user, "yubikey")
    _touch(client)
    one_key = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert one_key.status_code == 403
    assert "passkey" in one_key.json()["detail"].lower()
    assert Target.objects.filter(pk=target.pk).exists()


@pytest.mark.req("UX-F5-T2-T3-FRICTION")
def test_t3_rollback_is_one_click_and_never_step_up_gated():
    """T3 rollback is one click and never RequireRecentTouch / step-up.

    Transcribes tests/test_webauthn_t1.py::
    test_t3_rollback_never_uses_require_recent_touch,
    tests/test_action_tiers.py::test_t3_rollback_never_grows_a_step_up, and
    frontend/tests/actions.test.ts::
    rollback_restart_and_rerun_are_t3_and_never_behind_step_up.
    """
    import inspect

    from core.actions import ACTION_TIERS
    from deploys.views import SiteRollbackView

    classes = SiteRollbackView.permission_classes
    names = [getattr(cls, "__name__", str(cls)) for cls in classes]
    assert "RequireRecentTouch" not in names
    source = inspect.getsource(SiteRollbackView)
    assert "RequireRecentTouch" not in source
    assert "hardware_touch" not in source

    row = next(r for r in ACTION_TIERS if r["id"] == "site.rollback")
    assert row["tier"] == "T3"
    assert "step_up" not in row and "stepUp" not in row
    client = (REPO / "frontend" / "src" / "actions.js").read_text(encoding="utf-8")
    assert (
        'if (row.tier === "T3") return { confirm: false, undo: true, stepUp: "none" }'
        in client
    )
    tests = (REPO / "frontend" / "tests" / "actions.test.ts").read_text(encoding="utf-8")
    assert "rollback_restart_and_rerun_are_t3_and_never_behind_step_up" in tests


@pytest.mark.django_db
@pytest.mark.req("SEC-A2-WEBAUTHN-PHASE4")
def test_idle_timeout_kills_stolen_session_past_30_min(client):
    """IdleTimeoutMiddleware kills a stolen session past 30 min.

    Transcribes tests/test_webauthn_t1.py::test_idle_timeout_expires_session.
    """
    import time

    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from test_webauthn_t1 import _login_password

    assert settings.HUB_SESSION_IDLE_TIMEOUT == 30 * 60
    user = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    _login_password(client, user)

    live = client.get("/api/auth/me/")
    assert live.status_code == 200
    assert live.json()["authenticated"] is True

    session = client.session
    session["_hub_last_activity"] = time.time() - settings.HUB_SESSION_IDLE_TIMEOUT - 1
    session.save()

    expired = client.get("/api/auth/me/")
    assert expired.status_code == 200
    assert expired.json()["authenticated"] is False

    gated = client.post(
        "/api/demo-jobs/",
        data=json.dumps({"name": "demo"}),
        content_type="application/json",
    )
    assert gated.status_code in (401, 403)


@pytest.mark.django_db
@pytest.mark.req("SCAN-DECLARED-TEST-MATERIAL")
@pytest.mark.req("SCAN-DECLARED-GUARDS")
def test_declared_drill_tree_blocks_until_wizard_accept(tmp_path):
    """deployhub.yaml drill tree: labelled heuristic still blocks until wizard
    accept; [proof] / .env still block; root declaration refused; reason-edit
    invalidates the confirm id.

    Transcribes tests/test_d012_reland.py::
    test_declared_heuristic_still_blocks_until_wizard_accept,
    ::test_proof_axis_unaffected_under_declaration,
    ::test_declared_env_still_blocks_after_wizard_accept,
    ::test_root_declaration_warns_and_downgrades_nothing, and
    ::test_reason_edit_invalidates_confirm_id.
    """
    from test_d012_reland import (
        DRILL_CONFIRM,
        DRILL_PATH,
        DRILL_REASON,
        FAKE_HIGH_ENTROPY,
        GHP_TOKEN,
        _answer_domain,
        _codes,
        _confirm_ids,
        _declaration,
        _drill_files,
        _problem,
        _rescan,
        _secret,
        _site,
    )

    from wizard import service
    from wizard.materialize import MaterializeRefused, materialize, preflight

    site = _site(tmp_path, _drill_files(), name="p4-drill")
    secret = _secret(site)
    assert secret["tier"] == "blocker", secret
    assert "declared:" in secret["detail"]
    assert DRILL_REASON in secret["detail"]
    assert secret["acceptance"]["blocking_only_declared"] is True
    assert DRILL_CONFIRM in secret["acceptance"]["questions"]
    _answer_domain(site)
    problems = preflight(site)
    assert "blockers_present" in _codes(problems)
    item = _problem(problems, "blockers_present")["items"][0]
    assert [q["id"] for q in item["awaiting_acceptance"]] == [DRILL_CONFIRM]
    with pytest.raises(MaterializeRefused):
        materialize(site)
    service.set_answers(site, {DRILL_CONFIRM: True})
    assert preflight(site) == []
    materialize(site, confirm_warnings=True)
    assert _secret(site)["tier"] == "blocker"

    files = dict(_drill_files())
    files["frontend/scripts/drill/real.mjs"] = f'const t = "{GHP_TOKEN}";\n'
    proof = _site(tmp_path, files, name="p4-proof")
    assert "[proof]" in _secret(proof)["detail"]
    assert _secret(proof)["acceptance"]["blocking_only_declared"] is False
    _answer_domain(proof)
    service.set_answers(proof, {DRILL_CONFIRM: True})
    with pytest.raises(MaterializeRefused):
        materialize(proof, confirm_warnings=True)

    env_files = dict(_drill_files())
    env_files["frontend/scripts/drill/.env"] = "API_KEY=x\n"
    env_site = _site(tmp_path, env_files, name="p4-env")
    assert ".env file present in the scan tree" in _secret(env_site)["detail"]
    assert _secret(env_site)["acceptance"]["blocking_only_declared"] is False
    _answer_domain(env_site)
    service.set_answers(env_site, {DRILL_CONFIRM: True})
    with pytest.raises(MaterializeRefused):
        materialize(env_site, confirm_warnings=True)

    root_files = {
        "Dockerfile": 'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n',
        "src/app.py": f'admin_password = "{FAKE_HIGH_ENTROPY}"\n',
        "deployhub.yaml": _declaration("."),
    }
    swallow = _site(tmp_path, root_files, name="p4-swallow")
    assert "declared:" not in _secret(swallow)["detail"]
    assert "scan root" in _secret(swallow)["detail"]
    assert _confirm_ids(swallow) == []
    _answer_domain(swallow)
    with pytest.raises(MaterializeRefused):
        materialize(swallow, confirm_warnings=True)

    swapped_site = _site(tmp_path, _drill_files(), name="p4-swap")
    _answer_domain(swapped_site)
    original = _confirm_ids(swapped_site)[0]
    service.set_answers(swapped_site, {original: True})
    assert preflight(swapped_site) == []
    swapped = dict(_drill_files())
    swapped["deployhub.yaml"] = _declaration(
        DRILL_PATH, "ACTUALLY covers prod secrets now")
    _rescan(swapped_site, tmp_path, swapped, name="p4-swap")
    assert original not in _confirm_ids(swapped_site)
    assert "blockers_present" in _codes(preflight(swapped_site))
    with pytest.raises(MaterializeRefused):
        materialize(swapped_site, confirm_warnings=True)


@pytest.mark.django_db
@pytest.mark.req("SEC-L5-ATTACK-PLAYBOOK")
@pytest.mark.req("SEC-L5-NEVER-SCALE-ATTACK")
def test_attack_playbook_fake_edge_and_never_scale():
    """z-score trip through FakeEdgeProtection: Under-Attack, ban, P1 Finding,
    Sites AttackState, Home banner, auto-relax; refuse_if_attack is named;
    missing edge ref is notify-only.

    Transcribes tests/test_attack_playbook.py::
    test_playbook_sets_under_attack_and_bans_ip,
    ::test_playbook_without_edge_ref_notifies_only,
    ::test_playbook_run_twice_zero_mutating_calls,
    ::test_attack_playbook_engaged_is_p1,
    ::test_refuse_if_attack_blocks_scale,
    ::test_pager_click_url_is_hash_findings, and
    frontend/tests/sites.test.ts::home_attack_banner_links_hash_findings.
    """
    from test_attack_playbook import (
        ATTACKER_IP,
        _attack_shaped,
        _plant_traffic,
        _world,
    )

    from core.models import Finding, TrafficStat
    from monitor.alert_rules import classify
    from monitor.attack_playbook import fingerprint_for, run
    from monitor.pager import get_pager, reset_pager
    from providers.fakes import FakeEdgeProtection
    from providers.registry import edge_protection_for, reset_scope_cache
    from scaling.attack_gate import AttackRefuse, refuse_if_attack
    from wizard.views import project_row_body

    reset_pager()
    reset_scope_cache()

    site = _world("p4-l5")
    _attack_shaped(site)
    edge = FakeEdgeProtection()
    row = run(site, edge)
    zone = site.dns_zone
    assert edge.security_level[zone] == "under_attack"
    assert any(item[1] == ATTACKER_IP for item in edge.banned)
    mutating = [call[0] for call in edge.mutating_calls()]
    assert mutating[0] == "set_security_level"
    assert mutating.index("set_security_level") < mutating.index("ban_ip")
    assert classify("attack-playbook-engaged") == "p1"
    assert row.severity == Finding.Severity.P1
    assert row.fingerprint == fingerprint_for(zone)
    first = list(edge.mutating_calls())
    run(site, edge)
    assert edge.mutating_calls()[len(first):] == []

    with pytest.raises(AttackRefuse) as exc:
        refuse_if_attack(site)
    assert exc.value.finding.pk == row.pk
    payload = project_row_body(site.project)["sites"][0]["attack_state"]
    assert payload["finding_id"] == row.pk
    assert payload["mode"] == "under_attack"

    click = get_pager().published[-1]["click_url"]
    base = settings.HUB_PUBLIC_URL.rstrip("/")
    assert click == f"{base}/#/findings/{row.pk}"

    home = (REPO / "frontend" / "src" / "screens" / "Home.jsx").read_text(
        encoding="utf-8")
    assert "export function AttackBanner" in home
    assert "Under attack" in home
    sites_jsx = (REPO / "frontend" / "src" / "screens" / "Sites.jsx").read_text(
        encoding="utf-8")
    assert "export function AttackState" in sites_jsx

    TrafficStat.objects.filter(site=site).delete()
    _plant_traffic(site, [10] * 21)
    relaxed = run(site, edge)
    assert edge.security_level[zone] == "medium"
    relaxed.refresh_from_db()
    assert relaxed.state == Finding.State.RESOLVED
    assert refuse_if_attack(site) is None

    missing = _world("p4-l5-none")
    _attack_shaped(missing)
    assert missing.dns_zone.account.edge_token_ref == ""
    assert edge_protection_for(missing.dns_zone) is None
    none_row = run(missing, None)
    blob = f"{none_row.title}\n{none_row.body}\n{none_row.fix_action}".lower()
    assert "notify-only" in blob or "notify only" in blob
    none_payload = project_row_body(missing.project)["sites"][0]["attack_state"]
    assert none_payload["mode"] == "notify_only"
    assert none_payload["finding_id"] == none_row.pk


@override_settings(HUB_PUBLIC_URL="https://hub.example.test")
@pytest.mark.django_db
@pytest.mark.req("TOPO-R1-R5-FINDINGS")
def test_topology_r1_r5_findings():
    """Map Findings for r1–r5 with the C5 fingerprints. No graph library.

    Transcribes tests/test_topology.py::test_hub_colocated_with_public_site_is_critical,
    ::test_blast_radius_finding, ::test_missing_per_site_docker_network_finding,
    ::test_db_off_mesh_finding, ::test_hub_and_public_origin_same_lan_finding, and
    ::test_topology_does_not_import_a_graph_library.
    """
    from test_topology import (
        HUB_HOST,
        _copy_ok,
        _instance,
        _site,
        _target,
        _zone,
        test_topology_does_not_import_a_graph_library,
    )

    from core.models import BackupUnit, Finding, Project
    from monitor.topology import evaluate

    project = Project.objects.create(name="p4-topo", slug="p4-topo")

    r1_zone = _zone("home-lan", "p4-r1-lan")
    hub_box = _target(r1_zone, HUB_HOST)
    shop = _site(project, "r1shop", hub_box)
    _instance(shop, hub_box, 20000)
    evaluate()
    r1 = Finding.objects.get(fingerprint="topology-hub-isolation:hub")
    assert r1.severity == Finding.Severity.P1
    _copy_ok(r1)

    r2_zone = _zone("prod", "p4-r2-prod")
    shared = _target(r2_zone, "shared-p4.example")
    r2shop = _site(project, "r2shop", shared)
    r2api = _site(project, "r2api", shared)
    _instance(r2shop, shared, 20000)
    _instance(r2api, shared, 20001)
    evaluate()
    r2 = Finding.objects.get(fingerprint=f"topology-blast-radius:{shared.pk}")
    assert r2.severity == Finding.Severity.P2
    _copy_ok(r2)

    r3_zone = _zone("prod", "p4-r3-prod")
    web = _target(r3_zone, "web-p4.example")
    r3shop = _site(project, "r3shop", web)
    _instance(r3shop, web, 20000)
    evaluate()
    r3 = Finding.objects.get(fingerprint=f"topology-site-network:{r3shop.pk}")
    assert r3.severity == Finding.Severity.P2
    _copy_ok(r3)

    r4_zone = _zone("prod", "p4-r4-prod")
    public_box = _target(r4_zone, "origin-p4.example")
    mesh_box = _target(r4_zone, "db-p4.example")
    r4shop = _site(project, "r4shop", public_box)
    r4db = _site(project, "r4db", mesh_box, exposure="mesh_only")
    _instance(r4shop, public_box, 20000)
    _instance(r4db, mesh_box, 20000)
    BackupUnit.objects.create(site=r4shop, kind=BackupUnit.Kind.POSTGRES)
    BackupUnit.objects.create(site=r4db, kind=BackupUnit.Kind.POSTGRES)
    evaluate()
    r4 = Finding.objects.get(fingerprint=f"topology-db-mesh-only:{r4shop.pk}")
    assert r4.severity == Finding.Severity.P2
    _copy_ok(r4)
    assert not Finding.objects.filter(
        fingerprint=f"topology-db-mesh-only:{r4db.pk}",
    ).exists()

    home = _zone("home-lan", "p4-r5-home")
    cloud = _zone("cloud", "p4-r5-cloud")
    r5_hub = _target(home, HUB_HOST)
    lan_box = _target(home, "public-p4.example")
    cloud_box = _target(cloud, "cdn-p4.example")
    _site(project, "r5hub", r5_hub, exposure="mesh_only", domain=HUB_HOST)
    r5shop = _site(project, "r5shop", lan_box)
    r5cdn = _site(project, "r5cdn", cloud_box)
    _instance(r5shop, lan_box, 20000)
    _instance(r5cdn, cloud_box, 20000)
    evaluate()
    r5 = Finding.objects.get(fingerprint=f"topology-lan-segment:{home.pk}")
    assert r5.severity == Finding.Severity.P2
    _copy_ok(r5)
    assert not Finding.objects.filter(
        fingerprint=f"topology-lan-segment:{cloud.pk}",
    ).exists()

    test_topology_does_not_import_a_graph_library()


@pytest.mark.django_db
@pytest.mark.req("SEC-B7-SSH-QUARTERLY-ROTATE")
def test_ssh_rotate_dual_key_run_twice():
    """Quarterly rotate is dual-key overlap; second run has zero mutating calls.

    Transcribes tests/test_ssh_rotate.py::
    test_ssh_rotate_generate_append_probe_revoke and
    ::test_ssh_rotate_run_twice_zero_mutating_calls.
    """
    from test_ssh_rotate import (
        OPERATOR_LINE,
        _blob,
        _factory,
        _public_line,
        _world,
    )

    from provision.ssh_rotate import rotate_ssh
    from vault import service as vault_service
    from vault.models import Secret

    target, transport, old, _old_pem, old_pub = _world()
    old_blob = _blob(old_pub)
    old_pk = old.pk
    old_ref = target.ssh_key_ref
    result = rotate_ssh(target, transport, make_transport=_factory(transport))
    assert result["status"] == "rotated"
    target.refresh_from_db()
    assert target.ssh_key_ref != old_ref
    assert not Secret.objects.filter(pk=old_pk).exists()
    new = Secret.objects.get(
        kind=Secret.Kind.SSH_PRIVATE_KEY, owner_id=target.ssh_key_ref,
    )
    new_pem = vault_service.get(new, reason="p4-ssh-assert")
    new_blob = _blob(_public_line(new_pem))
    first_text = transport.put_snapshots[0][1]
    if isinstance(first_text, (bytes, bytearray)):
        first_text = first_text.decode()
    last_text = transport.put_snapshots[-1][1]
    if isinstance(last_text, (bytes, bytearray)):
        last_text = last_text.decode()
    assert old_blob in first_text and new_blob in first_text
    assert OPERATOR_LINE.strip() in first_text
    assert old_blob not in last_text
    assert new_blob in last_text
    assert all(kind != "run" for kind, _ in transport.calls)
    for _kind, payload in transport.calls:
        blob = " ".join(payload) if isinstance(payload, list) else str(payload)
        assert "ssh-keygen" not in blob
    first = list(transport.mutating_calls())
    assert first
    transport.calls.clear()
    rotate_ssh(target, transport, make_transport=_factory(transport))
    assert transport.mutating_calls() == []
    assert all(kind == "probe" for kind, _ in transport.calls)
    entry = settings.CELERY_BEAT_SCHEDULE["ssh-rotate-quarterly"]
    assert float(entry["schedule"]) == 90 * 86400


@pytest.mark.django_db
@pytest.mark.req("UX-E5-BACKUP-OPERATOR")
def test_backup_list_test_now_command_block_and_p1(
        client, django_user_model, tmp_path, monkeypatch):
    """Sites list hides key material; test-now seals with BACKUP_KEY not KEK;
    restore is a command block with no POST; failed dump files P1.

    Transcribes tests/test_backup_operator.py::
    test_backup_list_hides_key_material,
    ::test_test_backup_now_seals_with_backup_key_not_kek,
    ::test_restore_is_command_block_not_a_post,
    ::test_restore_route_is_require_recent_touch, and
    ::test_failed_dump_files_hub_db_or_backup_failure.
    """
    import stat

    from django_otp.plugins.otp_totp.models import TOTPDevice
    from test_backup_operator import (
        DUMP,
        FORBIDDEN_LIST_NEEDLES,
        KIND,
        SITES_JSX,
        _blob_text,
        _unit,
    )

    from core.models import AuditEvent, CheckRun, Finding
    from core.transport import FakeTransport
    from monitor.alert_rules import classify
    from provision import backup as backup_mod
    from provision.backup import persist_backup
    from vault import backup as vault_backup
    from vault import service
    from vault.models import Secret

    store = tmp_path / "backups"
    store.mkdir()
    monkeypatch.setattr(backup_mod, "BACKUP_STORE_DIR", store, raising=False)
    user = django_user_model.objects.create_user(
        username="op-bak", password="pw-1234567890",
    )
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)

    site, unit = _unit("p4-list")
    run = persist_backup(unit, plaintext=DUMP)
    sealed = (store / str(run.pk)).read_bytes()
    key_row = Secret.objects.get(
        kind=Secret.Kind.BACKUP_KEY, owner_type="site", owner_id=str(site.pk),
    )
    backup_key = service.get(key_row, reason="p4-list")
    listed = client.get(f"/api/v1/sites/{site.pk}/backups/")
    assert listed.status_code == 200, listed.content
    body = listed.json()
    blob = _blob_text(body)
    for needle in FORBIDDEN_LIST_NEEDLES:
        assert needle not in blob, needle
    assert backup_key.hex() not in blob
    assert sealed.hex() not in blob
    command = body["restore_command"]
    assert "/var/lib/deploy-hub/backups/" in command
    assert "POST" not in command
    jsx = SITES_JSX.read_text(encoding="utf-8")
    assert "<pre" in jsx and "restore_command" in jsx
    assert "Test backup now" in jsx

    assert classify(KIND) == "p1"
    fail_site, fail_unit = _unit("p4-fail")
    transport = FakeTransport(
        responses={"pg_dump": {"exit_code": 1, "stderr": "pg_dump failed"}},
    )
    with pytest.raises(RuntimeError):
        persist_backup(fail_unit, transport=transport)
    finding = Finding.objects.get(fingerprint=f"{KIND}:{fail_unit.pk}")
    assert finding.severity == Finding.Severity.P1
    assert AuditEvent.objects.filter(action="backup-failed").exists()

    now_site, now_unit = _unit("p4-now")
    monkeypatch.setattr(
        backup_mod, "_collect",
        lambda unit, plaintext=None, transport=None: DUMP,
    )
    now = client.post(
        f"/api/v1/sites/{now_site.pk}/backups/{now_unit.pk}/test/",
        content_type="application/json",
    )
    assert now.status_code == 201, now.content
    now_body = now.json()
    assert set(now_body) == {
        "schema_version", "unit_id", "site_id", "bytes", "digest", "stored_at",
    }
    now_run = CheckRun.objects.get(kind=CheckRun.Kind.BACKUP, results__unit_id=now_unit.pk)
    path = store / str(now_run.pk)
    assert path.is_file()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    sealed_now = path.read_bytes()
    assert DUMP not in sealed_now
    now_key = Secret.objects.get(
        kind=Secret.Kind.BACKUP_KEY, owner_type="site", owner_id=str(now_site.pk),
    )
    key_bytes = service.get(now_key, reason="p4-now")
    aad = Secret.build_aad(Secret.Kind.BACKUP_KEY, "site", str(now_site.pk))
    assert vault_backup.unseal(sealed_now, key_bytes, aad=aad) == DUMP

    missing = client.post(
        f"/api/v1/sites/{site.pk}/backups/{unit.pk}/restore/",
        content_type="application/json",
    )
    assert missing.status_code == 403


@pytest.mark.django_db
def test_alerts_topic_unauthorized(client):
    """`alerts` is unauthorized; findings stays the one attention stream.

    Transcribes tests/test_findings_api.py::test_alerts_topic_is_unauthorized
    and ::test_findings_topic_unchanged (D-045 / D-061).
    """
    from test_findings_api import _enrolled_client

    from realtime.authorize import ALLOWED_PREFIXES, authorize_topic

    user = _enrolled_client(client)
    assert "alerts" not in ALLOWED_PREFIXES
    assert authorize_topic(user, "alerts") is False
    assert client.get("/api/topics/alerts/snapshot/").status_code == 403
    assert "findings" in ALLOWED_PREFIXES
    assert authorize_topic(user, "findings") is True


@pytest.mark.req("SEC-B4-REDIS-CROWN-JEWEL")
def test_compose_parse_redis_unpublished_requirepass_json():
    """Compose parse: Redis unpublished + requirepass; Celery JSON serializers.

    Transcribes tests/test_redis_crown_jewel.py::
    test_compose_redis_unpublished_and_requirepass and
    ::test_celery_serializers_are_json. C9: not an external port-scan.
    """
    from test_redis_crown_jewel import (
        test_celery_serializers_are_json,
        test_compose_redis_unpublished_and_requirepass,
    )

    test_compose_redis_unpublished_and_requirepass()
    test_celery_serializers_are_json()


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_exhaust_gate_greps_captured_output():
    """Exhaust gate greps captured pytest stdout/stderr/log and Celery kwargs.

    Transcribes tests/test_secrets_in_exhaust.py::
    test_exhaust_gate_flags_plaintext_in_captured_output and
    ::test_exhaust_gate_flags_plaintext_in_celery_kwargs. C9: not log-scrub.
    """
    from test_secrets_in_exhaust import (
        test_exhaust_gate_flags_plaintext_in_captured_output,
        test_exhaust_gate_flags_plaintext_in_celery_kwargs,
    )

    test_exhaust_gate_flags_plaintext_in_captured_output()
    test_exhaust_gate_flags_plaintext_in_celery_kwargs()


@pytest.mark.django_db
@pytest.mark.req("SEC-B8-TAILSCALE-DEVICE-POLL")
def test_tailscale_skip_unless_or_fake_unknown_device():
    """Absent vault ref is SKIPPED + dated waiver; FakeTailscale files unknown-device.

    Transcribes tests/test_tailscale_devices.py::
    test_absent_ref_skips_and_does_not_green_a_live_tier and
    ::test_unknown_device_files_finding. Do not invent a live token env.
    """
    from django.test import override_settings
    from test_tailscale_devices import (
        KIND,
        REF,
        TOKEN,
        _findings,
        _plant_token,
    )

    from core.models import CheckRun, Finding
    from providers.fakes import FakeTailscale
    from providers.tailscale import audit_devices

    with override_settings(HUB_TAILSCALE_API_TOKEN_REF=""):
        skipped = audit_devices()
        assert skipped.kind == CheckRun.Kind.TAILSCALE_DEVICES
        assert skipped.status == CheckRun.Status.SKIPPED
        assert skipped.status != CheckRun.Status.SUCCEEDED

    lines = _waiver_lines(TAILSCALE_ID)
    assert lines, f"{TAILSCALE_ID} must stay skip-unless-configured"
    assert "skip-unless-configured" in lines[0]

    _plant_token(REF, TOKEN)
    fake = FakeTailscale(devices=[{
        "id": "nStranger",
        "hostname": "laptop-stranger",
        "name": "laptop-stranger.tailnet.ts.net",
        "addresses": ["100.64.0.99"],
    }])
    with override_settings(HUB_TAILSCALE_API_TOKEN_REF=REF):
        run = audit_devices(client=fake)
    assert run.status == CheckRun.Status.SUCCEEDED
    finding = _findings().get()
    assert finding.severity == Finding.Severity.P2
    assert finding.fingerprint == f"{KIND}:nStranger"
    assert TOKEN not in finding.body
    assert "HUB_TEST_TAILSCALE" not in (
        REPO / "hub" / "settings" / "base.py"
    ).read_text(encoding="utf-8")


@pytest.mark.django_db
@pytest.mark.req("SEC-A3-KMS-KEK-ADAPTER")
def test_kms_kek_moto_refuse_cache_keyfile():
    """KmsKEK wrap/unwrap under moto; unconfigured kms refuses; DEK cache
    survives a FakeKms blip; keyfile still boots tests. No live AWS.

    Transcribes tests/test_kms_kek.py::test_kms_kek_wrap_unwrap_with_moto,
    ::test_kms_backend_refuses_unless_configured,
    ::test_dek_cache_survives_kms_blip,
    ::test_keyfile_backend_still_default_in_tests, and
    ::test_vault_and_kms_tests_do_not_import_boto3.
    """
    import os

    from django.test import override_settings

    from providers.fakes import FakeKms
    from providers.kms import KmsClient, create_test_key, mock_aws_kms
    from vault import service
    from vault.kek import KEKError, KmsKEK, LocalKeyfileKEK, get_backend
    from vault.models import Secret

    dek = os.urandom(32)
    with mock_aws_kms():
        kek = KmsKEK(KmsClient(create_test_key()))
        wrapped = kek.wrap(dek)
        assert wrapped != dek
        assert kek.unwrap(wrapped) == dek
        assert kek.kek_id.startswith("kms:")

    with override_settings(VAULT_KEK_BACKEND="kms"):
        with pytest.raises(KEKError, match="VAULT_KMS_KEY_ID"):
            get_backend()

    assert settings.VAULT_KEK_BACKEND != "kms"
    assert getattr(settings, "VAULT_KMS_KEY_ID", "") == ""
    assert type(get_backend()).__name__ != "KmsKEK"
    doc = LocalKeyfileKEK.__doc__ or ""
    assert "Hub disk" in doc

    reset = getattr(service, "reset_dek_cache", None)
    if reset is not None:
        reset()
    port = FakeKms(key_id="alias/hub-test")
    cache_kek = KmsKEK(port)
    from unittest.mock import patch
    with patch.object(service, "get_backend", lambda: cache_kek):
        secret = service.put(
            kind=Secret.Kind.ENV_BUNDLE, owner_type="site",
            owner_id="p4-kms", plaintext=b"VAULT-TEST-PLAINTEXT-MARKER-do-not-log",
        )
        if reset is not None:
            reset()
        assert service.get(secret) == b"VAULT-TEST-PLAINTEXT-MARKER-do-not-log"
        assert port.decrypt_calls == 1
        port.down = True
        assert service.get(secret) == b"VAULT-TEST-PLAINTEXT-MARKER-do-not-log"
        assert port.decrypt_calls == 1

    from test_kms_kek import test_vault_and_kms_tests_do_not_import_boto3
    test_vault_and_kms_tests_do_not_import_boto3()


@pytest.mark.django_db
def test_audit_hash_chain_local_never_blocks_on_s3(monkeypatch):
    """audit() writes prev_hash locally and never blocks on S3.

    Transcribes tests/test_audit.py::test_audit_genesis_empty_prev,
    ::test_audit_event_prev_hash_chains, and ::test_audit_does_not_call_s3.
    Does not mark SEC-B3-AUDIT-HASH-CHAIN (full text includes live S3 P2, SLIP).
    """
    import sys
    from hashlib import sha256

    from test_audit import _canonical_row

    from core.audit import audit
    from core.models import AuditEvent

    AuditEvent.objects.all().delete()
    first = audit("p4-one", source="system", note="a")
    second = audit("p4-two", source="system", note="b")
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.prev_hash == ""
    expected = sha256(
        (first.prev_hash + _canonical_row(first)).encode("utf-8")
    ).hexdigest()
    assert second.prev_hash == expected
    assert len(second.prev_hash) == 64

    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError(f"audit() blocked on S3 via {name}")

        def __call__(self, *args, **kwargs):
            raise AssertionError("audit() blocked on S3")

    monkeypatch.setitem(sys.modules, "boto3", Forbidden())
    event = audit("p4-local-chain", source="system")
    event.refresh_from_db()
    assert event.shipped_at is None


def test_rel_p2_24h_still_not_claimed():
    """REL-P2 24 h stays waived. This record is T1 fakes, not a Hub-down.

    Transcribes tests/test_drills.py::test_hub_down_still_refuses_to_claim_24h
    (D-042) and pins the Phase 4 demo as the honest outstanding line.
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


def test_hub_central_dns01_stays_first_slip():
    """Hub-central DNS-01 stays phase 4 and is marked. Both TLS-B2 and
    full-text SEC-B2 waivers are retired. LE-staging stays waived.

    Transcribes tests/test_certs_phase_pin.py and
    tests/test_conformance_gate.py::test_tls_b2_hub_dns01_stays_phase_4.
    """
    import check
    from test_certs_phase_pin import _unproxied_class_docstring, _unproxied_fix_action

    reg = _registry()
    assert reg[DNS01_ID]["phase"] == 4
    markers = check.collect_markers(REPO)
    assert DNS01_ID in markers
    assert FULL_TEXT_SEC_B2 in markers

    assert not _waiver_lines(DNS01_ID), (
        f"{DNS01_ID} waiver retires now that Hub-central DNS-01 is marked"
    )
    assert not _waiver_lines(FULL_TEXT_SEC_B2), (
        f"{FULL_TEXT_SEC_B2} waiver retires now that both clauses hold"
    )
    waivers = _waivers()
    assert any("RETIRED" in line and DNS01_ID in line for line in waivers.splitlines())
    assert any(
        "RETIRED" in line and FULL_TEXT_SEC_B2 in line for line in waivers.splitlines()
    )

    le = _waiver_lines(LE_STAGING)
    assert le, f"{LE_STAGING} must stay — leftover Task 8 owns that line"
    assert "no-test-zone-credentials" in le[0]

    doc = _unproxied_class_docstring()
    assert "phase 4" in doc.lower()
    fix = _unproxied_fix_action()
    assert "phase 4" in fix.lower()

    demo_req = reg["P4-SECURITY-DEMO"]
    assert demo_req["verify"] == "demo"
    assert "conformance/demos/phase-4.md" in demo_req.get("demo", [])

    record = _assert_honest_t1_demo()
    assert DNS01_ID in record
    assert "first slip" not in record.lower()


def test_conformance_4_excludes_t2_t3():
    """conformance-4 is --phase 4 minus t2/t3. conformance-3 stays all-tiers 3.

    Transcribes tests/test_makefile_nightly.py::
    test_conformance_4_is_phase_4_minus_live_tiers and
    ::test_conformance_3_still_all_tiers_phase_3, and
    tests/test_d023_actions_not_required.py::
    test_phase_gate_is_local_make_conformance_3_not_a_gha_check.
    Do not add t4.
    """
    import check
    import gates

    recipe = gates.recipe(REPO, "conformance-4")
    assert recipe, "Makefile has no `conformance-4` recipe"
    assert "--phase 4" in recipe
    assert "--exclude-tier t2" in recipe
    assert "--exclude-tier t3" in recipe
    recipe3 = gates.recipe(REPO, "conformance-3")
    assert "--phase 3" in recipe3
    assert "--exclude-tier" not in recipe3
    assert check.VALID_TIERS == {"t1", "t2", "t3"}
    assert "t4" not in check.VALID_TIERS
    record = _assert_honest_t1_demo()
    assert "conformance-3" in record.lower()
    assert "all-tiers" in record.lower() or "all tiers" in record.lower()
