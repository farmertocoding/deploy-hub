"""One HUD command dispatcher. Resource views are catalogs, not copy-pasted posts."""
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.actions import ACTION_TIERS
from core.hud.common import (
    accepted,
    aws_configured,
    idempotency_key,
    persist_command,
    refuse_cap,
    scoped,
)
from core.hud.permissions import RequireAdminRead
from core.models import (
    DnsAccount,
    Finding,
    HudOperation,
    NetworkZone,
    Partner,
    Project,
    Site,
    Target,
)
from core.permissions import RequireRecentTouch
from core.rbac import request_workspace


def replay_if_any(request, action):
    key = idempotency_key(request)
    if not key:
        return None
    prev = HudOperation.objects.filter(
        workspace=request_workspace(request), actor=request.user,
        action=action, idempotency_key=key,
    ).order_by("-pk").first()
    if not prev:
        return None
    return accepted(action, {
        "operation_id": prev.pk,
        "object_id": prev.object_id,
        "state": prev.state,
        "replayed": True,
    })


class Command:
    action = ""
    object_type = ""
    topic = "hud.command.recorded"

    def resolve(self, request, pk, data):
        return None

    def validate(self, request, obj, data):
        return None

    def apply(self, request, obj, data):
        return str(getattr(obj, "pk", "") or ""), {}


class ProjectScan(Command):
    action = "project.scan"
    object_type = "project"
    topic = "hud.project.scan"

    def resolve(self, request, pk, data):
        return get_object_or_404(scoped(request, Project.objects.all()), pk=pk)


class TargetCreate(Command):
    action = "target.create"
    object_type = "target"

    def validate(self, request, obj, data):
        host = str(data.get("host") or "").strip()
        zone_id = data.get("zone_id")
        if not host or not zone_id:
            return Response(
                {"detail": "host and zone_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return None

    def apply(self, request, obj, data):
        zone = get_object_or_404(
            scoped(request, NetworkZone.objects.all()), pk=data.get("zone_id"),
        )
        target = Target.objects.create(
            zone=zone,
            host=str(data.get("host") or "").strip(),
            kind=data.get("kind") or Target.Kind.SSH,
        )
        return str(target.pk), {"object_id": target.pk, "state": "queued"}


class TargetProbe(Command):
    action = "target.probe"
    object_type = "target"
    topic = "hud.target.probe"

    def resolve(self, request, pk, data):
        return get_object_or_404(
            scoped(request, Target.objects.all(), "zone__workspace"), pk=pk,
        )


class FindingAck(Command):
    action = "finding.ack"
    object_type = "finding"

    def resolve(self, request, pk, data):
        return get_object_or_404(scoped(request, Finding.objects.all()), pk=pk)

    def apply(self, request, obj, data):
        from core import findings as findings_service

        findings_service.ack(obj, actor=request.user, source="api")
        return str(obj.pk), {"object_id": obj.pk, "state": obj.state}


class PartnerCreate(Command):
    action = "partner.create"
    object_type = "partner"

    def validate(self, request, obj, data):
        slug = str(data.get("slug") or "").strip()
        if not slug:
            return Response({"detail": "slug is required."}, status=status.HTTP_400_BAD_REQUEST)
        if scoped(request, Partner.objects.all()).filter(slug=slug).exists():
            return Response(
                {"detail": "Partner slug already exists."},
                status=status.HTTP_409_CONFLICT,
            )
        return None

    def apply(self, request, obj, data):
        slug = str(data.get("slug") or "").strip()
        name = str(data.get("name") or slug).strip()
        partner = Partner.objects.create(
            workspace=request_workspace(request), slug=slug, name=name or slug,
        )
        return str(partner.pk), {"object_id": partner.pk, "state": "queued"}


class IntegrationVerify(Command):
    object_type = "integration"
    topic = "hud.integration.verify"

    def __init__(self, action):
        self.action = action

    def validate(self, request, obj, data):
        accounts = scoped(request, DnsAccount.objects.all())
        if self.action == "aws.verify" and not aws_configured(request):
            return Response(
                {"detail": "AWS credentials are not configured."},
                status=status.HTTP_409_CONFLICT,
            )
        if (
            self.action == "cloudflare.verify"
            and not accounts.filter(provider="cloudflare").exists()
        ):
            return Response(
                {"detail": "No Cloudflare account is configured."},
                status=status.HTTP_409_CONFLICT,
            )
        if self.action == "dns.verify" and not accounts.exists():
            return Response(
                {"detail": "No DNS account is configured."},
                status=status.HTTP_409_CONFLICT,
            )
        if self.action == "integration.verify" and not (
            accounts.exists() or aws_configured(request)
        ):
            return Response(
                {"detail": "No integration is configured to verify."},
                status=status.HTTP_409_CONFLICT,
            )
        return None

    def apply(self, request, obj, data):
        return "", {"state": "queued"}


class SiteCreate(Command):
    action = "site.create"
    object_type = "site"

    def validate(self, request, obj, data):
        name = str(data.get("name") or "").strip()
        project_id = data.get("project_id")
        if not name or not project_id:
            return Response(
                {"detail": "name and project_id are required."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        exposure = data.get("exposure") or Site.Exposure.MESH_ONLY
        dns_zone_id = data.get("dns_zone_id")
        if exposure != Site.Exposure.MESH_ONLY and not dns_zone_id:
            return Response(
                {"detail": "dns_zone_id is required for public sites."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if dns_zone_id and not scoped(request, DnsAccount.objects.all()).filter(
            zones__pk=dns_zone_id,
        ).exists():
            return Response({"detail": "DNS zone not found."}, status=status.HTTP_404_NOT_FOUND)
        return None

    def apply(self, request, obj, data):
        project = get_object_or_404(
            scoped(request, Project.objects.all()), pk=data.get("project_id"),
        )
        environment = (data.get("environment") or "").strip() or Site.Environment.PRODUCTION
        if environment not in Site.Environment.values:
            environment = Site.Environment.PRODUCTION
        site = Site.objects.create(
            project=project,
            name=str(data.get("name") or "").strip(),
            exposure=data.get("exposure") or Site.Exposure.MESH_ONLY,
            environment=environment,
            dns_zone_id=data.get("dns_zone_id") or None,
            created_by=request.user,
        )
        return str(site.pk), {"object_id": site.pk, "state": "queued"}


_T1_ACTIONS = {row["id"] for row in ACTION_TIERS if row["tier"] == "T1"}
_T1_ACTIONS.add("target.create")


class CommandSerializer(serializers.Serializer):
    action = serializers.CharField()


class CommandView(APIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]
    serializer_class = CommandSerializer
    catalog = {}

    def post(self, request, pk=None):
        action = (request.data or {}).get("action")
        cmd = self.catalog.get(action)
        if cmd is None:
            return Response(
                {"detail": "Action is not authorized."},
                status=status.HTTP_403_FORBIDDEN,
            )
        denied = refuse_cap(request, action)
        if denied:
            return denied
        if action in _T1_ACTIONS:
            perm = RequireRecentTouch()
            if not perm.has_permission(request, self):
                return Response(
                    {"detail": perm.message, "code": "touch_required"},
                    status=status.HTTP_403_FORBIDDEN,
                )
        replay = replay_if_any(request, action)
        if replay:
            return replay
        data = request.data or {}
        obj = cmd.resolve(request, pk, data)
        error = cmd.validate(request, obj, data)
        if error is not None:
            return error
        object_id, extra = cmd.apply(request, obj, data)
        operation, _replayed = persist_command(
            request,
            cmd.action,
            object_type=cmd.object_type,
            object_id=object_id,
            topic=cmd.topic,
            idempotency_key=idempotency_key(request),
        )
        extra.setdefault("operation_id", operation.pk)
        extra.setdefault("object_id", extra.get("object_id", object_id))
        extra.setdefault("state", extra.get("state", "queued"))
        return accepted(cmd.action, extra)


class ProjectCommandView(CommandView):
    catalog = {"project.scan": ProjectScan()}


class TargetCommandView(CommandView):
    catalog = {
        "target.create": TargetCreate(),
        "target.probe": TargetProbe(),
    }

    @extend_schema(operation_id="v1_hud_targets_item_commands_create")
    def post(self, request, pk=None):
        return super().post(request, pk)


class TargetCollectionCommandView(TargetCommandView):
    @extend_schema(operation_id="v1_hud_targets_collection_commands_create")
    def post(self, request, pk=None):
        return super().post(request, pk)


class FindingCommandView(CommandView):
    catalog = {"finding.ack": FindingAck()}


class PartnerCommandView(CommandView):
    catalog = {"partner.create": PartnerCreate()}


class IntegrationCommandView(CommandView):
    catalog = {
        action: IntegrationVerify(action)
        for action in (
            "integration.verify", "aws.verify", "cloudflare.verify", "dns.verify",
        )
    }


class SiteCommandView(CommandView):
    catalog = {"site.create": SiteCreate()}
