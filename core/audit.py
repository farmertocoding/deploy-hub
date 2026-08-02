"""audit() — the one-line helper §D1 demands. If emitting isn't one line, coverage rots."""
from .models import AuditEvent


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
    )
