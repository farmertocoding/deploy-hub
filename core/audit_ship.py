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

    object_lock = True
    versioning = True

    def __init__(self):
        self.objects = []
        self.down = False
        self.object_lock = True
        self.versioning = True

    def put(self, key, body):
        if self.down:
            raise AuditShipError("s3 down")
        if not self.object_lock or not self.versioning:
            raise AuditShipError("object lock required")
        existing = next((item for item in self.objects if item[0] == key), None)
        if existing is not None:
            if existing[1] != body:
                raise AuditShipError("immutable object already exists")
            return
        self.objects.append((key, body))

    def get(self, key):
        for stored_key, body in self.objects:
            if stored_key == key:
                return body
        return None


def configured_bucket():
    return (getattr(settings, "AUDIT_S3_BUCKET", "") or "").strip()


def production_store():
    """Append-only S3 store from settings. Constructed even when tests inject a fake."""
    from providers.audit_store import S3AuditStore

    return S3AuditStore.from_settings()


def ship(*, bucket=None, store=None):
    """Append unshipped rows to `store`. Absent bucket → skip, never succeeded."""
    name = configured_bucket() if bucket is None else (bucket or "").strip()
    if not name:
        return {"status": "skipped", "reason": "absent_bucket", "n": 0}
    if store is None:
        store = production_store()
    locked = bool(getattr(store, "object_lock", False) and getattr(store, "versioning", False))
    if not locked:
        _file_ship_failed()
        return {"status": "failed", "reason": "no_store", "n": 0}

    pending = list(
        AuditEvent.objects.filter(shipped_at__isnull=True).order_by("pk")
    )
    n = 0
    try:
        for event in pending:
            body = _payload(event)
            store.put(_object_key(event), body)
            event.shipped_at = timezone.now()
            event.save(update_fields=["shipped_at"])
            n += 1
    except Exception:
        _file_ship_failed()
        pending = AuditEvent.objects.filter(shipped_at__isnull=True).count()
        return {"status": "failed", "n": n, "pending": pending}
    return {"status": "shipped", "n": n}


def verify_shipped(*, store):
    """Independent of Hub DB: download, check order, hashes, and tamper."""
    if store is None or not getattr(store, "object_lock", False):
        raise AuditShipError("store is not an append-only Object Lock target")
    objects = list(getattr(store, "objects", []))
    prev_hash = ""
    seen = []
    for key, body in objects:
        payload = json.loads(body)
        if payload["prev_hash"] != prev_hash:
            raise AuditShipError("chain reordered or broken")
        row = json.dumps(payload["row"], separators=(",", ":"), sort_keys=True)
        expected = sha256((payload["prev_hash"] + row).encode("utf-8")).hexdigest()
        if payload["chain_hash"] != expected:
            raise AuditShipError("tampered object")
        prev_hash = payload["chain_hash"]
        seen.append(key)
    return {"ok": True, "n": len(seen)}


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
    from core.models import default_workspace
    from monitor.alerts import raise_alert

    raise_alert(
        "audit-ship-failed",
        "s3",
        fingerprint=FINGERPRINT,
        workspace=default_workspace(),
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
