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
