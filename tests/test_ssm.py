"""T1: SSM pull seam (D-069 / AWS-SSM-PULL).

boto3, botocore, and moto must not appear as imports in this file. Dummy
creds and the moto 5.x context live in providers/ssm.py so the tested client
is the shipped client (the D-034 split).
"""
from __future__ import annotations

import json
import pathlib
import re

import pytest
from django.test import override_settings

from core.transport import FakeTransport

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
PLANTED = "SSM-PULL-PLANTED-VALUE-do-not-log"
AKI = "AKIASSMPULLTESTNOTAREALKEY"
SAK = "ssm-pull-hub-secret-access-key-not-a-credential"
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)


def _zone(slug="ssm-zone"):
    from core.models import NetworkZone

    return NetworkZone.objects.create(name=slug, slug=slug)


def _target(*, slug="ssm-host"):
    from core.models import Target

    return Target.objects.create(
        zone=_zone(slug),
        kind=Target.Kind.AWS_EC2,
        host=f"{slug}.example.test",
        ssh_user="deploy",
        status=Target.Status.READY,
    )


def _desired(target, ssm, transport, *, mode=None, mapping=None, slug="app"):
    desired = {
        "transport": transport,
        "target": target,
        "ssm": ssm,
        "site_slug": slug,
        "deployment_id": 1,
        "env_mapping": mapping if mapping is not None else {"APP_SECRET": PLANTED},
    }
    if mode is not None:
        desired["secrets_mode"] = mode
    return desired


def _blobs(*parts):
    out = []
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (bytes, bytearray)):
            out.append(bytes(part))
        elif isinstance(part, (list, tuple, dict)):
            out.append(json.dumps(part, default=str).encode())
        else:
            out.append(str(part).encode())
    return out


def _assert_no_planted(blobs, *, where):
    for raw in _blobs(*blobs):
        text = raw.decode("utf-8", "replace")
        assert PLANTED not in text, f"{where} leaked the SSM value"
        assert PLANTED.encode() not in raw, f"{where} leaked SSM value bytes"
        assert AKI not in text, f"{where} leaked AWS_ACCESS_KEY_ID material"
        assert SAK not in text, f"{where} leaked Hub secret_access_key"


def _actions_and_resources(document):
    actions, resources = [], []
    stmt = (document or {}).get("Statement") or []
    if isinstance(stmt, dict):
        stmt = [stmt]
    for row in stmt:
        if not isinstance(row, dict):
            continue
        act = row.get("Action") or []
        res = row.get("Resource") or []
        if isinstance(act, str):
            act = [act]
        if isinstance(res, str):
            res = [res]
        actions.extend(str(a) for a in act)
        resources.extend(str(r) for r in res)
    return actions, resources


@pytest.mark.req("AWS-SSM-PULL")
def test_push_remains_default():
    """Vaulted env still lands in the 0600 env file when secrets_mode is omitted.

    What would make this fail: defaulting to ssm_pull so every deploy stops
    writing the env file, or reading Site.tier to pick the seam.
    """
    from deploys.steps import _put_env_file, _secrets_mode
    from providers.fakes import FakeSsm

    assert _secrets_mode({}) == "push"
    assert _secrets_mode({"manifest_body": {}}) == "push"
    assert _secrets_mode({"manifest_body": {"secrets_mode": None}}) == "push"

    target = _target(slug="push-default")
    ssm = FakeSsm(target=target)
    transport = FakeTransport()
    _put_env_file(_desired(target, ssm, transport))
    assert ssm.mutating_calls() == []
    assert ssm.parameters == {}
    env_bodies = [body for body in transport.files.values()]
    assert env_bodies, transport.files
    joined = b"\n".join(body if isinstance(body, (bytes, bytearray)) else str(body).encode()
                        for body in env_bodies)
    assert b"APP_SECRET=" + PLANTED.encode() in joined
    assert transport.put_modes[next(iter(transport.files))] == 0o600


@pytest.mark.req("AWS-SSM-PULL")
def test_ssm_pull_uses_prefix_deploy_hub_target_pk():
    """Pull Put/Get names are /deploy-hub/{target.pk}/KEY, never a slug or host.

    What would make this fail: interpolating Site.name / target.host into the
    path so two targets can collide, or writing /deploy-hub/{slug}/.
    """
    from deploys.steps import _put_env_file
    from providers.fakes import FakeSsm
    from providers.ssm import parameter_name

    target = _target(slug="not-the-pk")
    ssm = FakeSsm(target=target)
    transport = FakeTransport()
    slug = "not-the-pk"
    _put_env_file(_desired(target, ssm, transport, mode="ssm_pull", slug=slug))
    expect = parameter_name(target, "APP_SECRET")
    assert expect == f"/deploy-hub/{target.pk}/APP_SECRET"
    assert expect in ssm.parameters
    assert list(ssm.parameters) == [expect]
    assert slug not in expect
    assert target.host not in expect
    assert f"/deploy-hub/{target.pk}/" in expect
    assert PLANTED == ssm.parameters[expect]


@pytest.mark.req("AWS-SSM-PULL")
def test_instance_profile_policy_is_get_only():
    """Instance profile is ssm:GetParameter* on /deploy-hub/{target.pk}/* only.

    What would make this fail: PutParameter, /deploy-hub/* (every target),
    ec2:*, or iam:* so a stolen profile is the Hub user.
    """
    from providers.ssm import instance_profile_policy

    target = _target(slug="profile-get")
    document = instance_profile_policy(target)
    actions, resources = _actions_and_resources(document)
    blob = json.dumps(document)
    assert actions, document
    assert all(
        action == "ssm:GetParameter*" or action.startswith("ssm:GetParameter")
        for action in actions
    )
    assert not any("Put" in action or "Delete" in action or "AddTags" in action
                   for action in actions)
    assert not any(action.startswith("ec2:") or action == "ec2:*" for action in actions)
    assert not any(action.startswith("iam:") or action == "iam:*" for action in actions)
    assert "ec2:*" not in blob
    assert "iam:*" not in blob
    assert "ssm:PutParameter" not in blob
    prefix = f"/deploy-hub/{target.pk}/"
    assert all(str(target.pk) in resource for resource in resources)
    assert all(prefix.rstrip("/") in resource or prefix in resource for resource in resources)
    assert not any(
        resource.endswith("parameter/deploy-hub/*") or resource.endswith(":parameter/*")
        or resource == "*"
        for resource in resources
    )


@pytest.mark.req("AWS-SSM-PULL")
def test_no_aws_access_key_id_on_target():
    """Pull never writes AWS_ACCESS_KEY_ID, Hub keys, or parameter values to the env file.

    What would make this fail: stuffing Hub CLOUD_CREDENTIAL or the SSM value
    into the 0600 env file so the target has static AWS keys (SEC-B2 for AWS).
    """
    from deploys.steps import _put_env_file
    from providers.fakes import FakeSsm

    target = _target(slug="no-aki")
    ssm = FakeSsm(target=target)
    transport = FakeTransport()
    mapping = {
        "APP_SECRET": PLANTED,
        "AWS_ACCESS_KEY_ID": AKI,
        "AWS_SECRET_ACCESS_KEY": SAK,
    }
    _put_env_file(_desired(target, ssm, transport, mode="ssm_pull", mapping=mapping))
    for remote, body in transport.files.items():
        raw = body if isinstance(body, (bytes, bytearray)) else str(body).encode()
        text = raw.decode("utf-8", "replace")
        assert "AWS_ACCESS_KEY_ID" not in text, remote
        assert "AWS_SECRET_ACCESS_KEY" not in text, remote
        assert AKI not in text
        assert SAK not in text
        assert PLANTED not in text
    assert not any(
        isinstance(body, (bytes, bytearray)) and PLANTED.encode() in body
        for body in transport.files.values()
    )
    argv_blob = json.dumps([payload for kind, payload in transport.calls], default=str)
    assert AKI not in argv_blob
    assert SAK not in argv_blob
    assert PLANTED not in argv_blob


@pytest.mark.req("AWS-SSM-PULL")
def test_no_ssm_value_in_finding_checkrun_log_task_arg_detail(caplog):
    """ssm-fail fingerprint is ssm-fail:{target.pk}; the planted value is absent.

    What would make this fail: interpolating Parameter.Value into Finding
    copy, CheckRun.results, a log line, a Celery kwarg, or AuditEvent.detail.
    """
    from core.models import AuditEvent, CheckRun, Finding
    from deploys.steps import _put_env_file
    from deploys.tasks import run_deploy
    from providers.fakes import FakeSsm
    from providers.ssm import SsmError

    target = _target(slug="ssm-fail-scan")
    ssm = FakeSsm(target=target, fail=True)
    transport = FakeTransport()
    with caplog.at_level("DEBUG"):
        with pytest.raises(SsmError):
            _put_env_file(_desired(target, ssm, transport, mode="ssm_pull"))
    row = Finding.objects.get(fingerprint=f"ssm-fail:{target.pk}")
    assert row.fingerprint != "ssm-fail"
    assert row.severity == Finding.Severity.P2
    surfaces = {
        "title": row.title,
        "body": row.body,
        "fix_action": row.fix_action,
        "entity": row.entity,
        "fingerprint": row.fingerprint,
        "checkruns": list(CheckRun.objects.values("kind", "status", "results")),
        "audit": list(AuditEvent.objects.values("action", "detail", "object_id")),
        "calls": ssm.calls,
        "files": {str(k): (v.decode() if isinstance(v, (bytes, bytearray)) else v)
                  for k, v in transport.files.items()},
        "transport": transport.calls,
        "logs": caplog.text,
        "celery": [run_deploy.s(target.pk).args, run_deploy.s(target.pk).kwargs],
    }
    _assert_no_planted([surfaces], where="finding/checkrun/log/task/detail")
    assert str(target.pk) in row.fingerprint
    assert str(target.pk) in row.body or str(target.pk) in row.entity


@pytest.mark.req("AWS-SSM-PULL")
def test_off_prefix_put_refuses():
    """Hub Put/Get/Delete/AddTags refuse anything outside /deploy-hub/{target.pk}/.

    What would make this fail: writing /other/*, /deploy-hub-not/*, or a
    sibling target's prefix, so the instance profile (or another principal)
    can read Hub-planted secrets it was not scoped for.
    """
    from providers.aws_creds import AwsCredsError
    from providers.fakes import FakeSsm
    from providers.registry import ssm_for
    from providers.ssm import SsmClient, SsmError, mock_aws_ssm

    target = _target(slug="off-prefix")
    other = _target(slug="other-prefix")
    ssm = FakeSsm(target=target)
    forbidden = (
        "/other/APP_SECRET",
        "/deploy-hub-not/APP_SECRET",
        f"/deploy-hub/{other.pk}/APP_SECRET",
        f"/deploy-hub/{target.host}/APP_SECRET",
        "APP_SECRET",
        "*",
    )
    for name in forbidden:
        with pytest.raises(SsmError, match="prefix|deploy-hub"):
            ssm.put_parameter(name, PLANTED)
        assert name not in ssm.parameters

    with mock_aws_ssm():
        client = SsmClient(
            target=target,
            access_key_id="testing",
            secret_access_key="testing",
            region_name="us-east-1",
        )
        for name in forbidden:
            with pytest.raises(SsmError, match="prefix|deploy-hub"):
                client.put_parameter(name, PLANTED)

    with override_settings(AWS_CREDENTIALS_REF=""):
        with pytest.raises((SsmError, AwsCredsError), match="empty|AWS_CREDENTIALS_REF"):
            ssm_for(target)


@pytest.mark.req("AWS-SSM-PULL")
def test_secrets_mode_is_not_site_tier():
    """Flip is desired/manifest secrets_mode, not Site.tier or a Site column.

    What would make this fail: adding Site.secrets_mode / Site.tier, or
    ignoring desired['secrets_mode'] so only a schema change can flip pull.
    """
    from core.models import Site
    from deploys.steps import _put_env_file, _secrets_mode
    from providers.fakes import FakeSsm

    assert "tier" not in {f.name for f in Site._meta.get_fields()}
    assert "secrets_mode" not in {f.name for f in Site._meta.get_fields()}

    target = _target(slug="mode-not-tier")
    ssm = FakeSsm(target=target)
    transport = FakeTransport()
    desired = _desired(target, ssm, transport)
    desired["manifest_body"] = {"secrets_mode": "ssm_pull"}
    assert _secrets_mode(desired) == "ssm_pull"
    _put_env_file(desired)
    assert list(ssm.parameters) == [f"/deploy-hub/{target.pk}/APP_SECRET"]
    for body in transport.files.values():
        raw = body if isinstance(body, (bytes, bytearray)) else str(body).encode()
        assert PLANTED.encode() not in raw


def test_ssm_tests_do_not_import_boto3():
    """This module never imports boto3/moto; the shipped helper is the client.

    What would make this fail: a convenience `import boto3` here, so the
    tested client is no longer providers/ssm.py (the D-034 split).
    """
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(text) is None
    offenders = []
    for py in (REPO / "tests").rglob("*.py"):
        if _IMPORT_BOTO.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py.relative_to(REPO)))
    assert offenders == [], f"boto3/botocore/moto import in tests/: {offenders}"


@pytest.mark.req("AWS-SSM-PULL")
def test_ssm_run_twice_zero_mutating_calls():
    """A second ssm_pull against matching parameters records no Put/Delete/AddTags.

    What would make this fail: PutParameter on every start, or a Transport
    put of the env values the second time (D-018).
    """
    from deploys.steps import _put_env_file
    from providers.fakes import FakeSsm

    target = _target(slug="ssm-twice")
    ssm = FakeSsm(target=target)
    transport = FakeTransport()
    desired = _desired(target, ssm, transport, mode="ssm_pull")
    _put_env_file(desired)
    assert ssm.mutating_calls(), "first pull must Put so the second can skip"
    first = list(ssm.mutating_calls())
    transport.calls.clear()
    _put_env_file(desired)
    assert ssm.mutating_calls()[len(first):] == []
    assert transport.mutating_calls() == []
