"""TOTP second factor enforced for enrolled users (P0-2FA-TOTP)."""
import json

import pytest


@pytest.mark.req("P0-2FA-TOTP")
@pytest.mark.django_db
def test_enrolled_user_cannot_login_without_totp(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user("joseph", password="a-long-dev-password")
    device = TOTPDevice.objects.create(user=user, name="phone", confirmed=True)

    # Password alone is no longer enough.
    r = client.post("/api/auth/login/",
                    data=json.dumps({"username": "joseph", "password": "a-long-dev-password"}),
                    content_type="application/json")
    assert r.status_code == 400

    # The failed attempt above trips django-otp's failure throttle (correct
    # behavior in prod); reset it so the valid attempt isn't rate-limited.
    device.refresh_from_db()
    device.throttle_reset()

    # Password + a valid current token works.
    import time

    from django_otp.oath import TOTP

    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    r = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "joseph", "password": "a-long-dev-password",
                         "otp_code": format(totp.token(), "06d")}),
        content_type="application/json",
    )
    assert r.status_code == 200
    assert r.json()["otp_enrolled"] is True
