"""AWS enroll: Hub-minted public-only SSH, pin, then provision_host (C5).

Mint Ed25519 in-Hub, vault the private key, set ssh_key_ref, inject the
public key only, pin host_key_fingerprint before any Transport, store
kind=aws_ec2 + provider_ref + Transport host, then provision_host.
Never AWS-held private keys. Never TOFU. boto3 stays in providers/.
"""
import secrets

from django.conf import settings

from vault import service as vault_service
from vault.models import Secret
from vault.ssh import generate_ed25519_keypair

SOURCE = "provision.aws_enroll"


class EnrollError(RuntimeError):
    """Enroll refused. Never carries private-key or credential material."""


class TerminateError(RuntimeError):
    """Terminate refused or provider failed. Never carries credential material."""


def enroll_aws_target(
    *,
    host,
    zone,
    name=None,
    provider=None,
    make_transport=None,
    spec=None,
    instance_type="t3.micro",
    region_name="us-east-1",
):
    """Create → pin → provision. Idempotent: a pinned Target is returned as-is."""
    from core.models import Target
    from core.ssh import SshTransport
    from provision.service import provision_host

    name = name or host
    existing = (
        Target.objects.filter(host=host, kind=Target.Kind.AWS_EC2)
        .order_by("pk")
        .first()
    )
    if (
        existing is not None
        and existing.provider_ref
        and existing.host_key_fingerprint
        and existing.ssh_key_ref
    ):
        return existing

    provider = provider or _cloud_provider(region_name=region_name)
    spec = _public_spec(spec, name=name, instance_type=instance_type)
    cost = _estimate_or_refuse(provider, spec)
    _budget_or_refuse(cost)

    pem, pub = generate_ed25519_keypair()
    _refuse_private_inject(pub)
    spec["ssh_public_key"] = pub

    target = existing or Target(
        zone=zone,
        kind=Target.Kind.AWS_EC2,
        host=host,
        ssh_user="deploy",
        lifecycle=Target.Lifecycle.EPHEMERAL,
        status=Target.Status.PENDING,
    )
    if target.pk is None:
        target.save()
    owner_id = target.ssh_key_ref or f"target-{target.pk}-ssh-{secrets.token_hex(8)}"
    vault_service.put(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_type="target",
        owner_id=owner_id,
        plaintext=pem if isinstance(pem, bytes) else str(pem).encode(),
    )
    target.ssh_key_ref = owner_id
    target.kind = Target.Kind.AWS_EC2
    target.host = host
    target.save(update_fields=["ssh_key_ref", "kind", "host"])

    try:
        inst = provider.create_instance(spec)
    except Exception as exc:
        msg = str(exc).lower()
        if "timeout" in msg or "tofu" in msg:
            _file_host_key_timeout(name)
            raise EnrollError("host key timeout; refusing TOFU") from exc
        _file_create_failed(name)
        raise EnrollError("create_instance failed") from exc

    instance_id = (inst or {}).get("id") or (inst or {}).get("instance_id") or ""
    if instance_id:
        target.provider_ref = instance_id
        target.host = host
        target.kind = Target.Kind.AWS_EC2
        target.save(update_fields=["provider_ref", "host", "kind"])

    fingerprint = (inst or {}).get("host_key_fingerprint") or ""
    if not str(fingerprint).strip():
        raise EnrollError("empty host key pin; refusing Transport")

    target.host_key_fingerprint = fingerprint
    target.provider_ref = instance_id or target.provider_ref
    target.host = host
    target.kind = Target.Kind.AWS_EC2
    target.save(
        update_fields=["host_key_fingerprint", "provider_ref", "host", "kind"]
    )

    if make_transport is None:
        make_transport = SshTransport
    transport = make_transport(target)
    provision_host(target, transport)
    target.status = Target.Status.READY
    target.save(update_fields=["status"])
    return target


def terminate_aws_target(target, *, provider=None, region_name="us-east-1"):
    """AWS terminate. Idempotent: already-decommissioned is a no-op.

    Absent instance == success. Failure files C12 and does not delete the
    row; status will not stay READY.
    """
    from core.models import Target

    if target.kind != Target.Kind.AWS_EC2:
        raise TerminateError("instance.terminate is the AWS call")
    if target.status == Target.Status.DECOMMISSIONED:
        return target
    try:
        provider = provider or _cloud_provider(region_name=region_name)
        provider.terminate_instance(target.provider_ref)
    except Exception as exc:
        _file_terminate_failed(target)
        target.status = Target.Status.ERROR
        target.save(update_fields=["status"])
        raise TerminateError("terminate_instance failed") from exc
    target.status = Target.Status.DECOMMISSIONED
    target.save(update_fields=["status"])
    return target


def _cloud_provider(*, region_name="us-east-1"):
    from providers.registry import cloud_provider_for

    return cloud_provider_for(region_name=region_name)


def _public_spec(spec, *, name, instance_type):
    spec = dict(spec or {})
    spec.setdefault("name", name)
    spec.setdefault("instance_type", instance_type)
    spec.setdefault("size", spec.get("instance_type") or instance_type)
    tags = dict(spec.get("tags") or {})
    tags.setdefault("Name", name)
    if getattr(settings, "HUB_TEST_MODE", False):
        tags.setdefault("purpose", "test")
    spec["tags"] = tags
    spec.pop("private_key", None)
    spec.pop("ssh_private_key", None)
    return spec


def _refuse_private_inject(pub):
    blob = pub if isinstance(pub, str) else (pub or b"").decode()
    for marker in (
        "BEGIN OPENSSH PRIVATE KEY",
        "BEGIN PRIVATE KEY",
        "BEGIN RSA PRIVATE KEY",
    ):
        if marker in blob:
            raise EnrollError("refusing private key as public inject")


def _estimate_or_refuse(provider, spec):
    try:
        cost = provider.estimate_hourly_cost(spec)
    except Exception as exc:
        raise EnrollError("unconfigured hourly cost estimate") from exc
    if cost is None:
        raise EnrollError("unconfigured hourly cost estimate")
    try:
        value = float(cost)
    except (TypeError, ValueError) as exc:
        raise EnrollError("unconfigured hourly cost estimate") from exc
    if value <= 0:
        raise EnrollError("refusing $0 as free; estimate unconfigured")
    return value


def _budget_or_refuse(cost):
    raw = str(getattr(settings, "AWS_HOURLY_BUDGET_USD", "") or "").strip()
    if not raw:
        return
    try:
        cap = float(raw)
    except ValueError as exc:
        raise EnrollError("unconfigured hourly cost estimate") from exc
    if float(cost) <= cap:
        return
    from core.models import default_workspace
    from monitor.alerts import raise_alert

    raise_alert(
        "budget-cap-hit",
        "aws",
        workspace=default_workspace(),
        fingerprint="budget-cap-hit:aws",
        source_engine=SOURCE,
        title="AWS hourly budget cap would be exceeded",
        body=(
            f"Estimated {cost} USD/h exceeds the configured "
            f"HUB_AWS_HOURLY_BUDGET_USD cap of {cap}."
        ),
        fix_action="Raise HUB_AWS_HOURLY_BUDGET_USD or pick a smaller size.",
    )
    raise EnrollError("budget cap hit")


def _file_create_failed(name):
    from core.models import default_workspace
    from monitor.alerts import raise_alert

    raise_alert(
        "aws-create-failed",
        f"aws:{name}",
        workspace=default_workspace(),
        fingerprint=f"aws-create:{name}",
        source_engine=SOURCE,
        title=f"EC2 create failed for {name}",
        body=f"create_instance refused for {name}; the Target was not enrolled.",
        fix_action="Inspect the provider and retry Create target.",
    )


def _file_terminate_failed(target):
    from core.models import default_workspace
    from monitor.alerts import raise_alert

    raise_alert(
        "aws-terminate-failed",
        f"aws:{target.pk}",
        workspace=default_workspace(),
        fingerprint=f"aws-terminate:{target.pk}",
        source_engine=SOURCE,
        title=f"EC2 terminate failed for {target.host}",
        body=(
            f"terminate_instance refused for target {target.pk}; "
            "the Target row is kept so the operator can retry."
        ),
        fix_action="Inspect the provider and retry Terminate target.",
    )


def _file_host_key_timeout(name):
    from core.models import default_workspace
    from monitor.alerts import raise_alert

    raise_alert(
        "aws-host-key-timeout",
        f"aws:{name}",
        workspace=default_workspace(),
        fingerprint=f"aws-host-key-timeout:{name}",
        source_engine=SOURCE,
        title="EC2 host keys did not arrive in time",
        body=(
            f"GetConsoleOutput produced no pin-able host key for {name}; "
            "Transport refused (never TOFU)."
        ),
        fix_action=(
            "Inspect the instance console and retry create; "
            "do not accept an unpinned host key"
        ),
    )
