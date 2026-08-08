"""core: shared kernel. AuditEvent (§D1) plus the two product models the whole
system is about — Project (code) and Site (project + domain + config), per §D9's
canonical vocabulary.

core deliberately imports nothing from scanner/, deploys/ or wizard/: everything
imports core, so a dependency here becomes a dependency everywhere (see
wizard/__init__.py for the transitive-import finding that made this explicit).
"""
from django.conf import settings
from django.db import models

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


class Site(models.Model):
    """Project + domain + config (§D9). One Site = ONE manifest (§V5)."""

    project = models.ForeignKey(Project, on_delete=models.CASCADE,
                                related_name="sites")
    name = models.CharField(max_length=128)
    domain = models.CharField(max_length=253, blank=True)
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
