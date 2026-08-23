"""audit() — the one-line helper §D1 demands. If emitting isn't one line, coverage rots."""
import json
from hashlib import sha256

from .models import AuditEvent


def _canonical_row(event):
    payload = {
        "action": event.action,
        "actor_id": event.actor_id,
        "detail": event.detail,
        "object_id": event.object_id,
        "object_type": event.object_type,
        "severity": event.severity,
        "source": event.source,
        "source_ip": event.source_ip,
        "ts": event.ts.isoformat(timespec="microseconds"),
    }
    return json.dumps(payload, separators=(",", ":"), sort_keys=True)


def _next_prev_hash():
    last = AuditEvent.objects.order_by("pk").last()
    if last is None:
        return ""
    return sha256((last.prev_hash + _canonical_row(last)).encode("utf-8")).hexdigest()


def audit(action, obj=None, *, actor=None, source="system", severity="info",
          source_ip=None, **detail):
    return AuditEvent.objects.create(
        action=action,
        actor=actor,
        source=source,
        severity=severity,
        source_ip=source_ip,
        object_type=type(obj).__name__ if obj is not None else "",
        object_id=str(getattr(obj, "pk", "")) if obj is not None else "",
        detail=detail,
        prev_hash=_next_prev_hash(),
    )
