"""AuditEvent hash chain (SEC-B3 local MUST, D-056). S3 ship is not this helper."""
import json
import sys
from hashlib import sha256

import pytest

pytestmark = pytest.mark.django_db


def _canonical_row(event):
    """Spec canonical JSON: sorted keys, no whitespace, the nine chained fields."""
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


@pytest.mark.req("SEC-B3-AUDIT-HASH-CHAIN")
def test_audit_genesis_empty_prev():
    """The first audit() row stores prev_hash="", not a hash of itself.

    What would make this fail: writing sha256('' + canonical_row) onto genesis
    so an empty prev is never observable, or leaving prev_hash unset/null.
    """
    from core.audit import audit
    from core.models import AuditEvent

    assert not AuditEvent.objects.exists()
    event = audit("genesis", source="system")
    event.refresh_from_db()
    assert event.prev_hash == ""


@pytest.mark.req("SEC-B3-AUDIT-HASH-CHAIN")
def test_audit_event_prev_hash_chains():
    """Each later row's prev_hash is sha256(prev.prev_hash + canonical(prev)).

    What would make this fail: hashing the current row into its own prev_hash
    (genesis content never enters the chain), hashing without the previous
    prev_hash, pretty-printed JSON, or unsorted keys so two encodings of the
    same row diverge.
    """
    from core.audit import audit

    first = audit("one", source="system", note="a")
    second = audit("two", source="system", note="b")
    third = audit("three", source="api")

    first.refresh_from_db()
    second.refresh_from_db()
    third.refresh_from_db()

    assert first.prev_hash == ""
    expected_second = sha256(
        (first.prev_hash + _canonical_row(first)).encode("utf-8")
    ).hexdigest()
    assert second.prev_hash == expected_second
    assert len(second.prev_hash) == 64
    expected_third = sha256(
        (second.prev_hash + _canonical_row(second)).encode("utf-8")
    ).hexdigest()
    assert third.prev_hash == expected_third


@pytest.mark.req("SEC-B3-AUDIT-HASH-CHAIN")
def test_audit_does_not_call_s3(monkeypatch):
    """Writing the chain is local. A missing bucket must not raise or delay.

    What would make this fail: audit() importing boto3, putting an object,
    or stamping shipped_at so the helper blocks on Task 11's shipper.
    """
    from core.audit import audit
    from core.models import AuditEvent

    class Forbidden:
        def __getattr__(self, name):
            raise AssertionError(f"audit() blocked on S3 via {name}")

        def __call__(self, *args, **kwargs):
            raise AssertionError("audit() blocked on S3")

        def client(self, *args, **kwargs):
            raise AssertionError("audit() constructed an S3 client")

    monkeypatch.setitem(sys.modules, "boto3", Forbidden())
    monkeypatch.setitem(sys.modules, "botocore", Forbidden())

    event = audit("local-chain", source="system")
    event.refresh_from_db()
    assert event.shipped_at is None
    assert AuditEvent.objects.filter(pk=event.pk, action="local-chain").exists()
    assert event.prev_hash == ""
