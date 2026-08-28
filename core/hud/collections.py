from django.conf import settings as dj_settings
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import get_object_or_404
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from core.hud.common import (
    HudAPIView,
    authorized_action_lists,
    collection,
    persist_command,
    refuse_cap,
    scoped,
    target_readiness,
    workspace_secrets,
)
from core.hud.permissions import RequireAdminRead
from core.hud.ports import FleetRefuse, wizard
from core.models import (
    AuditEvent,
    DnsAccount,
    Finding,
    HudOperation,
    OperationLock,
    Partner,
    Project,
    Site,
    Target,
)
from core.rbac import has_capability, request_workspace


class ProjectsView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request):
        rows = []
        for project in scoped(request, Project.objects.all()).prefetch_related("sites")[:200]:
            rows.append({
                "id": project.pk,
                "name": project.name,
                "slug": project.slug,
                "source_kind": project.source_kind,
                "source": project.git_url or project.local_path,
                "scan_state": "scanned" if project.scanned_at else "never_scanned",
                "sites": project.sites.count(),
                "observed_at": timezone.now(),
                "allowed_actions": [
                    {"id": "project.open", "label": "Open"},
                    {"id": "project.scan", "label": "Scan now"},
                ],
                "disabled_actions": [{
                    "id": "project.delete",
                    "code": "has_sites",
                    "label": "Delete permanently",
                    "reason": "Sites still exist.",
                }] if project.sites.exists() else [],
            })
        allowed, disabled = authorized_action_lists(
            request, [{"id": "project.create", "label": "ADD APPLICATION"}],
        )
        return collection(rows, allowed=allowed, disabled=disabled)

    def post(self, request):
        denied = refuse_cap(request, "project.create")
        if denied:
            return denied
        ser = wizard.ProjectCreateSerializer(data=request.data or {})
        ser.is_valid(raise_exception=True)
        try:
            project = wizard.create_project(
                ser.validated_data,
                user=request.user,
                workspace=request_workspace(request),
            )
        except FleetRefuse as exc:
            return exc.response
        persist_command(
            request, "project.create",
            object_type="project", object_id=str(project.pk),
        )
        return Response(wizard.project_row_body(project), status=status.HTTP_201_CREATED)


class TargetsAdminView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request):
        rows = []
        targets = scoped(request, Target.objects.all(), "zone__workspace")
        for target in targets.select_related("zone")[:200]:
            hosted = target.primary_for_sites.count()
            allowed = [
                {"id": "target.open", "label": "Open"},
                {"id": "target.probe", "label": "Probe router"},
            ]
            disabled = []
            if hosted:
                disabled.append({
                    "id": "target.decommission",
                    "code": "has_workloads",
                    "label": "Decommission Target",
                    "reason": "Workloads still scheduled.",
                })
            else:
                allowed.append({"id": "target.decommission", "label": "Decommission Target"})
            rows.append({
                "id": target.pk,
                "host": target.host,
                "kind": target.kind,
                "zone": target.zone.name if target.zone_id else "",
                "status": (
                    target_readiness(target)
                    if target.status != Target.Status.READY else "ready"
                ),
                "lifecycle": target.lifecycle,
                "sites": hosted,
                "observed_at": timezone.now(),
                "allowed_actions": allowed,
                "disabled_actions": disabled,
            })
        allowed, disabled = authorized_action_lists(
            request, [{"id": "target.create", "label": "Create Target"}],
        )
        return collection(rows, allowed=allowed, disabled=disabled)


class FindingsAdminView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request):
        facet = request.query_params.get("facet") or ""
        entity = (request.query_params.get("entity") or "").strip().lower()
        rows = []
        qs = scoped(request, Finding.objects.all()).order_by("severity", "-last_seen")[:200]
        for finding in qs:
            if facet == "p1p2" and finding.severity not in ("p1", "p2"):
                continue
            if entity and entity not in (finding.entity or "").lower():
                continue
            allowed, disabled = authorized_action_lists(
                request,
                [
                    {"id": "finding.open", "label": "Open"},
                    {"id": "finding.ack", "label": "Ack"},
                ],
            )
            rows.append({
                "id": finding.pk,
                "severity": finding.severity,
                "state": finding.state,
                "title": finding.title,
                "entity": finding.entity,
                "source_engine": finding.source_engine,
                "fingerprint": finding.fingerprint,
                "observed_at": timezone.now(),
                "allowed_actions": allowed,
                "disabled_actions": disabled,
            })
        now = timezone.now()
        locks = []
        for lock in scoped(request, OperationLock.objects.all())[:20]:
            acquired = lock.acquired_at
            age = (now - acquired).total_seconds() if acquired else None
            locks.append({
                "id": f"lock-{lock.pk}",
                "kind": lock.kind,
                "state": "held",
                "object": f"{lock.scope}:{lock.object_id}",
                "holder": lock.holder,
                "acquired_at": acquired,
                "heartbeat_at": lock.heartbeat_at,
                "age_s": age,
            })
        return collection(rows, extra={"operations": locks})


class PartnersAdminView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request):
        rows = []
        for partner in scoped(request, Partner.objects.all())[:200]:
            site_names = [ps.site.name for ps in partner.partner_sites.select_related("site")[:20]]
            rows.append({
                "id": partner.pk,
                "slug": partner.slug,
                "name": partner.name,
                "suspended": partner.suspended,
                "sites": partner.partner_sites.count(),
                "affected_sites": site_names,
                "intake": "degraded" if not partner.webhook_url else "configured",
                "observed_at": timezone.now(),
                "allowed_actions": [
                    {"id": "partner.open", "label": "Open"},
                    {"id": "partner.view_sites", "label": "View Sites"},
                ],
                "disabled_actions": [],
            })
        allowed, disabled = authorized_action_lists(
            request, [{"id": "partner.create", "label": "Create Partner"}],
        )
        return collection(rows, allowed=allowed, disabled=disabled)


class IntegrationsView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request):
        accounts = list(scoped(request, DnsAccount.objects.all())[:20])
        cf = next((a for a in accounts if a.provider == "cloudflare"), None)
        allowed, disabled = authorized_action_lists(
            request, [{"id": "integration.verify", "label": "Verify again"}],
        )
        return Response({
            "observed_at": timezone.now(),
            "aws": {"state": "missing", "account_last4": "", "region": ""},
            "cloudflare": {
                "state": "connected" if cf else "missing",
                "account": cf.label if cf else "",
                "origin_ca": "present" if cf and cf.origin_ca_key_ref else "missing",
                "last_check": None,
            },
            "dns": [
                {
                    "id": a.pk,
                    "provider": a.provider,
                    "label": a.label,
                    "zones": a.zones.count(),
                    "last_check": None,
                }
                for a in accounts
            ],
            "vault": {
                "kek_id": "local",
                "kek_age_days": 0,
                "active_secrets": workspace_secrets(request).count(),
            },
            "allowed_actions": allowed,
            "disabled_actions": disabled,
        })


class AuditView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request):
        events = scoped(request, AuditEvent.objects.all()).select_related("actor")
        if request.query_params.get("export") == "csv":
            if not has_capability(
                request.user, "audit.export", request_workspace(request),
            ):
                return Response(
                    {"detail": "audit.export required.", "code": "not_permitted"},
                    status=status.HTTP_403_FORBIDDEN,
                )
            lines = ["ts,actor,action,object_type,object_id,result,source_ip"]
            for event in events[:1000]:
                actor = event.actor.username if event.actor_id else ""
                lines.append(
                    f"{event.ts},{actor},{event.action},{event.object_type},"
                    f"{event.object_id},{event.severity},{event.source_ip or ''}"
                )
            return Response({
                "observed_at": timezone.now(),
                "csv": "\n".join(lines) + "\n",
                "filename": "audit.csv",
                "results": [],
            })
        rows = []
        for event in events[:100]:
            rows.append({
                "id": event.pk,
                "ts": event.ts,
                "actor": event.actor.username if event.actor_id else "",
                "action": event.action,
                "object_type": event.object_type,
                "object_id": event.object_id,
                "result": (event.detail or {}).get("result") or event.severity,
                "source_ip": event.source_ip or "",
                "correlation_id": (event.detail or {}).get("correlation_id") or "",
                "detail": event.detail or {},
            })
        return collection(rows)


class SearchView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request):
        from django.db.models import Q

        q = (request.query_params.get("q") or "").strip().lower()
        groups = []
        if q:
            projects = [
                {"id": p.pk, "label": p.name, "href": f"projects/{p.pk}"}
                for p in scoped(request, Project.objects.all()).filter(name__icontains=q)[:8]
            ]
            site_q = Q(name__icontains=q) | Q(domain__icontains=q) | Q(project__name__icontains=q)
            sites = [
                {"id": s.pk, "label": s.domain or s.name, "href": f"sites/{s.pk}"}
                for s in scoped(
                    request, Site.objects.all(), "project__workspace",
                ).filter(site_q)[:8]
            ]
            targets = [
                {"id": t.pk, "label": t.host, "href": f"targets/{t.pk}"}
                for t in scoped(
                    request, Target.objects.all(), "zone__workspace",
                ).filter(host__icontains=q)[:8]
            ]
            deploys = []
            if q.isdigit():
                deploys = [
                    {"id": d.pk, "label": f"deployment {d.pk}", "href": f"deployments/{d.pk}"}
                    for d in scoped(
                        request, deploys.Deployment.objects.all(),
                        "manifest__site__project__workspace",
                    ).filter(pk=int(q))[:8]
                ]
            findings = [
                {"id": f.pk, "label": f.fingerprint, "href": f"findings/{f.pk}"}
                for f in scoped(request, Finding.objects.all()).filter(fingerprint__icontains=q)[:8]
            ]
            partners = [
                {"id": p.pk, "label": p.slug, "href": f"partners/{p.pk}"}
                for p in scoped(request, Partner.objects.all()).filter(slug__icontains=q)[:8]
            ]
            packed = [
                ("project", projects),
                ("site", sites),
                ("target", targets),
                ("deployment", deploys),
                ("finding", findings),
                ("partner", partners),
            ]
            groups = [{"kind": kind, "results": items} for kind, items in packed if items]
        return Response({"observed_at": timezone.now(), "groups": groups})


class ShellView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request):
        p1p2 = scoped(request, Finding.objects.all()).filter(
            state="open", severity__in=["p1", "p2"],
        ).count()
        ops = [
            {
                "id": f"lock-{lock.pk}",
                "state": "running",
                "label": f"{lock.kind} {lock.scope}:{lock.object_id}",
            }
            for lock in scoped(request, OperationLock.objects.all())[:10]
        ]
        workspace = request_workspace(request)
        return Response({
            "observed_at": timezone.now(),
            "p1_p2": p1p2,
            "scope": request.query_params.get("scope") or "production",
            "operations": ops,
            "build_id": getattr(dj_settings, "HUD_BUILD_ID", "") or "",
            "workspace": {
                "id": workspace.pk,
                "slug": workspace.slug,
                "name": workspace.name,
            },
            "allowed_actions": [],
        })


class ProjectTestSourceView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request):
        url = (request.query_params.get("git_url") or "").strip()
        local = (request.query_params.get("local_path") or "").strip()
        observed = timezone.now()
        if local or url:
            return Response({
                "ok": False, "state": "unknown",
                "detail": "source not probed", "observed_at": observed,
            })
        return Response({
            "ok": False, "state": "missing",
            "detail": "provide git_url or local_path", "observed_at": observed,
        })


class OperationView(HudAPIView):
    permission_classes = [IsAuthenticated, RequireAdminRead]

    def get(self, request, pk):
        operation = get_object_or_404(
            HudOperation.objects.select_related("audit_event"),
            pk=pk,
            workspace=request_workspace(request),
        )
        event = operation.audit_event
        return Response({
            "operation_id": operation.pk,
            "action": operation.action,
            "state": operation.state,
            "object_type": operation.object_type,
            "object_id": operation.object_id,
            "observed_at": operation.heartbeat_at or operation.created_at,
            "started_at": operation.started_at,
            "finished_at": operation.finished_at,
            "attempts": operation.attempts,
            "result": operation.result,
            "error": ({
                "code": operation.error_code,
                "message": operation.error_message,
            } if operation.error_code else None),
            "detail": event.detail,
        })
