"""T1 fake off-host audit shipper. Skip unless bucket configured.

audit() never calls this. The local hash chain is the MUST; this store is
in-process and append-only. A live Object Lock adapter, if Joseph-approved,
lives under providers/. This module has no AWS SDK.
"""
import json
from hashlib import sha256

from django.conf import settings
from django.utils import timezone

from core.audit import _canonical_row
from core.models import AuditEvent

FINGERPRINT = "audit-ship-failed:s3"
SOURCE_ENGINE = "core.audit_ship"


class AuditShipError(RuntimeError):
    """Off-host put failed. Never carries bucket credentials."""


class FakeAuditStore:
    """In-process append-only stand-in. Put only; no read, no delete."""

    def __init__(self):
        self.objects = []
        self.down = False

    def put(self, key, body):
        if self.down:
            raise AuditShipError("s3 down")
        self.objects.append((key, body))


def configured_bucket():
    return (getattr(settings, "AUDIT_S3_BUCKET", "") or "").strip()


def ship(*, bucket=None, store=None):
    """Append unshipped rows to `store`. Absent bucket → skip, never succeeded."""
    name = configured_bucket() if bucket is None else (bucket or "").strip()
    if not name:
        return {"status": "skipped", "reason": "absent_bucket", "n": 0}
    if store is None:
        _file_ship_failed()
        return {"status": "failed", "reason": "no_store", "n": 0}

    pending = list(
        AuditEvent.objects.filter(shipped_at__isnull=True).order_by("pk")
    )
    n = 0
    try:
        for event in pending:
            store.put(_object_key(event), _payload(event))
            event.shipped_at = timezone.now()
            event.save(update_fields=["shipped_at"])
            n += 1
    except Exception:
        _file_ship_failed()
        return {"status": "failed", "n": n}
    return {"status": "shipped", "n": n}


def _object_key(event):
    return f"audit/{event.pk:020d}.json"


def _payload(event):
    row = _canonical_row(event)
    chain_hash = sha256((event.prev_hash + row).encode("utf-8")).hexdigest()
    return json.dumps(
        {
            "chain_hash": chain_hash,
            "pk": event.pk,
            "prev_hash": event.prev_hash,
            "row": json.loads(row),
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _file_ship_failed():
    from monitor.alerts import raise_alert

    raise_alert(
        "audit-ship-failed",
        "s3",
        fingerprint=FINGERPRINT,
        source_engine=SOURCE_ENGINE,
        title="Audit trail failed to ship off-host",
        body=(
            "The local hash chain is intact but the off-host put did not "
            "succeed. An attacker who owns the Hub DB can still rewrite the "
            "local trail until shipping resumes."
        ),
        fix_action=(
            "Restore the configured audit bucket. Live Object Lock remains a "
            "Joseph interrupt. Do not treat this as hub-db-or-backup-failure."
        ),
    )
