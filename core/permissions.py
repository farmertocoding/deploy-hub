"""T1 step-up: WebAuthn hardware touch, never TOTP (D-062 / Security F1).

RequireRecentTouch reads session["hardware_touch_at"] written only by
POST /api/auth/webauthn/touch/. Two confirmed WebAuthn credentials are
required before T1 is available; TOTP-only operators keep today's refuse.
"""
from datetime import timedelta
from datetime import timezone as dt_timezone

from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.permissions import SAFE_METHODS, BasePermission


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
            touched = timezone.make_aware(touched, dt_timezone.utc)
        age = timezone.now() - touched
        if age > timedelta(minutes=self.minutes) or age < timedelta(0):
            self.message = "Recent hardware touch required."
            return False
        return True


class RequireWorkspace(BasePermission):
    message = "Workspace required."

    def has_permission(self, request, view):
        from core.rbac import request_workspace

        return request_workspace(request) is not None


class RequireAction(BasePermission):
    """Mutating views set ``action_id``. Unmapped actions fail closed."""

    message = "Action is not permitted in this workspace."

    def has_permission(self, request, view):
        from core.rbac import ACTION_CAPABILITY, has_operator_capability, request_workspace

        if request.method in SAFE_METHODS:
            return True
        action = getattr(view, "action_id", None) or ""
        cap = ACTION_CAPABILITY.get(action)
        if not cap:
            return False
        if not has_operator_capability(request.user, cap, request_workspace(request)):
            self.message = f"{cap} required."
            return False
        return True


class RequireSystemAdmin(BasePermission):
    """Platform-global mutations. Does not consult the selected workspace."""

    message = "System administrator required."

    def has_permission(self, request, view):
        from core.rbac import is_system_admin

        return is_system_admin(getattr(request, "user", None))
