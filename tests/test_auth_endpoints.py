"""Logout, /me, the mandatory-2FA gate, security-event audits, and login CSRF —
round-1 findings: these behaviors existed with zero direct tests."""
import json

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


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
    assert r.json() == {"authenticated": True, "username": "joseph", "otp_enrolled": True}


@pytest.mark.req("P0-LOGIN")
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

    # Once a confirmed device exists, the gate opens.
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.get(username="joseph")
    TOTPDevice.objects.filter(user=user).delete()
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    r = client.post("/api/demo-jobs/", data=json.dumps({"name": "demo"}),
                    content_type="application/json")
    assert r.status_code == 201


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
