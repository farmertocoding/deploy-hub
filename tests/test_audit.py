"""AuditEvent hash chain (SEC-B3 local MUST, D-056). S3 ship is not this helper."""
import sys
from hashlib import sha256

import pytest

pytestmark = pytest.mark.django_db


def _canonical_row(event):
    from core.audit import _canonical_row as shipped

    return shipped(event)


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


def test_audit_omitted_workspace_on_tenant_object_is_inferred_or_rejected():
    from core.audit import AuditWorkspaceRequired, audit
    from core.models import Project, Workspace

    workspace = Workspace.objects.create(name="Audit A", slug="audit-a")
    project = Project.objects.create(
        workspace=workspace, name="a", slug="a-audit",
    )
    event = audit("project.touched", project, source="api")
    assert event.workspace_id == workspace.pk
    assert event.scope == "workspace"
    with pytest.raises(AuditWorkspaceRequired):
        audit("ambiguous", object(), source="api", scope="workspace")


def test_tenant_audit_stays_in_that_workspace():
    from core.audit import audit
    from core.models import AuditEvent, Project, Workspace

    a = Workspace.objects.create(name="A", slug="trail-a")
    b = Workspace.objects.create(name="B", slug="trail-b")
    pa = Project.objects.create(workspace=a, name="pa", slug="pa")
    pb = Project.objects.create(workspace=b, name="pb", slug="pb")
    audit("project.create", pa, source="api", workspace=a)
    audit("project.create", pb, source="api", workspace=b)
    assert AuditEvent.objects.filter(workspace=a, action="project.create").count() == 1
    assert AuditEvent.objects.filter(workspace=b, action="project.create").count() == 1


def test_editing_workspace_or_partner_breaks_verification():
    from core.audit import audit, verify_chain
    from core.models import Partner, Project, Workspace

    workspace = Workspace.objects.create(name="Hash", slug="hash-ws")
    other = Workspace.objects.create(name="Other", slug="hash-other")
    project = Project.objects.create(workspace=workspace, name="p", slug="p-hash")
    partner = Partner.objects.create(
        workspace=workspace, name="hash partner", slug="hash-partner",
    )
    first = audit("project.create", project, source="api", workspace=workspace)
    second = audit(
        "partner.create", partner, source="api", workspace=workspace, partner=partner,
    )
    third = audit("project.scan", project, source="api", workspace=workspace)
    assert verify_chain([first, second, third]) is True
    second.workspace = other
    second.save(update_fields=["workspace"])
    second.refresh_from_db()
    assert verify_chain([first, second, third]) is False


def test_verify_chain_none_reads_db_pk_order_and_rejects_genesis_prev():
    """Calling verify_chain() with no list must use AuditEvent.order_by("pk").

    What would make this fail: `events is None` inverted (list(None)), or
    order_by("XXpkXX"), or returning True when genesis already has a prev_hash.
    """
    from core.audit import audit, verify_chain
    from core.models import AuditEvent, Workspace

    workspace = Workspace.objects.create(name="Verify", slug="verify-none")
    audit("one", source="system", workspace=workspace)
    audit("two", source="system", workspace=workspace)
    assert verify_chain() is True
    first = AuditEvent.objects.filter(workspace=workspace).order_by("pk").first()
    first.prev_hash = "a" * 64
    first.save(update_fields=["prev_hash"])
    assert verify_chain() is False


@pytest.mark.django_db(transaction=True)
def test_concurrent_audit_writers_produce_one_linear_chain():
    from concurrent.futures import ThreadPoolExecutor

    from core.audit import audit, verify_chain
    from core.models import AuditEvent, Workspace

    workspace = Workspace.objects.create(name="Race", slug="audit-race")

    def _write(n):
        from django.db import connections

        connections.close_all()
        return audit("race", source="api", workspace=workspace, n=n).pk

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(_write, range(8)))
    rows = list(AuditEvent.objects.filter(workspace=workspace).order_by("pk"))
    assert len(rows) == 8
    assert verify_chain(rows) is True
    hashes = [row.prev_hash for row in rows]
    assert hashes[0] == ""
    assert len(set(hashes)) == len(hashes)


def test_workspace_delete_retains_audit_rows():
    from django.db.models.deletion import ProtectedError

    from core.audit import audit
    from core.models import AuditEvent, Project, Workspace

    workspace = Workspace.objects.create(name="Keep", slug="keep-audit")
    project = Project.objects.create(workspace=workspace, name="k", slug="k-audit")
    event = audit("project.create", project, source="api", workspace=workspace)
    with pytest.raises(ProtectedError):
        workspace.delete()
    assert AuditEvent.objects.filter(pk=event.pk).exists()
