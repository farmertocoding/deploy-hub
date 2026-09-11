"""T1: daily IAM allowlist Beat (D-067). Same refuse as construction.

boto3, botocore, and moto must not appear as imports in this file. Dummy
creds, FakeIam, and inspect live in providers/aws_creds.py so the audit
reuses Task 2 rather than re-spelling ListGroupsForUser.
"""
import ast
import json
import os
import pathlib
import re

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
ACCOUNT = "123456789012"
REF = "hub-aws"
AKI = "t1-aws-access-key-id-not-a-credential"
SAK = "t1-aws-secret-access-key-not-a-credential"
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)


class _Sts:
    def get_caller_identity(self):
        return {
            "Account": ACCOUNT,
            "Arn": f"arn:aws:iam::{ACCOUNT}:user/hub",
        }


def _star_doc():
    return {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
    }


def _plant(*, owner_id=REF):
    from vault import service as vault_service
    from vault.models import Secret

    return vault_service.put(
        kind=Secret.Kind.CLOUD_CREDENTIAL,
        owner_type="aws",
        owner_id=owner_id,
        plaintext=json.dumps(
            {"access_key_id": AKI, "secret_access_key": SAK}
        ).encode(),
    )


def _findings():
    from core.models import Finding

    return Finding.objects.filter(fingerprint__startswith="aws-scope:")


def _audit(*, iam, sts=None, **settings_kw):
    from providers.aws_creds import audit_iam_scope

    _plant()
    kw = {"AWS_CREDENTIALS_REF": REF}
    kw.update(settings_kw)
    with override_settings(**kw):
        return audit_iam_scope(iam=iam, sts=sts or _Sts())


def _dump(run):
    from core.models import AuditEvent, Finding

    blobs = [run.kind, run.status, run.results]
    for row in Finding.objects.all():
        blobs.extend([
            row.title, row.body, row.fix_action, row.entity,
            row.fingerprint, row.severity, row.source_engine,
        ])
    for event in AuditEvent.objects.all():
        blobs.extend([event.action, event.detail, event.object_type, event.object_id])
    return json.dumps(blobs, default=str)


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_daily_audit_refuses_star():
    """Inline Action:* is drift: CheckRun aws_iam_scope plus aws-scope P2.

    What would make this fail: the daily Beat judging only managed-policy
    names (or skipping inspect) so an inline star Hub user stays silent
    until the next Settings paste.
    """
    from core.models import CheckRun
    from providers.aws_creds import FakeIam

    run = _audit(iam=FakeIam(inline=[{"name": "too-wide", "document": _star_doc()}]))
    assert run.kind == CheckRun.Kind.AWS_IAM_SCOPE
    assert run.status == CheckRun.Status.SUCCEEDED
    row = _findings().get()
    assert row.fingerprint == f"aws-scope:{ACCOUNT}"
    assert row.severity == "p2"
    assert "*" in row.body or "Action" in row.body or "refused" in row.body.lower()


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_daily_audit_refuses_administrator_access():
    """Attached AdministratorAccess is the same refuse as construction.

    What would make this fail: only scanning inline JSON so the AWS-managed
    Admin policy (the console default) looks clean because the audit never
    fetched the attached name.
    """
    from core.models import CheckRun
    from providers.aws_creds import FakeIam

    iam = FakeIam(
        attached=[
            {
                "name": "AdministratorAccess",
                "arn": "arn:aws:iam::aws:policy/AdministratorAccess",
                "document": _star_doc(),
            }
        ]
    )
    run = _audit(iam=iam)
    assert run.kind == CheckRun.Kind.AWS_IAM_SCOPE
    assert run.status == CheckRun.Status.SUCCEEDED
    row = _findings().get()
    assert "AdministratorAccess" in row.body or "AdministratorAccess" in row.title
    assert row.fingerprint == f"aws-scope:{ACCOUNT}"


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_daily_audit_refuses_group_attached_admin(monkeypatch):
    """Group-attached AdministratorAccess is the console path and must refuse.

    What would make this fail: inspecting only user attached+inline, or
    re-spelling ListGroupsForUser here so construction and the Beat drift
    (D-067: one helper, user AND groups).
    """
    from core.models import CheckRun
    from providers import aws_creds
    from providers.aws_creds import FakeIam

    seen = []
    real = aws_creds.collect_iam_documents

    def spy(iam):
        seen.append(iam)
        return real(iam)

    monkeypatch.setattr(aws_creds, "collect_iam_documents", spy)
    iam = FakeIam(
        groups=["admins"],
        group_attached={
            "admins": [
                {
                    "name": "AdministratorAccess",
                    "arn": "arn:aws:iam::aws:policy/AdministratorAccess",
                    "document": _star_doc(),
                }
            ]
        },
    )
    run = _audit(iam=iam)
    assert run.kind == CheckRun.Kind.AWS_IAM_SCOPE
    assert run.status == CheckRun.Status.SUCCEEDED
    assert seen, "daily audit must reuse providers.aws_creds.collect_iam_documents"
    row = _findings().get()
    assert row.fingerprint == f"aws-scope:{ACCOUNT}"
    assert "AdministratorAccess" in row.body or "AdministratorAccess" in row.title


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_daily_audit_files_aws_scope_on_drift():
    """Drift files kind aws-scope, fingerprint aws-scope:{account_id}, P2.

    What would make this fail: using kind as the fingerprint (second star
    overwrites the first), minting aws-scope:{secret}, or writing a second
    Finding kind the C12 table does not know.
    """
    from core.models import CheckRun, Finding
    from monitor.alert_rules import classify
    from providers.aws_creds import FakeIam

    assert classify("aws-scope") == "p2"
    iam = FakeIam(inline=[{"name": "star", "document": _star_doc()}])
    _audit(iam=iam)
    _audit(iam=iam)
    rows = _findings()
    assert rows.count() == 1
    row = rows.get()
    assert row.fingerprint == f"aws-scope:{ACCOUNT}"
    assert row.fingerprint != "aws-scope"
    assert row.severity == Finding.Severity.P2
    assert row.state == Finding.State.OPEN
    assert CheckRun.objects.filter(kind=CheckRun.Kind.AWS_IAM_SCOPE).count() == 2


def test_absent_ref_skips_and_does_not_green_live_aws():
    """Empty AWS_CREDENTIALS_REF is SKIPPED, never SUCCEEDED, not a live green.

    What would make this fail: writing succeeded when the vault ref is the
    default empty string (a T1-sibling green of a live IAM poll), scanning a
    leftover CLOUD_CREDENTIAL row, inventing HUB_TEST_AWS_TOKEN, marking
    these proofs t2/t3, or omitting the Beat owner.
    """
    from django.conf import settings

    from core.models import CheckRun
    from monitor import tasks as monitor_tasks
    from providers.aws_creds import audit_iam_scope

    _plant(owner_id="leftover-aws")
    with override_settings(AWS_CREDENTIALS_REF=""):
        run = audit_iam_scope()
        assert run.kind == CheckRun.Kind.AWS_IAM_SCOPE
        assert run.status == CheckRun.Status.SKIPPED
        assert run.status != CheckRun.Status.SUCCEEDED
        assert _findings().count() == 0

        outcome = monitor_tasks.audit_aws_iam_scope()
        assert outcome["kind"] == CheckRun.Kind.AWS_IAM_SCOPE
        assert outcome["status"] == CheckRun.Status.SKIPPED
        assert AKI not in json.dumps(outcome)
        assert SAK not in json.dumps(outcome)

    entry = settings.CELERY_BEAT_SCHEDULE["aws-iam-scope-daily"]
    assert entry["task"] == monitor_tasks.audit_aws_iam_scope.name
    assert float(entry["schedule"]) == 86400.0
    assert "kwargs" not in entry
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "control"

    src = pathlib.Path(__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    live_marks = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Attribute):
            continue
        if node.attr in {"t2", "t3"}:
            live_marks.append(node.attr)
    assert live_marks == [], f"T1 skip proof must not carry a live-tier mark: {live_marks}"

    base = (REPO / "hub" / "settings" / "base.py").read_text(encoding="utf-8")
    assert 'os.environ.get("HUB_AWS_CREDENTIALS_REF", "")' in base
    assert "HUB_TEST_AWS_TOKEN" not in base
    assert "HUB_TEST_CF_TOKEN" not in base
    assert "HUB_TEST_AWS_TOKEN" not in os.environ


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_results_have_refs_never_secret():
    """Clean CheckRun.results name the vault ref and account, never the keys.

    What would make this fail: interpolating access_key_id / secret material
    into results, Finding copy, or the Beat return dict so the inbox becomes
    a secret store.
    """
    from core.models import CheckRun
    from providers.aws_creds import FakeIam

    run = _audit(iam=FakeIam())
    assert run.kind == CheckRun.Kind.AWS_IAM_SCOPE
    assert run.status == CheckRun.Status.SUCCEEDED
    assert _findings().count() == 0
    payload = json.dumps(run.results)
    assert "schema_version" in run.results
    assert REF in payload
    assert ACCOUNT in payload
    assert AKI not in payload
    assert SAK not in payload
    assert "secret_access_key" not in payload
    assert "session_token" not in payload
    assert AKI not in _dump(run)
    assert SAK not in _dump(run)

    drifted = _audit(
        iam=FakeIam(inline=[{"name": "star", "document": _star_doc()}]),
    )
    blob = _dump(drifted)
    assert REF in blob
    assert ACCOUNT in blob
    assert AKI not in blob
    assert SAK not in blob
    assert "secret_access_key" not in json.dumps(drifted.results)


def _ec2_run(region=None):
    stmt = {
        "Effect": "Allow",
        "Action": "ec2:RunInstances",
        "Resource": "*",
    }
    if region is not None:
        stmt["Condition"] = {
            "StringEquals": {"aws:RequestedRegion": region},
        }
    return {"Version": "2012-10-17", "Statement": [stmt]}


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_daily_audit_uses_observe_region_not_empty_test_plane_list():
    """A C4 EC2 user pinned to the audit region is clean in prod.

    What would make this fail: forwarding HUB_TEST_AWS_REGIONS (prod default
    []) as refuse_iam_scope allowed_regions so a valid RunInstances +
    aws:RequestedRegion Hub user is a perpetual aws-scope P2. Construction
    observe defaults allowed_regions to (region_name,); the Beat must too.
    """
    from core.models import CheckRun
    from providers.aws_creds import FakeIam

    prod = {"HUB_TEST_AWS_REGIONS": [], "HUB_TEST_MODE": False}
    run = _audit(
        iam=FakeIam(inline=[{"name": "c4-ec2", "document": _ec2_run("us-east-1")}]),
        **prod,
    )
    assert run.kind == CheckRun.Kind.AWS_IAM_SCOPE
    assert run.status == CheckRun.Status.SUCCEEDED
    assert run.results.get("drift") in (None, "")
    assert _findings().count() == 0

    unbounded = _audit(
        iam=FakeIam(inline=[{"name": "ec2-any", "document": _ec2_run()}]),
        **prod,
    )
    assert unbounded.results.get("drift")
    assert _findings().filter(fingerprint=f"aws-scope:{ACCOUNT}").exists()

    _findings().delete()
    off = _audit(
        iam=FakeIam(inline=[{"name": "ec2-eu", "document": _ec2_run("eu-west-1")}]),
        **prod,
    )
    assert off.results.get("drift")
    assert _findings().filter(fingerprint=f"aws-scope:{ACCOUNT}").exists()


def test_aws_iam_audit_tests_do_not_import_boto3():
    """This module never imports boto3/moto; the tested client is the helper.

    What would make this fail: a convenience `import boto3` here, so the
    daily inspect is no longer the shipped Task 2 helper (the D-034 split).
    """
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(text) is None
    offenders = []
    for py in (REPO / "tests").rglob("*.py"):
        if _IMPORT_BOTO.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py.relative_to(REPO)))
    assert offenders == [], f"boto3/botocore/moto import in tests/: {offenders}"
