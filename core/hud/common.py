"""Shared HUD HTTP helpers: workspace scoping, action lists, site read models."""
from django.db.models import Q
from django.utils import timezone
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView

from core.hud.ports import deploys
from core.models import Site, Target, TlsCertificate
from core.rbac import (
    ACTION_CAPABILITY,
    SYSTEM_ACTIONS,
    has_capability,
    has_operator_capability,
    is_system_admin,
    request_workspace,
    scope_queryset,
)
from vault.models import Secret

STEP_NAMES = [
    "build", "ship", "migrate", "start_green", "health_check",
    "dns", "route_tls", "smoke_test", "cutover",
]

RESOURCE_OWNER_TYPES = (
    "site", "project", "target", "partner", "manifest", "dns_account",
)


class HudAPIView(APIView):
    """APIView with explicit schema metadata so privileged routes stay in OpenAPI."""

    serializer_class = serializers.Serializer


class DisabledActionSerializer(serializers.Serializer):
    id = serializers.CharField()
    code = serializers.CharField()
    reason = serializers.CharField()
    label = serializers.CharField(required=False)


class AllowedActionSerializer(serializers.Serializer):
    id = serializers.CharField()
    label = serializers.CharField()


def scoped(request, queryset, field="workspace"):
    return scope_queryset(queryset, request_workspace(request), field)


def idempotency_key(request):
    return (
        request.headers.get("Idempotency-Key")
        or (request.data or {}).get("idempotency_key")
        or ""
    )


def refuse_cap(request, action):
    cap = ACTION_CAPABILITY.get(action)
    if not cap:
        return Response(
            {"detail": "Action is not permitted in this workspace.", "code": "not_permitted"},
            status=status.HTTP_403_FORBIDDEN,
        )
    if not has_operator_capability(request.user, cap, request_workspace(request)):
        return Response(
            {"detail": f"{cap} required.", "code": "not_permitted", "capability": cap},
            status=status.HTTP_403_FORBIDDEN,
        )
    return None


def authorized_action_lists(request, allowed, disabled=None):
    """Keep action metadata aligned with the same capability gate as commands."""
    visible = []
    refused = list(disabled or [])
    workspace = request_workspace(request)
    for action in allowed or []:
        action_id = action.get("id")
        if action_id in SYSTEM_ACTIONS:
            if is_system_admin(request.user):
                visible.append(action)
            else:
                refused.append({
                    "id": action_id,
                    "code": "not_permitted",
                    "label": action.get("label", action_id),
                    "reason": "System administrator required.",
                })
            continue
        capability = ACTION_CAPABILITY.get(action_id)
        if capability and not has_capability(request.user, capability, workspace):
            refused.append({
                "id": action_id,
                "code": "not_permitted",
                "label": action.get("label", action_id),
                "reason": f"{capability} is required in this workspace.",
            })
        else:
            visible.append(action)
    return visible, refused


def accepted(action, extra=None):
    extra = extra or {}
    op_id = extra.get("operation_id")
    if op_id in (None, ""):
        raise ValueError("accepted commands must persist a durable operation_id")
    body = {
        "operation_id": op_id,
        "state": extra.get("state", "queued"),
        "action": action,
        "observed_at": timezone.now(),
        "status_url": extra.get("status_url") or f"/api/v1/hud/operations/{op_id}/",
    }
    body.update(extra)
    return Response(body, status=status.HTTP_202_ACCEPTED)


def persist_command(request, action, **kwargs):
    from core.hud.operations import create_operation

    object_type = kwargs.pop("object_type", "")
    object_id = kwargs.pop("object_id", "")
    topic = {
        "project.scan": "hud.project.scan",
        "target.probe": "hud.target.probe",
        "integration.verify": "hud.integration.verify",
        "aws.verify": "hud.integration.verify",
        "cloudflare.verify": "hud.integration.verify",
        "dns.verify": "hud.integration.verify",
    }.get(action, kwargs.pop("topic", "hud.command.recorded"))
    kwargs.pop("topic", None)
    operation, replayed = create_operation(
        request,
        action,
        object_type=object_type,
        object_id=object_id,
        idempotency_key=kwargs.pop("idempotency_key", "") or idempotency_key(request),
        topic=topic,
        audit_detail=kwargs,
    )
    return operation, replayed


def site_tls(site):
    cert = None
    if hasattr(site, "tls_certificates"):
        cached = list(site.tls_certificates.all())
        cert = cached[0] if cached else None
    if cert is None:
        cert = TlsCertificate.objects.filter(site=site).order_by("-id").first()
    if cert is None:
        return "unknown"
    if cert.not_after and cert.not_after < timezone.now():
        return "expired"
    if cert.fingerprint or cert.pushed_at:
        return "ok"
    return "unknown"


def site_releases(site):
    latest = site.manifests.order_by("-version").first()
    desired = f"v{latest.version}" if latest else ""
    live_dep = (
        deploys.Deployment.objects.filter(
            manifest__site=site, status=deploys.Deployment.Status.SUCCEEDED,
        )
        .select_related("manifest")
        .order_by("-pk")
        .first()
    )
    live = f"v{live_dep.manifest.version}" if live_dep else ""
    return live, desired


def site_health(site):
    if not site.primary_target_id:
        return "unhealthy"
    target = site.primary_target
    if target and target.status == Target.Status.ERROR:
        return "unhealthy"
    if site.config_stale:
        return "stale"
    instances = list(site.instances.all()) if hasattr(site, "instances") else []
    if any(getattr(i, "observed_state", "") == "warming" for i in instances):
        return "warming"
    if any(getattr(i, "observed_state", "") == "unhealthy" for i in instances):
        return "unhealthy"
    return "healthy"


def site_environment(site):
    if getattr(site, "preview_of_id", None):
        return Site.Environment.PREVIEW
    return getattr(site, "environment", None) or Site.Environment.PRODUCTION


def site_in_scope(site, purpose):
    if not purpose:
        return True
    if site.dns_zone_id and site.dns_zone.purpose:
        return site.dns_zone.purpose == purpose
    if site.primary_target_id and site.primary_target.zone_id:
        return site.primary_target.zone.purpose == purpose
    return purpose == "prod"


def scope_purpose(request):
    raw = (request.query_params.get("scope") or "").lower()
    if raw == "test":
        return "test"
    if raw == "production":
        return "prod"
    return None


def target_readiness(target):
    if target.status == Target.Status.DECOMMISSIONED:
        return "decommissioned"
    if target.status == Target.Status.ERROR:
        return "unreachable"
    if target.status == Target.Status.PENDING:
        return "pressured"
    return "ready"


def int_param(request, name, default, *, lo, hi):
    raw = request.query_params.get(name)
    try:
        value = int(raw) if raw not in (None, "") else default
    except (TypeError, ValueError):
        value = default
    return max(lo, min(hi, value))


def collection(results, extra=None, allowed=None, disabled=None):
    body = {
        "observed_at": timezone.now(),
        "results": results,
        "allowed_actions": allowed or [],
        "disabled_actions": disabled or [],
    }
    if extra:
        body.update(extra)
    return Response(body)


def workspace_secret_owner_ids(request):
    from core.models import DnsAccount, Partner, Project, Site, Target

    sites = scoped(request, Site.objects.all(), "project__workspace")
    projects = scoped(request, Project.objects.all())
    targets = scoped(request, Target.objects.all(), "zone__workspace")
    partners = scoped(request, Partner.objects.all())
    manifests = deploys.Manifest.objects.filter(site__in=sites)
    accounts = scoped(request, DnsAccount.objects.all())
    dns_refs = set()
    for account in accounts:
        dns_refs.update(filter(None, (
            account.dns_token_ref, account.edge_token_ref, account.origin_ca_key_ref,
            str(account.pk),
        )))
    return {
        "site": [str(pk) for pk in sites.values_list("pk", flat=True)],
        "project": [str(pk) for pk in projects.values_list("pk", flat=True)],
        "target": [str(pk) for pk in targets.values_list("pk", flat=True)],
        "partner": [str(pk) for pk in partners.values_list("pk", flat=True)],
        "manifest": [str(pk) for pk in manifests.values_list("pk", flat=True)],
        "dns_account": sorted(dns_refs),
    }


def _foreign_secret_owner_ids(workspace):
    from core.models import DnsAccount, Partner, Project, Site, Target

    others = ~Q(workspace=workspace)
    site_ids = {
        str(pk) for pk in Site.objects.exclude(
            project__workspace=workspace,
        ).values_list("pk", flat=True)
    }
    project_ids = {
        str(pk) for pk in Project.objects.filter(others).values_list("pk", flat=True)
    }
    target_ids = {
        str(pk) for pk in Target.objects.exclude(
            zone__workspace=workspace,
        ).values_list("pk", flat=True)
    }
    partner_ids = {str(pk) for pk in Partner.objects.filter(others).values_list("pk", flat=True)}
    accounts = DnsAccount.objects.filter(others)
    dns_ids = set()
    for account in accounts:
        dns_ids.update(filter(None, (
            account.dns_token_ref, account.edge_token_ref, account.origin_ca_key_ref,
            str(account.pk),
        )))
    return {
        "site": site_ids,
        "project": project_ids,
        "target": target_ids,
        "partner": partner_ids,
        "dns_account": dns_ids,
        "manifest": set(),
    }


def workspace_secrets(request):
    owners = workspace_secret_owner_ids(request)
    visible = Q(pk__in=[])
    for owner_type, ids in owners.items():
        visible |= Q(owner_type=owner_type, owner_id__in=ids)
    workspace = request_workspace(request)
    if workspace and workspace.slug == "default":
        visible |= ~Q(owner_type__in=RESOURCE_OWNER_TYPES)
        foreign = _foreign_secret_owner_ids(workspace)
        for owner_type in RESOURCE_OWNER_TYPES:
            claimed = foreign.get(owner_type) or set()
            if claimed:
                visible |= Q(owner_type=owner_type) & ~Q(owner_id__in=sorted(claimed))
            else:
                visible |= Q(owner_type=owner_type)
    return Secret.objects.filter(visible)


def secret_owner_allowed(request, owner_type, owner_id):
    return str(owner_id) in set(workspace_secret_owner_ids(request).get(owner_type, ()))


def aws_configured(request=None):
    from django.conf import settings

    ref = str(getattr(settings, "AWS_CREDENTIALS_REF", "") or "").strip()
    if not ref:
        return False
    secrets = workspace_secrets(request) if request is not None else Secret.objects.all()
    return secrets.filter(
        kind=Secret.Kind.CLOUD_CREDENTIAL, owner_type="aws", owner_id=ref,
    ).exists()


def vault_status(request):
    if not workspace_secrets(request).exists():
        return "unknown"
    return "connected"
