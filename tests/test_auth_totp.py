"""TOTP second factor enforced for enrolled users (P0-2FA-TOTP)."""
import json
import time

import pytest


def _current_code(device):
    from django_otp.oath import TOTP

    totp = TOTP(device.bin_key, device.step, device.t0, device.digits, device.drift)
    totp.time = time.time()
    return format(totp.token(), "06d")


@pytest.mark.req("P0-2FA-TOTP")
@pytest.mark.django_db
def test_enrollment_flow_qr_confirm_recovery_codes(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import RecoveryCode

    User.objects.create_user("joseph", password="a-long-dev-password")
    client.login(username="joseph", password="a-long-dev-password")

    # Enroll: unconfirmed device + provisioning URI + QR.
    r = client.post("/api/auth/totp/enroll/")
    assert r.status_code == 201
    assert r.json()["otpauth_url"].startswith("otpauth://totp/")
    assert "<svg" in r.json()["qr_svg"]

    # Wrong code does not confirm.
    r = client.post("/api/auth/totp/confirm/", data=json.dumps({"otp_code": "000000"}),
                    content_type="application/json")
    assert r.status_code == 400

    # Right code confirms and returns recovery codes exactly once.
    device = TOTPDevice.objects.get(user__username="joseph", confirmed=False)
    device.throttle_reset()
    r = client.post("/api/auth/totp/confirm/",
                    data=json.dumps({"otp_code": _current_code(device)}),
                    content_type="application/json")
    assert r.status_code == 200
    codes = r.json()["recovery_codes"]
    assert len(codes) == 8
    stored = list(RecoveryCode.objects.filter(user__username="joseph")
                  .values_list("code_hash", flat=True))
    assert len(stored) == 8
    # Never plaintext at rest (round-1 security finding).
    assert not set(codes) & set(stored)
    assert all(len(h) == 64 for h in stored)

    # Second enrollment attempt is refused while a confirmed device exists.
    assert client.post("/api/auth/totp/enroll/").status_code == 409


@pytest.mark.req("P0-2FA-TOTP")
@pytest.mark.django_db
def test_recovery_code_works_as_second_factor_once(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import RecoveryCode
    from core.otp import hash_recovery_code

    user = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    RecoveryCode.objects.create(user=user, code_hash=hash_recovery_code("rescue12345"))

    payload = {"username": "joseph", "password": "a-long-dev-password",
               "otp_code": "rescue12345"}
    r = client.post("/api/auth/login/", data=json.dumps(payload),
                    content_type="application/json")
    assert r.status_code == 200
    # Consumed: the same code cannot be used again.
    client.post("/api/auth/logout/")
    r = client.post("/api/auth/login/", data=json.dumps(payload),
                    content_type="application/json")
    assert r.status_code == 400


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
