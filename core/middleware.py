"""Mandatory-2FA enforcement (§6.10) and idle session timeout (D-062).

A session belonging to a user with NO confirmed OTP device may only reach the
enrollment endpoints (and login/logout/me). Round-1 security finding:
without this, a stolen password of a not-yet-enrolled user gives full API access
— including enrolling the attacker's own device. The gate lives in middleware so
no future endpoint can forget it. `/api/schema/` is not in this list: the OpenAPI
document names every mutating path and requires a verified session.

IdleTimeoutMiddleware enforces existing HUB_SESSION_IDLE_TIMEOUT (~30 min) so a
stolen live session dies even when the absolute cookie age is still 12 h.
"""
import time

from django.contrib.auth import logout
from django.http import JsonResponse

ENROLLMENT_ALLOWED_PREFIXES = (
    "/api/auth/",     # login, logout, me, totp/*, webauthn/*
    "/admin/",        # dev convenience; Tailscale-IP-bound + 2FA in deployment (§B10)
    "/static/",
)

# First-run enroll is allowed without is_verified(). Extra factors are not.
_EXTRA_FACTOR_PREFIXES = (
    "/api/auth/webauthn/registration/",
)

LAST_ACTIVITY_KEY = "_hub_last_activity"


class EnrollmentRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            if (
                request.path.startswith(_EXTRA_FACTOR_PREFIXES)
                and _has_confirmed_device(user)
                and not _session_verified(user)
            ):
                return JsonResponse(
                    {
                        "detail": (
                            "Two-factor verification required before enrolling "
                            "another factor."
                        ),
                    },
                    status=403,
                )
            if (
                request.path.startswith("/api/")
                and not request.path.startswith(ENROLLMENT_ALLOWED_PREFIXES)
            ):
                if not _has_confirmed_device(user):
                    return JsonResponse(
                        {"detail": "Two-factor enrollment required before using the API."},
                        status=403,
                    )
                if not _session_verified(user):
                    return JsonResponse(
                        {"detail": "Two-factor verification required before using the API."},
                        status=403,
                    )
        return self.get_response(request)


def _has_confirmed_device(user):
    from django_otp import devices_for_user

    return any(devices_for_user(user, confirmed=True))


def _session_verified(user):
    """OTPMiddleware sets is_verified() from session otp_device_id."""
    checker = getattr(user, "is_verified", None)
    if callable(checker):
        return bool(checker())
    return False


class SecurityHeadersMiddleware:
    """CSP + Permissions-Policy on every response.

    `/api/` is JSON: default-src 'none' so a browser must not treat the body as
    a document. Admin HTML needs 'self' plus inline styles Django's admin ships.
    """

    API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'"
    PAGE_CSP = (
        "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; font-src 'self'; object-src 'none'; "
        "frame-ancestors 'none'; base-uri 'self'; form-action 'self'"
    )
    PERMISSIONS = "camera=(), microphone=(), geolocation=(), payment=(), usb=()"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if "Content-Security-Policy" not in response:
            if request.path.startswith("/api/"):
                response["Content-Security-Policy"] = self.API_CSP
            else:
                response["Content-Security-Policy"] = self.PAGE_CSP
        if "Permissions-Policy" not in response:
            response["Permissions-Policy"] = self.PERMISSIONS
        return response


class IdleTimeoutMiddleware:
    """Rolling idle timeout on HUB_SESSION_IDLE_TIMEOUT. After AuthenticationMiddleware."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        from django.conf import settings

        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            now = time.time()
            last = request.session.get(LAST_ACTIVITY_KEY)
            timeout = int(getattr(settings, "HUB_SESSION_IDLE_TIMEOUT", 30 * 60))
            if last is not None and (now - float(last)) > timeout:
                logout(request)
            else:
                request.session[LAST_ACTIVITY_KEY] = now
        return self.get_response(request)
