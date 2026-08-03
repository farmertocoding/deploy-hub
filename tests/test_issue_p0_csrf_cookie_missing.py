"""Regression (found live in the Phase 0 exit-demo run, 2026-08-03): the SPA is
served by vite, so no Django GET ever planted the csrftoken cookie; login succeeded
but EVERY subsequent authed POST 403'd in a clean browser. Invisible to the plain
pytest client (CSRF skipped) — these tests use enforce_csrf_checks=True to walk the
real browser path. Evolved in round 1: /api/auth/me/ is now the bootstrap that
plants the cookie, and the login POST itself is CSRF-protected (login-CSRF fix)."""
import json
import time

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


def _current_code(device):
    from django_otp.oath import TOTP

    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    return format(totp.token(), "06d")


@pytest.mark.req("P0-LOGIN")
def test_clean_browser_flow_bootstrap_login_authed_post():
    """The full real-browser sequence: /me bootstrap plants the CSRF cookie →
    CSRF-checked login (password+TOTP) → authed POST with token succeeds →
    same POST without the header is still rejected."""
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    u = User.objects.create_user("joseph", password="a-long-dev-password")
    device = TOTPDevice.objects.create(user=u, name="phone", confirmed=True)
    client = Client(enforce_csrf_checks=True)

    boot = client.get("/api/auth/me/")
    assert boot.status_code == 200
    assert "csrftoken" in boot.cookies, "bootstrap must plant the CSRF cookie"
    token = boot.cookies["csrftoken"].value

    r = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "joseph", "password": "a-long-dev-password",
                         "otp_code": _current_code(device)}),
        content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 200
    # Login rotates the CSRF token; the browser uses the fresh cookie.
    token = r.cookies["csrftoken"].value if "csrftoken" in r.cookies else token

    r = client.post("/api/demo-jobs/", data=json.dumps({"name": "demo"}),
                    content_type="application/json", HTTP_X_CSRFTOKEN=token)
    assert r.status_code == 201, r.content

    # And without the header the POST is still rejected (CSRF enforcement intact).
    r = client.post("/api/demo-jobs/", data=json.dumps({"name": "demo"}),
                    content_type="application/json")
    assert r.status_code == 403


def test_dev_settings_trust_vite_origins():
    """Second half of the same live finding: vite's proxy rewrites Host, so the
    browser Origin must be in CSRF_TRUSTED_ORIGINS or every dev POST 403s."""
    from django.conf import settings

    assert "http://127.0.0.1:5173" in settings.CSRF_TRUSTED_ORIGINS
    assert "http://localhost:5173" in settings.CSRF_TRUSTED_ORIGINS
