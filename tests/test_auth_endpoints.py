"""Logout, /me, the mandatory-2FA gate, security-event audits, and login CSRF —
round-1 findings: these behaviors existed with zero direct tests."""
import json

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def _own_default(user):
    from core.models import WorkspaceMembership, default_workspace

    WorkspaceMembership.objects.get_or_create(
        workspace=default_workspace(), user=user, defaults={"role": "owner"},
    )
    return user


def _login(client, username="joseph", password="a-long-dev-password"):
    from django.contrib.auth.models import User

    User.objects.get_or_create(username=username) or None
    u = User.objects.get(username=username)
    u.set_password(password)
    u.save()
    assert client.login(username=username, password=password)
    return u


@pytest.mark.req("P0-LOGIN")
def test_logout_invalidates_session(client):
    _login(client)
    r = client.post("/api/auth/logout/")
    assert r.status_code == 204
    # The session no longer authenticates subsequent requests.
    r = client.post("/api/demo-jobs/", data=json.dumps({"name": "demo"}),
                    content_type="application/json")
    assert r.status_code == 403


@pytest.mark.req("P0-LOGIN")
def test_me_hydrates_session_and_bootstraps_anonymous(client):
    # Anonymous: 200 bootstrap (NOT 403) + CSRF cookie planted for the login POST.
    r = client.get("/api/auth/me/")
    assert r.status_code == 200
    assert r.json() == {"authenticated": False}
    assert "csrftoken" in r.cookies

    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    u = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=u, name="phone", confirmed=True)
    client.login(username="joseph", password="a-long-dev-password")
    r = client.get("/api/auth/me/")
    body = r.json()
    assert body["authenticated"] is True
    assert body["username"] == "joseph"
    assert body["otp_enrolled"] is True


@pytest.mark.req("P0-LOGIN")
@pytest.mark.req("SEC-A1-SESSION-AUTH")
def test_login_post_is_csrf_protected():
    """Round-1 finding: login-CSRF — a cross-site page must not be able to log the
    victim into an attacker-chosen account. The login POST itself requires the
    CSRF token planted by the /me bootstrap."""
    from django.contrib.auth.models import User

    User.objects.create_user("joseph", password="a-long-dev-password")
    client = Client(enforce_csrf_checks=True)

    payload = json.dumps({"username": "joseph", "password": "a-long-dev-password"})
    r = client.post("/api/auth/login/", data=payload, content_type="application/json")
    assert r.status_code == 403  # no token → rejected

    token = client.get("/api/auth/me/").cookies["csrftoken"].value
    r = client.post("/api/auth/login/", data=payload, content_type="application/json",
                    HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 200


@pytest.mark.req("P0-2FA-TOTP")
@pytest.mark.req("SEC-610-MANDATORY-2FA")
def test_admin_password_login_of_enrolled_staff_cannot_mutate_api():
    """H2: Django admin password login must not skip Hub 2FA on mutating /api/.

    What would make this fail: EnrollmentRequiredMiddleware only checking that
    a confirmed device *exists*, not that this session is OTP-verified
    (`user.is_verified()`), so POST /admin/login/ with a staff password yields
    a cookie that can POST /api/demo-jobs/.
    """
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    User.objects.create_superuser(
        "staff", email="staff@example.test", password="a-long-dev-password",
    )
    user = User.objects.get(username="staff")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)

    admin_client = Client()
    admin_client.post(
        "/admin/login/",
        {"username": "staff", "password": "a-long-dev-password"},
    )
    r = admin_client.post(
        "/api/demo-jobs/",
        data=json.dumps({"name": "demo"}),
        content_type="application/json",
    )
    assert r.status_code == 403, r.content
    me = admin_client.get("/api/auth/me/").json()
    if me.get("authenticated"):
        detail = r.json().get("detail", "").lower()
        assert "verification" in detail or "two-factor" in detail


@pytest.mark.req("P0-2FA-TOTP")
@pytest.mark.req("SEC-610-MANDATORY-2FA")
def test_enrolled_unverified_session_cannot_mutate_api(client):
    """H2: a password-only session of an already-enrolled user is not Hub 2FA.

    What would make this fail: the gate treating `devices_for_user(...,
    confirmed=True)` as sufficient, so `force_login` without `otp_device_id`
    can POST mutating APIs.
    """
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user("enrolled", password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    session = client.session
    session.pop("otp_device_id", None)
    session.save()

    r = client.post(
        "/api/demo-jobs/",
        data=json.dumps({"name": "demo"}),
        content_type="application/json",
    )
    assert r.status_code == 403, r.content
    assert client.get("/api/auth/me/").status_code == 200


@pytest.mark.req("P0-2FA-TOTP")
@pytest.mark.req("SEC-610-MANDATORY-2FA")
def test_enrolled_unverified_session_cannot_register_another_passkey(client):
    """Stolen pre-2FA cookie must not add the attacker's WebAuthn credential."""
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user("enroll-thief", password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    session = client.session
    session.pop("otp_device_id", None)
    session.save()

    r = client.post(
        "/api/auth/webauthn/registration/begin/",
        data=json.dumps({}),
        content_type="application/json",
    )
    assert r.status_code == 403, r.content
    assert client.get("/api/auth/me/").status_code == 200


@pytest.mark.req("P0-2FA-TOTP")
@pytest.mark.req("SEC-610-MANDATORY-2FA")
def test_hub_login_with_totp_verifies_the_session_for_mutating_api(client):
    """Hub /api/auth/login/ with a live TOTP must stamp OTP so later POSTs work.

    What would make this fail: LoginView calling django.contrib.auth.login
    without django_otp.login, leaving is_verified() false after a good OTP.
    """
    import time

    from django.contrib.auth.models import User
    from django_otp.oath import TOTP
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user("otp-ok", password="a-long-dev-password")
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    code = format(totp.token(), "06d")
    r = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "otp-ok",
            "password": "a-long-dev-password",
            "otp_code": code,
        }),
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    r = client.post(
        "/api/demo-jobs/",
        data=json.dumps({"name": "demo"}),
        content_type="application/json",
    )
    assert r.status_code == 201, r.content


@pytest.mark.req("P0-2FA-TOTP")
@pytest.mark.req("SEC-610-MANDATORY-2FA")
def test_unenrolled_session_is_gated_to_enrollment(client):
    """Round-1 security finding: a password-only session of a not-yet-enrolled user
    had full API access. The middleware gate restricts it to /api/auth/*."""
    _login(client)  # no confirmed device

    r = client.post("/api/demo-jobs/", data=json.dumps({"name": "demo"}),
                    content_type="application/json")
    assert r.status_code == 403
    assert "enrollment required" in r.json()["detail"].lower()
    assert client.get("/api/topics/demo.x.log/snapshot/").status_code == 403

    # Enrollment endpoints stay reachable — the gate must not lock the user out
    # of the only path that clears it.
    assert client.post("/api/auth/totp/enroll/").status_code == 201
    assert client.get("/api/auth/me/").status_code == 200

    # A confirmed device without this-session OTP is still gated (H2).
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.get(username="joseph")
    TOTPDevice.objects.filter(user=user).delete()
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    r = client.post("/api/demo-jobs/", data=json.dumps({"name": "demo"}),
                    content_type="application/json")
    assert r.status_code == 403
    assert "verification" in r.json()["detail"].lower()


@pytest.mark.req("P0-AUDIT")
def test_security_events_are_audited(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import AuditEvent

    u = User.objects.create_user("joseph", password="a-long-dev-password")

    # Failed password login.
    client.post("/api/auth/login/",
                data=json.dumps({"username": "joseph", "password": "wrong"}),
                content_type="application/json")
    assert AuditEvent.objects.filter(action="login_failed", severity="security").exists()

    # Failed OTP.
    TOTPDevice.objects.create(user=u, name="phone", confirmed=True)
    client.post("/api/auth/login/",
                data=json.dumps({"username": "joseph", "password": "a-long-dev-password",
                                 "otp_code": "000000"}),
                content_type="application/json")
    assert AuditEvent.objects.filter(action="otp_failed", severity="security").exists()

    # Logout audited.
    client.login(username="joseph", password="a-long-dev-password")
    client.post("/api/auth/logout/")
    assert AuditEvent.objects.filter(action="logout").exists()


# ── SEC-A1-SESSION-AUTH: the clauses the login-CSRF test never touched ──────────
#
# R4-11 WI-4: the sole SEC-A1 marker was on test_login_post_is_csrf_protected, which
# proves the "CSRF header" clause only. Setting SESSION_COOKIE_HTTPONLY = False and
# SESSION_COOKIE_SAMESITE = "None" in hub/settings/base.py left it green, and left the
# whole auth + ws suite green. The requirement also claims HttpOnly/Secure/SameSite=Lax,
# "not JWT", and "WebSocket rides the same session".

@pytest.mark.req("SEC-A1-SESSION-AUTH")
def test_issue_r4_11_session_cookie_carries_the_hardening_attributes():
    """HttpOnly stops document.cookie theft; SameSite=Lax is what makes the CSRF
    token a second factor rather than the only one. Neither was pinned."""
    from django.conf import settings

    assert settings.SESSION_COOKIE_HTTPONLY is True
    assert settings.SESSION_COOKIE_SAMESITE == "Lax"
    assert settings.CSRF_COOKIE_SAMESITE == "Lax"


@pytest.mark.req("SEC-A1-SESSION-AUTH")
def test_issue_r4_11_prod_settings_mark_the_session_cookie_secure(monkeypatch):
    """`Secure` is a prod-only attribute (dev runs on http), so it has to be read
    off hub.settings.prod — nothing asserted it there."""
    import importlib

    monkeypatch.setenv("HUB_SECRET_KEY", "test-only-key-for-settings-import")
    monkeypatch.setenv("HUB_VAULT_KEK_BACKEND", "local")
    monkeypatch.setenv("HUB_TASK_ENVELOPE_SECRET", "e" * 50)
    monkeypatch.setenv("HUB_AUDIT_S3_BUCKET", "hub-audit-test")
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://hub.example.test")
    monkeypatch.setenv("HUB_PAGER_BACKEND", "ntfy")
    prod = importlib.import_module("hub.settings.prod")
    importlib.reload(prod)

    assert prod.SESSION_COOKIE_SECURE is True
    assert prod.CSRF_COOKIE_SECURE is True
    assert prod.SESSION_COOKIE_HTTPONLY is True     # inherited from base, not lost
    assert prod.SESSION_COOKIE_SAMESITE == "Lax"


@pytest.mark.req("SEC-A1-SESSION-AUTH")
def test_issue_r4_11_hub_auth_is_session_based_and_not_jwt():
    """"not JWT" is half the requirement's sentence and had no assertion at all.
    A JWT authentication class added to DRF would move auth off the session — and
    off the CSRF + HttpOnly protections the rest of this requirement relies on."""
    from django.conf import settings

    auth_classes = settings.REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]
    assert auth_classes == ["rest_framework.authentication.SessionAuthentication"]

    installed = " ".join(settings.INSTALLED_APPS + settings.MIDDLEWARE
                         + list(auth_classes)).lower()
    for token in ("jwt", "simplejwt", "knox", "oauth2_provider", "tokenauthentication"):
        assert token not in installed, f"{token} installed — auth is no longer session-only"


def _assert_login_matches_me(client, login_body, *, staff):
    """Login and GET /api/auth/me/ must be one canonical session-user shape."""
    assert login_body["authenticated"] is True
    assert "capabilities" in login_body
    assert isinstance(login_body["capabilities"], list)
    me = client.get("/api/auth/me/")
    assert me.status_code == 200
    me_body = me.json()
    for key in (
        "authenticated", "username", "otp_enrolled", "webauthn_count",
        "totp_enrolled", "t1_available", "capabilities", "hud_ui", "role",
    ):
        assert key in login_body, key
        assert login_body[key] == me_body[key], key
    if staff:
        assert "admin_read" in login_body["capabilities"]
    else:
        assert "admin_read" not in login_body["capabilities"]


@pytest.mark.req("P0-LOGIN")
def test_password_login_matches_me_and_staff_gets_admin_read(client):
    from django.contrib.auth.models import User

    user = User.objects.create_user(
        "staff-pw", password="a-long-dev-password", is_staff=True, is_superuser=True,
    )
    _own_default(user)
    r = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "staff-pw", "password": "a-long-dev-password"}),
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    _assert_login_matches_me(client, r.json(), staff=True)


@pytest.mark.req("P0-LOGIN")
def test_password_login_of_non_staff_never_includes_admin_read(client):
    from django.contrib.auth.models import User

    User.objects.create_user("op-pw", password="a-long-dev-password")
    r = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "op-pw", "password": "a-long-dev-password"}),
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    _assert_login_matches_me(client, r.json(), staff=False)
    assert "hud_ui_v1" not in r.json()["capabilities"]
    assert r.json()["hud_ui"] is True
    assert r.json()["role"] == ""


@pytest.mark.req("P0-LOGIN")
def test_totp_login_matches_me_capabilities(client):
    import time

    from django.contrib.auth.models import User
    from django_otp.oath import TOTP
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user(
        "staff-totp", password="a-long-dev-password", is_staff=True,
    )
    _own_default(user)
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    code = format(totp.token(), "06d")
    r = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "staff-totp",
            "password": "a-long-dev-password",
            "otp_code": code,
        }),
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    _assert_login_matches_me(client, r.json(), staff=True)


@pytest.mark.req("P0-LOGIN")
def test_recovery_code_login_matches_me_capabilities(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import RecoveryCode
    from core.otp import hash_recovery_code

    user = User.objects.create_user(
        "staff-rec", password="a-long-dev-password", is_superuser=True,
    )
    _own_default(user)
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    RecoveryCode.objects.create(user=user, code_hash=hash_recovery_code("rescue12345aaaa"))
    r = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "staff-rec",
            "password": "a-long-dev-password",
            "otp_code": "rescue12345aaaa",
        }),
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    _assert_login_matches_me(client, r.json(), staff=True)


@pytest.mark.req("P0-LOGIN")
def test_passkey_login_matches_me_capabilities(client, monkeypatch):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from test_webauthn_t1 import _make_cred, _patch_webauthn_helper

    _patch_webauthn_helper(monkeypatch)
    user = User.objects.create_user(
        "staff-pk", password="a-long-dev-password", is_staff=True, is_superuser=True,
    )
    _own_default(user)
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    _make_cred(user, name="yubikey")
    begin = client.post(
        "/api/auth/webauthn/login/begin/",
        data=json.dumps({"username": "staff-pk"}),
        content_type="application/json",
    )
    assert begin.status_code == 200, begin.content
    r = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "staff-pk",
            "password": "a-long-dev-password",
            "webauthn": {"id": "cred-1", "response": {}},
        }),
        content_type="application/json",
    )
    assert r.status_code == 200, r.content
    _assert_login_matches_me(client, r.json(), staff=True)


@pytest.mark.req("SEC-A1-SESSION-AUTH")
def test_schema_rejects_anonymous(client):
    """The OpenAPI document names every mutating path. It is not a public map.

    What would make this fail: SpectacularAPIView staying AllowAny, so
    GET /api/schema/ is 200 without a session.
    """
    r = client.get("/api/schema/")
    assert r.status_code == 403
    assert b"openapi" not in r.content.lower()


@pytest.mark.req("SEC-610-MANDATORY-2FA")
def test_schema_rejects_password_only_session(client):
    """Stolen password-only cookie must not download the API map.

    What would make this fail: /api/schema/ remaining on
    ENROLLMENT_ALLOWED_PREFIXES so an enrolled-but-unverified session
    still receives the document.
    """
    from django.contrib.auth.models import User
    from django_otp import DEVICE_ID_SESSION_KEY
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user("schema-thief", password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    session = client.session
    session.pop(DEVICE_ID_SESSION_KEY, None)
    session.save()
    r = client.get("/api/schema/")
    assert r.status_code == 403
    assert b"openapi" not in r.content.lower()


@pytest.mark.req("P0-LOGIN")
def test_schema_served_to_verified_operator(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user("schema-op", password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    r = client.get("/api/schema/")
    assert r.status_code == 200, r.content
    assert b"openapi" in r.content.lower()


def test_api_responses_carry_csp_and_permissions_policy(client):
    """JSON responses must not be a document the browser will interpret.

    What would make this fail: no Content-Security-Policy on /api/auth/me/,
    or a policy that allows default-src other than 'none'.
    """
    r = client.get("/api/auth/me/")
    assert r.status_code == 200
    csp = r.headers.get("Content-Security-Policy", "")
    assert "default-src 'none'" in csp
    assert "frame-ancestors 'none'" in csp
    policy = r.headers.get("Permissions-Policy", "")
    assert "camera=()" in policy
    assert "microphone=()" in policy
