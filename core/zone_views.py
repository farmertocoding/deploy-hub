"""Cloudflare-connect API (Task 12b): paste a token, observe it, vault it,
then create the DnsAccount + DnsZone rows.

Cloudflare HTTP stays inside providers/ — this view calls observe_token, the
ONE pinned verify + zone-set probe. core/views.py is untouched so auth-code
custody stays clean.

Origin-CA plant (Task 2 / I-plant): a Hub-local file path under an Origin-CA
subdir becomes vault.put(API_TOKEN, dns_account, ref). The file is a Bearer
token with Zone SSL and Certificates Edit, not a deprecated v1.0- service
key. Token bytes never enter the request or response.
"""
import uuid
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.models import DnsAccount, DnsZone
from core.permissions import RequireAction, RequireRecentTouch, RequireWorkspace
from core.rbac import request_workspace, scoped_get
from providers import cloudflare
from vault import service as vault_service
from vault.models import Secret

ORIGIN_CA_PLANT_ROOTS = (
    Path("/etc/deploy-hub/origin-ca"),
    Path("/var/lib/deploy-hub/origin-ca"),
)
_PLANT_BODY_KEYS = frozenset({"path"})
_KEY_MARKERS = ("BEGIN ", "PRIVATE KEY", "-----")


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


def _observe_origin_ca(token, account):
    """One-zone Bearer wall for Origin CA, same observation as DNS tokens."""
    observed = cloudflare.observe_token(token)
    if observed["status"] != "active":
        raise cloudflare.CloudflareError(
            f"token verify returned status {observed['status']!r}, not 'active'"
        )
    if observed["zone_count"] != 1:
        raise cloudflare.CloudflareError(
            f"token reaches {observed['zone_count']} zones; Origin CA must "
            "be scoped to exactly one zone"
        )
    declared = {zone.provider_zone_id for zone in account.zones.all()}
    if declared:
        got = (observed["zones"][0] or {}).get("id")
        if got not in declared:
            raise cloudflare.CloudflareError(
                "Origin CA token zone does not match this DnsAccount"
            )
    return observed


class CloudflareConnectView(APIView):
    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "dns.cloudflare_connect"
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
                workspace = request_workspace(request)
                if workspace is None:
                    _refuse("Workspace required.")
                account = DnsAccount.objects.create(
                    workspace=workspace,
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


class OriginCaPlantSerializer(serializers.Serializer):
    path = serializers.CharField(write_only=True, trim_whitespace=True, min_length=1)


class OriginCaPlantResultSerializer(serializers.Serializer):
    planted = serializers.BooleanField()


def _body_has_key_bytes(data):
    """Refuse anything except `{path}` — and refuse a path that is key material."""
    if not isinstance(data, dict):
        return True
    if set(data.keys()) - _PLANT_BODY_KEYS:
        return True
    raw = data.get("path") or ""
    return isinstance(raw, str) and any(marker in raw for marker in _KEY_MARKERS)


def _under_origin_ca_root(resolved):
    for root in ORIGIN_CA_PLANT_ROOTS:
        try:
            if resolved.is_relative_to(Path(root).resolve()):
                return True
        except (OSError, RuntimeError, ValueError):
            continue
    return False


def _resolve_plant_path(raw):
    path = Path(raw)
    try:
        resolved = path.resolve(strict=True)
    except (FileNotFoundError, OSError) as exc:
        raise serializers.ValidationError({"path": "path does not exist"}) from exc
    if not _under_origin_ca_root(resolved):
        raise serializers.ValidationError(
            {"path": "path is outside an Origin-CA directory"}
        )
    if path.is_symlink():
        raise serializers.ValidationError({"path": "path must not be a symlink"})
    if not resolved.is_file() or resolved.is_symlink():
        raise serializers.ValidationError({"path": "path must be a regular file"})
    if resolved.stat().st_mode & 0o777 != 0o600:
        raise serializers.ValidationError({"path": "path must be mode 0600"})
    vault_key = Path(settings.VAULT_KEYFILE).resolve()
    if resolved == vault_key:
        raise serializers.ValidationError(
            {"path": "path is not a plantable Origin-CA file"}
        )
    return resolved


class OriginCaPlantView(APIView):
    permission_classes = [IsAuthenticated, RequireWorkspace, RequireAction, RequireRecentTouch]
    action_id = "dns.origin_ca_plant"
    @extend_schema(
        request=OriginCaPlantSerializer,
        responses={200: OriginCaPlantResultSerializer},
    )
    def post(self, request, account_id):
        account = scoped_get(request, DnsAccount.objects.all(), pk=account_id)
        if _body_has_key_bytes(getattr(request, "data", None)):
            raise serializers.ValidationError(
                {"path": "body must be {path} only; key bytes are not accepted"}
            )
        ser = OriginCaPlantSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        resolved = _resolve_plant_path(ser.validated_data["path"])
        plaintext = resolved.read_bytes()
        try:
            token = cloudflare.refuse_origin_ca_service_key(plaintext)
        except cloudflare.CloudflareError as exc:
            raise serializers.ValidationError({"path": str(exc)}) from exc
        try:
            _observe_origin_ca(token, account)
        except cloudflare.CloudflareError as exc:
            raise serializers.ValidationError({"path": str(exc)}) from exc
        ref = account.origin_ca_key_ref or uuid.uuid4().hex
        vault_service.put(
            kind=Secret.Kind.API_TOKEN,
            owner_type="dns_account",
            owner_id=ref,
            plaintext=plaintext,
            actor=request.user,
        )
        if account.origin_ca_key_ref != ref:
            account.origin_ca_key_ref = ref
            account.save(update_fields=["origin_ca_key_ref"])
        try:
            resolved.unlink()
        except OSError as exc:
            raise serializers.ValidationError(
                {"path": "vaulted but could not remove the plant file"}
            ) from exc
        return Response(
            OriginCaPlantResultSerializer({"planted": True}).data,
            status=status.HTTP_200_OK,
        )
