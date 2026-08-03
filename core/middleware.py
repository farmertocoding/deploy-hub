"""Mandatory-2FA enforcement (§6.10) — server-side, not just UI routing.

A session belonging to a user with NO confirmed OTP device may only reach the
enrollment endpoints (and login/logout/me/schema). Round-1 security finding:
without this, a stolen password of a not-yet-enrolled user gives full API access
— including enrolling the attacker's own device. The gate lives in middleware so
no future endpoint can forget it.
"""
from django.http import JsonResponse

ENROLLMENT_ALLOWED_PREFIXES = (
    "/api/auth/",     # login, logout, me, totp/enroll, totp/confirm
    "/api/schema/",
    "/admin/",        # dev convenience; Tailscale-IP-bound + 2FA in deployment (§B10)
    "/static/",
)


class EnrollmentRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if (
            user is not None
            and user.is_authenticated
            and request.path.startswith("/api/")
            and not request.path.startswith(ENROLLMENT_ALLOWED_PREFIXES)
            and not _has_confirmed_device(user)
        ):
            return JsonResponse(
                {"detail": "Two-factor enrollment required before using the API."},
                status=403,
            )
        return self.get_response(request)


def _has_confirmed_device(user):
    from django_otp import devices_for_user

    return any(devices_for_user(user, confirmed=True))
