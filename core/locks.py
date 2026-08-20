"""Postgres operation locks (§A5). Redis is the broker, never the lock store.

acquire is INSERT; a unique conflict on (scope, object_id, kind) refuses.
SELECT FOR UPDATE is a later Postgres-only concern (Phase 2.5 / T2).
"""
from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import OperationLock


def acquire(scope, object_id, kind, holder):
    """Take the lock. Returns the row, or None if it is already held."""
    try:
        with transaction.atomic():
            return OperationLock.objects.create(
                scope=scope,
                object_id=str(object_id),
                kind=kind,
                holder=holder,
            )
    except IntegrityError:
        return None


def release(scope, object_id, kind, holder=None):
    """Drop the lock row. holder, if given, must match."""
    qs = OperationLock.objects.filter(
        scope=scope, object_id=str(object_id), kind=kind,
    )
    if holder is not None:
        qs = qs.filter(holder=holder)
    deleted, _ = qs.delete()
    return deleted > 0


def heartbeat(scope, object_id, kind, holder=None):
    """Touch heartbeat_at so a sweep knows the holder is still alive."""
    qs = OperationLock.objects.filter(
        scope=scope, object_id=str(object_id), kind=kind,
    )
    if holder is not None:
        qs = qs.filter(holder=holder)
    return qs.update(heartbeat_at=timezone.now()) > 0
