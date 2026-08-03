"""Session login with mandatory TOTP second factor (§A1; WebAuthn arrives Phase 4 §E9).

Mockup-first: one endpoint takes password + TOTP code together. Split ceremony
(password step, then OTP step) can come later without changing the session model.
"""
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django_otp import devices_for_user, match_token
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import audit
from .otp import consume_recovery_code


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)
    otp_code = serializers.CharField(required=False, allow_blank=True)


@method_decorator(csrf_protect, name="post")
class LoginView(APIView):
    """CSRF-protected even though unauthenticated (round-1 finding: login-CSRF —
    a cross-site page must not be able to log the victim into an attacker account).
    The SPA fetches /api/auth/me/ on load, which plants the CSRF cookie."""

    authentication_classes = []
    permission_classes = [AllowAny]

    @extend_schema(request=LoginSerializer, responses={200: dict})
    def post(self, request):
        ser = LoginSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=ser.validated_data["username"],
            password=ser.validated_data["password"],
        )
        if user is None:
            audit("login_failed", source="api", severity="security",
                  source_ip=request.META.get("REMOTE_ADDR"),
                  username=ser.validated_data["username"])
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)

        has_device = any(devices_for_user(user, confirmed=True))
        if has_device:
            code = ser.validated_data.get("otp_code", "")
            device = match_token(user, code)
            if device is None and not consume_recovery_code(user, code):
                audit("otp_failed", source="api", severity="security", actor=user,
                      source_ip=request.META.get("REMOTE_ADDR"))
                return Response({"detail": "Invalid or missing OTP code."},
                                status=status.HTTP_400_BAD_REQUEST)
        # No device yet: allow login so first-run enrollment can happen; the UI
        # forces TOTP setup before anything else is usable (§6.10 mandatory-2FA).
        login(request, user)
        # The SPA is served by vite, so no Django GET ever plants the CSRF cookie;
        # without this line every subsequent authed POST 403s in a clean browser.
        get_token(request)
        audit("login", source="api", actor=user, source_ip=request.META.get("REMOTE_ADDR"))
        return Response({"username": user.username, "otp_enrolled": has_device})


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        audit("logout", source="api", actor=request.user)
        logout(request)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MeView(APIView):
    """Session hydration for the SPA. AllowAny: the anonymous response is the
    SPA's pre-login bootstrap and plants the CSRF cookie (get_token) so the
    login POST itself can be CSRF-checked."""

    permission_classes = [AllowAny]

    def get(self, request):
        get_token(request)
        if not request.user.is_authenticated:
            return Response({"authenticated": False})
        return Response(
            {
                "authenticated": True,
                "username": request.user.username,
                "otp_enrolled": any(devices_for_user(request.user, confirmed=True)),
            }
        )
