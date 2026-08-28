"""Durable HUD command operations and the transactional outbox."""
from django.conf import settings
from django.db import models
from django.utils import timezone

from .fleet import AuditEvent
from .workspace import Workspace


class HudOperation(models.Model):
    """Durable state for one accepted HUD command.

    The audit event is also the public integer identifier.  That keeps the
    existing operation URLs stable while separating mutable execution state
    from the append-only audit record.
    """

    class State(models.TextChoices):
        QUEUED = "queued"
        RUNNING = "running"
        SUCCEEDED = "succeeded"
        FAILED = "failed"
        CANCELLED = "cancelled"

    audit_event = models.OneToOneField(
        AuditEvent,
        on_delete=models.PROTECT,
        primary_key=True,
        related_name="hud_operation",
    )
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.PROTECT,
        related_name="hud_operations",
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="hud_operations",
    )
    action = models.CharField(max_length=64, db_index=True)
    object_type = models.CharField(max_length=64, blank=True, default="")
    object_id = models.CharField(max_length=64, blank=True, default="")
    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.QUEUED,
        db_index=True,
    )
    idempotency_key = models.CharField(max_length=128, null=True, blank=True)
    result = models.JSONField(default=dict, blank=True)
    error_code = models.CharField(max_length=64, blank=True, default="")
    error_message = models.CharField(max_length=512, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    started_at = models.DateTimeField(null=True, blank=True)
    heartbeat_at = models.DateTimeField(null=True, blank=True)
    finished_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "actor", "action", "idempotency_key"],
                name="uniq_hud_operation_idempotency",
            ),
        ]
        indexes = [
            models.Index(
                fields=["workspace", "state", "-created_at"],
                name="core_hudop_workspa_ef6115_idx",
            ),
            models.Index(
                fields=["object_type", "object_id"],
                name="core_hudop_object__795aa1_idx",
            ),
        ]

    def __str__(self):
        return f"hud-operation:{self.pk}:{self.action}:{self.state}"


class HudCommandOutbox(models.Model):
    """Transactional hand-off from an accepted HTTP command to a worker.

    Payloads are deliberately IDs-only.  Secrets and raw request bodies never
    cross the database/broker boundary.
    """

    class State(models.TextChoices):
        PENDING = "pending"
        PROCESSING = "processing"
        SUCCEEDED = "succeeded"
        FAILED = "failed"

    operation = models.OneToOneField(
        HudOperation,
        on_delete=models.CASCADE,
        related_name="outbox",
    )
    topic = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)
    state = models.CharField(
        max_length=16,
        choices=State.choices,
        default=State.PENDING,
        db_index=True,
    )
    available_at = models.DateTimeField(default=timezone.now, db_index=True)
    claimed_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    last_error = models.CharField(max_length=512, blank=True, default="")

    class Meta:
        indexes = [
            models.Index(
                fields=["state", "available_at"],
                name="core_hudco_state_47ed1d_idx",
            ),
        ]

    def __str__(self):
        return f"hud-outbox:{self.pk}:{self.topic}:{self.state}"
