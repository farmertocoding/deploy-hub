"""AWS vault-ref credentials + IAM allowlist at construction and daily audit.

The only module that may import boto3 for Hub-user STS/IAM. Constructors pass
explicit keys into boto3.client and never omit them (no default chain, no
~/.aws, no instance-profile-on-the-Hub). tests/ import this helper (or FakeIam
/ a policy document), never boto3.

Vault JSON is exactly {access_key_id, secret_access_key}. Extra keys and
session tokens refuse. Empty AWS_CREDENTIALS_REF refuses construction and
skips the daily Beat even if a leftover CLOUD_CREDENTIAL row exists — we
never scan the vault for owner_id. The daily audit reuses collect_iam_documents
/ refuse_iam_scope (user AND groups); it does not re-spell IAM inspect.
"""
import json
import os
from contextlib import contextmanager
from urllib.parse import unquote

import boto3
from django.conf import settings

from core.test_mode import assert_test_aws

_CRED_KEYS = frozenset({"access_key_id", "secret_access_key"})
_CLIENT_KWARGS = []  # last boto3.client kwargs; tests inspect, never boto3

_IAM_SELF = frozenset({
    "iam:GetUser",
    "iam:ListAttachedUserPolicies",
    "iam:GetPolicy",
    "iam:GetPolicyVersion",
    "iam:ListUserPolicies",
    "iam:GetUserPolicy",
    "iam:ListGroupsForUser",
    "iam:ListAttachedGroupPolicies",
    "iam:ListGroupPolicies",
    "iam:GetGroupPolicy",
})
_EC2_EXACT = frozenset({
    "ec2:RunInstances",
    "ec2:TerminateInstances",
    "ec2:CreateTags",
    "ec2:GetConsoleOutput",
    "ec2:CreateImage",
    "ec2:AuthorizeSecurityGroupIngress",
    "ec2:RevokeSecurityGroupIngress",
    "ec2:AuthorizeSecurityGroupEgress",
    "ec2:RevokeSecurityGroupEgress",
    "ec2:CreateSecurityGroup",
    "ec2:DeleteSecurityGroup",
    "ec2:DescribeSecurityGroups",
    "ec2:DescribeSecurityGroupRules",
    "ec2:ModifySecurityGroupRules",
})
_SSM = frozenset({
    "ssm:PutParameter",
    "ssm:GetParameter",
    "ssm:GetParameters",
    "ssm:GetParametersByPath",
    "ssm:GetParameterHistory",
    "ssm:DeleteParameter",
    "ssm:DeleteParameters",
    "ssm:AddTagsToResource",
    "ssm:ListTagsForResource",
    "ssm:RemoveTagsFromResource",
})
_R53 = frozenset({
    "route53:GetHostedZone",
    "route53:ListResourceRecordSets",
    "route53:ChangeResourceRecordSets",
    "route53:GetChange",
})
_ESCALATION = frozenset({
    "iam:CreateAccessKey",
    "iam:AttachUserPolicy",
    "iam:PutUserPolicy",
    "sts:AssumeRole",
})
_SERVICE_STARS = frozenset({"ec2:*", "ssm:*", "iam:*"})
_SSM_PREFIX = "/deploy-hub/"
_REGION_CONDITION_KEYS = frozenset({"aws:requestedregion", "ec2:region"})
RESULTS_SCHEMA_VERSION = 1


class AwsCredsError(RuntimeError):
    """Credential load / shape / STS observe failed. Never carries key material."""


class AwsScopeError(AwsCredsError):
    """IAM allowlist refusal (construction). Finding is filed by refuse_iam_scope."""


def last_client_kwargs():
    """Kwargs of the most recent boto3_client call. tests/ inspect this, not boto3."""
    return dict(_CLIENT_KWARGS[-1]) if _CLIENT_KWARGS else None


def reset_client_log():
    _CLIENT_KWARGS.clear()


def boto3_client(service, *, access_key_id, secret_access_key, region_name, **extra):
    """The one boto3.client wrapper: both keys required, session token never from env."""
    if extra:
        raise AwsCredsError(
            "boto3_client refuses extra kwargs (no aws_session_token, no default chain)"
        )
    if not access_key_id or not secret_access_key:
        raise AwsCredsError("explicit AWS keys are required; refusing default chain")
    kwargs = {
        "aws_access_key_id": access_key_id,
        "aws_secret_access_key": secret_access_key,
        "region_name": region_name,
    }
    _CLIENT_KWARGS.append(dict(kwargs))
    return boto3.client(service, **kwargs)


@contextmanager
def mock_aws():
    """T1 moto 5.x context. Dummy creds so boto3 never reaches live AWS."""
    from moto import mock_aws as _mock_aws

    dummy = "testing"
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
        with _mock_aws():
            yield
    finally:
        for name, old in saved.items():
            if old is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = old


def parse_credential_json(raw):
    """JSON must be exactly {access_key_id, secret_access_key}."""
    if isinstance(raw, (bytes, bytearray)):
        raw = raw.decode()
    try:
        data = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise AwsCredsError("AWS credential is not JSON") from exc
    if not isinstance(data, dict):
        raise AwsCredsError("AWS credential JSON must be an object")
    keys = set(data)
    if keys != _CRED_KEYS:
        raise AwsCredsError(
            "AWS credential JSON must be exactly {access_key_id, secret_access_key}; "
            "session tokens and extra keys are refused"
        )
    access_key_id = str(data["access_key_id"] or "").strip()
    secret_access_key = str(data["secret_access_key"] or "").strip()
    if not access_key_id or not secret_access_key:
        raise AwsCredsError("AWS credential fields must be non-empty")
    return {"access_key_id": access_key_id, "secret_access_key": secret_access_key}


def load_credentials(*, reason="aws client construction"):
    """Load CLOUD_CREDENTIAL for settings.AWS_CREDENTIALS_REF. Empty ref refuses."""
    ref = str(getattr(settings, "AWS_CREDENTIALS_REF", "") or "").strip()
    if not ref:
        raise AwsCredsError(
            "AWS_CREDENTIALS_REF is empty; set HUB_AWS_CREDENTIALS_REF"
        )
    from vault import service as vault_service
    from vault.models import Secret

    secret = (
        Secret.objects.filter(
            kind=Secret.Kind.CLOUD_CREDENTIAL,
            owner_type="aws",
            owner_id=ref,
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if secret is None:
        raise AwsCredsError(f"no cloud_credential in the vault for ref {ref!r}")
    return parse_credential_json(vault_service.get(secret, reason=reason))


class FakeIam:
    """T1 IAM double. tests/ import this, not boto3. Methods match boto3 iam."""

    def __init__(
        self,
        *,
        user_name="hub",
        account_id="123456789012",
        attached=(),
        inline=(),
        groups=(),
        group_attached=None,
        group_inline=None,
        boundary=None,
        fail_user=False,
        fail_groups=False,
        fail_group_inspect=False,
    ):
        self.user_name = user_name
        self.account_id = account_id
        self.attached = list(attached)
        self.inline = list(inline)
        self.groups = list(groups)
        self.group_attached = group_attached or {}
        self.group_inline = group_inline or {}
        self.boundary = boundary
        self.fail_user = fail_user
        self.fail_groups = fail_groups
        self.fail_group_inspect = fail_group_inspect
        self._policies = {}
        for row in self.attached:
            self._index_policy(row)
        for rows in self.group_attached.values():
            for row in rows:
                self._index_policy(row)
        if boundary:
            self._index_policy(boundary)

    def _index_policy(self, row):
        arn = row.get("arn") or f"arn:aws:iam::{self.account_id}:policy/{row['name']}"
        self._policies[arn] = row

    def get_user(self, **_kwargs):
        if self.fail_user:
            raise RuntimeError("AccessDenied: missing IAM inspect")
        user = {
            "UserName": self.user_name,
            "Arn": f"arn:aws:iam::{self.account_id}:user/{self.user_name}",
        }
        if self.boundary:
            user["PermissionsBoundary"] = {
                "PermissionsBoundaryArn": self.boundary.get("arn", ""),
                "PermissionsBoundaryType": "Policy",
            }
        return {"User": user}

    def list_attached_user_policies(self, **_kwargs):
        if self.fail_user:
            raise RuntimeError("AccessDenied: missing IAM inspect")
        return {
            "AttachedPolicies": [
                {
                    "PolicyName": row["name"],
                    "PolicyArn": row.get("arn")
                    or f"arn:aws:iam::{self.account_id}:policy/{row['name']}",
                }
                for row in self.attached
            ]
        }

    def get_policy(self, PolicyArn, **_kwargs):
        row = self._policies.get(PolicyArn)
        if row is None:
            raise RuntimeError("NoSuchEntity")
        return {
            "Policy": {
                "PolicyName": row["name"],
                "Arn": PolicyArn,
                "DefaultVersionId": "v1",
            }
        }

    def get_policy_version(self, PolicyArn, VersionId, **_kwargs):
        row = self._policies.get(PolicyArn)
        if row is None:
            raise RuntimeError("NoSuchEntity")
        return {"PolicyVersion": {"Document": row.get("document") or {}}}

    def list_user_policies(self, **_kwargs):
        if self.fail_user:
            raise RuntimeError("AccessDenied: missing IAM inspect")
        return {"PolicyNames": [row["name"] for row in self.inline]}

    def get_user_policy(self, PolicyName, **_kwargs):
        for row in self.inline:
            if row["name"] == PolicyName:
                return {"PolicyName": PolicyName, "PolicyDocument": row["document"]}
        raise RuntimeError("NoSuchEntity")

    def list_groups_for_user(self, **_kwargs):
        if self.fail_groups:
            raise RuntimeError("AccessDenied: missing group inspect")
        return {"Groups": [{"GroupName": name} for name in self.groups]}

    def list_attached_group_policies(self, GroupName, **_kwargs):
        if self.fail_group_inspect:
            raise RuntimeError("AccessDenied: missing group inspect")
        rows = self.group_attached.get(GroupName, [])
        return {
            "AttachedPolicies": [
                {
                    "PolicyName": row["name"],
                    "PolicyArn": row.get("arn")
                    or f"arn:aws:iam::{self.account_id}:policy/{row['name']}",
                }
                for row in rows
            ]
        }

    def list_group_policies(self, GroupName, **_kwargs):
        if self.fail_group_inspect:
            raise RuntimeError("AccessDenied: missing group inspect")
        rows = self.group_inline.get(GroupName, [])
        return {"PolicyNames": [row["name"] for row in rows]}

    def get_group_policy(self, GroupName, PolicyName, **_kwargs):
        for row in self.group_inline.get(GroupName, []):
            if row["name"] == PolicyName:
                return {"PolicyName": PolicyName, "PolicyDocument": row["document"]}
        raise RuntimeError("NoSuchEntity")


def _as_list(value):
    if value is None:
        return []
    if isinstance(value, list):
        return value
    return [value]


def _statements(document):
    if not document:
        return []
    stmt = document.get("Statement", [])
    return stmt if isinstance(stmt, list) else [stmt]


def _policy_document(raw):
    if raw is None:
        return {}
    if isinstance(raw, dict):
        return raw
    text = unquote(str(raw))
    return json.loads(text)


def _is_admin_name(name):
    short = str(name).rsplit("/", 1)[-1]
    return short == "AdministratorAccess"


def _ssm_on_prefix(resource):
    if not resource or resource == "*":
        return False
    marker = ":parameter"
    if marker in resource:
        path = resource.split(marker, 1)[1]
    elif resource.startswith("/"):
        path = resource
    else:
        return False
    if not path.startswith("/"):
        path = "/" + path
    return path == "/deploy-hub" or path.startswith(_SSM_PREFIX)


def _hosted_zone_id(resource):
    if "hostedzone/" not in resource:
        return None
    return resource.split("hostedzone/", 1)[1].split("/")[0]


def _condition_regions(condition):
    """Region values from aws:RequestedRegion / ec2:Region. Missing → []."""
    if not isinstance(condition, dict):
        return []
    found = []
    for block in condition.values():
        if not isinstance(block, dict):
            continue
        for key, value in block.items():
            if str(key).lower() in _REGION_CONDITION_KEYS:
                found.extend(str(part) for part in _as_list(value))
    return found


def _ec2_region_reason(condition, allowed_regions):
    allowed = {str(region) for region in (allowed_regions or ())}
    if not allowed:
        return "EC2 region condition missing or off allowlist"
    pinned = _condition_regions(condition)
    if not pinned or not set(pinned) <= allowed:
        return "EC2 region condition missing or off allowlist"
    return None


def _action_reason(
    action,
    resources,
    *,
    hosted_zone_ids,
    pass_role_arns,
    allowed_regions,
    condition,
):
    resources = resources or ["*"]
    if action == "*":
        return "Action * refused"
    if action in _SERVICE_STARS:
        return f"{action} refused"
    if action in _ESCALATION:
        return f"{action} refused"
    if action == "iam:PassRole":
        if any(res == "*" for res in resources):
            return "iam:PassRole on * refused"
        if not pass_role_arns or not set(resources) <= set(pass_role_arns):
            return "iam:PassRole off the SSM instance-profile role"
        return None
    if action == "sts:GetCallerIdentity" or action in _IAM_SELF:
        return None
    if action.startswith("ec2:Describe") or action in _EC2_EXACT:
        return _ec2_region_reason(condition, allowed_regions)
    if (
        action in _SSM
        or action == "ssm:GetParameter*"
        or action.startswith("ssm:GetParameter")
    ):
        if any(not _ssm_on_prefix(res) for res in resources):
            return "SSM resource off /deploy-hub/ prefix"
        return None
    if action in _R53:
        if action == "route53:GetChange":
            return None
        if not hosted_zone_ids or any(res == "*" for res in resources):
            return "Route 53 resource off-zone"
        for res in resources:
            zone_id = _hosted_zone_id(res)
            if zone_id not in hosted_zone_ids:
                return "Route 53 resource off-zone"
        return None
    return f"{action} is not on the Hub-user allowlist"


def evaluate_iam_scope(
    documents,
    *,
    attached_policy_names=(),
    hosted_zone_ids=(),
    pass_role_arns=(),
    allowed_regions=(),
):
    """Return refusal reasons (empty = pass). Does not file a Finding."""
    reasons = []
    for name in attached_policy_names:
        if _is_admin_name(name):
            reasons.append("AdministratorAccess refused")
    hosted = set(hosted_zone_ids or ())
    roles = set(pass_role_arns or ())
    regions = set(allowed_regions or ())
    for document in documents:
        for stmt in _statements(document):
            if not isinstance(stmt, dict):
                continue
            if stmt.get("Effect", "Allow") != "Allow":
                continue
            if "NotAction" in stmt:
                reasons.append("NotAction refused")
                continue
            actions = _as_list(stmt.get("Action"))
            resources = _as_list(stmt.get("Resource")) or ["*"]
            for action in actions:
                reason = _action_reason(
                    str(action),
                    [str(res) for res in resources],
                    hosted_zone_ids=hosted,
                    pass_role_arns=roles,
                    allowed_regions=regions,
                    condition=stmt.get("Condition"),
                )
                if reason:
                    reasons.append(reason)
    # Stable unique order
    seen = set()
    out = []
    for reason in reasons:
        if reason not in seen:
            seen.add(reason)
            out.append(reason)
    return out


def _attached_rows(iam, method, **kwargs):
    payload = method(**kwargs)
    return list(payload.get("AttachedPolicies") or [])


def collect_iam_documents(iam):
    """User attached+inline + each group's attached+inline + present boundary.

    Missing user inspect or missing group inspect raises AwsScopeError.
    """
    documents = []
    names = []
    try:
        user = iam.get_user()["User"]
        user_name = user["UserName"]
        for row in _attached_rows(iam, iam.list_attached_user_policies, UserName=user_name):
            names.append(row.get("PolicyName") or row.get("PolicyArn") or "")
            arn = row["PolicyArn"]
            policy = iam.get_policy(PolicyArn=arn)["Policy"]
            version = iam.get_policy_version(
                PolicyArn=arn, VersionId=policy["DefaultVersionId"],
            )
            documents.append(_policy_document(version["PolicyVersion"]["Document"]))
        inline_names = iam.list_user_policies(UserName=user_name).get("PolicyNames") or []
        for policy_name in inline_names:
            got = iam.get_user_policy(UserName=user_name, PolicyName=policy_name)
            documents.append(_policy_document(got.get("PolicyDocument")))
        boundary = user.get("PermissionsBoundary") or {}
        boundary_arn = boundary.get("PermissionsBoundaryArn")
        if boundary_arn:
            # Present boundary must be readable (missing inspect = refuse).
            policy = iam.get_policy(PolicyArn=boundary_arn)["Policy"]
            iam.get_policy_version(
                PolicyArn=boundary_arn, VersionId=policy["DefaultVersionId"],
            )
    except AwsScopeError:
        raise
    except Exception as exc:
        raise AwsScopeError("missing IAM inspect") from exc

    try:
        groups = iam.list_groups_for_user(UserName=user_name).get("Groups") or []
        for group in groups:
            group_name = group["GroupName"]
            for row in _attached_rows(
                iam, iam.list_attached_group_policies, GroupName=group_name,
            ):
                names.append(row.get("PolicyName") or row.get("PolicyArn") or "")
                arn = row["PolicyArn"]
                policy = iam.get_policy(PolicyArn=arn)["Policy"]
                version = iam.get_policy_version(
                    PolicyArn=arn, VersionId=policy["DefaultVersionId"],
                )
                documents.append(
                    _policy_document(version["PolicyVersion"]["Document"])
                )
            inline_names = (
                iam.list_group_policies(GroupName=group_name).get("PolicyNames") or []
            )
            for policy_name in inline_names:
                got = iam.get_group_policy(
                    GroupName=group_name, PolicyName=policy_name,
                )
                documents.append(_policy_document(got.get("PolicyDocument")))
    except AwsScopeError:
        raise
    except Exception as exc:
        raise AwsScopeError("missing group inspect") from exc
    return documents, names


def file_aws_scope(*, account_id, reasons, ref=""):
    """kind aws-scope, fingerprint aws-scope:{account_id}. Refs, never secrets."""
    from monitor.alerts import raise_alert

    owner = ref or str(getattr(settings, "AWS_CREDENTIALS_REF", "") or "")
    body = (
        f"IAM allowlist refused for account {account_id} (ref {owner}): "
        + "; ".join(reasons)
    )
    raise_alert(
        "aws-scope",
        f"aws:{account_id}",
        fingerprint=f"aws-scope:{account_id}",
        source_engine="aws_scope",
        title=f"AWS IAM scope refused for account {account_id}",
        body=body,
        fix_action="Narrow the Hub IAM user and its groups to the C4 allowlist",
    )


def refuse_iam_scope(
    *,
    iam=None,
    documents=None,
    attached_policy_names=(),
    account_id,
    ref="",
    hosted_zone_ids=(),
    pass_role_arns=(),
    allowed_regions=(),
    file=True,
):
    """Judge documents (or inspect iam) and refuse a superset. Files aws-scope."""
    try:
        if documents is None:
            documents, attached_policy_names = collect_iam_documents(iam)
    except AwsScopeError as exc:
        if file:
            file_aws_scope(account_id=account_id, reasons=[str(exc)], ref=ref)
        raise
    reasons = evaluate_iam_scope(
        documents,
        attached_policy_names=attached_policy_names,
        hosted_zone_ids=hosted_zone_ids,
        pass_role_arns=pass_role_arns,
        allowed_regions=allowed_regions,
    )
    if not reasons:
        return
    if file:
        file_aws_scope(account_id=account_id, reasons=reasons, ref=ref)
    raise AwsScopeError("; ".join(reasons))


def observe_credentials(
    access_key_id,
    secret_access_key,
    *,
    region_name="us-east-1",
    iam=None,
    sts=None,
    hosted_zone_ids=(),
    pass_role_arns=(),
    allowed_regions=None,
    ref="",
):
    """Throwaway explicit-key client: GetCallerIdentity + IAM allowlist.

    Not the product CloudProvider client. Callers (Settings connect) must
    invoke this BEFORE vault.put. Empty hosted_zone_ids / pass_role_arns
    refuse Route 53 zone actions and PassRole (fail-closed, not skip).
    """
    if allowed_regions is None:
        allowed_regions = (region_name,)
    sts = sts or boto3_client(
        "sts",
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        region_name=region_name,
    )
    try:
        ident = sts.get_caller_identity()
    except Exception as exc:
        raise AwsCredsError("sts:GetCallerIdentity failed") from exc
    account_id = str(ident["Account"])
    assert_test_aws(account_id, region_name)
    iam = iam or boto3_client(
        "iam",
        access_key_id=access_key_id,
        secret_access_key=secret_access_key,
        region_name=region_name,
    )
    refuse_iam_scope(
        iam=iam,
        account_id=account_id,
        ref=ref or str(getattr(settings, "AWS_CREDENTIALS_REF", "") or ""),
        hosted_zone_ids=hosted_zone_ids,
        pass_role_arns=pass_role_arns,
        allowed_regions=allowed_regions,
    )
    return {
        "account_id": account_id,
        "arn": ident.get("Arn", ""),
        "region": region_name,
    }


def _declared_hosted_zone_ids():
    from core.models import DnsAccount, DnsZone

    return set(
        DnsZone.objects.filter(
            account__provider=DnsAccount.Provider.ROUTE53,
        ).exclude(provider_zone_id="").values_list("provider_zone_id", flat=True)
    )


def audit_iam_scope(*, iam=None, sts=None, region_name="us-east-1"):
    """Daily D-067 allowlist audit. Empty ref SKIPPED; drift files aws-scope.

    Inspect is collect_iam_documents / refuse_iam_scope (user attached+inline
    AND each group's attached+inline). CheckRun.results carry the vault ref
    and account id, never key material. Observation failure is FAILED; a
    judged superset is SUCCEEDED plus the Finding — the Beat observed.
    """
    from core.models import CheckRun
    from monitor.drills import record_run

    ref = str(getattr(settings, "AWS_CREDENTIALS_REF", "") or "").strip()
    if not ref:
        return record_run(
            CheckRun.Kind.AWS_IAM_SCOPE,
            CheckRun.Status.SKIPPED,
            {"schema_version": RESULTS_SCHEMA_VERSION, "skipped": "absent_ref"},
        )

    try:
        creds = load_credentials(reason="aws iam daily audit")
    except AwsCredsError:
        return record_run(
            CheckRun.Kind.AWS_IAM_SCOPE,
            CheckRun.Status.FAILED,
            {
                "schema_version": RESULTS_SCHEMA_VERSION,
                "ref": ref,
                "error": "no_secret",
            },
        )

    sts = sts or boto3_client(
        "sts",
        access_key_id=creds["access_key_id"],
        secret_access_key=creds["secret_access_key"],
        region_name=region_name,
    )
    try:
        ident = sts.get_caller_identity()
        account_id = str(ident["Account"])
    except Exception:
        return record_run(
            CheckRun.Kind.AWS_IAM_SCOPE,
            CheckRun.Status.FAILED,
            {
                "schema_version": RESULTS_SCHEMA_VERSION,
                "ref": ref,
                "error": "sts_failed",
            },
        )

    iam = iam or boto3_client(
        "iam",
        access_key_id=creds["access_key_id"],
        secret_access_key=creds["secret_access_key"],
        region_name=region_name,
    )
    drift = None
    try:
        refuse_iam_scope(
            iam=iam,
            account_id=account_id,
            ref=ref,
            hosted_zone_ids=_declared_hosted_zone_ids(),
            pass_role_arns=(),
            allowed_regions=tuple(
                getattr(settings, "HUB_TEST_AWS_REGIONS", ()) or ()
            ),
        )
    except AwsScopeError as exc:
        drift = str(exc)
    return record_run(
        CheckRun.Kind.AWS_IAM_SCOPE,
        CheckRun.Status.SUCCEEDED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "ref": ref,
            "account_id": account_id,
            "drift": drift,
        },
    )
