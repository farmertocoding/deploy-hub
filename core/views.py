"""Session login with mandatory TOTP second factor (§A1; WebAuthn arrives Phase 4 §E9).

Mockup-first: one endpoint takes password + TOTP code together. Split ceremony
(password step, then OTP step) can come later without changing the session model.
"""
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django_otp import devices_for_user, match_token
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import audit


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)
    otp_code = serializers.CharField(required=False, allow_blank=True)


class LoginView(APIView):
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
            device = match_token(user, ser.validated_data.get("otp_code", ""))
            if device is None:
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
    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(
            {
                "username": request.user.username,
                "otp_enrolled": any(devices_for_user(request.user, confirmed=True)),
            }
        )
