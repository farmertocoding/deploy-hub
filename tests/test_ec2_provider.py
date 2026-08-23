"""T1: EC2 CloudProvider adapter (D-068 / AWS-EC2-ADAPTER).

boto3, botocore, and moto must not appear as imports in this file. Dummy
creds, the RunInstances kwargs log, SG inspect, console plant, and
`mock_aws_ec2` live in providers/ec2.py so the tested client is the shipped
client. Tests inject FakeCloudProvider for pipeline defaults; they go through
`cloud_provider_for` here only to prove that constructor.
"""
import ast
import json
import pathlib
import re
from contextlib import contextmanager

import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
ACCOUNT = "123456789012"
REF = "hub-aws"
AKI = "t1-ec2-access-key-id-not-a-credential"
SAK = "t1-ec2-secret-access-key-not-a-credential"
PUB = (
    "ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIEc2AdapterTestPublicKeyOnly "
    "deploy-hub-t1"
)
_IMPORT_BOTO = re.compile(r"^\s*(import|from)\s+(boto3|botocore|moto)\b", re.M)
_PUBLIC = {"0.0.0.0/0", "::/0"}


def _put_creds():
    from vault import service as vault_service
    from vault.models import Secret

    return vault_service.put(
        kind=Secret.Kind.CLOUD_CREDENTIAL,
        owner_type="aws",
        owner_id=REF,
        plaintext=json.dumps(
            {"access_key_id": AKI, "secret_access_key": SAK}
        ).encode(),
    )


def _host_key():
    from paramiko import ECDSAKey

    key = ECDSAKey.generate()
    line = f"{key.get_name()} {key.get_base64()}"
    text = (
        "cloud-init: starting\n"
        "-----BEGIN SSH HOST KEY KEYS-----\n"
        f"{line}\n"
        "-----END SSH HOST KEY KEYS-----\n"
    )
    return key, line, text


def _spec(**extra):
    spec = {
        "image_id": "ami-0123456789abcdef0",
        "instance_type": "t3.micro",
        "name": "hub-t1-ec2",
        "tags": {"purpose": "test", "Name": "hub-t1-ec2"},
        "ssh_public_key": PUB,
    }
    tags = extra.pop("tags", None)
    spec.update(extra)
    if tags is not None:
        spec["tags"] = tags
    return spec


@contextmanager
def opened_ec2(*, console=True, **provider_kwargs):
    from providers.ec2 import mock_aws_ec2, plant_next_console_output, reset_ec2_log
    from providers.registry import cloud_provider_for

    _put_creds()
    key = None
    with override_settings(
        HUB_TEST_MODE=True,
        AWS_CREDENTIALS_REF=REF,
        HUB_TEST_AWS_ACCOUNT_IDS=[ACCOUNT],
        HUB_TEST_AWS_REGIONS=["us-east-1"],
    ), mock_aws_ec2():
        reset_ec2_log()
        if console:
            key, _line, text = _host_key()
            plant_next_console_output(text)
        yield cloud_provider_for(region_name="us-east-1", **provider_kwargs), key


def _userdata_text(kwargs):
    raw = (kwargs or {}).get("UserData") or ""
    if isinstance(raw, bytes):
        raw = raw.decode()
    return raw


def _has_public_22(permissions):
    for perm in permissions or []:
        proto = str(perm.get("IpProtocol") or "").lower()
        from_port = perm.get("FromPort")
        to_port = perm.get("ToPort")
        cidrs = [row.get("CidrIp") for row in perm.get("IpRanges") or []]
        cidrs += [row.get("CidrIpv6") for row in perm.get("Ipv6Ranges") or []]
        covers_22 = proto in {"-1", "all"} or (
            from_port is not None
            and to_port is not None
            and int(from_port) <= 22 <= int(to_port)
        )
        if covers_22 and _PUBLIC.intersection(cidrs):
            return True
    return False


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_cloud_provider_for_is_the_only_constructor():
    """AST scan: Ec2CloudProvider(...) only in the registry (D-068).

    What would make this fail: a view, enroll playbook, or reaper constructing
    the adapter (or boto3.client('ec2')) and skipping vault-ref load, STS, and
    the test-plane wall.
    """
    from providers.aws_creds import AwsCredsError
    from providers.ec2 import Ec2CloudProvider
    from providers.registry import cloud_provider_for

    allowed = {"providers/registry.py", "tests/test_ec2_provider.py"}
    skip_dirs = {
        ".git", ".venv", ".venv-scaffold", ".worktrees", "node_modules",
        "frontend", "mutants", "staticfiles", "__pycache__",
    }
    offenders = []
    for path in sorted(REPO.rglob("*.py")):
        rel = path.relative_to(REPO)
        if set(rel.parts) & skip_dirs or str(rel) in allowed:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = getattr(node.func, "id", None) or getattr(node.func, "attr", None)
                if name == "Ec2CloudProvider":
                    offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], offenders

    registry_src = (REPO / "providers" / "registry.py").read_text(encoding="utf-8")
    assert "Ec2CloudProvider(" in registry_src
    assert "def cloud_provider_for" in registry_src

    with override_settings(AWS_CREDENTIALS_REF=""):
        with pytest.raises(AwsCredsError, match="empty|HUB_AWS_CREDENTIALS_REF"):
            cloud_provider_for(region_name="us-east-1")

    with opened_ec2() as (provider, _key):
        assert isinstance(provider, Ec2CloudProvider)


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_create_instance_returns_host_key_fingerprint():
    """create_instance pins a paramiko-equal fingerprint from GetConsoleOutput.

    What would make this fail: returning host_keys strings the pin cannot
    compare, or synthesizing a fingerprint instead of loading the console
    public key through paramiko.PKey.fingerprint.
    """
    with opened_ec2() as (provider, key):
        inst = provider.create_instance(_spec())
    assert inst["id"].startswith("i-")
    assert inst["state"]
    assert "public_ip" in inst
    assert inst["host_key_fingerprint"] == key.fingerprint
    assert inst["host_key_fingerprint"].startswith("SHA256:")


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_runinstances_requires_imdsv2_and_hop_limit_1():
    """RunInstances kwargs set HttpTokens=required and hop-limit 1 (C5).

    What would make this fail: omitting MetadataOptions so moto's stored
    default hop-limit 1 hides a missing HttpTokens=required on the wire.
    """
    from providers.ec2 import last_run_instances_kwargs

    with opened_ec2() as (provider, _key):
        provider.create_instance(_spec())
    kwargs = last_run_instances_kwargs()
    assert kwargs is not None
    meta = kwargs["MetadataOptions"]
    assert meta["HttpTokens"] == "required"
    assert meta["HttpPutResponseHopLimit"] == 1


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_default_sg_has_no_public_22():
    """The SG attached at create has no 22/tcp from 0.0.0.0/0 or ::/0.

    What would make this fail: AuthorizeSecurityGroupIngress of ssh from
    the world as a 'so we can log in' default, which D-068 forbids.
    """
    from providers.ec2 import last_sg_ingress

    with opened_ec2() as (provider, _key):
        provider.create_instance(_spec())
    rules = last_sg_ingress()
    assert rules is not None
    assert _has_public_22(rules) is False


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_ensure_ingress_rules_refuses_public_22_ipv4_and_ipv6():
    """ensure_ingress_rules refuses 22/tcp and ssh from 0.0.0.0/0 and ::/0.

    What would make this fail: a temporary=True bypass, or treating ::/0 as
    not-public so IPv6 world-open SSH lands.
    """
    from providers.ec2 import Ec2Error

    with opened_ec2() as (provider, _key):
        inst = provider.create_instance(_spec())
        iid = inst["id"]
        with pytest.raises(Ec2Error, match="22|ssh|public"):
            provider.ensure_ingress_rules(iid, [
                {"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": "0.0.0.0/0"},
            ])
        with pytest.raises(Ec2Error, match="22|ssh|public"):
            provider.ensure_ingress_rules(iid, [
                {"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": "::/0"},
            ])
        with pytest.raises(Ec2Error, match="22|ssh|public"):
            provider.ensure_ingress_rules(iid, [
                {"protocol": "ssh", "cidr": "0.0.0.0/0", "temporary": True},
            ])
        provider.ensure_ingress_rules(iid, [
            {"protocol": "tcp", "from_port": 22, "to_port": 22, "cidr": "203.0.113.5/32"},
        ])


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_purpose_test_required_under_hub_test_mode():
    """Under HUB_TEST_MODE, spec without tags.purpose=test refuses.

    What would make this fail: creating an untagged (or purpose=prod)
    instance on the test-plane so a live-looking target can be launched
    from tests.
    """
    from providers.ec2 import Ec2Error

    with opened_ec2() as (provider, _key):
        with pytest.raises(Ec2Error, match="purpose"):
            provider.create_instance(_spec(tags={"Name": "hub-t1-ec2"}))


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_terminate_absent_is_success():
    """terminate_instance is idempotent, including moto-missing-id.

    What would make this fail: InvalidInstanceID.NotFound propagating so
    the reaper cannot close a row whose instance is already gone.
    """
    with opened_ec2() as (provider, _key):
        inst = provider.create_instance(_spec())
        provider.terminate_instance(inst["id"])
        provider.terminate_instance(inst["id"])
        provider.terminate_instance("i-000000000000dead0")


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_host_key_timeout_refuses_not_tofu():
    """Empty console after the wait files aws-host-key-timeout and raises.

    What would make this fail: falling back to AutoAdd / returning an empty
    pin so Transport TOFUs the first host key it sees (SEC-68).
    """
    from core.models import Finding
    from providers.ec2 import Ec2Error

    with opened_ec2(console=False, host_key_timeout_s=0, sleep=lambda _s: None) as (
        provider, _key,
    ):
        with pytest.raises(Ec2Error, match="host key|TOFU|timeout"):
            provider.create_instance(_spec())
    row = Finding.objects.get(fingerprint="aws-host-key-timeout:hub-t1-ec2")
    assert row.severity == "p1"
    assert "TOFU" in row.body
    src = (REPO / "providers" / "ec2.py").read_text(encoding="utf-8")
    assert "AutoAdd" not in src
    assert "WarningPolicy" not in src


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_create_keypair_not_used():
    """Hub-minted public key is injected; CreateKeyPair is never called.

    What would make this fail: RunInstances KeyName from CreateKeyPair, so
    AWS holds the private key the Hub should have minted.
    """
    from providers.ec2 import api_calls, last_run_instances_kwargs

    with opened_ec2() as (provider, _key):
        provider.create_instance(_spec())
    assert "create_key_pair" not in api_calls()
    src = (REPO / "providers" / "ec2.py").read_text(encoding="utf-8")
    assert "CreateKeyPair" not in src
    assert "create_key_pair" not in src
    kwargs = last_run_instances_kwargs()
    assert kwargs.get("KeyName") in (None, "")
    userdata = _userdata_text(kwargs)
    assert "ssh_authorized_keys" in userdata
    assert PUB in userdata


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_no_hub_cloud_credential_in_userdata():
    """UserData never carries Hub CLOUD_CREDENTIAL, private keys, or SSM values.

    What would make this fail: stuffing the vaulted access key or the
    per-target private key into cloud-init so IMDS publishes Hub creds.
    """
    from providers.ec2 import last_run_instances_kwargs

    with opened_ec2() as (provider, _key):
        provider.create_instance(_spec())
    userdata = _userdata_text(last_run_instances_kwargs())
    assert AKI not in userdata
    assert SAK not in userdata
    assert "BEGIN OPENSSH PRIVATE KEY" not in userdata
    assert "BEGIN RSA PRIVATE KEY" not in userdata
    assert "AWS_SECRET_ACCESS_KEY" not in userdata
    assert "AWS_ACCESS_KEY_ID" not in userdata
    assert "/deploy-hub/" not in userdata


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_estimate_hourly_cost_fake_is_0_05():
    """FakeCloudProvider.estimate_hourly_cost is $0.05 (T1 overlay).

    What would make this fail: returning 0 so the overlay reads as free, or
    calling the live Price List from the Fake.
    """
    from providers.fakes import FakeCloudProvider

    assert FakeCloudProvider().estimate_hourly_cost({"instance_type": "t3.small"}) == 0.05


@pytest.mark.req("AWS-EC2-ADAPTER")
def test_create_image_returns_id_and_is_not_a_secret_store():
    """create_image returns an ami- id; the payload is not a vault.

    What would make this fail: stuffing UserData / CLOUD_CREDENTIAL into the
    AMI description, or returning a dict that looks like a secret store.
    """
    with opened_ec2() as (provider, _key):
        inst = provider.create_instance(_spec())
        img = provider.create_image(inst["id"], "hub-t1-image")
    assert img["image_id"].startswith("ami-")
    assert img["name"] == "hub-t1-image"
    blob = json.dumps(img)
    assert AKI not in blob
    assert SAK not in blob
    assert "secret" not in blob.lower()
    assert set(img) == {"image_id", "name"}


def test_fake_cloud_create_still_has_id_and_idempotent_terminate():
    """Fake return shape matches the pin dict; terminate stays absent==success."""
    from providers.fakes import FakeCloudProvider

    cloud = FakeCloudProvider()
    inst = cloud.create_instance({"size": "t3.small", "tags": {"purpose": "test"}})
    assert inst["id"]
    assert inst["state"]
    assert "public_ip" in inst
    assert inst["host_key_fingerprint"]
    cloud.terminate_instance(inst["id"])
    cloud.terminate_instance(inst["id"])


def test_ec2_tests_do_not_import_boto3():
    """This module never imports boto3/botocore/moto (D-034 split)."""
    text = pathlib.Path(__file__).read_text(encoding="utf-8")
    assert _IMPORT_BOTO.search(text) is None


def test_deploys_vault_monitor_tests_still_do_not_import_boto3():
    """deploys/, vault/, monitor/, and tests/ still do not import boto3/moto."""
    offenders = []
    for pkg in ("deploys", "vault", "monitor", "tests"):
        for py in (REPO / pkg).rglob("*.py"):
            if _IMPORT_BOTO.search(py.read_text(encoding="utf-8")):
                offenders.append(str(py.relative_to(REPO)))
    assert offenders == [], offenders
