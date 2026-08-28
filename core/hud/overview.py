from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.hud.common import (
    AllowedActionSerializer,
    DisabledActionSerializer,
    authorized_action_lists,
    scoped,
    site_health,
    target_readiness,
    vault_status,
)
from core.hud.permissions import RequireAdminRead
from core.hud.ports import deploys
from core.models import DnsAccount, Finding, OperationLock, Site, Target
from core.rbac import request_workspace


class OverviewSerializer(serializers.Serializer):
    observed_at = serializers.DateTimeField()
    version = serializers.IntegerField()
    findings = serializers.DictField(child=serializers.IntegerField())
    deployments = serializers.DictField(child=serializers.IntegerField())
    site_health = serializers.DictField(child=serializers.IntegerField())
    target_readiness = serializers.DictField(child=serializers.IntegerField())
    attention = serializers.ListField()
    active_deployments = serializers.ListField()
    integrations = serializers.DictField()
    setup = serializers.ListField()
    links = serializers.DictField()
    allowed_actions = AllowedActionSerializer(many=True)
    disabled_actions = DisabledActionSerializer(many=True)


class OverviewView(APIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    @extend_schema(responses={200: OverviewSerializer})
    def get(self, request):
        observed = timezone.now()
        finding_qs = scoped(request, Finding.objects.all())
        lock_qs = scoped(request, OperationLock.objects.all())
        deployment_qs = scoped(
            request, deploys.Deployment.objects.all(), "manifest__site__project__workspace",
        )
        site_qs = scoped(request, Site.objects.all(), "project__workspace")
        target_qs = scoped(request, Target.objects.all(), "zone__workspace")
        dns_account_qs = scoped(request, DnsAccount.objects.all())
        findings = {
            "p1": finding_qs.filter(severity="p1", state="open").count(),
            "p2": finding_qs.filter(severity="p2", state="open").count(),
            "p3": finding_qs.filter(severity="p3", state="open").count(),
            "open": finding_qs.filter(state="open").count(),
        }
        waiting = lock_qs.filter(kind=OperationLock.Kind.DEPLOY).count()
        deployments = {
            "active": deployment_qs.filter(status__in=["queued", "running"]).count(),
            "queued": deployment_qs.filter(status="queued").count(),
            "running": deployment_qs.filter(status="running").count(),
            "waiting_for_lock": waiting,
            "failed": deployment_qs.filter(status="failed").count(),
        }
        health_counts = {"healthy": 0, "warming": 0, "unhealthy": 0, "stale": 0}
        for site in site_qs.prefetch_related("instances").select_related("primary_target"):
            key = site_health(site)
            health_counts[key] = health_counts.get(key, 0) + 1
        readiness = {"ready": 0, "pressured": 0, "unreachable": 0, "decommissioned": 0}
        for target in target_qs:
            key = target_readiness(target)
            readiness[key] = readiness.get(key, 0) + 1
        attention = [
            {
                "id": f"finding-{f.pk}",
                "severity": f.severity,
                "title": f.title,
                "href": f"#/findings/{f.pk}",
            }
            for f in finding_qs.filter(state="open").order_by("severity")[:10]
        ]
        active = []
        for dep in deployment_qs.filter(
            status__in=["queued", "running"],
        ).select_related("manifest__site")[:10]:
            current = dep.steps.exclude(status="succeeded").order_by("seq").first()
            active.append({
                "id": dep.pk,
                "site": f"{dep.manifest.site.project.name}/{dep.manifest.site.name}",
                "version": dep.manifest.version,
                "state": dep.status,
                "current_step": current.name if current else "",
            })
        allowed, disabled = authorized_action_lists(
            request, [{"id": "project.create", "label": "ADD APPLICATION"}],
        )
        body = {
            "observed_at": observed,
            "version": 1,
            "findings": findings,
            "deployments": deployments,
            "site_health": health_counts,
            "target_readiness": readiness,
            "attention": attention,
            "active_deployments": active,
            "integrations": {
                "cloudflare": (
                    "connected"
                    if dns_account_qs.filter(provider="cloudflare").exists()
                    else "missing"
                ),
                "aws": "unknown",
                "vault": vault_status(request),
                "notifications": "unknown",
            },
            "setup": [] if target_qs.filter(status="ready").exists() else [
                {"id": "enroll", "title": "Enroll a target", "href": "targets"},
            ],
            "links": {
                "findings": "#/admin/findings",
                "deploys": "#/admin/deployments",
                "sites": "#/admin/sites",
                "targets": "#/admin/targets",
            },
            "allowed_actions": allowed,
            "disabled_actions": disabled,
            "workspace": {
                "id": request_workspace(request).pk,
                "slug": request_workspace(request).slug,
            },
        }
        return Response(OverviewSerializer(body).data)
