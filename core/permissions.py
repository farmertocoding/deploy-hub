"""T1 step-up: WebAuthn hardware touch, never TOTP (D-062 / Security F1).

RequireRecentTouch reads session["hardware_touch_at"] written only by
POST /api/auth/webauthn/touch/. Two confirmed WebAuthn credentials are
required before T1 is available; TOTP-only operators keep today's refuse.
"""
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.permissions import BasePermission


class RequireRecentTouch(BasePermission):
    """DRF permission: recent WebAuthn touch + two passkeys. minutes=5."""

    minutes = 5
    message = "Recent hardware touch required."

    def has_permission(self, request, view):
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            return False
        from django_otp_webauthn.models import WebAuthnCredential

        n = WebAuthnCredential.objects.filter(user=user, confirmed=True).count()
        if n < 2:
            self.message = "Add a passkey before T1 actions are available."
            return False
        raw = request.session.get("hardware_touch_at")
        if not raw:
            self.message = "Recent hardware touch required."
            return False
        touched = parse_datetime(raw) if isinstance(raw, str) else raw
        if touched is None:
            self.message = "Recent hardware touch required."
            return False
        if timezone.is_naive(touched):
            touched = timezone.make_aware(touched, timezone.utc)
        age = timezone.now() - touched
        if age > timedelta(minutes=self.minutes) or age < timedelta(0):
            self.message = "Recent hardware touch required."
            return False
        return True
