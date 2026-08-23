"""Settings Partners API (Task 5): T1 partner.create, never Connect.

POST /api/v1/partners/ — included from core/zone_urls.py (same api/v1/
prefix as AWS connect). Do not hang this off core/urls.py (/api/auth/).

201 returns hubk_* + whsec_ once (Enroll once-panel). GET / list never
echo them. Fake / empty INTAKE_URL / post-create never Connected.
The Ed25519 private key is not a Partner column and is never vaulted.
"""
import base64
import secrets

from django.conf import settings
from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import audit
from core.models import AuditEvent, Finding, Partner
from core.permissions import RequireRecentTouch
from vault import service as vault_service
from vault.models import Secret
from vault.ssh import generate_ed25519_raw

# nosec B105 — prefixes naming minted material, not credentials.
HUBK_TEST_PREFIX = "hubk_test_"  # nosec B105
HUBK_LIVE_PREFIX = "hubk_live_"  # nosec B105
WHSEC_PREFIX = "whsec_"  # nosec B105


class PartnerCreateSerializer(serializers.Serializer):
    slug = serializers.SlugField(max_length=64)
    name = serializers.CharField(
        max_length=128, required=False, allow_blank=True, default="",
    )
    confirm_name = serializers.CharField()


class PartnerCreateResultSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()
    hubk = serializers.CharField()
    whsec = serializers.CharField()


class IntakeStatusSerializer(serializers.Serializer):
    status = serializers.ChoiceField(choices=("degraded", "error"))
    mode = serializers.ChoiceField(choices=("fake", "configured"))
    configured = serializers.BooleanField()
    as_of = serializers.CharField(allow_null=True, required=False)


class PartnerPublicSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    slug = serializers.CharField()
    name = serializers.CharField()
    destination_order = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True,
    )
    suspended = serializers.BooleanField()
    site_ids = serializers.ListField(
        child=serializers.IntegerField(), allow_empty=True,
    )


class PartnerListSerializer(serializers.Serializer):
    partners = PartnerPublicSerializer(many=True)
    intake = IntakeStatusSerializer()


def _mint_hubk():
    private_raw, public_raw = generate_ed25519_raw()
    prefix = (
        HUBK_TEST_PREFIX
        if getattr(settings, "HUB_TEST_MODE", False)
        else HUBK_LIVE_PREFIX
    )
    hubk = prefix + base64.b64encode(private_raw).decode("ascii")
    pubkey = base64.b64encode(public_raw).decode("ascii")
    return hubk, pubkey


def _mint_whsec():
    return WHSEC_PREFIX + base64.b64encode(secrets.token_bytes(24)).decode("ascii")


def _intake_payload():
    url = str(getattr(settings, "INTAKE_URL", "") or "").strip()
    error = Finding.objects.filter(
        fingerprint="partner-intake-unreachable",
    ).exclude(state=Finding.State.RESOLVED).exists()
    return {
        "status": "error" if error else "degraded",
        "mode": "fake" if not url else "configured",
        "configured": bool(url),
        "as_of": timezone.now().isoformat() if error else None,
    }


def _public_partner(partner):
    return {
        "id": partner.pk,
        "slug": partner.slug,
        "name": partner.name,
        "destination_order": list(partner.destination_order or []),
        "suspended": partner.suspended,
        "site_ids": list(
            partner.partner_sites.values_list("site_id", flat=True),
        ),
    }


class PartnerListCreateView(APIView):
    """GET is the operator list (no secrets). POST is T1 partner.create."""

    permission_classes = [IsAuthenticated, RequireRecentTouch]

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated()]
        return [IsAuthenticated(), RequireRecentTouch()]

    @extend_schema(responses={200: PartnerListSerializer})
    def get(self, request):
        partners = [
            _public_partner(row)
            for row in Partner.objects.order_by("pk")
        ]
        return Response(
            PartnerListSerializer(
                {"partners": partners, "intake": _intake_payload()}
            ).data
        )

    @extend_schema(
        request=PartnerCreateSerializer,
        responses={201: PartnerCreateResultSerializer},
    )
    def post(self, request):
        ser = PartnerCreateSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        slug = ser.validated_data["slug"]
        if ser.validated_data["confirm_name"] != slug:
            return Response(
                {"detail": "Type the partner slug to confirm."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        name = (ser.validated_data.get("name") or "").strip() or slug
        if Partner.objects.filter(slug=slug).exists():
            return Response(
                {"detail": "Partner slug already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        hubk, pubkey = _mint_hubk()
        whsec = _mint_whsec()
        with transaction.atomic():
            partner = Partner.objects.create(
                slug=slug,
                name=name,
                pubkey_current=pubkey,
            )
            vault_service.put(
                kind=Secret.Kind.WEBHOOK_SECRET,
                owner_type="partner",
                owner_id=str(partner.pk),
                plaintext=whsec.encode("utf-8"),
                actor=request.user,
            )
            event = audit(
                "partner.create",
                obj=partner,
                actor=request.user,
                source="api",
                severity="security",
                slug=slug,
            )
            AuditEvent.objects.filter(pk=event.pk).update(partner_id=partner.pk)
        body = PartnerCreateResultSerializer(
            {
                "id": partner.pk,
                "slug": partner.slug,
                "name": partner.name,
                "hubk": hubk,
                "whsec": whsec,
            }
        )
        return Response(body.data, status=status.HTTP_201_CREATED)


class PartnerDetailView(APIView):
    """GET never echoes hubk_ or whsec_."""

    permission_classes = [IsAuthenticated]

    @extend_schema(responses={200: PartnerPublicSerializer})
    def get(self, request, pk):
        partner = get_object_or_404(Partner, pk=pk)
        return Response(PartnerPublicSerializer(_public_partner(partner)).data)
