"""TOTP enrollment endpoints (§6.10 mandatory-2FA; WebAuthn joins in Phase 4).

Flow: POST enroll → unconfirmed device + otpauth URI + QR SVG → user scans →
POST confirm with a live code → device confirmed + one-time recovery codes
(shown exactly once, stored hashed-equivalent as StaticTokens).
"""
import io

import qrcode
import qrcode.image.svg
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .audit import audit

RECOVERY_CODE_COUNT = 8


def _qr_svg(text):
    img = qrcode.make(text, image_factory=qrcode.image.svg.SvgPathImage, box_size=12)
    buf = io.BytesIO()
    img.save(buf)
    return buf.getvalue().decode()


class EnrollView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        from django_otp.plugins.otp_totp.models import TOTPDevice

        if TOTPDevice.objects.filter(user=request.user, confirmed=True).exists():
            return Response(
                {"detail": "TOTP already enrolled. Remove the existing device first."},
                status=status.HTTP_409_CONFLICT,
            )
        # Replace any stale unconfirmed attempt — one pending enrollment at a time.
        TOTPDevice.objects.filter(user=request.user, confirmed=False).delete()
        device = TOTPDevice.objects.create(
            user=request.user, name="authenticator", confirmed=False
        )
        audit("totp_enroll_started", source="api", actor=request.user)
        return Response(
            {
                "otpauth_url": device.config_url,
                "qr_svg": _qr_svg(device.config_url),
            },
            status=status.HTTP_201_CREATED,
        )


class ConfirmSerializer(serializers.Serializer):
    otp_code = serializers.RegexField(r"^\d{6}$")


class ConfirmView(APIView):
    permission_classes = [IsAuthenticated]

    @extend_schema(request=ConfirmSerializer, responses={200: dict})
    def post(self, request):
        from django.utils.crypto import get_random_string
        from django_otp.plugins.otp_static.models import StaticDevice, StaticToken
        from django_otp.plugins.otp_totp.models import TOTPDevice

        ser = ConfirmSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        device = TOTPDevice.objects.filter(user=request.user, confirmed=False).first()
        if device is None:
            return Response({"detail": "No pending enrollment."}, status=400)
        if not device.verify_token(ser.validated_data["otp_code"]):
            audit("totp_confirm_failed", source="api", actor=request.user, severity="security")
            return Response({"detail": "Code did not verify — try the next code."}, status=400)

        device.confirmed = True
        device.save(update_fields=["confirmed"])

        # Recovery codes: shown once, usable once each (§6.10 resilience rules).
        static, _ = StaticDevice.objects.get_or_create(
            user=request.user, name="recovery", defaults={"confirmed": True}
        )
        static.token_set.all().delete()
        codes = [get_random_string(10, "abcdefghjkmnpqrstuvwxyz23456789")
                 for _ in range(RECOVERY_CODE_COUNT)]
        StaticToken.objects.bulk_create(
            [StaticToken(device=static, token=c) for c in codes]
        )
        audit("totp_enrolled", source="api", actor=request.user, severity="security")
        return Response({"enrolled": True, "recovery_codes": codes})
