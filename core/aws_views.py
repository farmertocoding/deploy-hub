"""Settings AWS-connect API (Task 2): paste keys, observe, vault.

POST /api/v1/aws/connect/ — included from core/zone_urls.py (same api/v1/
prefix as Cloudflare connect). Do not hang this off core/urls.py (/api/auth/).

Observe pasted keys (GetCallerIdentity + IAM allowlist including groups)
BEFORE any vault write. Empty AWS_CREDENTIALS_REF refuses with degraded
copy and does not invent a live token env. 201 never contains key material.
"""
import json

from django.conf import settings
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.test_mode import TestModeError
from providers import aws_creds
from vault import service as vault_service
from vault.models import Secret


class AwsConnectSerializer(serializers.Serializer):
    access_key_id = serializers.CharField(
        write_only=True, trim_whitespace=True, min_length=1,
    )
    secret_access_key = serializers.CharField(
        write_only=True, trim_whitespace=True, min_length=1,
    )
    region = serializers.CharField(
        required=False, default="us-east-1", trim_whitespace=True,
    )


class AwsConnectResultSerializer(serializers.Serializer):
    account_id_last4 = serializers.CharField()
    region = serializers.CharField()


class AwsStatusSerializer(serializers.Serializer):
    connected = serializers.BooleanField()
    reason = serializers.CharField(allow_blank=True)


def _refuse(message, field="non_field_errors"):
    raise serializers.ValidationError({field: message})


def _ref():
    return str(getattr(settings, "AWS_CREDENTIALS_REF", "") or "").strip()


class AwsConnectView(APIView):
    @extend_schema(responses={200: AwsStatusSerializer})
    def get(self, request):
        ref = _ref()
        if not ref:
            return Response(
                {
                    "connected": False,
                    "reason": "set HUB_AWS_CREDENTIALS_REF",
                }
            )
        exists = Secret.objects.filter(
            kind=Secret.Kind.CLOUD_CREDENTIAL,
            owner_type="aws",
            owner_id=ref,
        ).exists()
        return Response(
            {
                "connected": exists,
                "reason": (
                    ""
                    if exists
                    else "AWS credentials ref is set but the vault row is missing"
                ),
            }
        )

    @extend_schema(
        request=AwsConnectSerializer,
        responses={201: AwsConnectResultSerializer},
    )
    def post(self, request):
        ref = _ref()
        if not ref:
            return Response(
                {
                    "connected": False,
                    "reason": "set HUB_AWS_CREDENTIALS_REF",
                    "detail": "set HUB_AWS_CREDENTIALS_REF",
                    "errors": {
                        "non_field_errors": [
                            {
                                "code": "unconfigured",
                                "message": "set HUB_AWS_CREDENTIALS_REF",
                                "hint": "",
                            }
                        ]
                    },
                },
                status=status.HTTP_409_CONFLICT,
            )

        ser = AwsConnectSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        access_key_id = ser.validated_data["access_key_id"]
        secret_access_key = ser.validated_data["secret_access_key"]
        region = ser.validated_data.get("region") or "us-east-1"

        # Observe the pasted bytes BEFORE any vault write. Throwaway
        # explicit-key client, not the product CloudProvider.
        try:
            observed = aws_creds.observe_credentials(
                access_key_id,
                secret_access_key,
                region_name=region,
                ref=ref,
            )
        except aws_creds.AwsScopeError as exc:
            _refuse(str(exc))
        except aws_creds.AwsCredsError as exc:
            _refuse(str(exc))
        except TestModeError as exc:
            _refuse(str(exc))

        plaintext = json.dumps(
            {
                "access_key_id": access_key_id,
                "secret_access_key": secret_access_key,
            }
        ).encode()
        vault_service.put(
            kind=Secret.Kind.CLOUD_CREDENTIAL,
            owner_type="aws",
            owner_id=ref,
            plaintext=plaintext,
            actor=request.user,
        )
        account_id = observed["account_id"]
        return Response(
            AwsConnectResultSerializer(
                {
                    "account_id_last4": account_id[-4:],
                    "region": observed.get("region") or region,
                }
            ).data,
            status=status.HTTP_201_CREATED,
        )
