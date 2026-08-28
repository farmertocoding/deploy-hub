"""Workspace-scoped roles and capabilities for Administration.

Capabilities are always evaluated for one workspace. A user who owns
workspace A does not acquire owner rights while viewing workspace B. Global
Django staff/superuser flags only bootstrap the legacy ``default`` workspace;
other workspaces require an explicit membership.

``hud_ui_v1`` is a role capability for Administration members. Operator-shell
chrome is the ``HUD_UI_V1`` setting, returned on the session as ``hud_ui``.
"""
from django.conf import settings
from django.db.models import Q

ROLES = ("viewer", "auditor", "operator", "deployer", "admin", "owner")

ROLE_CAPABILITIES = {
    "viewer": ["hud_ui_v1", "admin_read"],
    "auditor": ["hud_ui_v1", "admin_read", "audit.export"],
    "operator": [
        "hud_ui_v1", "admin_read", "deployment.cancel", "deployment.rollback",
        "deployment.retry", "findings.manage",
    ],
    "deployer": [
        "hud_ui_v1", "admin_read", "config.write", "deployment.request",
        "deployment.cancel", "deployment.rollback", "deployment.retry",
        "findings.manage",
    ],
    "admin": [
        "hud_ui_v1", "admin_read", "audit.export", "config.write",
        "secrets.manage", "members.manage", "deployment.request",
        "deployment.approve_prod", "deployment.cancel", "deployment.rollback",
        "deployment.retry", "findings.manage", "findings.accept_risk",
    ],
    "owner": [
        "hud_ui_v1", "admin_read", "audit.export", "config.write",
        "deployment.request", "deployment.approve_prod", "deployment.cancel",
        "deployment.rollback", "deployment.retry", "secrets.manage",
        "members.manage", "lifecycle.destroy", "findings.manage",
        "findings.accept_risk",
    ],
}

SYSTEM_ACTIONS = frozenset({"partner.api_kill_switch", "aws.connect"})

ACTION_CAPABILITY = {
    "target.create": "config.write",
    "target.probe": "config.write",
    "target.delete": "lifecycle.destroy",
    "target.router_probe": "config.write",
    "instance.create": "config.write",
    "instance.terminate": "lifecycle.destroy",
    "ssh.rotate": "secrets.manage",
    "partner.create": "config.write",
    "partner.suspend": "members.manage",
    "partner.site_takedown": "deployment.request",
    "partner.destination_rank": "config.write",
    "site.create": "config.write",
    "site.deploy": "deployment.request",
    "site.env": "config.write",
    "site.rollback": "deployment.rollback",
    "site.adopt": "config.write",
    "site.preview_create": "deployment.request",
    "site.overflow_deploy": "deployment.request",
    "site.overflow_join": "deployment.request",
    "site.overflow_scale_in": "deployment.request",
    "site.backup_restore": "lifecycle.destroy",
    "site.backup_test": "config.write",
    "site.edge_owner": "config.write",
    "project.scan": "config.write",
    "project.create": "config.write",
    "wizard.answers": "config.write",
    "wizard.materialize": "deployment.request",
    "integration.verify": "config.write",
    "aws.verify": "config.write",
    "cloudflare.verify": "config.write",
    "dns.verify": "config.write",
    "dns.origin_ca_plant": "secrets.manage",
    "dns.cloudflare_connect": "secrets.manage",
    "deployment.cancel": "deployment.cancel",
    "deployment.abort": "deployment.cancel",
    "deployment.retry": "deployment.retry",
    "deployment.rollback": "deployment.rollback",
    "finding.ack": "findings.manage",
    "finding.resolve": "findings.manage",
    "finding.transition": "findings.manage",
    "finding.accept_risk": "findings.accept_risk",
    "secret.create": "secrets.manage",
    "member.invite": "members.manage",
}

SITE_FIELD = "project__workspace"
TARGET_FIELD = "zone__workspace"
DEPLOY_FIELD = "manifest__site__project__workspace"


def _hud_capabilities(role):
    caps = set(ROLE_CAPABILITIES.get(role, ()))
    if not getattr(settings, "HUD_UI_V1", True):
        caps.discard("hud_ui_v1")
    return sorted(caps)


def _default_workspace():
    from core.models import default_workspace

    return default_workspace()


def is_system_admin(user):
    """Platform-global authority. Independent of the selected workspace."""
    return bool(
        user and getattr(user, "is_authenticated", False) and user.is_superuser
    )


def workspace_membership(user, workspace):
    """Return persisted membership, or staff bootstrap on the default workspace."""
    if not user or not getattr(user, "is_authenticated", False) or not workspace:
        return None
    from core.models import WorkspaceMembership

    row = WorkspaceMembership.objects.filter(user=user, workspace=workspace).first()
    if row:
        return row
    if workspace.slug != "default":
        return None
    if user.is_staff or user.is_superuser:
        return type("BootstrapMembership", (), {
            "workspace": workspace,
            "workspace_id": workspace.pk,
            "user": user,
            "role": "owner" if user.is_superuser else "admin",
            "is_bootstrap": True,
        })()
    return None


def resolve_workspace(user, workspace_ref=None):
    """Resolve an accessible workspace without leaking inaccessible existence."""
    if not user or not getattr(user, "is_authenticated", False):
        return None
    from core.models import Workspace, WorkspaceMembership

    if workspace_ref not in (None, ""):
        lookup = Q(slug=str(workspace_ref))
        if str(workspace_ref).isdigit():
            lookup |= Q(pk=int(workspace_ref))
        candidate = Workspace.objects.filter(lookup).first()
        return candidate if workspace_membership(user, candidate) else None

    membership = (
        WorkspaceMembership.objects.filter(user=user)
        .select_related("workspace")
        .order_by("workspace__slug", "id")
        .first()
    )
    if membership:
        return membership.workspace
    default = _default_workspace()
    if workspace_membership(user, default):
        return default
    return None


def request_workspace(request):
    """Resolve and cache the request's authorization/isolation boundary."""
    if hasattr(request, "workspace"):
        return request.workspace
    ref = (
        request.headers.get("X-Workspace")
        or request.headers.get("X-Workspace-Id")
        or request.query_params.get("workspace")
    )
    request.workspace = resolve_workspace(request.user, ref)
    request.workspace_ref_requested = ref not in (None, "")
    return request.workspace


def capabilities_for(user, workspace):
    membership = workspace_membership(user, workspace)
    if not membership:
        return []
    if getattr(membership, "is_bootstrap", False) and not (
        user.is_staff or user.is_superuser
    ):
        return []
    return _hud_capabilities(membership.role)


def user_capabilities(user, workspace=None):
    """Capabilities for one selected workspace (never a cross-workspace union)."""
    workspace = workspace or resolve_workspace(user)
    return capabilities_for(user, workspace)


def user_role(user, workspace=None):
    membership = workspace_membership(user, workspace or resolve_workspace(user))
    if not membership:
        return ""
    if getattr(membership, "is_bootstrap", False) and not (
        user.is_staff or user.is_superuser
    ):
        return ""
    return membership.role


def hud_ui_enabled():
    return bool(getattr(settings, "HUD_UI_V1", True))


def has_capability(user, name, workspace=None):
    return name in user_capabilities(user, workspace)


def has_operator_capability(user, name, workspace=None):
    """Mutating operator APIs require a persisted membership (or staff bootstrap)."""
    workspace = workspace or resolve_workspace(user)
    return has_capability(user, name, workspace)


def workspace_payload(user):
    if not user or not getattr(user, "is_authenticated", False):
        return []
    from core.models import WorkspaceMembership

    rows = list(
        WorkspaceMembership.objects.filter(user=user)
        .select_related("workspace")
        .order_by("workspace__slug", "id")
    )
    payload = [{
        "id": row.workspace_id,
        "slug": row.workspace.slug,
        "name": row.workspace.name,
        "role": row.role,
        "capabilities": _hud_capabilities(row.role),
    } for row in rows]
    default = _default_workspace() if (user.is_staff or user.is_superuser) else None
    if default and not any(item["id"] == default.pk for item in payload):
        role = "owner" if user.is_superuser else "admin"
        payload.append({
            "id": default.pk,
            "slug": default.slug,
            "name": default.name,
            "role": role,
            "capabilities": _hud_capabilities(role),
        })
    return payload


def scope_queryset(queryset, workspace, field="workspace"):
    """Restrict a queryset to one workspace. Ownership is always explicit."""
    if workspace is None:
        return queryset.none()
    return queryset.filter(**{field: workspace})


def scoped_get(request, queryset, field="workspace", **lookup):
    """404 if the row is not in the request workspace. Never a global PK lookup."""
    from rest_framework.generics import get_object_or_404

    return get_object_or_404(
        scope_queryset(queryset, request_workspace(request), field),
        **lookup,
    )
