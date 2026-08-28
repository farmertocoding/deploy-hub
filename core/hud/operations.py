"""Durable HUD command operations and transactional outbox processing.

HTTP handlers persist an ``AuditEvent`` + ``HudOperation`` + IDs-only outbox
row in one database transaction.  Celery is merely a wake-up mechanism: a
broker outage cannot lose the command because Beat polls pending rows again.
"""
from datetime import timedelta

from django.conf import settings
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.utils import timezone

from core.audit import audit
from core.hud.ports import TOPIC_HANDLERS
from core.models import (
    HudCommandOutbox,
    HudOperation,
)


class OperationDispatchError(RuntimeError):
    code = "dispatch_failed"

    def __init__(self, message, *, code=None):
        super().__init__(message)
        if code:
            self.code = code


def request_workspace(request):
    """Resolve the workspace selected by authorization middleware/RBAC.

    This deliberately does not authorize the request; HUD permissions do that
    before command creation.  It only records the already-selected isolation
    boundary on the durable operation.
    """
    from core.rbac import request_workspace as resolve_request_workspace

    workspace = resolve_request_workspace(request)
    if workspace is None:
        # Permission classes normally refuse before this service is called.
        # Keeping this fail-closed protects callers that bypass an APIView.
        raise OperationDispatchError("Workspace access is required.", code="workspace_required")
    return workspace


def create_operation(
    request,
    action,
    *,
    object_type="",
    object_id="",
    idempotency_key="",
    topic="hud.command.recorded",
    audit_detail=None,
):
    """Atomically persist an accepted command and its worker hand-off."""
    workspace = request_workspace(request)
    normalized_key = str(idempotency_key or "").strip() or None
    lookup = dict(
        workspace=workspace, actor=request.user, action=action,
        idempotency_key=normalized_key,
    )
    if normalized_key:
        existing = HudOperation.objects.filter(**lookup).first()
        if existing:
            return existing, True

    try:
        with transaction.atomic():
            event = audit(
                action,
                actor=request.user,
                source="api",
                workspace=workspace,
                object_type=object_type,
                object_id=str(object_id or ""),
                **(audit_detail or {}),
            )
            # audit() derives type/id from obj; commands often refer to an object by
            # ID before a model instance is available, so pin those canonical fields.
            event.object_type = object_type
            event.object_id = str(object_id or "")
            event.workspace = workspace
            event.save(update_fields=["object_type", "object_id", "workspace"])
            operation = HudOperation.objects.create(
                audit_event=event,
                workspace=workspace,
                actor=request.user,
                action=action,
                object_type=object_type,
                object_id=str(object_id or ""),
                idempotency_key=normalized_key,
            )
            outbox = HudCommandOutbox.objects.create(
                operation=operation,
                topic=topic,
                payload={"operation_id": operation.pk},
            )
            if not getattr(settings, "CELERY_TASK_ALWAYS_EAGER", False):
                transaction.on_commit(lambda: _nudge_worker(outbox.pk), robust=True)
    except IntegrityError:
        existing = HudOperation.objects.filter(**lookup).first()
        if existing:
            return existing, True
        raise
    return operation, False


def envelope_for_outbox(outbox_id):
    """Sign the worker envelope at enqueue. Never delay an unsigned id."""
    from core.task_envelope import wrap

    outbox = HudCommandOutbox.objects.select_related("operation").get(pk=outbox_id)
    return wrap(
        task="core.tasks.process_hud_outbox",
        workspace_id=outbox.operation.workspace_id,
        resource_type="HudCommandOutbox",
        resource_id=outbox.pk,
    )


def _nudge_worker(outbox_id):
    try:
        from core.tasks import process_hud_outbox

        process_hud_outbox.delay(outbox_id, envelope_for_outbox(outbox_id))
    except Exception:  # broker outage: Beat will find the pending row
        return False
    return True


def pending_outbox_ids(*, limit=100, now=None):
    clock = now or timezone.now()
    stale_before = clock - timedelta(
        seconds=int(getattr(settings, "HUD_OUTBOX_CLAIM_TIMEOUT_SECONDS", 300)),
    )
    return list(
        HudCommandOutbox.objects.filter(available_at__lte=clock)
        .filter(
            Q(state=HudCommandOutbox.State.PENDING)
            | Q(
                state=HudCommandOutbox.State.PROCESSING,
                claimed_at__lt=stale_before,
            )
        )
        .order_by("available_at", "pk")
        .values_list("pk", flat=True)[:limit]
    )


def process_outbox(outbox_id):
    """Claim and execute one row. Duplicate Celery deliveries are harmless."""
    clock = timezone.now()
    stale_before = clock - timedelta(
        seconds=int(getattr(settings, "HUD_OUTBOX_CLAIM_TIMEOUT_SECONDS", 300)),
    )
    with transaction.atomic():
        row = (
            HudCommandOutbox.objects.select_for_update()
            .select_related("operation")
            .get(pk=outbox_id)
        )
        if row.state in (row.State.SUCCEEDED, row.State.FAILED):
            return row.operation.result
        if row.state == row.State.PROCESSING and row.claimed_at and row.claimed_at >= stale_before:
            return {"duplicate": True, "operation_id": row.operation_id}
        row.state = row.State.PROCESSING
        row.claimed_at = clock
        row.attempts += 1
        row.last_error = ""
        row.save(update_fields=["state", "claimed_at", "attempts", "last_error"])
        operation = row.operation
        operation.state = operation.State.RUNNING
        operation.started_at = operation.started_at or clock
        operation.heartbeat_at = clock
        operation.attempts = row.attempts
        operation.error_code = ""
        operation.error_message = ""
        operation.save(update_fields=[
            "state", "started_at", "heartbeat_at", "attempts",
            "error_code", "error_message",
        ])

    try:
        result = _dispatch(row.topic, operation)
    except Exception as exc:  # worker boundary must persist a useful terminal state
        return _record_failure(row.pk, exc)

    finished = timezone.now()
    with transaction.atomic():
        row = (
            HudCommandOutbox.objects.select_for_update()
            .select_related("operation").get(pk=row.pk)
        )
        row.state = row.State.SUCCEEDED
        row.completed_at = finished
        row.save(update_fields=["state", "completed_at"])
        operation = row.operation
        operation.state = operation.State.SUCCEEDED
        operation.result = result or {}
        operation.heartbeat_at = finished
        operation.finished_at = finished
        operation.save(update_fields=["state", "result", "heartbeat_at", "finished_at"])
    return result or {}


def _record_failure(outbox_id, exc):
    finished = timezone.now()
    code = getattr(exc, "code", "worker_error")
    # Exception text is bounded and never includes request bodies or credentials.
    message = str(exc)[:512] or type(exc).__name__
    with transaction.atomic():
        row = (
            HudCommandOutbox.objects.select_for_update()
            .select_related("operation").get(pk=outbox_id)
        )
        row.state = row.State.FAILED
        row.completed_at = finished
        row.last_error = message
        row.save(update_fields=["state", "completed_at", "last_error"])
        operation = row.operation
        operation.state = operation.State.FAILED
        operation.error_code = code
        operation.error_message = message
        operation.heartbeat_at = finished
        operation.finished_at = finished
        operation.save(update_fields=[
            "state", "error_code", "error_message", "heartbeat_at", "finished_at",
        ])
    return {"ok": False, "error_code": code}


def _dispatch(topic, operation):
    if topic == "hud.command.recorded":
        return {"ok": True, "effect": "persisted", "object_id": operation.object_id}
    handler = TOPIC_HANDLERS.get(topic)
    if handler is None:
        raise OperationDispatchError(
            "No worker is registered for this command.", code="handler_missing",
        )
    return handler(operation)
