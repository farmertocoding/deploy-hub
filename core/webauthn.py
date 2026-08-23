"""WebAuthn enroll / login-begin / hardware touch (django-otp-webauthn).

Enrollment lives under /api/auth/webauthn/. POST .../touch/ is the only writer
of session["hardware_touch_at"] — login assertions never call this view.
"""
import json

from django.http import JsonResponse
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django_otp_webauthn.exceptions import NotAuthenticated
from django_otp_webauthn.models import WebAuthnCredential
from django_otp_webauthn.views import (
    CompleteCredentialAuthenticationView,
    CompleteCredentialRegistrationView,
)
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .otp import issue_recovery_codes


class CompleteRegistrationView(CompleteCredentialRegistrationView):
    """First passkey issues recovery codes once; later enrolls do not rotate them."""

    def post(self, *args, **kwargs):
        response = super().post(*args, **kwargs)
        if response.status_code != 200:
            return response
        payload = json.loads(response.content)
        codes = issue_recovery_codes(self.request.user, replace=False)
        if codes:
            payload["recovery_codes"] = codes
        payload["webauthn_count"] = WebAuthnCredential.objects.filter(
            user=self.request.user, confirmed=True,
        ).count()
        return JsonResponse(payload)


@method_decorator(csrf_protect, name="post")
class LoginBeginView(APIView):
    """Unauthenticated begin so login can take a WebAuthn assertion as 2FA."""

    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        from django.contrib.auth.models import User

        username = request.data.get("username") or ""
        user = User.objects.filter(username=username).first()
        helper = WebAuthnCredential.get_webauthn_helper(request=request)
        data, state = helper.authenticate_begin(
            user=user, require_user_verification=True,
        )
        request.session["otp_webauthn_authentication_state"] = state
        return Response(data)


class TouchView(CompleteCredentialAuthenticationView):
    """Step-up: verify a WebAuthn assertion and stamp hardware_touch_at.

    Login complete must not subclass this. TOTP/recovery never reach it.
    """

    def check_can_authenticate(self):
        if not self.request.user.is_authenticated:
            raise NotAuthenticated()

    def complete_auth(self, device):
        self.request.session["hardware_touch_at"] = timezone.now().isoformat()
        self.request.session.save()

    def get_success_data(self, device):
        return {
            "touched": True,
            "hardware_touch_at": self.request.session["hardware_touch_at"],
        }
