"""T1: AWS vault-ref credentials, construction IAM allowlist, test-plane wall.

boto3, botocore, and moto must not appear as imports in this file. Dummy
creds, the client-kwargs log, FakeIam, and the moto context live in
providers/aws_creds.py so the tested client is the shipped client.
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
CONNECT = "/api/v1/aws/connect/"
ACCOUNT = "123456789012"
REF = "hub-aws"
AKI = "t1-aws-access-key-id-not-a-credential"
SAK = "t1-aws-secret-access-key-not-a-credential"
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)


def _enrolled_client(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.login(username="joseph", password="a-long-dev-password")
    return user


def _put_leftover(*, owner_id="leftover-aws"):
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


def _connect(client, **body):
    payload = {"access_key_id": AKI, "secret_access_key": SAK}
    payload.update(body)
    return client.post(CONNECT, payload, content_type="application/json")


def _star_doc():
    return {
        "Version": "2012-10-17",
        "Statement": [{"Effect": "Allow", "Action": "*", "Resource": "*"}],
    }


# ── AWS-TEST-PLANE ──────────────────────────────────────────────────────────


@pytest.mark.req("AWS-TEST-PLANE")
def test_empty_aws_credentials_ref_refuses():
    """Empty AWS_CREDENTIALS_REF refuses even when a leftover vault row exists.

    What would make this fail: scanning CLOUD_CREDENTIAL rows and using the
    newest one when the setting is "", so a deleted env still constructs a
    client from yesterday's secret — the leftover-row hole C3 names.
    """
    from providers.aws_creds import AwsCredsError, load_credentials
    from providers.registry import load_aws_credentials

    _put_leftover()
    with override_settings(AWS_CREDENTIALS_REF=""):
        with pytest.raises(AwsCredsError, match="empty|HUB_AWS_CREDENTIALS_REF"):
            load_credentials()
        with pytest.raises(AwsCredsError, match="empty|HUB_AWS_CREDENTIALS_REF"):
            load_aws_credentials()


@pytest.mark.req("AWS-TEST-PLANE")
def test_explicit_keys_passed_into_client_never_default_chain(monkeypatch):
    """boto3.client kwargs always carry both keys; session token is not from env.

    What would make this fail: constructing boto3.client('sts') with no
    aws_access_key_id so moto (or a Hub instance profile) quietly supplies
    the default chain. The test inspects the kwargs the helper passed, not
    whether a call happened to succeed.
    """
    from providers.aws_creds import boto3_client, last_client_kwargs, mock_aws

    with mock_aws():
        monkeypatch.setenv("AWS_ACCESS_KEY_ID", "ENVACCESS")
        monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "ENVSECRET")
        monkeypatch.setenv("AWS_SESSION_TOKEN", "ENVSESSION")
        boto3_client(
            "sts",
            access_key_id="EXPLICITAKI",
            secret_access_key="EXPLICITSECRET",
            region_name="us-east-1",
        )
    kwargs = last_client_kwargs()
    assert kwargs is not None
    assert kwargs["aws_access_key_id"] == "EXPLICITAKI"
    assert kwargs["aws_secret_access_key"] == "EXPLICITSECRET"
    assert kwargs.get("aws_session_token") not in {"ENVSESSION", "testing"}
    assert "aws_session_token" not in kwargs


@pytest.mark.req("AWS-TEST-PLANE")
def test_session_token_or_extra_json_keys_refused():
    """Vault JSON is exactly {access_key_id, secret_access_key}.

    What would make this fail: accepting session_token (or any extra key)
    so a temporary session can be stored as if it were the Hub user.
    """
    from providers.aws_creds import AwsCredsError, parse_credential_json

    ok = parse_credential_json(
        json.dumps({"access_key_id": AKI, "secret_access_key": SAK})
    )
    assert ok == {"access_key_id": AKI, "secret_access_key": SAK}

    for blob in (
        {"access_key_id": AKI, "secret_access_key": SAK, "session_token": "t"},
        {"access_key_id": AKI, "secret_access_key": SAK, "aws_session_token": "t"},
        {"access_key_id": AKI, "secret_access_key": SAK, "extra": "x"},
        {"access_key_id": AKI},
        {"secret_access_key": SAK},
        [],
    ):
        with pytest.raises(AwsCredsError, match="exactly|session|extra|JSON"):
            parse_credential_json(json.dumps(blob))


@pytest.mark.req("AWS-TEST-PLANE")
def test_empty_allowlist_refuses_live():
    """Under HUB_TEST_MODE an empty account or region allowlist refuses live.

    What would make this fail: treating an unset list as 'any', so the test
    plane is the operator's whole AWS account the moment the flag is on.
    """
    from core.test_mode import TestModeError, assert_test_aws

    with override_settings(
        HUB_TEST_MODE=True,
        HUB_TEST_AWS_ACCOUNT_IDS=[],
        HUB_TEST_AWS_REGIONS=["us-east-1"],
    ):
        with pytest.raises(TestModeError, match="allowlist"):
            assert_test_aws(ACCOUNT, "us-east-1")
    with override_settings(
        HUB_TEST_MODE=True,
        HUB_TEST_AWS_ACCOUNT_IDS=[ACCOUNT],
        HUB_TEST_AWS_REGIONS=[],
    ):
        with pytest.raises(TestModeError, match="allowlist"):
            assert_test_aws(ACCOUNT, "us-east-1")
    with override_settings(
        HUB_TEST_MODE=True,
        HUB_TEST_AWS_ACCOUNT_IDS=[],
        HUB_TEST_AWS_REGIONS=[],
    ):
        with pytest.raises(TestModeError, match="allowlist"):
            assert_test_aws(ACCOUNT, "us-east-1")


@pytest.mark.req("AWS-TEST-PLANE")
def test_off_allowlist_account_or_region_refuses_under_hub_test_mode():
    """Both account id and region must sit on the named allowlists.

    What would make this fail: checking only the account, so an allowlisted
    account in eu-west-1 is live while HUB_TEST_AWS_REGIONS names us-east-1.
    """
    from core.test_mode import TestModeError, assert_test_aws

    with override_settings(
        HUB_TEST_MODE=True,
        HUB_TEST_AWS_ACCOUNT_IDS=[ACCOUNT],
        HUB_TEST_AWS_REGIONS=["us-east-1"],
    ):
        with pytest.raises(TestModeError):
            assert_test_aws("999999999999", "us-east-1")
        with pytest.raises(TestModeError):
            assert_test_aws(ACCOUNT, "eu-west-1")
        assert_test_aws(ACCOUNT, "us-east-1")


@pytest.mark.req("AWS-TEST-PLANE")
def test_purpose_test_refuses_outside_hub_test_mode():
    """purpose=test tagged AWS calls refuse when HUB_TEST_MODE is off.

    What would make this fail: the wall only running under the flag, so a
    prod Hub still terminates a purpose=test instance it should never see.
    """
    from core.test_mode import TestModeError, assert_test_aws

    with override_settings(HUB_TEST_MODE=False):
        with pytest.raises(TestModeError, match="HUB_TEST_MODE"):
            assert_test_aws(ACCOUNT, "us-east-1", purpose="test")
        with pytest.raises(TestModeError, match="HUB_TEST_MODE"):
            assert_test_aws(ACCOUNT, "us-east-1", tags={"purpose": "test"})
        assert_test_aws(ACCOUNT, "us-east-1")


@pytest.mark.req("AWS-TEST-PLANE")
def test_connect_without_ref_does_not_invent_a_token_env(client):
    """Empty setting → 400/409 with the degraded reason; no HUB_TEST_AWS_TOKEN.

    What would make this fail: inventing HUB_TEST_AWS_TOKEN (the
    HUB_TEST_CF_TOKEN lie) or writing a vault row under a minted owner_id
    so the paste paints Connected when the operator never set the ref.
    """
    from vault.models import Secret

    _enrolled_client(client)
    assert "HUB_TEST_AWS_TOKEN" not in os.environ
    with override_settings(AWS_CREDENTIALS_REF=""):
        response = _connect(client)
    assert response.status_code in (400, 409), response.content
    body = response.json()
    blob = json.dumps(body)
    assert "HUB_AWS_CREDENTIALS_REF" in blob or "not connected" in blob.lower()
    assert "Connected" not in blob
    assert AKI not in blob and SAK not in blob
    assert "HUB_TEST_AWS_TOKEN" not in os.environ
    assert Secret.objects.filter(kind="cloud_credential").count() == 0
    for rel in (
        "providers/aws_creds.py",
        "core/aws_views.py",
        "hub/settings/base.py",
        "hub/settings/prod.py",
        "core/test_mode.py",
    ):
        text = (REPO / rel).read_text(encoding="utf-8")
        assert "HUB_TEST_AWS_TOKEN" not in text, rel


# ── AWS-IAM-ALLOWLIST ───────────────────────────────────────────────────────


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_star_action_refuses_and_files_aws_scope():
    """Action: '*' refuses at construction and files kind aws-scope.

    What would make this fail: judging only managed-policy names so an
    inline Action:* Hub user connects and can do anything.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    with pytest.raises(AwsScopeError, match=r"\*"):
        refuse_iam_scope(
            documents=[_star_doc()], account_id=ACCOUNT, ref=REF,
        )
    row = _findings().get()
    assert row.fingerprint == f"aws-scope:{ACCOUNT}"
    assert row.severity == "p2"


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_administrator_access_refuses():
    """Attached AdministratorAccess refuses even without parsing its document.

    What would make this fail: only scanning inline JSON so the AWS-managed
    Admin policy (the console default) passes because we never fetched it.
    """
    from providers.aws_creds import AwsScopeError, FakeIam, refuse_iam_scope

    iam = FakeIam(
        attached=[
            {
                "name": "AdministratorAccess",
                "arn": "arn:aws:iam::aws:policy/AdministratorAccess",
                "document": _star_doc(),
            }
        ]
    )
    with pytest.raises(AwsScopeError, match="AdministratorAccess"):
        refuse_iam_scope(iam=iam, account_id=ACCOUNT, ref=REF)


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_group_attached_administrator_access_refuses():
    """Group-attached AdministratorAccess is the console path and must refuse.

    What would make this fail: inspecting only user attached+inline, so a
    Hub user in an Admins group with no user policy connects as Admin.
    """
    from providers.aws_creds import AwsScopeError, FakeIam, refuse_iam_scope

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
    with pytest.raises(AwsScopeError, match="AdministratorAccess"):
        refuse_iam_scope(iam=iam, account_id=ACCOUNT, ref=REF)


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_missing_iam_inspect_refuses():
    """A failed GetUser / attached / inline listing is fail-closed, not a pass.

    What would make this fail: treating AccessDenied on self-inspect as
    'no policies' and connecting an unreadable (and therefore unbounded) user.
    """
    from providers.aws_creds import AwsScopeError, FakeIam, refuse_iam_scope

    with pytest.raises(AwsScopeError, match="inspect"):
        refuse_iam_scope(
            iam=FakeIam(fail_user=True), account_id=ACCOUNT, ref=REF,
        )
    assert _findings().filter(fingerprint=f"aws-scope:{ACCOUNT}").exists()


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_missing_group_inspect_refuses():
    """ListGroupsForUser (or a group's attached/inline) failing refuses.

    What would make this fail: skipping groups when the call errors, which
    is the same hole as user-only inspect with a quieter traceback.
    """
    from providers.aws_creds import AwsScopeError, FakeIam, refuse_iam_scope

    with pytest.raises(AwsScopeError, match="group"):
        refuse_iam_scope(
            iam=FakeIam(fail_groups=True), account_id=ACCOUNT, ref=REF,
        )
    with pytest.raises(AwsScopeError, match="group"):
        refuse_iam_scope(
            iam=FakeIam(groups=["ops"], fail_group_inspect=True),
            account_id=ACCOUNT,
            ref=REF,
        )


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_not_action_refuses():
    """NotAction is almost-admin and is refused fail-closed.

    What would make this fail: only matching Action keys, so
    NotAction: iam:* on Resource * connects as everything-but-IAM.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    doc = {
        "Statement": [
            {"Effect": "Allow", "NotAction": "iam:*", "Resource": "*"}
        ]
    }
    with pytest.raises(AwsScopeError, match="NotAction"):
        refuse_iam_scope(documents=[doc], account_id=ACCOUNT, ref=REF)


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_ec2_star_or_ssm_star_refuses():
    """Hub-user ec2:* and ssm:* are a superset of C4 and refuse.

    What would make this fail: only refusing Action:* so a service-star
    policy still RunInstances / PutParameter anywhere.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    for action in ("ec2:*", "ssm:*", "iam:*"):
        doc = {
            "Statement": [
                {"Effect": "Allow", "Action": action, "Resource": "*"}
            ]
        }
        with pytest.raises(AwsScopeError, match=re.escape(action)):
            refuse_iam_scope(documents=[doc], account_id=ACCOUNT, ref=REF)


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_escalation_verbs_refuse():
    """CreateAccessKey / AttachUserPolicy / PutUserPolicy / PassRole * / AssumeRole.

    What would make this fail: allowing those verbs because they are not
    Action:*, so the Hub user can mint a second key or assume a role that
    is Admin.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    verbs = (
        ("iam:CreateAccessKey", "*"),
        ("iam:AttachUserPolicy", "*"),
        ("iam:PutUserPolicy", "*"),
        ("iam:PassRole", "*"),
        ("sts:AssumeRole", "*"),
    )
    for action, resource in verbs:
        doc = {
            "Statement": [
                {"Effect": "Allow", "Action": action, "Resource": resource}
            ]
        }
        with pytest.raises(AwsScopeError):
            refuse_iam_scope(documents=[doc], account_id=ACCOUNT, ref=REF)


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_off_prefix_ssm_refuses():
    """SSM Put/Get/Delete must be on /deploy-hub/* only.

    What would make this fail: granting ssm:PutParameter on Resource * or
    /other/*, so the Hub user can write parameters the instance profile
    (or another account principal) can read.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    for resource in (
        "*",
        "arn:aws:ssm:*:*:parameter/other/*",
        "arn:aws:ssm:*:*:parameter/deploy-hub-not",
    ):
        doc = {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "ssm:PutParameter",
                    "Resource": resource,
                }
            ]
        }
        with pytest.raises(AwsScopeError, match="ssm|prefix|deploy-hub"):
            refuse_iam_scope(documents=[doc], account_id=ACCOUNT, ref=REF)


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_off_zone_route53_refuses():
    """Route 53 ChangeResourceRecordSets is that DnsZone hosted zone only.

    What would make this fail: Resource * (or another hostedzone id) so
    connect writes a Hub user that can mutate prod DNS.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    doc = {
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "route53:ChangeResourceRecordSets",
                "Resource": "arn:aws:route53:::hostedzone/ZOTHER",
            }
        ]
    }
    with pytest.raises(AwsScopeError, match="Route 53|route53|zone"):
        refuse_iam_scope(
            documents=[doc],
            account_id=ACCOUNT,
            ref=REF,
            hosted_zone_ids={"ZTESTZONE"},
        )


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_empty_hosted_zone_allowlist_refuses_route53():
    """Empty hosted_zone_ids refuses Change/Get/List, not 'any zone'.

    What would make this fail: `if hosted_zone_ids:` skipping the bound so
    Settings observe (which has no DnsZone set yet) vaults a user that can
    mutate an unlisted hosted zone.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    doc = {
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "route53:ChangeResourceRecordSets",
                "Resource": "arn:aws:route53:::hostedzone/ZTESTZONE",
            }
        ]
    }
    with pytest.raises(AwsScopeError, match="Route 53|route53|zone"):
        refuse_iam_scope(documents=[doc], account_id=ACCOUNT, ref=REF)
    with pytest.raises(AwsScopeError, match="Route 53|route53|zone"):
        refuse_iam_scope(
            documents=[doc], account_id=ACCOUNT, ref=REF, hosted_zone_ids=(),
        )


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_empty_pass_role_allowlist_refuses():
    """Empty pass_role_arns refuses PassRole on a specific ARN, not only *.

    What would make this fail: skipping the bound when the set is empty so
    connect vaults PassRole to an Admin role because the resource was not *.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    admin_role = f"arn:aws:iam::{ACCOUNT}:role/Admin"
    ssm_role = f"arn:aws:iam::{ACCOUNT}:role/hub-ssm"
    doc = {
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "iam:PassRole",
                "Resource": admin_role,
            }
        ]
    }
    with pytest.raises(AwsScopeError, match="PassRole"):
        refuse_iam_scope(documents=[doc], account_id=ACCOUNT, ref=REF)
    with pytest.raises(AwsScopeError, match="PassRole"):
        refuse_iam_scope(
            documents=[doc], account_id=ACCOUNT, ref=REF, pass_role_arns=(),
        )
    with pytest.raises(AwsScopeError, match="PassRole"):
        refuse_iam_scope(
            documents=[doc],
            account_id=ACCOUNT,
            ref=REF,
            pass_role_arns={ssm_role},
        )


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_observe_without_allow_set_refuses_pass_role_and_off_zone_r53():
    """Settings observe passes empty allow-sets; PassRole-to-Admin and R53 refuse.

    What would make this fail: observe_credentials forwarding empty
    hosted_zone_ids / pass_role_arns into a helper that treats empty as
    unconstrained, so connect 201s and vaults the overscope.
    """
    from providers.aws_creds import AwsScopeError, FakeIam, observe_credentials

    class _Sts:
        def get_caller_identity(self):
            return {
                "Account": ACCOUNT,
                "Arn": f"arn:aws:iam::{ACCOUNT}:user/hub",
            }

    admin_role = f"arn:aws:iam::{ACCOUNT}:role/Admin"
    pass_iam = FakeIam(
        inline=[
            {
                "name": "pass-admin",
                "document": {
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": "iam:PassRole",
                            "Resource": admin_role,
                        }
                    ]
                },
            }
        ]
    )
    with pytest.raises(AwsScopeError, match="PassRole"):
        observe_credentials(AKI, SAK, iam=pass_iam, sts=_Sts(), ref=REF)

    r53_iam = FakeIam(
        inline=[
            {
                "name": "r53-any",
                "document": {
                    "Statement": [
                        {
                            "Effect": "Allow",
                            "Action": "route53:ChangeResourceRecordSets",
                            "Resource": "arn:aws:route53:::hostedzone/ZPROD",
                        }
                    ]
                },
            }
        ]
    )
    with pytest.raises(AwsScopeError, match="Route 53|route53|zone"):
        observe_credentials(AKI, SAK, iam=r53_iam, sts=_Sts(), ref=REF)


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_ec2_region_condition_must_match_allowlist():
    """EC2 RunInstances/Describe*/SG mutate need a region condition on the allowlist.

    What would make this fail: allowing Resource * with no aws:RequestedRegion
    / ec2:Region condition, or skipping the check when allowed_regions is empty,
    so construction vaults a Hub user that RunInstances in any region.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    unbounded = {
        "Statement": [
            {"Effect": "Allow", "Action": "ec2:RunInstances", "Resource": "*"}
        ]
    }
    with pytest.raises(AwsScopeError, match="region"):
        refuse_iam_scope(documents=[unbounded], account_id=ACCOUNT, ref=REF)
    with pytest.raises(AwsScopeError, match="region"):
        refuse_iam_scope(
            documents=[unbounded],
            account_id=ACCOUNT,
            ref=REF,
            allowed_regions={"us-east-1"},
        )
    off = {
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "ec2:RunInstances",
                "Resource": "*",
                "Condition": {
                    "StringEquals": {"aws:RequestedRegion": "eu-west-1"}
                },
            }
        ]
    }
    with pytest.raises(AwsScopeError, match="region"):
        refuse_iam_scope(
            documents=[off],
            account_id=ACCOUNT,
            ref=REF,
            allowed_regions={"us-east-1"},
        )
    pinned = {
        "Statement": [
            {
                "Effect": "Allow",
                "Action": "ec2:RunInstances",
                "Resource": "*",
                "Condition": {
                    "StringEquals": {"aws:RequestedRegion": "us-east-1"}
                },
            }
        ]
    }
    refuse_iam_scope(
        documents=[pinned],
        account_id=ACCOUNT,
        ref=REF,
        allowed_regions={"us-east-1"},
        file=False,
    )


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_ec2_region_negative_operator_is_not_an_allowlist():
    """StringNotEquals / StringNotLike of the construction region is not a pin.

    What would make this fail: treating any operator that names
    aws:RequestedRegion as an allowlist, so StringNotEquals of us-east-1
    vaults a Hub user that RunInstances in every other region.
    """
    from core.models import Finding
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    for operator in ("StringNotEquals", "StringNotLike"):
        Finding.objects.filter(fingerprint=f"aws-scope:{ACCOUNT}").delete()
        denied = {
            "Statement": [
                {
                    "Effect": "Allow",
                    "Action": "ec2:RunInstances",
                    "Resource": "*",
                    "Condition": {
                        operator: {"aws:RequestedRegion": "us-east-1"}
                    },
                }
            ]
        }
        with pytest.raises(AwsScopeError, match="region"):
            refuse_iam_scope(
                documents=[denied],
                account_id=ACCOUNT,
                ref=REF,
                allowed_regions={"us-east-1"},
            )
        row = Finding.objects.get(fingerprint=f"aws-scope:{ACCOUNT}")
        assert row.fingerprint == f"aws-scope:{ACCOUNT}"
        assert row.fingerprint != "aws-scope"


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_finding_body_has_refs_never_secret():
    """The aws-scope Finding names the vault ref and account, never the keys.

    What would make this fail: interpolating access_key_id / secret material
    into title/body/fix_action so the inbox becomes a secret store.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    with pytest.raises(AwsScopeError):
        refuse_iam_scope(
            documents=[_star_doc()],
            account_id=ACCOUNT,
            ref=REF,
        )
    row = _findings().get()
    blob = json.dumps(
        {
            "title": row.title,
            "body": row.body,
            "fix_action": row.fix_action,
            "entity": row.entity,
            "fingerprint": row.fingerprint,
        }
    )
    assert REF in row.body
    assert ACCOUNT in row.body or ACCOUNT in row.fingerprint
    assert AKI not in blob
    assert SAK not in blob
    assert "secret_access_key" not in blob
    assert "session_token" not in blob


@pytest.mark.req("AWS-IAM-ALLOWLIST")
def test_finding_fingerprint_is_aws_scope_account_id():
    """Fingerprint is aws-scope:{account_id}, not the kind alone and not a secret.

    What would make this fail: using kind as the fingerprint (second star
    overwrites the first) or minting aws-scope:{secret}.
    """
    from providers.aws_creds import AwsScopeError, refuse_iam_scope

    with pytest.raises(AwsScopeError):
        refuse_iam_scope(
            documents=[_star_doc()], account_id=ACCOUNT, ref=REF,
        )
    row = _findings().get()
    assert row.fingerprint == f"aws-scope:{ACCOUNT}"
    assert row.fingerprint != "aws-scope"


def test_settings_unconfigured_is_degraded_not_connected(client):
    """Empty AWS_CREDENTIALS_REF paints degraded 'not connected', never Connected.

    UX-P5-AWS-OPERATOR waits for Task 5; this pins the refuse-unless copy.
    What would make this fail: GET/POST treating an empty ref as Connected,
    or the AWS tab defaulting to the Cloudflare success line.
    """
    _enrolled_client(client)
    with override_settings(AWS_CREDENTIALS_REF=""):
        response = client.get(CONNECT)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body.get("connected") is False
    assert "HUB_AWS_CREDENTIALS_REF" in json.dumps(body)
    assert "Connected" not in json.dumps(body)

    src = (REPO / "frontend" / "src" / "screens" / "Settings.jsx").read_text(
        encoding="utf-8"
    )
    aws_fn = src.split("export function AwsPanel")[1].split("export function")[0]
    assert re.search(r"not connected", aws_fn, re.I)
    assert "Connected" not in aws_fn


def test_connect_observes_before_vault_write(client, monkeypatch):
    """GetCallerIdentity + IAM allowlist run before any vault.put.

    What would make this fail: putting the pasted keys and then observing,
    so an Admin paste is already in the vault when construction refuses.
    """
    from providers import aws_creds
    from vault import service as vault_service
    from vault.models import Secret

    order = []
    real_put = vault_service.put

    def boom(*_a, **_k):
        order.append("observe")
        raise aws_creds.AwsScopeError("Action * refused")

    def spy_put(**kwargs):
        order.append("put")
        return real_put(**kwargs)

    monkeypatch.setattr(aws_creds, "observe_credentials", boom)
    monkeypatch.setattr("core.aws_views.vault_service.put", spy_put)
    _enrolled_client(client)
    with override_settings(AWS_CREDENTIALS_REF=REF):
        response = _connect(client)
    assert response.status_code == 400, response.content
    assert order == ["observe"]
    assert Secret.objects.filter(owner_type="aws").count() == 0

    order.clear()

    def ok_observe(*_a, **_k):
        order.append("observe")
        return {"account_id": ACCOUNT, "arn": f"arn:aws:iam::{ACCOUNT}:user/hub",
                "region": "us-east-1"}

    monkeypatch.setattr(aws_creds, "observe_credentials", ok_observe)
    with override_settings(AWS_CREDENTIALS_REF=REF):
        response = _connect(client)
    assert response.status_code == 201, response.content
    assert order == ["observe", "put"]


def test_connect_201_never_echoes_keys(client, monkeypatch):
    """201 names account last-4 and region; the pasted keys never come back.

    What would make this fail: putting access_key_id on the result serializer
    so the Settings panel can render the secret it just stored.
    """
    from providers import aws_creds
    from vault import service as vault_service
    from vault.models import Secret

    monkeypatch.setattr(
        aws_creds,
        "observe_credentials",
        lambda *a, **k: {
            "account_id": ACCOUNT,
            "arn": f"arn:aws:iam::{ACCOUNT}:user/hub",
            "region": "us-east-1",
        },
    )
    _enrolled_client(client)
    with override_settings(AWS_CREDENTIALS_REF=REF):
        response = _connect(client)
    assert response.status_code == 201, response.content
    raw = response.content.decode()
    assert AKI not in raw
    assert SAK not in raw
    body = response.json()
    assert AKI not in json.dumps(body)
    assert "access_key_id" not in body
    assert "secret_access_key" not in body
    assert body.get("account_id_last4") == ACCOUNT[-4:]
    assert body.get("region") == "us-east-1"
    secret = Secret.objects.get(
        kind=Secret.Kind.CLOUD_CREDENTIAL, owner_type="aws", owner_id=REF,
    )
    stored = json.loads(vault_service.get(secret, reason="connect-test"))
    assert stored == {"access_key_id": AKI, "secret_access_key": SAK}


def test_aws_creds_tests_do_not_import_boto3():
    """This module and the other tests/ files never import boto3/moto.

    What would make this fail: a convenience `import boto3` here, so the
    tested client is no longer the shipped helper (the D-034 split).
    """
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(text) is None
    offenders = []
    for py in (REPO / "tests").rglob("*.py"):
        if _IMPORT_BOTO.search(py.read_text(encoding="utf-8")):
            offenders.append(str(py.relative_to(REPO)))
    assert offenders == [], f"boto3/botocore/moto import in tests/: {offenders}"


def test_nav_still_six():
    """AWS credentials live on a Settings tab; NAV stays the six objects.

    What would make this fail: adding Cloud/Instances as a 7th NAV item.
    """
    src = (REPO / "frontend" / "src" / "Chrome.jsx").read_text(encoding="utf-8")
    start = src.index("export const NAV = [")
    end = src.index("];", start)
    ids = re.findall(r'id:\s*"(\w+)"', src[start:end])
    assert ids == ["home", "sites", "targets", "deploys", "findings", "settings"]


def test_checklist_has_no_connect_aws():
    """connect_aws is not a first-run ITEM_IDS member.

    What would make this fail: a mandatory Settings paste before the
    operator can finish first-run, which C9 forbids.
    """
    from core.checklist import ITEM_IDS

    assert "connect_aws" not in ITEM_IDS
    text = (REPO / "core" / "checklist.py").read_text(encoding="utf-8")
    assert "connect_aws" not in text


def test_c12_kinds_registered():
    """Every C12 kind is a classify() row before the first raise_alert.

    What would make this fail: raising aws-create-failed later with no
    table row, which is UnclassifiedAlert — the alert cannot ship.
    """
    from monitor.alert_rules import RULES_BY_KIND

    expected = {
        "aws-scope": "p2",
        "aws-create-failed": "p2",
        "aws-terminate-failed": "p1",
        "aws-host-key-timeout": "p1",
        "r53-fail": "p2",
        "ssm-fail": "p2",
        "budget-cap-hit": "p1",
    }
    for kind, sev in expected.items():
        assert kind in RULES_BY_KIND, kind
        assert RULES_BY_KIND[kind].severity == sev


def test_aws_connect_is_not_on_auth_urls():
    """POST /api/v1/aws/connect/ must not hang off core/urls.py (/api/auth/).

    What would make this fail: including aws_views on the auth urlconf so
    the peer of Cloudflare-connect is session-gated at the wrong prefix.
    """
    auth = (REPO / "core" / "urls.py").read_text(encoding="utf-8")
    assert "aws" not in auth.lower() or "aws_views" not in auth
    tree = ast.parse(auth)
    imported = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.append(node.module)
    assert "core.aws_views" not in imported
    assert "aws_views" not in imported
    zone = (REPO / "core" / "zone_urls.py").read_text(encoding="utf-8")
    assert "aws/connect/" in zone
