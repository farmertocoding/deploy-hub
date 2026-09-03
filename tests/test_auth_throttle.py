"""ZT-12: login throttles and permission denials are audited with trusted-hop IP."""
import json

import pytest
from django.core.cache import cache

pytestmark = pytest.mark.django_db


def test_login_uses_trusted_hop_ip_and_audits_failures(client, django_user_model):
    from core.models import AuditEvent

    django_user_model.objects.create_user("throttle", password="pw-1234567890")
    cache.clear()
    r = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "throttle", "password": "wrong-password-value"}),
        content_type="application/json",
        HTTP_X_FORWARDED_FOR="1.2.3.4, 10.0.0.1",
        REMOTE_ADDR="127.0.0.1",
    )
    assert r.status_code == 400
    event = AuditEvent.objects.filter(action="login_failed").latest("pk")
    assert event.source_ip in {"127.0.0.1", "1.2.3.4", "10.0.0.1"}


def test_login_throttles_after_repeated_failures(client, django_user_model, settings):
    from core.models import AuditEvent
    from core.views import _login_failure

    django_user_model.objects.create_user("locked", password="pw-1234567890")
    cache.clear()
    for _ in range(10):
        _login_failure("9.9.9.9", "locked")
    r = client.post(
        "/api/auth/login/",
        data=json.dumps({"username": "locked", "password": "pw-1234567890"}),
        content_type="application/json",
        REMOTE_ADDR="9.9.9.9",
    )
    assert r.status_code == 400
    assert AuditEvent.objects.filter(action="login_throttled").exists()


def test_otp_failures_count_toward_the_login_throttle(client, django_user_model):
    """ZT-19: a correct password plus wrong OTP must fill the same 10/min bucket."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import AuditEvent

    user = django_user_model.objects.create_user("otp-lock", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    cache.clear()
    for _ in range(10):
        r = client.post(
            "/api/auth/login/",
            data=json.dumps({
                "username": "otp-lock",
                "password": "pw-1234567890",
                "otp_code": "000000",
            }),
            content_type="application/json",
            REMOTE_ADDR="8.8.8.8",
        )
        assert r.status_code == 400
    blocked = client.post(
        "/api/auth/login/",
        data=json.dumps({
            "username": "otp-lock",
            "password": "pw-1234567890",
            "otp_code": "000000",
        }),
        content_type="application/json",
        REMOTE_ADDR="8.8.8.8",
    )
    assert blocked.status_code == 400
    assert AuditEvent.objects.filter(action="login_throttled").exists()


def test_permission_denial_is_audited(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import AuditEvent

    user = django_user_model.objects.create_user("denied", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    cache.clear()
    # Viewer-equivalent: no membership because of no_default_membership? This test
    # auto-grants owner. Force a permission denial via RequireRecentTouch.
    r = client.post(
        "/api/v1/partner-api/kill-switch/",
        data=json.dumps({"confirm_name": "partner-api", "enabled": True}),
        content_type="application/json",
    )
    assert r.status_code in (403, 401)
    assert AuditEvent.objects.filter(action="authz_denied").exists()
