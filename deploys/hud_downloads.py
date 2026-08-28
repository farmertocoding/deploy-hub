"""Short-lived, actor-bound deployment log and artifact downloads."""
import re
from datetime import timedelta
from io import BytesIO

from django.conf import settings
from django.core import signing
from django.http import FileResponse
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.audit import audit
from core.hud.permissions import RequireAdminRead
from core.rbac import request_workspace, scope_queryset
from deploys.models import Deployment, DeploymentArtifact, DeploymentStep

SIGNING_SALT = "deploy-hub.hud-download.v1"


class DownloadGrantSerializer(serializers.Serializer):
    resource = serializers.ChoiceField(choices=("log", "artifact"))
    step = serializers.ChoiceField(
        choices=DeploymentStep.Name.values, required=False, allow_blank=True,
    )
    artifact_id = serializers.IntegerField(required=False, min_value=1)

    def validate(self, attrs):
        if attrs["resource"] == "artifact" and not (
            attrs.get("artifact_id") or attrs.get("step")
        ):
            raise serializers.ValidationError(
                "artifact_id or step is required for an artifact download.",
            )
        if attrs["resource"] == "log" and attrs.get("artifact_id"):
            raise serializers.ValidationError("artifact_id is not valid for a log download.")
        return attrs


def _deployment_queryset(request):
    return scope_queryset(
        Deployment.objects.select_related("manifest__site__project"),
        request_workspace(request),
        "manifest__site__project__workspace",
    )


class DeploymentDownloadGrantView(APIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]
    serializer_class = DownloadGrantSerializer

    def post(self, request, pk):
        deployment = get_object_or_404(_deployment_queryset(request), pk=pk)
        serializer = DownloadGrantSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if data.get("artifact_id") and not DeploymentArtifact.objects.filter(
            pk=data["artifact_id"], deployment=deployment,
        ).exists():
            # Do not reveal whether an artifact exists on another deployment.
            return Response({"detail": "Artifact not found."}, status=status.HTTP_404_NOT_FOUND)
        if data.get("step") and not DeploymentStep.objects.filter(
            deployment=deployment, name=data["step"],
        ).exists():
            return Response({"detail": "Step not found."}, status=status.HTTP_404_NOT_FOUND)

        ttl = int(getattr(settings, "HUD_SIGNED_DOWNLOAD_TTL_SECONDS", 60))
        claims = {
            "v": 1,
            "user_id": request.user.pk,
            "workspace_id": request_workspace(request).pk,
            "deployment_id": deployment.pk,
            "resource": data["resource"],
            "step": data.get("step") or "",
            "artifact_id": data.get("artifact_id") or None,
        }
        token = signing.dumps(claims, salt=SIGNING_SALT, compress=True)
        event = audit(
            "deployment-download-granted",
            deployment,
            actor=request.user,
            source="api",
            resource=data["resource"],
            step=claims["step"],
            artifact_id=claims["artifact_id"],
            expires_in_seconds=ttl,
        )
        event.workspace = request_workspace(request)
        event.save(update_fields=["workspace"])
        return Response({
            "url": f"/api/v1/hud/downloads/{token}/",
            "expires_at": timezone.now() + timedelta(seconds=ttl),
            "expires_in_seconds": ttl,
        })


class SignedDeploymentDownloadView(APIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]
    serializer_class = serializers.Serializer

    def get(self, request, token):
        ttl = int(getattr(settings, "HUD_SIGNED_DOWNLOAD_TTL_SECONDS", 60))
        try:
            claims = signing.loads(token, salt=SIGNING_SALT, max_age=ttl)
        except signing.SignatureExpired:
            return Response(
                {"detail": "Download link expired.", "code": "download_expired"},
                status=status.HTTP_410_GONE,
            )
        except signing.BadSignature:
            return Response({"detail": "Download not found."}, status=status.HTTP_404_NOT_FOUND)

        workspace = request_workspace(request)
        if (
            claims.get("v") != 1
            or claims.get("user_id") != request.user.pk
            or claims.get("workspace_id") != workspace.pk
        ):
            return Response({"detail": "Download not found."}, status=status.HTTP_404_NOT_FOUND)
        deployment = get_object_or_404(
            _deployment_queryset(request), pk=claims.get("deployment_id"),
        )
        try:
            body, filename, content_type = _render_download(deployment, claims)
        except (DeploymentArtifact.DoesNotExist, DeploymentStep.DoesNotExist):
            return Response({"detail": "Download not found."}, status=status.HTTP_404_NOT_FOUND)
        max_bytes = int(getattr(settings, "HUD_DOWNLOAD_MAX_BYTES", 10 * 1024 * 1024))
        encoded = body.encode("utf-8")
        if len(encoded) > max_bytes:
            return Response(
                {
                    "detail": "Download exceeds the configured size limit.",
                    "code": "download_too_large",
                },
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        event = audit(
            "deployment-download-completed",
            deployment,
            actor=request.user,
            source="api",
            resource=claims["resource"],
            step=claims.get("step") or "",
            artifact_id=claims.get("artifact_id"),
            bytes=len(encoded),
        )
        event.workspace = workspace
        event.save(update_fields=["workspace"])
        response = FileResponse(
            BytesIO(encoded), as_attachment=True, filename=filename,
            content_type=content_type,
        )
        response["Cache-Control"] = "private, no-store, max-age=0"
        response["Pragma"] = "no-cache"
        response["X-Content-Type-Options"] = "nosniff"
        return response


def _render_download(deployment, claims):
    step_name = claims.get("step") or ""
    if claims["resource"] == "log":
        if step_name:
            step = DeploymentStep.objects.get(deployment=deployment, name=step_name)
            body = step.log_text
            filename = f"deployment-{deployment.pk}-{_safe_name(step.name)}.log"
        else:
            rows = DeploymentStep.objects.filter(deployment=deployment).order_by("seq")
            body = "\n".join(f"## {row.name}\n{row.log_text}" for row in rows)
            filename = f"deployment-{deployment.pk}.log"
        return body, filename, "text/plain; charset=utf-8"

    artifact_id = claims.get("artifact_id")
    if artifact_id:
        artifact = DeploymentArtifact.objects.get(pk=artifact_id, deployment=deployment)
        return (
            artifact.content,
            f"deployment-{deployment.pk}-{_safe_name(artifact.kind)}.txt",
            "text/plain; charset=utf-8",
        )
    step = DeploymentStep.objects.get(deployment=deployment, name=step_name)
    return (
        signing.JSONSerializer().dumps(step.artifacts).decode("latin1"),
        f"deployment-{deployment.pk}-{_safe_name(step.name)}-artifacts.json",
        "application/json",
    )


def _safe_name(value):
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", str(value)).strip("-.") or "artifact"
