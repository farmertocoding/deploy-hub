"""Session login: password + (WebAuthn assertion OR TOTP OR recovery).

WebAuthn is the primary second factor; TOTP/recovery are fallbacks. None of
those login paths write session["hardware_touch_at"] (D-062).
"""
from django.contrib.auth import authenticate, login, logout
from django.core.cache import cache
from django.middleware.csrf import get_token
from django.utils.decorators import method_decorator
from django.views.decorators.csrf import csrf_protect
from django_otp import devices_for_user, match_token
from django_otp import login as otp_login
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import audit
from .exception_handlers import client_ip
from .models import NetworkZone, Site, Target
from .otp import consume_recovery_code
from .permissions import RequireAction, RequireRecentTouch, RequireWorkspace
from .rbac import SITE_FIELD, TARGET_FIELD, scoped_get


def _login_bucket(ip, username):
    return f"login-ip:{ip or 'unknown'}", f"login-user:{(username or '').lower()}"


def _login_throttled(ip, username):
    """Bounded per-IP and per-account authentication throttle."""
    ip_key, user_key = _login_bucket(ip, username)
    return cache.get(ip_key, 0) >= 10 or cache.get(user_key, 0) >= 10


def _login_failure(ip, username):
    ip_key, user_key = _login_bucket(ip, username)
    cache.set(ip_key, cache.get(ip_key, 0) + 1, 60)
    cache.set(user_key, cache.get(user_key, 0) + 1, 60)


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
        ip = client_ip(request)
        username = ser.validated_data["username"]
        if _login_throttled(ip, username):
            audit(
                "login_throttled", source="api", severity="security",
                source_ip=ip, username=username,
            )
            return Response(
                {"detail": "Invalid credentials."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        user = authenticate(
            request,
            username=username,
            password=ser.validated_data["password"],
        )
        if user is None:
            _login_failure(ip, username)
            audit("login_failed", source="api", severity="security",
                  source_ip=ip, username=username)
            return Response({"detail": "Invalid credentials."}, status=status.HTTP_400_BAD_REQUEST)

        has_device = any(devices_for_user(user, confirmed=True))
        otp_device = None
        if has_device:
            assertion = ser.validated_data.get("webauthn")
            code = ser.validated_data.get("otp_code") or ""
            if assertion:
                otp_device = _verify_webauthn_login(request, user, assertion)
            else:
                otp_device = match_token(user, code)
                if otp_device is None and consume_recovery_code(user, code):
                    otp_device = next(devices_for_user(user, confirmed=True), None)
            if otp_device is None:
                _login_failure(ip, username)
                audit("otp_failed", source="api", severity="security", actor=user,
                      source_ip=client_ip(request))
                return Response({"detail": "Invalid or missing OTP code."},
                                status=status.HTTP_400_BAD_REQUEST)
        # No device yet: allow login so first-run enrollment can happen; the UI
        # forces WebAuthn setup before anything else is usable (§6.10 mandatory-2FA).
        login(request, user)
        if otp_device is not None:
            otp_login(request, otp_device)
        # The SPA is served by vite, so no Django GET ever plants the CSRF cookie;
        # without this line every subsequent authed POST 403s in a clean browser.
        get_token(request)
        audit("login", source="api", actor=user, source_ip=client_ip(request))
        return Response(session_user_payload(request))


class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    serializer_class = serializers.Serializer

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
    role = serializers.CharField(required=False, allow_blank=True)
    capabilities = serializers.ListField(
        child=serializers.CharField(), required=False,
    )
    is_system_admin = serializers.BooleanField(required=False)
    hud_ui = serializers.BooleanField(required=False)
    workspaces = serializers.ListField(child=serializers.DictField(), required=False)


class MeView(APIView):
    """Session hydration for the SPA. AllowAny: the anonymous response is the
    SPA's pre-login bootstrap and plants the CSRF cookie (get_token) so the
    login POST itself can be CSRF-checked."""

    permission_classes = [AllowAny]

    @extend_schema(responses={200: MeSerializer})
    def get(self, request):
        get_token(request)
        return Response(session_user_payload(request))


def session_user_payload(request):
    """Canonical SPA session user — login and /me/ return this same shape."""
    if not request.user.is_authenticated:
        return {"authenticated": False}
    from django_otp.plugins.otp_totp.models import TOTPDevice
    from django_otp_webauthn.models import WebAuthnCredential

    from core.rbac import (
        hud_ui_enabled,
        is_system_admin,
        request_workspace,
        user_capabilities,
        user_role,
        workspace_payload,
    )

    workspace = request_workspace(request)
    webauthn_count = WebAuthnCredential.objects.filter(
        user=request.user, confirmed=True,
    ).count()
    totp_enrolled = TOTPDevice.objects.filter(
        user=request.user, confirmed=True,
    ).exists()
    return MeSerializer({
        "authenticated": True,
        "username": request.user.username,
        "otp_enrolled": any(devices_for_user(request.user, confirmed=True)),
        "webauthn_count": webauthn_count,
        "totp_enrolled": totp_enrolled,
        "t1_available": webauthn_count >= 2,
        "role": user_role(request.user, workspace),
        "capabilities": user_capabilities(request.user, workspace),
        "is_system_admin": is_system_admin(request.user),
        "hud_ui": hud_ui_enabled(),
        "workspaces": workspace_payload(request.user),
    }).data


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

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "target.delete"

    @extend_schema(request=TargetDeleteSerializer, responses={204: None})
    def post(self, request, pk):
        target = scoped_get(request, Target.objects.all(), TARGET_FIELD, pk=pk)
        ser = TargetDeleteSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != target.host:
            return Response(
                {"detail": "Type the target host name to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if target.kind == Target.Kind.AWS_EC2:
            from provision.aws_enroll import TerminateError, terminate_aws_target

            try:
                terminate_aws_target(target)
            except TerminateError as exc:
                return Response(
                    {"detail": str(exc)},
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

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "ssh.rotate"

    @extend_schema(request=SshRotateSerializer, responses={204: None})
    def post(self, request, pk):
        target = scoped_get(request, Target.objects.all(), TARGET_FIELD, pk=pk)
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


class InstanceCreateSerializer(serializers.Serializer):
    confirm_name = serializers.CharField()
    host = serializers.CharField()
    zone = serializers.SlugField()
    instance_type = serializers.CharField(required=False, default="t3.micro")
    overflow_site = serializers.IntegerField(required=False)


class InstanceCreateCostSerializer(serializers.Serializer):
    cost = serializers.FloatField()
    cost_display = serializers.CharField()


class InstanceCreateResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    host = serializers.CharField()
    kind = serializers.CharField()


class InstanceCreateView(APIView):
    """T1: two passkeys + recent WebAuthn touch + type-the-name, then enroll."""

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "instance.create"

    def get_permissions(self):
        if self.request.method == "GET":
            return [IsAuthenticated(), RequireWorkspace()]
        return [IsAuthenticated(), RequireWorkspace(), RequireAction(), RequireRecentTouch()]

    @extend_schema(responses={200: InstanceCreateCostSerializer})
    def get(self, request):
        from provision.aws_enroll import _cloud_provider, _estimate_or_refuse

        instance_type = request.query_params.get("instance_type") or "t3.micro"
        spec = {"instance_type": instance_type, "size": instance_type}
        try:
            provider = _cloud_provider()
            cost = _estimate_or_refuse(provider, spec)
        except Exception:
            return Response(
                {"detail": "unconfigured hourly cost estimate"},
                status=status.HTTP_409_CONFLICT,
            )
        display = f"${float(cost):.2f}/h"
        ser = InstanceCreateCostSerializer(
            {"cost": float(cost), "cost_display": display}
        )
        return Response(ser.data)

    @extend_schema(
        request=InstanceCreateSerializer,
        responses={201: InstanceCreateResultSerializer},
    )
    def post(self, request):
        ser = InstanceCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        host = ser.validated_data["host"]
        if ser.validated_data["confirm_name"] != host:
            return Response(
                {"detail": "Type the target host name to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        zone = scoped_get(
            request, NetworkZone.objects.all(), slug=ser.validated_data["zone"],
        )
        from provision import aws_enroll as aws_enroll_mod

        overflow_site = ser.validated_data.get("overflow_site")
        try:
            if overflow_site is not None:
                from provision import overflow as overflow_mod

                site = scoped_get(request, Site.objects.all(), SITE_FIELD, pk=overflow_site)
                target = overflow_mod.enroll_overflow_target(
                    site=site,
                    host=host,
                    zone=zone,
                    confirm_name=ser.validated_data["confirm_name"],
                )
            else:
                target = aws_enroll_mod.enroll_aws_target(
                    host=host,
                    name=host,
                    zone=zone,
                    instance_type=ser.validated_data.get("instance_type") or "t3.micro",
                )
        except aws_enroll_mod.EnrollError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        audit(
            "instance.create",
            source="api",
            actor=request.user,
            obj=target,
            severity="security",
        )
        body = InstanceCreateResultSerializer(
            {"id": target.pk, "host": target.host, "kind": target.kind}
        )
        return Response(body.data, status=status.HTTP_201_CREATED)


class InstanceTerminateSerializer(serializers.Serializer):
    confirm_name = serializers.CharField()


class InstanceTerminateView(APIView):
    """T1: two passkeys + recent WebAuthn touch + type-the-name, then AWS terminate."""

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "instance.terminate"

    @extend_schema(request=InstanceTerminateSerializer, responses={204: None})
    def post(self, request, pk):
        target = scoped_get(request, Target.objects.all(), TARGET_FIELD, pk=pk)
        ser = InstanceTerminateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        if ser.validated_data["confirm_name"] != target.host:
            return Response(
                {"detail": "Type the target host name to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from provision.aws_enroll import TerminateError, terminate_aws_target

        try:
            terminate_aws_target(target)
        except TerminateError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        audit(
            "instance.terminate",
            source="api",
            actor=request.user,
            obj=target,
            severity="security",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)


class OverflowDeploySerializer(serializers.Serializer):
    target = serializers.IntegerField()
    confirm_name = serializers.CharField()


class OverflowDeployResultSerializer(serializers.Serializer):
    deployment = serializers.IntegerField()
    target = serializers.IntegerField()


class OverflowDeployView(APIView):
    """T1: two passkeys + recent WebAuthn touch + type-the-host, then overflow copy."""

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "site.overflow_deploy"

    @extend_schema(
        request=OverflowDeploySerializer,
        responses={201: OverflowDeployResultSerializer},
    )
    def post(self, request, pk):
        site = scoped_get(request, Site.objects.all(), SITE_FIELD, pk=pk)
        ser = OverflowDeploySerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        target = scoped_get(
            request, Target.objects.all(), TARGET_FIELD, pk=ser.validated_data["target"],
        )
        if ser.validated_data["confirm_name"] != target.host:
            return Response(
                {"detail": "Type the target host name to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from core import overflow_deploys

        try:
            deployment = overflow_deploys.deploy(site, target)
        except overflow_deploys.OverflowDeployError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        audit(
            "site.overflow_deploy",
            source="api",
            actor=request.user,
            obj=site,
            severity="security",
        )
        body = OverflowDeployResultSerializer(
            {"deployment": deployment.pk, "target": target.pk}
        )
        return Response(body.data, status=status.HTTP_201_CREATED)


class OverflowJoinSerializer(serializers.Serializer):
    target = serializers.IntegerField()
    confirm_name = serializers.CharField()


class OverflowJoinResultSerializer(serializers.Serializer):
    target = serializers.IntegerField()
    joined = serializers.CharField()
    name = serializers.CharField(required=False)
    values = serializers.ListField(child=serializers.CharField(), required=False)


class OverflowJoinView(APIView):
    """T1: two passkeys + recent WebAuthn touch + type-the-host, then join."""

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "site.overflow_join"

    @extend_schema(
        request=OverflowJoinSerializer,
        responses={201: OverflowJoinResultSerializer},
    )
    def post(self, request, pk):
        site = scoped_get(request, Site.objects.all(), SITE_FIELD, pk=pk)
        ser = OverflowJoinSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        target = scoped_get(
            request, Target.objects.all(), TARGET_FIELD, pk=ser.validated_data["target"],
        )
        if ser.validated_data["confirm_name"] != target.host:
            return Response(
                {"detail": "Type the target host name to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from core import overflow_deploys

        try:
            result = overflow_deploys.join(site, target)
        except overflow_deploys.OverflowDeployError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        audit(
            "site.overflow_join",
            source="api",
            actor=request.user,
            obj=site,
            severity="security",
        )
        body = OverflowJoinResultSerializer(result)
        return Response(body.data, status=status.HTTP_201_CREATED)


class OverflowScaleInSerializer(serializers.Serializer):
    target = serializers.IntegerField()
    confirm_name = serializers.CharField()


class OverflowScaleInResultSerializer(serializers.Serializer):
    target = serializers.IntegerField()
    unjoined = serializers.CharField()


class OverflowScaleInView(APIView):
    """T1: two passkeys + recent WebAuthn touch + type-the-host, then scale-in."""

    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "site.overflow_scale_in"

    @extend_schema(
        request=OverflowScaleInSerializer,
        responses={200: OverflowScaleInResultSerializer},
    )
    def post(self, request, pk):
        site = scoped_get(request, Site.objects.all(), SITE_FIELD, pk=pk)
        ser = OverflowScaleInSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        target = scoped_get(
            request, Target.objects.all(), TARGET_FIELD, pk=ser.validated_data["target"],
        )
        if ser.validated_data["confirm_name"] != target.host:
            return Response(
                {"detail": "Type the target host name to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        from core import overflow_deploys

        try:
            result = overflow_deploys.scale_in(site, target)
        except overflow_deploys.OverflowDeployError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        audit(
            "site.overflow_scale_in",
            source="api",
            actor=request.user,
            obj=site,
            severity="security",
        )
        body = OverflowScaleInResultSerializer(result)
        return Response(body.data, status=status.HTTP_200_OK)
