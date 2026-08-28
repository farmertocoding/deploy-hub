from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from core.hud.common import (
    AllowedActionSerializer,
    DisabledActionSerializer,
    HudAPIView,
    authorized_action_lists,
    int_param,
    scope_purpose,
    scoped,
    site_environment,
    site_health,
    site_in_scope,
    site_releases,
    site_tls,
)
from core.hud.permissions import RequireAdminRead
from core.hud.ports import deploys
from core.models import Finding, Site

_SITE_SORTS = ("name", "project", "domain", "health", "target")


class SiteFleetRowSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    project = serializers.CharField()
    domain = serializers.CharField()
    health = serializers.CharField()
    environment = serializers.CharField()
    exposure = serializers.CharField()
    target = serializers.CharField(allow_blank=True)
    tls = serializers.CharField()
    backup = serializers.CharField(allow_blank=True)
    live_release = serializers.CharField(allow_blank=True)
    desired_release = serializers.CharField(allow_blank=True)
    active_deployment = serializers.IntegerField(allow_null=True)
    copies = serializers.IntegerField()
    owner = serializers.CharField(allow_blank=True)
    findings = serializers.IntegerField()
    last_deploy_at = serializers.DateTimeField(allow_null=True)
    last_deploy_actor = serializers.CharField(allow_blank=True)
    observed_at = serializers.DateTimeField()
    allowed_actions = AllowedActionSerializer(many=True)
    disabled_actions = DisabledActionSerializer(many=True)


class SiteFleetListSerializer(serializers.Serializer):
    observed_at = serializers.DateTimeField()
    results = SiteFleetRowSerializer(many=True)
    next = serializers.CharField(allow_null=True)
    page = serializers.IntegerField()
    sort = serializers.CharField()
    count = serializers.IntegerField()
    allowed_actions = AllowedActionSerializer(many=True)
    disabled_actions = DisabledActionSerializer(many=True)


class SitesFleetView(APIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    @extend_schema(operation_id="v1_hud_sites_list", responses={200: SiteFleetListSerializer})
    def get(self, request):
        q = (request.query_params.get("q") or "").strip().lower()
        health_filter = request.query_params.get("health") or ""
        facet = request.query_params.get("facet") or ""
        env_filter = request.query_params.get("env") or ""
        target_filter = (request.query_params.get("target") or "").strip().lower()
        tls_filter = request.query_params.get("tls") or ""
        sort = request.query_params.get("sort") or "name"
        reverse = sort.startswith("-")
        key = sort.lstrip("-")
        if key not in _SITE_SORTS:
            key, sort, reverse = "name", "name", False
        page = int_param(request, "page", 1, lo=1, hi=10_000)
        page_size = int_param(request, "page_size", 20, lo=1, hi=50)
        observed = timezone.now()
        rows = []
        purpose = scope_purpose(request)
        site_qs = scoped(request, Site.objects.all(), "project__workspace")
        if env_filter:
            site_qs = site_qs.filter(environment=env_filter)
        finding_qs = scoped(request, Finding.objects.all())
        collection_actions, collection_disabled = authorized_action_lists(
            request,
            [
                {"id": "site.create", "label": "ADD SITE"},
                {"id": "site.export_view", "label": "EXPORT VIEW"},
            ],
        )
        for site in site_qs.select_related(
            "project", "project__created_by", "created_by",
            "primary_target", "primary_target__zone", "dns_zone",
        ).prefetch_related("instances", "tls_certificates", "manifests", "backup_units"):
            if purpose and not site_in_scope(site, purpose):
                continue
            health = site_health(site)
            environment = site_environment(site)
            if health_filter and health != health_filter:
                continue
            host = site.primary_target.host if site.primary_target_id else ""
            if target_filter and target_filter not in host.lower():
                continue
            tls = site_tls(site)
            if tls_filter and tls != tls_filter:
                continue
            blob = f"{site.project.name} {site.name} {site.domain}".lower()
            if q and q not in blob:
                continue
            live_release, desired_release = site_releases(site)
            active = deploys.Deployment.objects.filter(
                manifest__site=site, status__in=["queued", "running"]
            ).order_by("-pk").first()
            finding_n = finding_qs.filter(entity__icontains=site.name, state="open").count()
            if facet == "needs_attention" and health == "healthy" and finding_n == 0:
                continue
            if facet == "active_deploy" and active is None:
                continue
            allowed = [
                {"id": "site.view_details", "label": "View site details"},
            ]
            if site.domain:
                allowed.append({"id": "site.open_live", "label": "Open live site"})
            if active:
                allowed.append({"id": "site.view_deploy", "label": "View deploy"})
            if finding_n:
                allowed.append({"id": "site.fix_blockers", "label": "Fix blockers"})
            allowed.append({"id": "site.deploy", "label": "Deploy"})
            allowed.append({"id": "site.more", "label": "More"})
            rows.append({
                "id": site.pk,
                "name": site.name,
                "project": site.project.name,
                "domain": site.domain,
                "health": health,
                "environment": environment,
                "exposure": site.exposure,
                "target": host,
                "tls": tls,
                "backup": "configured" if site.backup_units.exists() else "unknown",
                "live_release": live_release,
                "desired_release": desired_release,
                "active_deployment": active.pk if active else None,
                "copies": site.instances.count(),
                "owner": (
                    site.created_by.username if site.created_by_id else
                    (site.project.created_by.username if site.project.created_by_id else "")
                ),
                "findings": finding_n,
                "last_deploy_at": getattr(
                    deploys.Deployment.objects.filter(manifest__site=site).order_by("-pk").first(),
                    "last_heartbeat", None,
                ),
                "last_deploy_actor": "",
                "observed_at": observed,
                "allowed_actions": allowed,
                "disabled_actions": [{
                    "id": "site.delete",
                    "code": "not_permitted",
                    "label": "Delete",
                    "reason": "Sites are not deleted from this table.",
                }],
            })
        rows.sort(key=lambda r: (str(r.get(key) or "").lower(), r["id"]), reverse=reverse)
        count = len(rows)
        start = (page - 1) * page_size
        chunk = rows[start:start + page_size]
        nxt = str(page + 1) if start + page_size < count else None
        if request.query_params.get("export") == "csv":
            lines = ["project,name,domain,health"]
            lines.extend(
                f"{row['project']},{row['name']},{row['domain']},{row['health']}"
                for row in rows
            )
            return Response({
                "observed_at": observed,
                "csv": "\n".join(lines) + "\n",
                "filename": "sites.csv",
                "count": count,
                "results": [],
                "next": None,
                "page": page,
                "sort": sort,
                "allowed_actions": collection_actions,
                "disabled_actions": collection_disabled,
            })
        return Response(SiteFleetListSerializer({
            "observed_at": observed,
            "results": chunk,
            "next": nxt,
            "page": page,
            "sort": sort,
            "count": count,
            "allowed_actions": collection_actions,
            "disabled_actions": collection_disabled,
        }).data)


class SiteDetailView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    @extend_schema(operation_id="v1_hud_sites_retrieve")
    def get(self, request, pk):
        site = get_object_or_404(
            scoped(request, Site.objects.all(), "project__workspace").select_related(
                "project", "created_by", "primary_target", "dns_zone",
            ).prefetch_related("instances", "tls_certificates", "backup_units", "manifests"),
            pk=pk,
        )
        live, desired = site_releases(site)
        active = deploys.Deployment.objects.filter(
            manifest__site=site, status__in=["queued", "running"],
        ).order_by("-pk").first()
        return Response({
            "id": site.pk,
            "name": site.name,
            "project": site.project.name,
            "domain": site.domain,
            "environment": site_environment(site),
            "exposure": site.exposure,
            "health": site_health(site),
            "tls": site_tls(site),
            "backup": "configured" if site.backup_units.exists() else "unknown",
            "live_release": live,
            "desired_release": desired,
            "target": site.primary_target.host if site.primary_target_id else "",
            "copies": site.instances.count(),
            "owner": site.created_by.username if site.created_by_id else "",
            "deploy_strategy": site.deploy_strategy,
            "deploy_policy": site.deploy_policy,
            "deploy_window_cron": site.deploy_window_cron,
            "active_deployment": active.pk if active else None,
            "instances": [
                {
                    "id": inst.pk,
                    "target": inst.target.host if inst.target_id else "",
                    "desired_state": inst.desired_state,
                    "observed_state": inst.observed_state,
                    "observed_at": inst.observed_at,
                }
                for inst in site.instances.all()
            ],
            "manifests": [
                {"id": m.pk, "version": m.version, "created_at": m.created_at}
                for m in site.manifests.order_by("-version")[:20]
            ],
            "observed_at": timezone.now(),
            "allowed_actions": [{"id": "site.view_details", "label": "View site details"}],
            "disabled_actions": [{
                "id": "site.delete",
                "code": "not_permitted",
                "label": "Delete",
                "reason": "Sites are not deleted from this table.",
            }],
            "tabs": [
                "overview", "configuration", "environment", "releases",
                "instances", "backups", "adoption", "activity", "removal",
            ],
        })
