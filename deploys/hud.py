from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.hud.common import (
    AllowedActionSerializer,
    DisabledActionSerializer,
    authorized_action_lists,
    idempotency_key,
    refuse_cap,
    scoped,
)
from core.hud.permissions import RequireAdminRead
from deploys.models import Deployment
from deploys.pipeline import release_deploy_locks


def previous_succeeded(dep):
    return (
        Deployment.objects.filter(
            manifest__site=dep.manifest.site,
            status=Deployment.Status.SUCCEEDED,
        )
        .exclude(pk=dep.pk)
        .select_related("manifest")
        .order_by("-pk")
        .first()
    )


def named_previous(dep):
    prev = previous_succeeded(dep)
    if not prev:
        return None
    return f"v{prev.manifest.version}"


def fill_steps(dep):
    from core.hud.common import STEP_NAMES

    by_name = {s.name: s for s in dep.steps.all()}
    out = []
    for name in STEP_NAMES:
        step = by_name.get(name)
        duration = None
        if step and step.started and step.finished:
            duration = (step.finished - step.started).total_seconds()
        out.append({
            "name": name,
            "state": step.status if step else "pending",
            "started": step.started if step else None,
            "finished": step.finished if step else None,
            "duration_s": duration,
        })
    return out


def deploy_actions(dep):
    allowed = []
    disabled = []
    previous = named_previous(dep)
    if dep.status == Deployment.Status.QUEUED:
        allowed.append({"id": "deployment.cancel", "label": "Cancel queued"})
    elif dep.status == Deployment.Status.RUNNING:
        allowed.append({"id": "deployment.abort", "label": "Abort and clean up"})
    elif dep.status == Deployment.Status.FAILED:
        allowed.append({"id": "deployment.retry", "label": "Retry from failed step"})
        if previous:
            allowed.append({
                "id": "deployment.rollback",
                "label": f"Roll back to {previous}",
            })
        else:
            disabled.append({
                "id": "deployment.rollback",
                "code": "no_named_release",
                "label": "Roll back",
                "reason": "No named previous release is available.",
            })
    allowed.append({"id": "site.view_health", "label": "View site health"})
    return allowed, disabled, previous


class DeploymentDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    site = serializers.CharField()
    site_id = serializers.IntegerField()
    version = serializers.IntegerField()
    state = serializers.CharField()
    headline = serializers.CharField()
    live_release = serializers.CharField(allow_blank=True)
    desired_release = serializers.CharField()
    previous_release = serializers.CharField(allow_blank=True, allow_null=True)
    target = serializers.CharField(allow_blank=True)
    observed_at = serializers.DateTimeField()
    heartbeat_at = serializers.DateTimeField(allow_null=True)
    safe_next = serializers.CharField(allow_blank=True)
    safe_next_reason = serializers.CharField(allow_blank=True)
    log_text = serializers.CharField(allow_blank=True)
    log_cursor = serializers.IntegerField()
    log_truncated = serializers.BooleanField()
    artifacts = serializers.ListField()
    steps = serializers.ListField()
    allowed_actions = AllowedActionSerializer(many=True)
    disabled_actions = DisabledActionSerializer(many=True)


class DeploymentListSerializer(serializers.Serializer):
    observed_at = serializers.DateTimeField()
    results = serializers.ListField()


class DeploymentsView(APIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    @extend_schema(
        operation_id="v1_hud_deployments_list",
        responses={200: DeploymentListSerializer},
    )
    def get(self, request):
        observed = timezone.now()
        results = []
        facet = request.query_params.get("facet") or ""
        deployments = scoped(
            request, Deployment.objects.all(), "manifest__site__project__workspace",
        )
        for dep in deployments.select_related("manifest__site__project")[:100]:
            if facet == "active" and dep.status not in ("queued", "running"):
                continue
            if facet == "needs_attention" and dep.status not in ("failed", "running"):
                continue
            current = dep.steps.exclude(status="succeeded").order_by("seq").first()
            results.append({
                "id": dep.pk,
                "site": f"{dep.manifest.site.project.name}/{dep.manifest.site.name}",
                "version": dep.manifest.version,
                "state": dep.status,
                "current_step": current.name if current else "",
                "observed_at": observed,
                "allowed_actions": [{"id": "deployment.view", "label": "Open"}],
                "disabled_actions": [],
            })
        return Response({
            "observed_at": observed,
            "results": results,
            "allowed_actions": [],
            "disabled_actions": [],
        })


class DeploymentDetailView(APIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    @extend_schema(
        operation_id="v1_hud_deployments_retrieve",
        responses={200: DeploymentDetailSerializer},
    )
    def get(self, request, pk):
        dep = get_object_or_404(
            scoped(
                request, Deployment.objects.all(),
                "manifest__site__project__workspace",
            ).select_related("manifest__site__project", "manifest__site__primary_target"),
            pk=pk,
        )
        allowed, disabled, previous = deploy_actions(dep)
        allowed, disabled = authorized_action_lists(request, allowed, disabled)
        from deploys.failure_impact import OLD_VERSION_SERVING
        steps = fill_steps(dep)
        log_parts = [s.log_text for s in dep.steps.all() if getattr(s, "log_text", "")]
        artifacts = [
            {"kind": a.kind, "id": a.pk}
            for a in dep.text_artifacts.all()
        ]
        for step in dep.steps.all():
            if step.artifacts:
                artifacts.append({"kind": f"step:{step.name}", "payload": step.artifacts})
        if dep.status == Deployment.Status.FAILED:
            safe_next, reason = "deployment.retry", "Retry from the failed step."
            if previous:
                safe_next, reason = (
                    "deployment.rollback",
                    f"Named previous release {previous} is available.",
                )
        elif dep.status == Deployment.Status.RUNNING:
            safe_next, reason = "deployment.abort", "Abort and clean up the running attempt."
        elif dep.status == Deployment.Status.QUEUED:
            safe_next, reason = "deployment.cancel", "Cancel before the worker starts."
        else:
            safe_next, reason = "", "No mutating next step is required."
        log_text = "\n".join(log_parts)
        body = {
            "id": dep.pk,
            "site": f"{dep.manifest.site.project.name}/{dep.manifest.site.name}",
            "site_id": dep.manifest.site_id,
            "version": dep.manifest.version,
            "state": dep.status,
            "headline": (
                OLD_VERSION_SERVING if dep.status != "succeeded"
                else "Desired release is serving."
            ),
            "live_release": (
                f"v{dep.manifest.version}"
                if dep.status == Deployment.Status.SUCCEEDED
                else (previous or "")
            ),
            "desired_release": f"v{dep.manifest.version}",
            "previous_release": previous or "",
            "target": (
                dep.manifest.site.primary_target.host
                if dep.manifest.site.primary_target_id else ""
            ),
            "observed_at": timezone.now(),
            "heartbeat_at": dep.last_heartbeat,
            "safe_next": safe_next,
            "safe_next_reason": reason,
            "log_text": log_text,
            "log_cursor": len(log_text),
            "log_truncated": False,
            "artifacts": artifacts,
            "steps": steps,
            "allowed_actions": allowed,
            "disabled_actions": disabled,
        }
        return Response(DeploymentDetailSerializer(body).data)


class DeploymentCommandSerializer(serializers.Serializer):
    action = serializers.CharField()


def record_deployment_operation(request, action, deployment, *, enqueue=False, source=None):
    from core.hud.operations import create_operation

    operation, replayed = create_operation(
        request,
        action,
        object_type="deployment",
        object_id=deployment.pk,
        idempotency_key=idempotency_key(request),
        topic="hud.deployment.enqueue" if enqueue else "hud.command.recorded",
        audit_detail={"source_deployment_id": getattr(source, "pk", None)},
    )
    return {
        "command_operation_id": operation.pk,
        "operation_status_url": f"/api/v1/hud/operations/{operation.pk}/",
        "replayed": replayed,
    }


class DeploymentCommandView(APIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    @extend_schema(request=DeploymentCommandSerializer, responses={202: None})
    def post(self, request, pk):
        dep = get_object_or_404(
            scoped(request, Deployment.objects.all(), "manifest__site__project__workspace"),
            pk=pk,
        )
        ser = DeploymentCommandSerializer(data=request.data)
        ser.is_valid(raise_exception=True)
        action = ser.validated_data["action"]
        denied = refuse_cap(request, action)
        if denied:
            return denied
        allowed, _disabled, previous = deploy_actions(dep)
        allowed_ids = {a["id"] for a in allowed}
        if action not in allowed_ids:
            return Response(
                {"detail": "Action is not authorized for this deployment.", "code": "not_allowed"},
                status=status.HTTP_403_FORBIDDEN,
            )
        if action == "deployment.cancel" and dep.status == Deployment.Status.QUEUED:
            dep.status = Deployment.Status.CANCELLED
            dep.save(update_fields=["status"])
        elif action == "deployment.abort" and dep.status == Deployment.Status.RUNNING:
            dep.status = Deployment.Status.CANCELLED
            dep.save(update_fields=["status"])
            release_deploy_locks(dep)
        elif action == "deployment.retry" and dep.status == Deployment.Status.FAILED:
            created = Deployment.objects.create(
                manifest=dep.manifest, status=Deployment.Status.QUEUED,
            )
            command = record_deployment_operation(
                request, action, created, enqueue=True, source=dep,
            )
            return Response(
                {
                    "operation_id": created.pk,
                    "state": created.status,
                    "status_url": f"/api/v1/hud/deployments/{created.pk}/",
                    **command,
                },
                status=status.HTTP_202_ACCEPTED,
            )
        elif action == "deployment.rollback":
            prev = previous_succeeded(dep)
            if not prev:
                return Response(
                    {"detail": "Rollback target must be a named previous release."},
                    status=status.HTTP_409_CONFLICT,
                )
            created = Deployment.objects.create(
                manifest=prev.manifest,
                status=Deployment.Status.QUEUED,
                rollback_of=dep,
            )
            command = record_deployment_operation(
                request, action, created, enqueue=True, source=dep,
            )
            return Response(
                {
                    "operation_id": created.pk,
                    "state": created.status,
                    "rollback_target": f"v{prev.manifest.version}",
                    "status_url": f"/api/v1/hud/deployments/{created.pk}/",
                    **command,
                },
                status=status.HTTP_202_ACCEPTED,
            )
        else:
            return Response({"detail": "Unknown action."}, status=status.HTTP_400_BAD_REQUEST)
        command = record_deployment_operation(request, action, dep, source=dep)
        return Response(
            {"operation_id": dep.pk, "state": dep.status, **command},
            status=status.HTTP_202_ACCEPTED,
        )
