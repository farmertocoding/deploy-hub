"""WebAuthn primary + T1 hardware touch + idle timeout (Phase 4 Task 2).

SEC-A2-WEBAUTHN-PHASE4 / SEC-F5-T1-HARDWARE-TOUCH / D-062 / C2 / C9.

WebAuthn assertion on POST /api/auth/webauthn/touch/ is the only writer of
session["hardware_touch_at"]. TOTP and recovery authenticate login, never T1.
T3 rollback never takes RequireRecentTouch. Two passkeys before T1 is available.
"""
from __future__ import annotations

import inspect
import json
import os
import time

import pytest
from django.conf import settings
from django.contrib.auth.models import User

pytestmark = [pytest.mark.django_db]


def _current_code(device):
    from django_otp.oath import TOTP

    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    return format(totp.token(), "06d")


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


def _make_target(host="box-1.example.com"):
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(name=f"lan-{host}", slug=f"lan-{host.replace('.', '-')}")
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host=host,
        ssh_user="deploy",
        ssh_key_ref="vault-t1",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


def _login_password(client, user, password="a-long-dev-password"):
    client.force_login(user)
    session = client.session
    session["_hub_last_activity"] = time.time()
    session.save()


def _patch_webauthn_helper(monkeypatch):
    """Protocol tests never drive a real authenticator (T4 Playwright is SLIP)."""
    from django_otp_webauthn.models import WebAuthnCredential

    class FakeHelper:
        def __init__(self, request):
            self.request = request

        def register_begin(self, user):
            return (
                {"challenge": "Y2hhbGxlbmdl", "rp": {"id": "localhost", "name": "Deploy Hub"}},
                {"challenge": "Y2hhbGxlbmdl"},
            )

        def register_complete(self, user, state, data):
            return _make_cred(user, name=(data or {}).get("name") or "passkey")

        def authenticate_begin(self, user=None, require_user_verification=True):
            return (
                {"challenge": "YXV0aGNoYWxs", "rpId": "localhost"},
                {"challenge": "YXV0aGNoYWxs"},
            )

        def authenticate_complete(self, user, state, data):
            qs = WebAuthnCredential.objects.filter(confirmed=True)
            if user is not None:
                qs = qs.filter(user=user)
            device = qs.first()
            if device is None:
                raise AssertionError("FakeHelper.authenticate_complete has no credential")
            return device

    monkeypatch.setattr(
        WebAuthnCredential,
        "get_webauthn_helper",
        classmethod(lambda cls, request: FakeHelper(request)),
    )


def _delete_url(target):
    return f"/api/v1/targets/{target.pk}/delete/"


@pytest.mark.req("SEC-A2-WEBAUTHN-PHASE4")
def test_webauthn_enroll_and_confirm(client, monkeypatch):
    """Begin + complete under /api/auth/webauthn/ stores a confirmed credential
    and issues recovery codes once on the first passkey.
    """
    _patch_webauthn_helper(monkeypatch)
    user = User.objects.create_user("joseph", password="a-long-dev-password")
    _login_password(client, user)

    begin = client.post("/api/auth/webauthn/registration/begin/")
    assert begin.status_code == 200, begin.content
    body = begin.json()
    assert "challenge" in body

    complete = client.post(
        "/api/auth/webauthn/registration/complete/",
        data=json.dumps({"name": "yubikey", "id": "cred-1"}),
        content_type="application/json",
    )
    assert complete.status_code == 200, complete.content
    payload = complete.json()
    assert payload.get("recovery_codes")
    assert len(payload["recovery_codes"]) == 8

    from django_otp_webauthn.models import WebAuthnCredential

    from core.models import RecoveryCode

    assert WebAuthnCredential.objects.filter(user=user, confirmed=True).count() == 1
    assert RecoveryCode.objects.filter(user=user).count() == 8
    assert "hardware_touch_at" not in client.session


@pytest.mark.req("SEC-A2-WEBAUTHN-PHASE4")
def test_login_accepts_webauthn_or_totp_or_recovery(client, monkeypatch):
    """Login second factor is WebAuthn assertion OR TOTP OR a recovery code."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import RecoveryCode
    from core.otp import hash_recovery_code

    _patch_webauthn_helper(monkeypatch)
    password = "a-long-dev-password"
    user = User.objects.create_user("joseph", password=password)
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    RecoveryCode.objects.create(user=user, code_hash=hash_recovery_code("rescue12345aaaa"))
    _make_cred(user, name="yubikey")

    totp_login = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph", "password": password,
            "otp_code": _current_code(device),
        }),
        content_type="application/json",
    )
    assert totp_login.status_code == 200, totp_login.content
    client.post("/api/auth/logout/")

    recovery_login = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph", "password": password,
            "otp_code": "rescue12345aaaa",
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


@pytest.mark.req("SEC-A2-WEBAUTHN-PHASE4")
def test_second_passkey_enrolls(client, monkeypatch):
    """Onboarding's phone passkey is a second confirmed WebAuthn credential."""
    _patch_webauthn_helper(monkeypatch)
    user = User.objects.create_user("joseph", password="a-long-dev-password")
    _login_password(client, user)

    for name in ("yubikey", "phone"):
        assert client.post("/api/auth/webauthn/registration/begin/").status_code == 200
        complete = client.post(
            "/api/auth/webauthn/registration/complete/",
            data=json.dumps({"name": name, "id": name}),
            content_type="application/json",
        )
        assert complete.status_code == 200, complete.content

    from django_otp_webauthn.models import WebAuthnCredential

    assert WebAuthnCredential.objects.filter(user=user, confirmed=True).count() == 2


@pytest.mark.req("SEC-F5-T1-HARDWARE-TOUCH")
@pytest.mark.req("UX-F5-ACTION-TIERS")
def test_t1_target_delete_refuses_without_recent_touch(client, monkeypatch):
    """target.delete is T1: two passkeys are not enough without a recent touch."""
    _patch_webauthn_helper(monkeypatch)
    user = User.objects.create_user("joseph", password="a-long-dev-password")
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")
    target = _make_target()
    _login_password(client, user)

    response = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert response.status_code == 403, response.content
    assert "touch" in response.json()["detail"].lower()
    from core.models import Target

    assert Target.objects.filter(pk=target.pk).exists()
    assert "hardware_touch_at" not in client.session


@pytest.mark.req("SEC-F5-T1-HARDWARE-TOUCH")
def test_t1_requires_type_the_name(client, monkeypatch):
    """Hardware touch without typing the target host still refuses."""
    _patch_webauthn_helper(monkeypatch)
    user = User.objects.create_user("joseph", password="a-long-dev-password")
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")
    target = _make_target("box-1.example.com")
    _login_password(client, user)

    assert client.post("/api/auth/webauthn/authentication/begin/").status_code == 200
    touch = client.post(
        "/api/auth/webauthn/touch/",
        data=json.dumps({"id": "cred-1", "response": {}}),
        content_type="application/json",
    )
    assert touch.status_code == 200, touch.content
    assert client.session.get("hardware_touch_at")

    wrong = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": "wrong-host"}),
        content_type="application/json",
    )
    assert wrong.status_code == 400, wrong.content
    from core.models import Target

    assert Target.objects.filter(pk=target.pk).exists()

    ok = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": "box-1.example.com"}),
        content_type="application/json",
    )
    assert ok.status_code == 204, ok.content
    assert not Target.objects.filter(pk=target.pk).exists()


@pytest.mark.req("SEC-F5-T1-HARDWARE-TOUCH")
def test_t1_totp_does_not_write_hardware_touch_at(client):
    """A TOTP login of a two-passkey operator still cannot satisfy T1."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user("joseph", password="a-long-dev-password")
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")
    target = _make_target()

    login = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph",
            "password": "a-long-dev-password",
            "otp_code": _current_code(device),
        }),
        content_type="application/json",
    )
    assert login.status_code == 200, login.content
    assert "hardware_touch_at" not in client.session

    response = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert response.status_code == 403
    assert "hardware_touch_at" not in client.session


@pytest.mark.req("SEC-F5-T1-HARDWARE-TOUCH")
def test_t1_refused_until_two_webauthn_credentials(client, monkeypatch):
    """TOTP-only, and a single passkey, keep today's T1 refuse — add a passkey."""
    _patch_webauthn_helper(monkeypatch)
    from django_otp.plugins.otp_totp.models import TOTPDevice

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
    assert client.post("/api/auth/webauthn/authentication/begin/").status_code == 200
    assert client.post(
        "/api/auth/webauthn/touch/",
        data=json.dumps({"id": "cred-1"}),
        content_type="application/json",
    ).status_code == 200

    one_key = client.post(
        _delete_url(target),
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert one_key.status_code == 403
    assert "passkey" in one_key.json()["detail"].lower()
    from core.models import Target

    assert Target.objects.filter(pk=target.pk).exists()


@pytest.mark.req("UX-F5-T2-T3-FRICTION")
def test_t3_rollback_never_uses_require_recent_touch():
    """T3 recovery HTTP must not import or attach RequireRecentTouch (C2)."""
    from deploys.views import SiteRollbackView

    classes = SiteRollbackView.permission_classes
    names = [getattr(cls, "__name__", str(cls)) for cls in classes]
    assert "RequireRecentTouch" not in names
    source = inspect.getsource(SiteRollbackView)
    assert "RequireRecentTouch" not in source
    assert "hardware_touch" not in source


@pytest.mark.req("SEC-A2-WEBAUTHN-PHASE4")
def test_idle_timeout_expires_session(client):
    """IdleTimeoutMiddleware enforces existing HUB_SESSION_IDLE_TIMEOUT."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

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


@pytest.mark.req("SEC-F5-T1-HARDWARE-TOUCH")
def test_login_webauthn_and_recovery_do_not_write_hardware_touch_at(client, monkeypatch):
    """Login assertions and recovery codes authenticate, never T1 (Security F1)."""
    from core.models import RecoveryCode
    from core.otp import hash_recovery_code

    _patch_webauthn_helper(monkeypatch)
    password = "a-long-dev-password"
    user = User.objects.create_user("joseph", password=password)
    RecoveryCode.objects.create(user=user, code_hash=hash_recovery_code("rescue12345aaaa"))
    _make_cred(user, "yubikey")
    _make_cred(user, "phone")

    assert client.post(
        "/api/auth/webauthn/login/begin/",
        data=json.dumps({"username": "joseph"}),
        content_type="application/json",
    ).status_code == 200
    webauthn = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph", "password": password,
            "webauthn": {"id": "cred-1", "response": {}},
        }),
        content_type="application/json",
    )
    assert webauthn.status_code == 200, webauthn.content
    assert "hardware_touch_at" not in client.session
    client.post("/api/auth/logout/")

    recovery = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "joseph", "password": password,
            "otp_code": "rescue12345aaaa",
        }),
        content_type="application/json",
    )
    assert recovery.status_code == 200, recovery.content
    assert "hardware_touch_at" not in client.session

    root = settings.BASE_DIR
    login_and_totp = "\n".join(
        (root / "core" / name).read_text(encoding="utf-8")
        for name in ("views.py", "otp.py")
        if (root / "core" / name).exists()
    )
    assert 'session["hardware_touch_at"] =' not in login_and_totp
    assert "session['hardware_touch_at'] =" not in login_and_totp
    touch_mod = __import__("core.webauthn", fromlist=["TouchView"])
    assert 'session["hardware_touch_at"]' in inspect.getsource(touch_mod.TouchView)


# Paths that exist TODAY. T1 ids not listed must 404 at the obvious slug so a later
# unguarded export/rotate view cannot land silently. Do not invent
# key.export / kek.rotate HTTP here (review ruling). ssh.rotate is Task 6.
T1_HTTP = {
    "target.delete": "/api/v1/targets/{pk}/delete/",
    "ssh.rotate": "/api/v1/targets/{pk}/ssh-rotate/",
    "instance.create": "/api/v1/instance/create/",
    "instance.terminate": "/api/v1/targets/{pk}/terminate/",
    "partner.create": "/api/v1/partners/",
    "partner.suspend": "/api/v1/partners/{pk}/suspend/",
    "partner.api_kill_switch": "/api/v1/partner-api/kill-switch/",
    "site.overflow_deploy": "/api/v1/sites/{pk}/overflow-deploy/",
    "site.overflow_join": "/api/v1/sites/{pk}/overflow-join/",
}


@pytest.mark.req("SEC-F5-T1-HARDWARE-TOUCH")
def test_t1_action_ids_are_require_recent_touch_or_404(client):
    """Every T1 ACTION_TIERS id is RequireRecentTouch on its view, or 404."""
    from django.urls import resolve

    from core.actions import ACTION_TIERS
    from core.permissions import RequireRecentTouch

    t1_ids = [row["id"] for row in ACTION_TIERS if row["tier"] == "T1"]
    assert "target.delete" in t1_ids
    assert "key.export" in t1_ids
    assert "kek.rotate" in t1_ids
    extra = set(T1_HTTP) - set(t1_ids)
    assert not extra, f"T1_HTTP names unknown ids: {extra}"

    for action_id in t1_ids:
        template = T1_HTTP.get(action_id)
        if template is None:
            slug = action_id.replace(".", "/")
            for path in (f"/api/v1/{slug}/", f"/api/{slug}/"):
                response = client.post(path, content_type="application/json")
                assert response.status_code == 404, (
                    f"{action_id} must 404 at {path} until a view with "
                    f"RequireRecentTouch is listed in T1_HTTP"
                )
            continue
        match = resolve(template.format(pk=1))
        view_cls = getattr(match.func, "cls", None)
        assert view_cls is not None, f"{action_id} did not resolve to a CBV"
        assert RequireRecentTouch in view_cls.permission_classes, action_id


@pytest.mark.req("P0-VALIDATION")
def test_target_delete_confirm_name_goes_through_a_serializer():
    """Type-the-name is the T1 confirm; it belongs on a DRF serializer (§4.5)."""
    from core.views import TargetDeleteView

    source = inspect.getsource(TargetDeleteView)
    assert "TargetDeleteSerializer" in source
    assert "request.data.get" not in source


@pytest.mark.req("P0-VALIDATION")
def test_login_begin_username_goes_through_a_serializer():
    """Login-begin username is an API field; it belongs on a DRF serializer (§4.5)."""
    from core.webauthn import LoginBeginView

    source = inspect.getsource(LoginBeginView)
    assert "WebAuthnLoginBeginSerializer" in source
    assert "request.data.get" not in source


def test_generated_client_mirrors_webauthn_me_and_target_delete():
    """review-round check-generated: Login.webauthn, Me counts, target delete."""
    import pathlib

    api = pathlib.Path(__file__).resolve().parent.parent / "frontend" / "src" / "api"
    spec = (api / "openapi.yaml").read_text(encoding="utf-8")
    assert "webauthn:" in spec
    assert "webauthn_count" in spec
    assert "t1_available" in spec
    assert "totp_enrolled" in spec
    assert "confirm_name" in spec
    assert "/api/v1/targets/" in spec
    assert "delete" in spec
    zod = (api / "zod.ts").read_text(encoding="utf-8")
    assert "webauthn" in zod
    assert "webauthn_count" in zod
    assert "confirm_name" in zod
