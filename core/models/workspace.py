"""Workspace isolation boundary and memberships."""
from django.conf import settings
from django.db import models

DEFAULT_WORKSPACE_ID = 1


def default_workspace():
    workspace = Workspace.objects.filter(pk=DEFAULT_WORKSPACE_ID).first()
    if workspace is not None:
        return workspace
    # Field defaults are the constant 1. Keying only on slug after SQLite
    # autoincrement has moved (mutmut's second in-process pytest session)
    # inserts pk=N and leaves workspace_id=1 dangling.
    return Workspace.objects.create(
        pk=DEFAULT_WORKSPACE_ID,
        slug="default",
        name="Default workspace",
    )


def default_workspace_id():
    """Stable key created as the first workspace by migration 0019.

    Database-free so unsaved adapter objects can be constructed in tests that
    do not mark django_db. Saving a row with this default must create the
    workspace first — see ensure_default_workspace_row.
    """
    return DEFAULT_WORKSPACE_ID


def ensure_default_workspace_row(sender, instance, **kwargs):
    """pre_save: a workspace_id of 1 is not a real row until default exists."""
    if getattr(instance, "workspace_id", None) == DEFAULT_WORKSPACE_ID:
        default_workspace()


def require_workspace(obj=None, *, workspace=None):
    """Fail closed: never invent the default tenant for a tenant-scoped row."""
    chosen = workspace if workspace is not None else workspace_of(obj)
    if chosen is None:
        raise TypeError("workspace required")
    return chosen


def workspace_of(obj):
    """Deterministic owner workspace, or None when the object has no tenant."""
    if obj is None:
        return None
    workspace = getattr(obj, "workspace", None)
    if workspace is not None:
        return workspace
    for attr in (
        "project", "site", "zone", "account", "partner", "finding",
        "manifest", "operation",
    ):
        related = getattr(obj, attr, None)
        if related is None:
            continue
        found = workspace_of(related)
        if found is not None:
            return found
    zone = getattr(obj, "zone", None)
    if zone is not None:
        return getattr(zone, "workspace", None)
    owner_type = getattr(obj, "owner_type", None)
    owner_id = getattr(obj, "owner_id", None)
    if owner_type and owner_id not in (None, ""):
        return workspace_from_owner(owner_type, owner_id)
    return None


def workspace_from_owner(owner_type, owner_id):
    from core.models.fleet import Partner, Project, Site, Target

    raw = str(owner_id).split(":", 1)[0]
    if not raw.isdigit():
        return None
    pk = int(raw)
    if owner_type == "site":
        site = Site.objects.filter(pk=pk).select_related("project").first()
        return site.project.workspace if site is not None else None
    if owner_type == "project":
        project = Project.objects.filter(pk=pk).first()
        return project.workspace if project is not None else None
    if owner_type == "target":
        target = Target.objects.filter(pk=pk).select_related("zone").first()
        return target.zone.workspace if target is not None else None
    if owner_type == "partner":
        partner = Partner.objects.filter(pk=pk).first()
        return partner.workspace if partner is not None else None
    return None


class Workspace(models.Model):
    """Isolation boundary for Administration RBAC."""

    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.slug


class WorkspaceMembership(models.Model):
    class Role(models.TextChoices):
        VIEWER = "viewer"
        AUDITOR = "auditor"
        OPERATOR = "operator"
        DEPLOYER = "deployer"
        ADMIN = "admin"
        OWNER = "owner"

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="memberships",
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
        related_name="workspace_memberships",
    )
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.OPERATOR)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"], name="uniq_workspace_membership",
            ),
        ]

    def __str__(self):
        return f"{self.user_id}:{self.workspace.slug}:{self.role}"
