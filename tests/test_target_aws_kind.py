"""Phase 5 schema wave: Target.Kind.AWS_EC2 + nullable provider_ref (D-072).

0012_phase5.py is the only Hub migration this phase. CheckRun kinds and
DnsAccount.Provider.ROUTE53 are Python choices on existing CharFields.
No NetworkZone.kind, Site.tier, Site.secrets_mode, or CloudAccount table.
"""
import importlib
import json
import pathlib

import pytest
from django.core.exceptions import ValidationError
from django.db import migrations
from django.db.models import CharField

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent


def _zone(slug="aws-use1"):
    from core.models import NetworkZone

    return NetworkZone.objects.create(name=slug, slug=slug)


def test_target_kind_aws_ec2_exists():
    """Target.Kind includes aws_ec2 so enroll can store kind without overloading host.

    What would make this fail: Kind remaining {ssh} so a burst EC2 row cannot
    full_clean, or a different spelling that later tasks would have to invent.
    """
    from core.models import Target

    assert Target.Kind.AWS_EC2 == "aws_ec2"
    assert "aws_ec2" in Target.Kind.values
    assert Target.Kind.SSH == "ssh"

    target = Target(
        zone=_zone("kind-aws-ec2"),
        kind=Target.Kind.AWS_EC2,
        host="100.64.0.10",
        provider_ref="i-0123456789abcdef0",
    )
    target.full_clean()
    target.save()
    target.refresh_from_db()
    assert target.kind == "aws_ec2"
    assert target.host == "100.64.0.10"
    assert target.provider_ref == "i-0123456789abcdef0"


def test_provider_ref_nullable_on_ssh_target():
    """SSH rows leave provider_ref null. Instance id never lives on host.

    What would make this fail: a non-null default, blank=False, or stuffing
    i-… into host so Transport would try to SSH to an instance id.
    """
    from core.models import Target

    field = Target._meta.get_field("provider_ref")
    assert isinstance(field, CharField)
    assert field.null is True
    assert field.blank is True

    target = Target.objects.create(
        zone=_zone("ssh-null-ref"),
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
    )
    target.refresh_from_db()
    assert target.kind == Target.Kind.SSH
    assert target.provider_ref is None
    assert target.host == "10.0.0.8"
    target.full_clean()


def test_provider_ref_max_length_64():
    """provider_ref is CharField(max_length=64) — CloudProvider instance id, not host.

    What would make this fail: a shorter column that truncates i-… ids, a
    TextField, or max_length matching host (253) so the two columns blur.
    """
    from core.models import Target

    field = Target._meta.get_field("provider_ref")
    assert isinstance(field, CharField)
    assert field.max_length == 64
    assert Target._meta.get_field("host").max_length == 253

    zone = _zone("ref-len")
    ok = Target(
        zone=zone,
        kind=Target.Kind.AWS_EC2,
        host="100.64.0.11",
        provider_ref="i" + ("x" * 63),
    )
    ok.full_clean()
    ok.save()

    too_long = Target(
        zone=zone,
        kind=Target.Kind.AWS_EC2,
        host="100.64.0.12",
        provider_ref="i" + ("x" * 64),
    )
    with pytest.raises(ValidationError) as exc:
        too_long.full_clean()
    assert "provider_ref" in exc.value.message_dict


def test_dnsaccount_provider_route53_exists():
    """DnsAccount.Provider.ROUTE53 is a Python choice on the existing column.

    What would make this fail: omitting route53 so Task 4 invents a second
    table, or a migration that CreateModel-s a new DNS account type.
    """
    from core.models import DnsAccount

    assert DnsAccount.Provider.ROUTE53 == "route53"
    assert "route53" in DnsAccount.Provider.values
    assert DnsAccount.Provider.CLOUDFLARE == "cloudflare"

    account = DnsAccount(
        provider=DnsAccount.Provider.ROUTE53,
        label="r53-schema",
    )
    account.full_clean()
    account.save()
    account.refresh_from_db()
    assert account.provider == "route53"


def test_checkrun_kinds_aws_iam_scope_and_aws_reaper_exist():
    """aws_iam_scope and aws_reaper persist on the existing CheckRun table.

    What would make this fail: omitting a named kind so Task 9/6 edit
    models.py, AlterField-ing CheckRun.kind, or adding a CloudAccount table
    for the audit to hang off.
    """
    from core.models import CheckRun

    assert CheckRun.Kind.AWS_IAM_SCOPE == "aws_iam_scope"
    assert CheckRun.Kind.AWS_REAPER == "aws_reaper"

    for kind in (CheckRun.Kind.AWS_IAM_SCOPE, CheckRun.Kind.AWS_REAPER):
        run = CheckRun.objects.create(
            kind=kind,
            status=CheckRun.Status.SUCCEEDED,
            results={"schema_version": 1},
        )
        run.refresh_from_db()
        assert run.kind == kind


def test_no_networkzone_kind_and_no_site_tier():
    """0012 does not grow NetworkZone.kind, Site.tier, or a CloudAccount table.

    What would make this fail: VPC-as-zone-kind, D-053 Site.tier, a
    secrets_mode column, a new table, or reopening closed 0011.
    """
    from django.apps import apps

    from core import models as core_models
    from core.models import NetworkZone, Site

    assert "kind" not in {f.name for f in NetworkZone._meta.get_fields()}
    assert "tier" not in {f.name for f in Site._meta.get_fields()}
    assert "secrets_mode" not in {f.name for f in Site._meta.get_fields()}
    assert not hasattr(core_models, "CloudAccount")
    assert "CloudAccount" not in {m.__name__ for m in apps.get_models()}

    closed = importlib.import_module("core.migrations.0011_phase4").Migration
    assert closed.dependencies == [("core", "0010_phase3b")]
    assert not any(getattr(op, "model_name", "") == "target" for op in closed.operations)

    wave = importlib.import_module("core.migrations.0012_phase5").Migration
    assert wave.dependencies == [("core", "0011_phase4")]
    assert not any(isinstance(op, migrations.CreateModel) for op in wave.operations)
    assert not any(
        isinstance(op, migrations.AlterField)
        and getattr(op, "model_name", "") == "checkrun"
        for op in wave.operations
    )
    assert not any(
        isinstance(op, (migrations.AddField, migrations.AlterField))
        and getattr(op, "model_name", "") in {"networkzone", "site"}
        for op in wave.operations
    )
    added = [
        (op.model_name, op.name)
        for op in wave.operations
        if isinstance(op, migrations.AddField)
    ]
    assert ("target", "provider_ref") in added
    provider_ref = next(
        op.field
        for op in wave.operations
        if isinstance(op, migrations.AddField) and op.name == "provider_ref"
    )
    assert provider_ref.max_length == 64
    assert provider_ref.null is True
    assert provider_ref.blank is True


def test_seed_burst_ec2_1_kind_is_a_legal_choice():
    """simulation seed burst-ec2-1 kind=aws_ec2 full_cleans; no model clean error.

    What would make this fail: Target.Kind remaining {ssh} so the seed row is
    an illegal choice, or using host as the instance id because provider_ref
    does not exist.
    """
    from core.models import Target

    seed = json.loads((REPO / "simulation/seed_v1.json").read_text())
    row = next(t for t in seed["targets"] if t["name"] == "burst-ec2-1")
    assert row["kind"] == "aws_ec2"
    assert row["lifecycle"] == "ephemeral"

    target = Target(
        zone=_zone(row["zone"]),
        kind=row["kind"],
        host=row["name"],
        lifecycle=row["lifecycle"],
    )
    target.full_clean()
    assert target.kind == Target.Kind.AWS_EC2
    assert target.provider_ref is None
