"""Cloudflare-connect API (Task 12b): paste a token, observe it, vault it,
then create the DnsAccount + DnsZone rows.

Cloudflare HTTP stays inside providers/ — this view calls observe_token, the
ONE pinned verify + zone-set probe. core/views.py is untouched so auth-code
custody stays clean.
"""
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import DnsAccount, DnsZone
from providers import cloudflare
from vault import service as vault_service
from vault.models import Secret


class CloudflareConnectSerializer(serializers.Serializer):
    token = serializers.CharField(write_only=True, trim_whitespace=True, min_length=1)


class DnsAccountConnectedSerializer(serializers.ModelSerializer):
    class Meta:
        model = DnsAccount
        fields = ["id", "provider", "label"]


class DnsZoneConnectedSerializer(serializers.ModelSerializer):
    class Meta:
        model = DnsZone
        fields = ["id", "name", "provider_zone_id", "purpose"]


class CloudflareConnectResultSerializer(serializers.Serializer):
    account = DnsAccountConnectedSerializer()
    zone = DnsZoneConnectedSerializer()


def _zone_purpose(name):
    """Settings-connected zones default to prod. Test-plane purpose stays
    triple-keyed: HUB_TEST_MODE + allowlisted name + purpose=test."""
    if getattr(settings, "HUB_TEST_MODE", False):
        slugs = getattr(settings, "HUB_TEST_ZONE_SLUGS", ("hub-test",))
        if name in slugs:
            return DnsZone.Purpose.TEST
    return DnsZone.Purpose.PROD


def _refuse(message):
    raise serializers.ValidationError({"token": message})


class CloudflareConnectView(APIView):
    @extend_schema(
        request=CloudflareConnectSerializer,
        responses={201: CloudflareConnectResultSerializer},
    )
    def post(self, request):
        ser = CloudflareConnectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        raw = ser.validated_data["token"]
        token_bytes = raw.encode() if isinstance(raw, str) else bytes(raw)

        # Observe the pasted bytes BEFORE any row or vault write. observe_token
        # shape-refuses a Global API Key itself (safe by construction).
        try:
            observed = cloudflare.observe_token(token_bytes)
        except cloudflare.CloudflareError as exc:
            _refuse(str(exc))

        if observed["status"] != "active":
            _refuse(
                f"token verify returned status {observed['status']!r}, "
                "not 'active'"
            )
        zones = observed["zones"]
        if len(zones) != 1:
            _refuse(
                f"token reaches {len(zones)} zones; connect accepts a token "
                "scoped to exactly one zone"
            )

        probed = zones[0]
        zone_name = probed["name"]
        provider_zone_id = probed["id"]
        ref = uuid.uuid4().hex
        secret = vault_service.put(
            kind=Secret.Kind.API_TOKEN,
            owner_type="dns_account",
            owner_id=ref,
            plaintext=token_bytes,
            actor=request.user,
        )
        try:
            with transaction.atomic():
                account = DnsAccount.objects.create(
                    provider=DnsAccount.Provider.CLOUDFLARE,
                    label=zone_name,
                    dns_token_ref=ref,
                )
                zone = DnsZone.objects.create(
                    account=account,
                    name=zone_name,
                    provider_zone_id=provider_zone_id,
                    purpose=_zone_purpose(zone_name),
                )
        except DjangoValidationError as exc:
            secret.delete()
            # Settings shows errors.token; keep the operator-visible reason there
            # even when the model raised on name (duplicate zone).
            _refuse("; ".join(exc.messages))
        except Exception:
            secret.delete()
            raise

        return Response(
            CloudflareConnectResultSerializer(
                {"account": account, "zone": zone}
            ).data,
            status=status.HTTP_201_CREATED,
        )
