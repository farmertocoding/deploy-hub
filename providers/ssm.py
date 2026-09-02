"""SSM parameter port (D-069). The only module that may import boto3 for SSM.

Push (`_put_env_file`) stays default. Pull writes /deploy-hub/{target.pk}/… only.
Tests enter mock_aws_ssm() (moto 5.x, not LocalStack) instead of importing moto
themselves. Live AWS is a Joseph interrupt — dummy creds inside the T1 helper
so a missed context cannot pick up a real profile.
"""
import os
from contextlib import contextmanager

from core.models import require_workspace

from .aws_creds import boto3_client

HUB_PREFIX = "/deploy-hub/"


class SsmError(RuntimeError):
    """SSM call failed. Never carries parameter values or AWS keys."""


class ParameterNotFound(SsmError):
    """Get of a missing parameter. The playbook treats this as a miss, not a leak."""


def parameter_name(target, key):
    """Hub path for one env key: /deploy-hub/{target.pk}/{key} — never a slug."""
    pk = getattr(target, "pk", target)
    text = str(key or "").strip().lstrip("/")
    if not text or "/" in text or ".." in text:
        raise SsmError("SSM parameter key must be a single path segment")
    return f"{HUB_PREFIX}{pk}/{text}"


def assert_parameter_path(name, *, target=None):
    """Refuse anything outside /deploy-hub/ or, when bound, /deploy-hub/{pk}/."""
    path = str(name or "")
    if not path.startswith(HUB_PREFIX) or path in {HUB_PREFIX, HUB_PREFIX.rstrip("/")}:
        raise SsmError("SSM path is off /deploy-hub/ prefix")
    rest = path[len(HUB_PREFIX):]
    if not rest or rest.startswith("/") or ".." in rest.split("/"):
        raise SsmError("SSM path is off /deploy-hub/ prefix")
    if target is not None:
        pk = str(getattr(target, "pk", target))
        prefix = f"{HUB_PREFIX}{pk}/"
        if not path.startswith(prefix) or path == prefix:
            raise SsmError("SSM path is off /deploy-hub/{target.pk}/ prefix")


def instance_profile_policy(target):
    """Get-only on /deploy-hub/{target.pk}/* — no Put, no ec2:*, no iam:*."""
    pk = getattr(target, "pk", target)
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "SsmGetOnly",
                "Effect": "Allow",
                "Action": "ssm:GetParameter*",
                "Resource": f"arn:aws:ssm:*:*:parameter/deploy-hub/{pk}/*",
            }
        ],
    }


def file_ssm_fail(target, *, names=(), reason=""):
    """kind ssm-fail, fingerprint ssm-fail:{target.pk}. Refs, never values."""
    from core.models import Target
    from monitor.alerts import raise_alert

    pk = getattr(target, "pk", target)
    if not hasattr(target, "zone"):
        target = Target.objects.filter(pk=pk).select_related("zone").first() or target
    listed = ", ".join(str(item) for item in names if item)
    body = f"SSM parameter operation failed for target {pk} (prefix /deploy-hub/{pk}/"
    if listed:
        body += f"; names {listed}"
    if reason:
        body += f"; {reason}"
    body += "). Refs only; parameter values are omitted."
    raise_alert(
        "ssm-fail",
        f"target:{pk}",
        workspace=require_workspace(target),
        fingerprint=f"ssm-fail:{pk}",
        source_engine="ssm",
        title=f"SSM parameter operation failed for target {pk}",
        body=body,
        fix_action=(
            "Check Hub SSM Put/Get/Delete/AddTags on /deploy-hub/* and the "
            "Get-only instance profile on /deploy-hub/{target.pk}/*"
        ),
    )


class SsmClient:
    """Hub SSM client. Constructed by ssm_for, not by tests importing boto3."""

    _MUTATING = frozenset({"put_parameter", "delete_parameter", "add_tags"})

    def __init__(
        self,
        *,
        access_key_id,
        secret_access_key,
        region_name="us-east-1",
        target=None,
        client=None,
    ):
        if not access_key_id or not secret_access_key:
            raise SsmError("explicit AWS keys are required; refusing default chain")
        self.target = target
        self.calls = []
        self._client = client or boto3_client(
            "ssm",
            access_key_id=access_key_id,
            secret_access_key=secret_access_key,
            region_name=region_name,
        )

    def mutating_calls(self):
        return [call for call in self.calls if call[0] in self._MUTATING]

    def put_parameter(self, name, value, *, tags=None, overwrite=True):
        assert_parameter_path(name, target=self.target)
        self.calls.append(("put_parameter", name))
        try:
            self._client.put_parameter(
                Name=name,
                Value="" if value is None else str(value),
                Type="SecureString",
                Overwrite=overwrite,
            )
            if tags:
                self.calls.append(("add_tags", name))
                self._client.add_tags_to_resource(
                    ResourceType="Parameter",
                    ResourceId=name,
                    Tags=[{"Key": str(k), "Value": str(v)} for k, v in tags.items()],
                )
        except SsmError:
            raise
        except Exception as exc:
            raise SsmError("SSM PutParameter failed") from exc

    def get_parameter(self, name):
        assert_parameter_path(name, target=self.target)
        self.calls.append(("get_parameter", name))
        try:
            resp = self._client.get_parameter(Name=name, WithDecryption=True)
        except Exception as exc:
            raise ParameterNotFound("parameter not found") from exc
        return resp["Parameter"]["Value"]

    def delete_parameter(self, name):
        assert_parameter_path(name, target=self.target)
        self.calls.append(("delete_parameter", name))
        try:
            self._client.delete_parameter(Name=name)
        except Exception as exc:
            raise SsmError("SSM DeleteParameter failed") from exc


@contextmanager
def mock_aws_ssm():
    """T1 moto 5.x context. Dummy creds so boto3 never reaches live AWS."""
    from moto import mock_aws

    dummy = "testing"  # T1 dummy so boto3 cannot pick up a live profile
    pinned = {
        "AWS_ACCESS_KEY_ID": dummy,
        "AWS_SECRET_ACCESS_KEY": dummy,
        "AWS_SESSION_TOKEN": dummy,
        "AWS_SECURITY_TOKEN": dummy,
        "AWS_DEFAULT_REGION": "us-east-1",
        "AWS_REGION": "us-east-1",
    }
    saved = {name: os.environ.get(name) for name in pinned}
    os.environ.update(pinned)
    try:
        with mock_aws():
            yield
    finally:
        for name, old in saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old
