"""EC2 CloudProvider (D-068). The only module that may import boto3 for EC2.

cloud_provider_for in providers/registry.py is the only constructor. Tests
enter `mock_aws_ec2()` (moto 5.x, not LocalStack) instead of importing moto
themselves. Dummy static creds inside the helper so a missed context cannot
pick up a real profile.
"""

import base64
import binascii
import os
import time
import uuid
from contextlib import contextmanager

import paramiko
from botocore.exceptions import ClientError
from django.conf import settings

from core.test_mode import assert_test_aws

from .base import CloudProvider

HOURLY_USD = {
    "t3.micro": 0.0104,
    "t3.small": 0.0208,
}
HOST_KEY_TIMEOUT_S = 90
_PUBLIC_CIDRS = frozenset({"0.0.0.0/0", "::/0"})
_PRIVATE_MARKERS = (
    "BEGIN OPENSSH PRIVATE KEY",
    "BEGIN RSA PRIVATE KEY",
    "BEGIN EC PRIVATE KEY",
    "BEGIN DSA PRIVATE KEY",
)
_SECRET_MARKERS = _PRIVATE_MARKERS + (
    "AWS_SECRET_ACCESS_KEY",
    "AWS_ACCESS_KEY_ID",
    "aws_secret_access_key",
    "aws_access_key_id",
    "/deploy-hub/",
)
_HOSTKEY_TYPES = (
    "ssh-ed25519",
    "ecdsa-sha2-nistp256",
    "ecdsa-sha2-nistp384",
    "ecdsa-sha2-nistp521",
    "ssh-rsa",
    "ssh-dss",
)

_API_CALLS = []
_RUN_KWARGS = []
_SG_INGRESS = []
_PLANTED = {}
_NEXT_CONSOLE = []


class Ec2Error(RuntimeError):
    """EC2 adapter refusal or provider failure. Never carries key material."""


def reset_ec2_log():
    _API_CALLS.clear()
    _RUN_KWARGS.clear()
    _SG_INGRESS.clear()
    _PLANTED.clear()
    _NEXT_CONSOLE.clear()


def last_run_instances_kwargs():
    """Kwargs of the most recent RunInstances. tests/ inspect this, not boto3."""
    return dict(_RUN_KWARGS[-1]) if _RUN_KWARGS else None


def last_sg_ingress():
    """IpPermissions of the SG attached at the last create_instance."""
    return list(_SG_INGRESS[-1]) if _SG_INGRESS else None


def api_calls():
    """boto3 EC2 method names invoked on the recording client."""
    return list(_API_CALLS)


def plant_next_console_output(text):
    """T1: GetConsoleOutput for the next RunInstances id. tests/ use this."""
    _NEXT_CONSOLE.append(text)


def plant_console_output(instance_id, text):
    _PLANTED[instance_id] = text


@contextmanager
def mock_aws_ec2():
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


class _RecordingEc2:
    """Records method names and RunInstances kwargs for tests, never boto3."""

    def __init__(self, client):
        object.__setattr__(self, "_client", client)

    def __getattr__(self, name):
        attr = getattr(self._client, name)
        if not callable(attr):
            return attr

        def wrapper(*args, **kwargs):
            _API_CALLS.append(name)
            if name == "run_instances":
                _RUN_KWARGS.append(dict(kwargs))
            return attr(*args, **kwargs)

        return wrapper


def _missing_instance(exc):
    code = (exc.response or {}).get("Error", {}).get("Code", "")
    return code in {"InvalidInstanceID.NotFound", "InvalidInstanceId.NotFound"}


def _looks_private(text):
    blob = text if isinstance(text, str) else (text or b"").decode()
    return any(marker in blob for marker in _PRIVATE_MARKERS)


def _refuse_secrets(text):
    blob = text if isinstance(text, str) else (text or b"").decode()
    for marker in _SECRET_MARKERS:
        if marker in blob:
            raise Ec2Error("refusing Hub credential / private key / SSM in UserData")


def _compose_user_data(spec):
    pubkey = spec.get("ssh_public_key") or spec.get("public_key") or ""
    extra = spec.get("user_data") or spec.get("UserData") or ""
    if extra and not isinstance(extra, str):
        extra = extra.decode()
    if _looks_private(pubkey) or _looks_private(extra):
        raise Ec2Error("refusing private key in UserData")
    lines = ["#cloud-config"]
    if pubkey:
        lines.append("ssh_authorized_keys:")
        lines.append(f"  - {str(pubkey).strip()}")
    if extra:
        lines.append(str(extra).rstrip("\n"))
    text = "\n".join(lines) + "\n"
    _refuse_secrets(text)
    return text


def _parse_host_keys(text):
    """Public host keys from console output → (fingerprint, line) preferring ed25519."""
    found = []
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("-"):
            continue
        parts = line.split()
        if len(parts) < 2 or parts[0] not in _HOSTKEY_TYPES:
            continue
        try:
            blob = base64.b64decode(parts[1])
            key = paramiko.PKey.from_type_string(parts[0], blob)
        except (ValueError, paramiko.SSHException, TypeError, binascii.Error):
            continue
        found.append((key.fingerprint, line, parts[0]))
    found.sort(key=lambda row: 0 if row[2] == "ssh-ed25519" else 1)
    return found


def _is_public_ssh(rule):
    proto = str(rule.get("protocol") or rule.get("IpProtocol") or "").lower()
    cidr = str(
        rule.get("cidr")
        or rule.get("CidrIp")
        or rule.get("cidr_ipv6")
        or rule.get("CidrIpv6")
        or ""
    )
    from_port = rule.get("from_port", rule.get("FromPort", rule.get("port")))
    to_port = rule.get("to_port", rule.get("ToPort", rule.get("port")))
    if from_port is None and to_port is None and proto in {"ssh", "22"}:
        from_port = to_port = 22
    ssh_proto = proto in {"ssh", "22"}
    try:
        covers_22 = (
            ssh_proto
            or proto in {"-1", "all"}
            or (
                proto in {"tcp", ""}
                and from_port is not None
                and to_port is not None
                and int(from_port) <= 22 <= int(to_port)
            )
        )
    except (TypeError, ValueError):
        covers_22 = ssh_proto
    return bool(covers_22 and cidr in _PUBLIC_CIDRS)


class Ec2CloudProvider(CloudProvider):
    """Product EC2 adapter. Constructed only by cloud_provider_for."""

    def __init__(
        self,
        client,
        *,
        region_name,
        account_id,
        sleep=time.sleep,
        now=time.monotonic,
        host_key_timeout_s=HOST_KEY_TIMEOUT_S,
    ):
        self._client = _RecordingEc2(client)
        self.region_name = region_name
        self.account_id = str(account_id)
        self._sleep = sleep
        self._now = now
        self._host_key_timeout_s = host_key_timeout_s

    def create_instance(self, spec):
        spec = dict(spec or {})
        tags = dict(spec.get("tags") or {})
        if spec.get("name") and "Name" not in tags:
            tags["Name"] = spec["name"]
        if getattr(settings, "HUB_TEST_MODE", False) and tags.get("purpose") != "test":
            raise Ec2Error("HUB_TEST_MODE requires tags.purpose=test")
        assert_test_aws(self.account_id, self.region_name, tags=tags)

        image_id = spec.get("image_id") or spec.get("ami") or "ami-0123456789abcdef0"
        instance_type = spec.get("instance_type") or spec.get("size") or "t3.micro"
        user_data = _compose_user_data(spec)
        sg_id = self._create_closed_sg(spec, tags)
        kwargs = {
            "ImageId": image_id,
            "InstanceType": instance_type,
            "MinCount": 1,
            "MaxCount": 1,
            "UserData": user_data,
            "SecurityGroupIds": [sg_id],
            "MetadataOptions": {
                "HttpTokens": "required",
                "HttpPutResponseHopLimit": 1,
            },
            "TagSpecifications": [
                {
                    "ResourceType": "instance",
                    "Tags": [{"Key": k, "Value": str(v)} for k, v in tags.items()],
                }
            ],
        }
        try:
            resp = self._client.run_instances(**kwargs)
        except ClientError as exc:
            raise Ec2Error("RunInstances failed") from exc
        instance = resp["Instances"][0]
        instance_id = instance["InstanceId"]
        if _NEXT_CONSOLE:
            _PLANTED[instance_id] = _NEXT_CONSOLE.pop(0)
        self._record_instance_ingress(instance_id)
        try:
            fingerprint, host_keys = self._wait_for_host_keys(instance_id, tags, spec)
        except Ec2Error:
            try:
                self.terminate_instance(instance_id)
            except Ec2Error:
                pass
            raise
        described = self.get_instance(instance_id) or {}
        state = described.get("state") or instance.get("State", {}).get("Name")
        return {
            "id": instance_id,
            "state": state or "pending",
            "public_ip": described.get("public_ip") or instance.get("PublicIpAddress"),
            "host_key_fingerprint": fingerprint,
            "host_keys": host_keys,
        }

    def get_instance(self, instance_id):
        try:
            reservations = self._client.describe_instances(
                InstanceIds=[instance_id],
            )["Reservations"]
        except ClientError as exc:
            if _missing_instance(exc):
                return None
            raise Ec2Error("DescribeInstances failed") from exc
        if not reservations or not reservations[0].get("Instances"):
            return None
        row = reservations[0]["Instances"][0]
        tags = {t["Key"]: t["Value"] for t in row.get("Tags") or []}
        return {
            "id": row["InstanceId"],
            "state": row["State"]["Name"],
            "public_ip": row.get("PublicIpAddress"),
            "tags": tags,
        }

    def terminate_instance(self, instance_id):
        try:
            self._client.terminate_instances(InstanceIds=[instance_id])
        except ClientError as exc:
            if _missing_instance(exc):
                return
            raise Ec2Error("TerminateInstances failed") from exc

    def ensure_ingress_rules(self, instance_id, rules):
        for rule in rules or []:
            if _is_public_ssh(rule):
                raise Ec2Error("refusing public 22/ssh from 0.0.0.0/0 or ::/0")
        sg_id = self._sg_id(instance_id)
        for rule in rules or []:
            perm = _ip_permission(rule)
            try:
                self._client.authorize_security_group_ingress(
                    GroupId=sg_id,
                    IpPermissions=[perm],
                )
            except ClientError as exc:
                code = (exc.response or {}).get("Error", {}).get("Code", "")
                if code in {"InvalidPermission.Duplicate", "InvalidPermission.DuplicateRule"}:
                    continue
                raise Ec2Error("AuthorizeSecurityGroupIngress failed") from exc

    def list_tagged_instances(self, tags):
        filters = [
            {"Name": f"tag:{key}", "Values": [str(value)]} for key, value in (tags or {}).items()
        ]
        try:
            pages = self._client.describe_instances(Filters=filters)
        except ClientError as exc:
            raise Ec2Error("DescribeInstances failed") from exc
        out = []
        for reservation in pages.get("Reservations") or []:
            for row in reservation.get("Instances") or []:
                row_tags = {t["Key"]: t["Value"] for t in row.get("Tags") or []}
                out.append(
                    {
                        "id": row["InstanceId"],
                        "state": row["State"]["Name"],
                        "public_ip": row.get("PublicIpAddress"),
                        "tags": row_tags,
                    }
                )
        return out

    def create_image(self, instance_id, name):
        try:
            resp = self._client.create_image(
                InstanceId=instance_id,
                Name=name,
                NoReboot=True,
            )
        except ClientError as exc:
            raise Ec2Error("CreateImage failed") from exc
        return {"image_id": resp["ImageId"], "name": name}

    def estimate_hourly_cost(self, spec):
        size = (spec or {}).get("instance_type") or (spec or {}).get("size")
        if size not in HOURLY_USD:
            raise Ec2Error(f"no hourly cost for {size!r}; refusing $0 as free")
        return HOURLY_USD[size]

    def _create_closed_sg(self, spec, tags):
        vpc_id = spec.get("vpc_id") or self._default_vpc()
        name = tags.get("Name") or spec.get("name") or "hub"
        group_name = f"hub-{name}-{uuid.uuid4().hex[:10]}"
        try:
            sg = self._client.create_security_group(
                GroupName=group_name,
                Description="deploy-hub target (no public 22)",
                VpcId=vpc_id,
            )
        except ClientError as exc:
            raise Ec2Error("CreateSecurityGroup failed") from exc
        return sg["GroupId"]

    def _record_instance_ingress(self, instance_id):
        reservations = self._client.describe_instances(InstanceIds=[instance_id])
        row = reservations["Reservations"][0]["Instances"][0]
        ids = [g["GroupId"] for g in row.get("SecurityGroups") or []]
        if not ids:
            _SG_INGRESS.append([])
            return
        groups = self._client.describe_security_groups(GroupIds=ids)
        perms = []
        for group in groups["SecurityGroups"]:
            perms.extend(group.get("IpPermissions") or [])
        _SG_INGRESS.append(list(perms))

    def _default_vpc(self):
        vpcs = self._client.describe_vpcs()["Vpcs"]
        if not vpcs:
            raise Ec2Error("no VPC available for the security group")
        return vpcs[0]["VpcId"]

    def _sg_id(self, instance_id):
        info = self.get_instance(instance_id)
        if info is None:
            raise Ec2Error(f"instance {instance_id} not found")
        reservations = self._client.describe_instances(InstanceIds=[instance_id])
        row = reservations["Reservations"][0]["Instances"][0]
        groups = row.get("SecurityGroups") or []
        if not groups:
            raise Ec2Error("instance has no security group")
        return groups[0]["GroupId"]

    def _console_text(self, instance_id):
        if instance_id in _PLANTED:
            return _PLANTED[instance_id]
        resp = self._client.get_console_output(InstanceId=instance_id)
        output = resp.get("Output") or ""
        if isinstance(output, bytes):
            return output.decode("utf-8", "replace")
        return output

    def _wait_for_host_keys(self, instance_id, tags, spec):
        name = tags.get("Name") or spec.get("name") or instance_id
        deadline = self._now() + float(self._host_key_timeout_s)
        while True:
            parsed = _parse_host_keys(self._console_text(instance_id))
            if parsed:
                fingerprint = parsed[0][0]
                host_keys = [row[1] for row in parsed]
                return fingerprint, host_keys
            if self._now() >= deadline:
                self._file_host_key_timeout(name)
                raise Ec2Error("host key timeout; refusing TOFU")
            self._sleep(1)

    def _file_host_key_timeout(self, name):
        from monitor.alerts import raise_alert

        raise_alert(
            "aws-host-key-timeout",
            f"aws:{name}",
            fingerprint=f"aws-host-key-timeout:{name}",
            source_engine="providers.ec2",
            title="EC2 host keys did not arrive in time",
            body=(
                f"GetConsoleOutput produced no pin-able host key for {name}; "
                "Transport refused (never TOFU)."
            ),
            fix_action=(
                "Inspect the instance console and retry create; do not accept an unpinned host key"
            ),
        )


def _ip_permission(rule):
    proto = str(rule.get("protocol") or "tcp").lower()
    if proto in {"ssh", "22"}:
        proto = "tcp"
        from_port = to_port = 22
    else:
        from_port = rule.get("from_port", rule.get("FromPort", rule.get("port", 0)))
        to_port = rule.get("to_port", rule.get("ToPort", rule.get("port", from_port)))
    cidr = str(
        rule.get("cidr")
        or rule.get("CidrIp")
        or rule.get("cidr_ipv6")
        or rule.get("CidrIpv6")
        or ""
    )
    perm = {
        "IpProtocol": proto,
        "FromPort": int(from_port),
        "ToPort": int(to_port),
    }
    if ":" in cidr:
        perm["Ipv6Ranges"] = [{"CidrIpv6": cidr}]
    else:
        perm["IpRanges"] = [{"CidrIp": cidr}]
    return perm
