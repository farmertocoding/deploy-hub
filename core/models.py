"""core: shared kernel. Phase 0 owns only AuditEvent (§D1) — product models land
with the features that own them, so migrations stay honest."""
from django.conf import settings
from django.db import models


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
