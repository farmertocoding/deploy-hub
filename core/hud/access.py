from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.hud.common import (
    AllowedActionSerializer,
    DisabledActionSerializer,
    HudAPIView,
    persist_command,
    refuse_cap,
    secret_owner_allowed,
    workspace_secrets,
)
from core.hud.permissions import RequireAdminRead
from core.models import WorkspaceMembership
from core.permissions import RequireRecentTouch
from core.rbac import ROLES, request_workspace, workspace_membership
from vault.models import Secret

FORBIDDEN_SECRET_FIELDS = (
    "plaintext", "ciphertext", "wrapped_dek", "nonce", "private_url", "value",
)


class SecretMetaSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    kind = serializers.CharField()
    owner_type = serializers.CharField()
    owner_id = serializers.CharField()
    fingerprint = serializers.CharField()
    created_at = serializers.DateTimeField()
    last_used_at = serializers.DateTimeField(allow_null=True)
    exportable = serializers.BooleanField()
    references = serializers.ListField()
    allowed_actions = AllowedActionSerializer(many=True)
    disabled_actions = DisabledActionSerializer(many=True)


class SecretListSerializer(serializers.Serializer):
    observed_at = serializers.DateTimeField()
    results = SecretMetaSerializer(many=True)


def secret_row(secret):
    from core.models import Site

    exportable = secret.kind == Secret.Kind.BACKUP_KEY
    refs = []
    if secret.owner_type == "site":
        site = Site.objects.filter(pk=secret.owner_id).select_related("project").first()
        if site:
            refs.append({
                "type": "site",
                "id": str(site.pk),
                "name": f"{site.project.name}/{site.name}",
            })
    return {
        "id": secret.pk,
        "kind": secret.kind,
        "owner_type": secret.owner_type,
        "owner_id": secret.owner_id,
        "fingerprint": secret.fingerprint,
        "created_at": secret.created_at,
        "last_used_at": secret.last_used_at,
        "exportable": exportable,
        "references": refs,
        "allowed_actions": [{"id": "secret.rotate_plan", "label": "Plan rotation"}],
        "disabled_actions": [] if exportable else [{
            "id": "secret.export",
            "code": "not_exportable",
            "label": "Export",
            "reason": "This kind is not exportable.",
        }],
    }


class SecretsView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead, RequireRecentTouch]
    action_id = "secret.create"

    def get_permissions(self):
        if self.request.method in ("GET", "HEAD", "OPTIONS"):
            return [IsAuthenticated(), RequireAdminRead()]
        return [IsAuthenticated(), RequireAdminRead(), RequireRecentTouch()]

    @extend_schema(responses={200: SecretListSerializer})
    def get(self, request):
        q = (request.query_params.get("q") or "").strip().lower()
        rows = []
        for secret in workspace_secrets(request)[:200]:
            row = secret_row(secret)
            for forbidden in FORBIDDEN_SECRET_FIELDS:
                row.pop(forbidden, None)
            hay = " ".join((
                row["kind"], row["owner_type"], row["owner_id"], row["fingerprint"],
            )).lower()
            if q and q not in hay:
                continue
            rows.append(row)
        return Response(SecretListSerializer({
            "observed_at": timezone.now(),
            "results": rows,
        }).data)

    def post(self, request):
        from vault.service import put as vault_put

        denied = refuse_cap(request, "secret.create")
        if denied:
            return denied
        value = request.data.get("value") or request.data.get("plaintext")
        if not value:
            return Response(
                {"detail": "value is accepted once and never returned"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        raw = value.encode() if isinstance(value, str) else value
        owner_type = request.data.get("owner_type") or "site"
        owner_id = str(request.data.get("owner_id") or "0")
        if not secret_owner_allowed(request, owner_type, owner_id):
            return Response(
                {"detail": "Secret owner is outside this workspace.", "code": "not_found"},
                status=status.HTTP_404_NOT_FOUND,
            )
        secret = vault_put(
            kind=request.data.get("kind") or Secret.Kind.API_TOKEN,
            owner_type=owner_type,
            owner_id=owner_id,
            plaintext=raw,
        )
        return Response(
            {"secret_id": secret.pk, "kind": secret.kind},
            status=status.HTTP_201_CREATED,
        )


class RotatePlanSerializer(serializers.Serializer):
    secret_id = serializers.IntegerField()
    kind = serializers.CharField()
    owner_type = serializers.CharField()
    owner_id = serializers.CharField()
    fingerprint = serializers.CharField()
    affected = serializers.ListField()
    allowed_actions = AllowedActionSerializer(many=True)
    disabled_actions = DisabledActionSerializer(many=True)


class RotatePlanView(HudAPIView):
    """Read-only rotation plan: names affected objects. Does not write a new version."""

    permission_classes = [IsAuthenticated, RequireAdminRead]

    @extend_schema(responses={200: RotatePlanSerializer})
    def get(self, request, pk):
        secret = get_object_or_404(workspace_secrets(request), pk=pk)
        row = secret_row(secret)
        affected = list(row["references"])
        if not affected:
            affected = [{
                "type": secret.owner_type,
                "id": str(secret.owner_id),
                "name": f"{secret.owner_type}:{secret.owner_id}",
            }]
        return Response(RotatePlanSerializer({
            "secret_id": secret.pk,
            "kind": secret.kind,
            "owner_type": secret.owner_type,
            "owner_id": secret.owner_id,
            "fingerprint": secret.fingerprint,
            "affected": affected,
            "allowed_actions": [],
            "disabled_actions": [{
                "id": "secret.rotate_activate",
                "code": "plan_only",
                "label": "Activate rotation",
                "reason": (
                    "Rotation names affected objects first; "
                    "activation is a separate replacement write."
                ),
            }],
        }).data)


class MembersView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request):
        from django_otp.plugins.otp_totp.models import TOTPDevice
        from django_otp_webauthn.models import WebAuthnCredential

        from core.models import RecoveryCode

        workspace = request_workspace(request)
        memberships = list(
            WorkspaceMembership.objects.filter(workspace=workspace)
            .select_related("user")
            .order_by("user__id")[:50]
        )
        membership = workspace_membership(request.user, workspace)
        if not memberships and getattr(membership, "is_bootstrap", False):
            memberships = [membership]
        results = []
        for row in memberships:
            u = row.user
            results.append({
                "id": u.pk,
                "username": u.username,
                "email": u.email or "",
                "role": row.role,
                "is_active": u.is_active,
                "passkeys": WebAuthnCredential.objects.filter(user=u, confirmed=True).count(),
                "totp": TOTPDevice.objects.filter(user=u, confirmed=True).exists(),
                "recovery_codes": RecoveryCode.objects.filter(user=u, used_at__isnull=True).count(),
                "last_login": u.last_login,
            })
        disabled = []
        if sum(row.role == "owner" for row in memberships) <= 1:
            disabled.append({
                "id": "member.retire",
                "code": "last_owner",
                "label": "Retire owner",
                "reason": "The last Owner cannot be retired.",
            })
        return Response({
            "results": results,
            "allowed_actions": [],
            "disabled_actions": disabled,
        })

    def post(self, request):
        data = request.data or {}
        username = data.get("username") or ""
        email = (data.get("email") or "").strip()
        role = (data.get("role") or "operator").strip()
        if role not in ROLES:
            return Response(
                {"detail": "Unknown role.", "code": "invalid_role"},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not username:
            return Response({"detail": "username is required"}, status=status.HTTP_400_BAD_REQUEST)
        denied = refuse_cap(request, "member.invite")
        if denied:
            return denied
        operation, _replayed = persist_command(
            request, "member.invite",
            idempotency_key=data.get("idempotency_key") or "",
            username=username, email=email, role=role,
        )
        return Response(
            {
                "invitation_id": f"inv-{operation.pk}",
                "username": username,
                "email": email,
                "role": role,
                "state": "queued",
                "operation_id": operation.pk,
                "status_url": f"/api/v1/hud/operations/{operation.pk}/",
            },
            status=status.HTTP_202_ACCEPTED,
        )

    def delete(self, request):
        workspace = request_workspace(request)
        owners = WorkspaceMembership.objects.filter(workspace=workspace, role="owner")
        if owners.count() <= 1:
            return Response(
                {"detail": "The last Owner cannot be retired.", "code": "last_owner"},
                status=status.HTTP_409_CONFLICT,
            )
        return Response({"detail": "Owner retirement is not enabled on this deployment."},
                        status=status.HTTP_400_BAD_REQUEST)
