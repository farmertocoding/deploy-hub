"""Session login: password + (WebAuthn assertion OR TOTP OR recovery).

WebAuthn is the primary second factor; TOTP/recovery are fallbacks. None of
those login paths write session["hardware_touch_at"] (D-062).
"""
from django.contrib.auth import authenticate, login, logout
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django_otp import devices_for_user, match_token
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import audit
from .models import Target
from .otp import consume_recovery_code
from .permissions import RequireRecentTouch


class LoginSerializer(serializers.Serializer):
    username = serializers.CharField()
    password = serializers.CharField(trim_whitespace=False)
    otp_code = serializers.CharField(required=False, allow_blank=True)
    webauthn = serializers.JSONField(required=False, default=None)


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
            assertion = ser.validated_data.get("webauthn")
            code = ser.validated_data.get("otp_code") or ""
            ok = False
            if assertion:
                ok = _verify_webauthn_login(request, user, assertion) is not None
            else:
                ok = (
                    match_token(user, code) is not None
                    or consume_recovery_code(user, code)
                )
            if not ok:
                audit("otp_failed", source="api", severity="security", actor=user,
                      source_ip=request.META.get("REMOTE_ADDR"))
                return Response({"detail": "Invalid or missing OTP code."},
                                status=status.HTTP_400_BAD_REQUEST)
        # No device yet: allow login so first-run enrollment can happen; the UI
        # forces WebAuthn setup before anything else is usable (§6.10 mandatory-2FA).
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


class MeSerializer(serializers.Serializer):
    authenticated = serializers.BooleanField()
    username = serializers.CharField(required=False)
    otp_enrolled = serializers.BooleanField(required=False)
    webauthn_count = serializers.IntegerField(required=False)
    totp_enrolled = serializers.BooleanField(required=False)
    t1_available = serializers.BooleanField(required=False)


class MeView(APIView):
    """Session hydration for the SPA. AllowAny: the anonymous response is the
    SPA's pre-login bootstrap and plants the CSRF cookie (get_token) so the
    login POST itself can be CSRF-checked."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: MeSerializer})
    def get(self, request):
        get_token(request)
        if not request.user.is_authenticated:
            return Response(MeSerializer({"authenticated": False}).data)
        from django_otp.plugins.otp_totp.models import TOTPDevice
        from django_otp_webauthn.models import WebAuthnCredential

        webauthn_count = WebAuthnCredential.objects.filter(
            user=request.user, confirmed=True,
        ).count()
        totp_enrolled = TOTPDevice.objects.filter(
            user=request.user, confirmed=True,
        ).exists()
        return Response(MeSerializer({
            "authenticated": True,
            "username": request.user.username,
            "otp_enrolled": any(devices_for_user(request.user, confirmed=True)),
            "webauthn_count": webauthn_count,
            "totp_enrolled": totp_enrolled,
            "t1_available": webauthn_count >= 2,
        }).data)


def _verify_webauthn_login(request, user, data):
    """Verify a login assertion. Does not write hardware_touch_at."""
    from django_otp_webauthn.models import WebAuthnCredential

    state = request.session.pop("otp_webauthn_authentication_state", None)
    request.session.save()
    if not state:
        return None
    helper = WebAuthnCredential.get_webauthn_helper(request=request)
    try:
        device = helper.authenticate_complete(user=user, state=state, data=data)
    except Exception:  # noqa: BLE001 — invalid assertion is a failed second factor
        return None
    if device is None or not device.confirmed or device.user_id != user.pk:
        return None
    return device


class TargetDeleteSerializer(serializers.Serializer):
    confirm_name = serializers.CharField()


class TargetDeleteView(APIView):
    """T1: two passkeys + recent WebAuthn touch + type-the-name."""

    permission_classes = [IsAuthenticated, RequireRecentTouch]

    @extend_schema(request=TargetDeleteSerializer, responses={204: None})
    def post(self, request, pk):
        target = get_object_or_404(Target, pk=pk)
        ser = TargetDeleteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != target.host:
            return Response(
                {"detail": "Type the target host name to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        audit("target.delete", source="api", actor=request.user, obj=target,
              severity="security")
        target.delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class SshRotateSerializer(serializers.Serializer):
    confirm_name = serializers.CharField()


class SshRotateView(APIView):
    """T1: two passkeys + recent WebAuthn touch + type-the-name, then rotate."""

    permission_classes = [IsAuthenticated, RequireRecentTouch]

    @extend_schema(request=SshRotateSerializer, responses={204: None})
    def post(self, request, pk):
        target = get_object_or_404(Target, pk=pk)
        ser = SshRotateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != target.host:
            return Response(
                {"detail": "Type the target host name to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        audit("ssh.rotate", source="api", actor=request.user, obj=target,
              severity="security")
        from core.ssh import SshTransport
        from provision.ssh_rotate import rotate_ssh

        rotate_ssh(target, SshTransport(target), force=True)
        return Response(status=status.HTTP_204_NO_CONTENT)
