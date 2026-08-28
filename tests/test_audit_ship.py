"""T1 fake audit S3 shipper (SEC-B3 SLIP). Skip-unless-bucket; no boto3.

audit() already writes the local hash chain and must never wait on this
module. Live Object Lock is a Joseph interrupt. Absent bucket is skip,
never SUCCEEDED-live.
"""
import inspect
import json
import sys
from hashlib import sha256

import pytest
from django.test import override_settings

from core.audit import _canonical_row, audit

pytestmark = pytest.mark.django_db

BUCKET = "hub-audit-t1"


@pytest.mark.req("SEC-B3-AUDIT-HASH-CHAIN")
def test_fake_shipper_appends_hash_chain():
    """A configured bucket plus the T1 fake store appends events in chain order.

    What would make this fail: shipping without prev_hash, hashing the current
    row into its own chain_hash so genesis never enters the off-host copy, or
    replacing an earlier object instead of appending.
    """
    from core.audit_ship import FakeAuditStore, ship
    from core.models import AuditEvent

    first = audit("one", source="system", fingerprint="rotate:1")
    second = audit("two", source="system", fingerprint="rotate:2")
    store = FakeAuditStore()

    with override_settings(AUDIT_S3_BUCKET=BUCKET):
        result = ship(store=store)

    assert result["status"] == "shipped"
    assert result["status"] != "succeeded"
    assert len(store.objects) == 2
    body0 = json.loads(store.objects[0][1])
    body1 = json.loads(store.objects[1][1])
    assert body0["prev_hash"] == ""
    expected = sha256(
        (first.prev_hash + _canonical_row(first)).encode("utf-8")
    ).hexdigest()
    assert body1["prev_hash"] == expected
    assert body1["prev_hash"] == second.prev_hash
    assert body0["chain_hash"] == body1["prev_hash"]
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.shipped_at is not None
    assert second.shipped_at is not None
    assert AuditEvent.objects.filter(shipped_at__isnull=True).count() == 0


@pytest.mark.req("SEC-B3-AUDIT-HASH-CHAIN")
def test_absent_bucket_skips():
    """Empty AUDIT_S3_BUCKET is skip, never SUCCEEDED, never a live Object Lock.

    What would make this fail: writing shipped_at with no bucket, returning
    succeeded so a skip looks like a live ship, inventing HUB_TEST_CF_TOKEN,
    or constructing boto3.
    """
    import core.audit_ship as audit_ship
    from core.models import AuditEvent, CheckRun, Finding

    with override_settings(AUDIT_S3_BUCKET=""):
        event = audit("local-unshipped", source="system")
        before = CheckRun.objects.count()
        result = audit_ship.ship(store=audit_ship.FakeAuditStore())

    event.refresh_from_db()
    assert result["status"] == "skipped"
    assert result["status"] != "succeeded"
    assert result.get("reason") == "absent_bucket"
    assert event.shipped_at is None
    assert CheckRun.objects.count() == before
    assert not Finding.objects.filter(
        fingerprint__startswith="audit-ship-failed",
    ).exists()
    assert AuditEvent.objects.filter(pk=event.pk, shipped_at__isnull=True).exists()

    src = inspect.getsource(audit_ship)
    assert "boto3" not in src
    assert "botocore" not in src


@pytest.mark.req("SEC-B3-AUDIT-HASH-CHAIN")
def test_audit_write_does_not_block_on_s3_down(monkeypatch):
    """audit() stays local when the off-host put would fail; ship files P2.

    What would make this fail: audit() calling ship/put, stamping shipped_at
    on a failed put, overloading hub-db-or-backup-failure, or an unregistered
    audit-ship-failed kind so classify() raises.
    """
    from core.audit_ship import FakeAuditStore, ship
    from core.models import Finding
    from monitor.alert_rules import classify

    calls = []

    def boom(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("audit() blocked on S3")

    monkeypatch.setattr("core.audit_ship.ship", boom)
    store = FakeAuditStore()
    store.down = True

    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError(f"audit() blocked on S3 via {name}")

        def __call__(self, *args, **kwargs):
            raise AssertionError("audit() blocked on S3")

        def client(self, *args, **kwargs):
            raise AssertionError("audit() constructed an S3 client")

    monkeypatch.setitem(sys.modules, "boto3", Forbidden())
    monkeypatch.setitem(sys.modules, "botocore", Forbidden())

    with override_settings(AUDIT_S3_BUCKET=BUCKET):
        event = audit("local-while-s3-down", source="system", key_ref="target-1-ssh")

    assert calls == []
    event.refresh_from_db()
    assert event.shipped_at is None
    assert "ship" not in inspect.getsource(audit)

    monkeypatch.undo()
    store = FakeAuditStore()
    store.down = True
    with override_settings(AUDIT_S3_BUCKET=BUCKET):
        result = ship(store=store)

    assert result["status"] == "failed"
    assert result["status"] != "succeeded"
    event.refresh_from_db()
    assert event.shipped_at is None
    assert store.objects == []
    assert classify("audit-ship-failed") == "p2"
    row = Finding.objects.get(fingerprint="audit-ship-failed:s3")
    assert row.severity == Finding.Severity.P2
    assert "hub-db-or-backup-failure" not in row.fingerprint
    dump = json.dumps([row.title, row.body, row.fix_action, event.detail], default=str)
    assert "BEGIN " not in dump
    assert "-----" not in dump


def test_missing_object_lock_fails_closed():
    from core.audit_ship import FakeAuditStore, ship

    audit("lock-required", source="system")
    store = FakeAuditStore()
    store.object_lock = False
    with override_settings(AUDIT_S3_BUCKET=BUCKET):
        result = ship(store=store)
    assert result["status"] == "failed"
    from core.models import AuditEvent
    assert AuditEvent.objects.filter(action="lock-required", shipped_at__isnull=True).exists()


def test_retry_is_idempotent_and_partial_failure_leaves_pending():
    from core.audit_ship import FakeAuditStore, ship, verify_shipped

    first = audit("idem-1", source="system")
    second = audit("idem-2", source="system")
    store = FakeAuditStore()
    with override_settings(AUDIT_S3_BUCKET=BUCKET):
        assert ship(store=store)["n"] == 2
        again = ship(store=store)
    assert again["n"] == 0
    assert len(store.objects) == 2
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.shipped_at is not None
    store.objects[0] = (store.objects[0][0], store.objects[0][1].replace("idem-1", "tamper"))
    from core.audit_ship import AuditShipError

    with pytest.raises(AuditShipError):
        verify_shipped(store=store)


def test_beat_schedules_audit_shipping():
    from django.conf import settings

    entry = settings.CELERY_BEAT_SCHEDULE["ship-audit-trail"]
    assert entry["task"] == "core.tasks.ship_audit_trail"


def test_ship_without_store_uses_production_append_only_provider(monkeypatch):
    """Beat calls ship() with no store=; a configured bucket must still put.

    What would make this fail: ship() treating missing store as fail-closed
    even when AUDIT_S3_BUCKET is set, so the Beat task can only skip.
    """
    from core.audit_ship import FakeAuditStore, ship

    audit("prod-store", source="system")
    fake = FakeAuditStore()
    monkeypatch.setattr("core.audit_ship.production_store", lambda: fake)
    with override_settings(AUDIT_S3_BUCKET=BUCKET):
        result = ship()
    assert result["status"] == "shipped"
    assert result["n"] == 1
    assert fake.objects
