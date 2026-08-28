"""audit() — the one-line helper §D1 demands. If emitting isn't one line, coverage rots."""
import json
import time
from hashlib import sha256

from django.db import IntegrityError, transaction
from django.db.utils import OperationalError

from .models import AuditChainHead, AuditEvent, workspace_of

CHAIN_VERSION = 2


class AuditWorkspaceRequired(TypeError):
    """Omitted or ambiguous workspace is rejected, never defaulted."""


def _canonical_row(event):
    payload = {
        "action": event.action,
        "actor_id": event.actor_id,
        "chain_version": int(getattr(event, "chain_version", None) or CHAIN_VERSION),
        "detail": event.detail,
        "object_id": event.object_id,
        "object_type": event.object_type,
        "partner_id": event.partner_id,
        "scope": getattr(event, "scope", None) or "workspace",
        "severity": event.severity,
        "source": event.source,
        "source_ip": event.source_ip,
        "ts": event.ts.isoformat(timespec="microseconds"),
        "workspace_id": event.workspace_id,
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _row_hash(event):
    return sha256((event.prev_hash + _canonical_row(event)).encode("utf-8")).hexdigest()


def _resolve_workspace(obj, workspace, scope):
    if scope == "system":
        return None
    if workspace is not None:
        return workspace
    inferred = workspace_of(obj)
    if inferred is not None:
        return inferred
    if getattr(obj, "owner_type", None):
        return None
    raise AuditWorkspaceRequired(
        "audit() requires workspace or an object that owns one"
    )


def verify_chain(events=None):
    """Return True when each event's prev_hash matches the predecessor hash."""
    rows = list(events if events is not None else AuditEvent.objects.order_by("pk"))
    prev = None
    for event in rows:
        if prev is None:
            if event.prev_hash:
                return False
        elif event.prev_hash != _row_hash(prev):
            return False
        prev = event
    return True


def audit(action, obj=None, *, actor=None, source="system", severity="info",
          source_ip=None, workspace=None, scope=None, partner=None, **detail):
    if scope is None:
        if workspace is None and obj is None:
            scope = "system"
        else:
            scope = "workspace"
    workspace = _resolve_workspace(obj, workspace, scope)
    if scope == "workspace" and workspace is None and getattr(obj, "owner_type", None):
        scope = "system"
    if partner is None:
        partner = getattr(obj, "partner", None)
        if partner is None and type(obj).__name__ == "Partner":
            partner = obj
    last_error = None
    for attempt in range(8):
        try:
            with transaction.atomic():
                head_qs = AuditChainHead.objects.select_for_update()
                if scope == "system":
                    head = head_qs.filter(scope="system", workspace__isnull=True).first()
                else:
                    head = head_qs.filter(scope="workspace", workspace=workspace).first()
                if head is None:
                    try:
                        with transaction.atomic():
                            head = AuditChainHead.objects.create(
                                scope=scope,
                                workspace=workspace,
                                version=CHAIN_VERSION,
                            )
                    except IntegrityError:
                        if scope == "system":
                            head = head_qs.filter(
                                scope="system", workspace__isnull=True,
                            ).first()
                        else:
                            head = head_qs.filter(
                                scope="workspace", workspace=workspace,
                            ).first()
                    else:
                        head = AuditChainHead.objects.select_for_update().get(pk=head.pk)
                event = AuditEvent(
                    action=action,
                    actor=actor,
                    source=source,
                    severity=severity,
                    source_ip=source_ip,
                    object_type=type(obj).__name__ if obj is not None else "",
                    object_id=str(getattr(obj, "pk", "")) if obj is not None else "",
                    detail=detail,
                    prev_hash=head.last_hash,
                    workspace=workspace,
                    scope=scope,
                    chain_version=CHAIN_VERSION,
                    partner=partner,
                )
                event.save()
                head.last_hash = _row_hash(event)
                head.last_event = event
                head.save(update_fields=["last_hash", "last_event"])
                return event
        except (OperationalError, IntegrityError) as exc:
            last_error = exc
            time.sleep(0.01 * (attempt + 1))
    raise last_error
