"""core: shared kernel. AuditEvent (§D1) plus the product models the whole
system is about — Project (code), Site (project + domain + config), Zone,
Target, SiteInstance — per §D9's canonical vocabulary.

core deliberately imports nothing from scanner/, deploys/ or wizard/: everything
imports core, so a dependency here becomes a dependency everywhere (see
wizard/__init__.py for the transitive-import finding that made this explicit).
vault must not import core; Target.ssh_key_ref is a vault owner-id string, not
an FK.
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

from .validators import validate_git_url


class AuditEvent(models.Model):
    """Append-only audit trail (§D1). Off-host shipping lands in Phase 4 (§B3)."""

    class Source(models.TextChoices):
        UI = "ui"
        API = "api"
        CELERY = "celery"
        RECONCILER = "reconciler"
        SYSTEM = "system"
        WS = "ws"

    class Severity(models.TextChoices):
        INFO = "info"
        WARNING = "warning"
        SECURITY = "security"

    ts = models.DateTimeField(auto_now_add=True, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL
    )
    source = models.CharField(max_length=16, choices=Source.choices)
    action = models.SlugField(max_length=64)
    object_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    detail = models.JSONField(default=dict, blank=True)
    source_ip = models.GenericIPAddressField(null=True, blank=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.INFO)
    # Phase-5.5 early stub (§K9): becomes a real FK when the Partner model exists.
    partner_id_stub = models.IntegerField(null=True, blank=True)

    class Meta:
        indexes = [models.Index(fields=["object_type", "object_id"])]
        ordering = ["-ts"]

    def __str__(self):
        return f"{self.ts:%Y-%m-%d %H:%M:%S} {self.action}"


class RecoveryCode(models.Model):
    """One-time 2FA recovery codes, stored as sha256 hashes — a DB read (backup
    leak, SQL access) must never yield working second factors (round-1 finding;
    replaces the plaintext django-otp StaticToken storage)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE,
                             related_name="recovery_codes")
    code_hash = models.CharField(max_length=64, db_index=True)  # sha256 hex
    created = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user", "code_hash"], name="uniq_user_code_hash")
        ]


class Project(models.Model):
    """Code (§D9). A Project is a git URL or a local path — never a running thing."""

    class Source(models.TextChoices):
        GIT = "git"
        LOCAL_PATH = "local_path"   # dev + adopt-existing paths only

    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128, unique=True)
    source_kind = models.CharField(max_length=16, choices=Source.choices,
                                   default=Source.GIT)
    git_url = models.CharField(max_length=2048, blank=True,
                               validators=[validate_git_url])
    git_ref = models.CharField(max_length=255, default="main")
    local_path = models.CharField(max_length=1024, blank=True)

    # Latest scan (§5.1). Kept on the Project because the report is about the CODE;
    # a Site inherits it. schema_version travels inside the payload (§D8).
    scan_report = models.JSONField(null=True, blank=True)
    scanned_at = models.DateTimeField(null=True, blank=True)
    scan_source_fingerprint = models.CharField(max_length=64, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="projects_created")

    def __str__(self):
        return self.name


class NetworkZone(models.Model):
    """A network (§D9). Targets sit in a zone; the Hub talks to them through it."""

    name = models.CharField(max_length=128)
    slug = models.SlugField(max_length=128, unique=True)

    def __str__(self):
        return self.name


class Site(models.Model):
    """Project + domain + config (§D9). One Site = ONE manifest (§V5)."""

    class Exposure(models.TextChoices):
        PUBLIC = "public"
        MESH_ONLY = "mesh_only"

    class DeployStrategy(models.TextChoices):
        BLUE_GREEN = "blue_green"
        RECREATE = "recreate"

    class DeployPolicy(models.TextChoices):
        AUTO = "auto"
        CONFIRM = "confirm"
        WINDOWED = "windowed"

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="sites")
    name = models.CharField(max_length=128)
    domain = models.CharField(max_length=253, blank=True)
    exposure = models.CharField(
        max_length=16, choices=Exposure.choices, default=Exposure.PUBLIC,
    )
    deploy_strategy = models.CharField(
        max_length=16, choices=DeployStrategy.choices,
        default=DeployStrategy.BLUE_GREEN,
    )
    deploy_policy = models.CharField(
        max_length=16, choices=DeployPolicy.choices, default=DeployPolicy.AUTO,
    )
    deploy_window_cron = models.CharField(max_length=128, blank=True, default="")
    maintenance_until = models.DateTimeField(null=True, blank=True)
    reconcile_enabled = models.BooleanField(default=True)
    liveness_path = models.CharField(max_length=256, blank=True, default="/healthz")
    readiness_path = models.CharField(
        max_length=256, blank=True, default="/healthz.ready",
    )
    warmup_timeout_s = models.PositiveIntegerField(default=60)
    config_stale = models.BooleanField(default=False)
    primary_target = models.ForeignKey(
        "Target", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="primary_for_sites",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True,
                                   on_delete=models.SET_NULL,
                                   related_name="sites_created")

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["project", "name"], name="uniq_site_name")
        ]

    def __str__(self):
        return f"{self.name} ({self.domain or 'no domain yet'})"


class Target(models.Model):
    """A managed host (§D9) — never called an instance in UI copy."""

    class Kind(models.TextChoices):
        SSH = "ssh"

    class Lifecycle(models.TextChoices):
        PERMANENT = "permanent"
        EPHEMERAL = "ephemeral"

    class Status(models.TextChoices):
        PENDING = "pending"
        READY = "ready"
        ERROR = "error"
        DECOMMISSIONED = "decommissioned"

    zone = models.ForeignKey(NetworkZone, on_delete=models.PROTECT,
                             related_name="targets")
    kind = models.CharField(max_length=16, choices=Kind.choices, default=Kind.SSH)
    host = models.CharField(max_length=253)
    ssh_user = models.CharField(max_length=64, default="root")
    # Vault owner id (string), not an FK — vault must not import core.
    ssh_key_ref = models.CharField(max_length=64, blank=True, default="")
    host_key_fingerprint = models.CharField(max_length=256, blank=True, default="")
    lifecycle = models.CharField(
        max_length=16, choices=Lifecycle.choices, default=Lifecycle.PERMANENT,
    )
    status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.PENDING,
    )

    def __str__(self):
        return self.host


class SiteInstance(models.Model):
    """One running copy of a Site on one Target (§D3/§D9)."""

    class DesiredState(models.TextChoices):
        RUNNING = "running"
        STOPPED = "stopped"
        ABSENT = "absent"

    class ObservedState(models.TextChoices):
        RUNNING = "running"
        STOPPED = "stopped"
        ABSENT = "absent"
        UNHEALTHY = "unhealthy"
        WARMING = "warming"

    site = models.ForeignKey(Site, on_delete=models.CASCADE,
                             related_name="instances")
    target = models.ForeignKey(Target, on_delete=models.CASCADE,
                               related_name="instances")
    desired_image_tag = models.CharField(max_length=256, blank=True, default="")
    desired_state = models.CharField(
        max_length=16, choices=DesiredState.choices, default=DesiredState.ABSENT,
    )
    observed_state = models.CharField(
        max_length=16, choices=ObservedState.choices, default=ObservedState.ABSENT,
    )
    observed_at = models.DateTimeField(null=True, blank=True)
    last_reconciled_at = models.DateTimeField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    internal_port = models.PositiveIntegerField(
        validators=[MinValueValidator(20000), MaxValueValidator(29999)],
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["target", "internal_port"],
                name="uniq_siteinstance_target_port",
            ),
            models.CheckConstraint(
                condition=models.Q(internal_port__gte=20000)
                & models.Q(internal_port__lte=29999),
                name="siteinstance_internal_port_range",
            ),
        ]

    def __str__(self):
        return f"{self.site_id}@{self.target_id}:{self.internal_port}"


class OperationLock(models.Model):
    """Postgres lock row (§A5). Unique (scope, object_id, kind); INSERT-conflict refuses."""

    class Scope(models.TextChoices):
        SITE = "site"
        TARGET = "target"

    class Kind(models.TextChoices):
        DEPLOY = "deploy"
        PROVISION = "provision"
        RECONCILE = "reconcile"

    scope = models.CharField(max_length=16, choices=Scope.choices)
    object_id = models.CharField(max_length=64)
    kind = models.CharField(max_length=16, choices=Kind.choices)
    holder = models.CharField(max_length=128)
    acquired_at = models.DateTimeField(auto_now_add=True)
    heartbeat_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["scope", "object_id", "kind"],
                name="uniq_operationlock_scope_object_kind",
            ),
        ]

    def __str__(self):
        return f"{self.scope}:{self.object_id}:{self.kind}"


class DnsRecord(models.Model):
    """Desired DNS for a Site (§D3). observed_* is what the provider last showed."""

    site = models.ForeignKey(Site, on_delete=models.CASCADE,
                             related_name="dns_records")
    name = models.CharField(max_length=253)
    rtype = models.CharField(max_length=16)
    value = models.CharField(max_length=1024)
    observed_value = models.CharField(max_length=1024, blank=True, default="")
    last_verified = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "name", "rtype"],
                name="uniq_dnsrecord_site_name_rtype",
            ),
        ]

    def __str__(self):
        return f"{self.name} {self.rtype}"


class SiteVolume(models.Model):
    """Named volume belonging to a Site, never to a Deployment (§N5)."""

    class BackupPolicy(models.TextChoices):
        NONE = "none"
        DIRECTORY_SYNC = "directory_sync"

    site = models.ForeignKey(Site, on_delete=models.CASCADE,
                             related_name="volumes")
    name = models.CharField(max_length=128)
    container_path = models.CharField(max_length=512)
    backup_policy = models.CharField(
        max_length=32, choices=BackupPolicy.choices, default=BackupPolicy.NONE,
    )

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["site", "name"], name="uniq_sitevolume_site_name",
            ),
        ]

    def __str__(self):
        return f"{self.site_id}:{self.name}"
