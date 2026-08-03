"""Regression (found live in the Phase 0 exit-demo run, 2026-08-03): the SPA is
served by vite, so no Django GET ever plants the csrftoken cookie. Login succeeded
(its view skips SessionAuthentication) but EVERY subsequent authed POST 403'd in a
clean browser. Fix: LoginView calls get_token() so the login response sets the cookie.

The plain pytest client skips CSRF enforcement, which is why the suite was green —
this test uses enforce_csrf_checks=True to reproduce the real browser path."""
import json

import pytest
from django.test import Client

pytestmark = pytest.mark.django_db


@pytest.mark.req("P0-LOGIN")
def test_login_response_plants_csrf_cookie_and_authed_posts_work():
    from django.contrib.auth.models import User

    User.objects.create_user("joseph", password="a-long-dev-password")
    client = Client(enforce_csrf_checks=True)

    r = client.post("/api/auth/login/",
                    data=json.dumps({"username": "joseph", "password": "a-long-dev-password"}),
                    content_type="application/json")
    assert r.status_code == 200
    assert "csrftoken" in r.cookies, "login response must set the CSRF cookie"

    token = r.cookies["csrftoken"].value
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
