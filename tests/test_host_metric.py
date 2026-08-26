"""Phase 6 schema wave: HostMetric + Site.scale_ready.

0014_phase6.py is the only Hub migration this phase. 0013 stays closed.
No ScalePolicy, no CheckRun.Kind, no new OperationLock.Kind, no scale_ready
backfill. Schema tests stay unmarked (C11).
"""
import importlib
from datetime import UTC, datetime

import pytest
from django.db import migrations
from django.db.models import (
    CASCADE,
    BooleanField,
    DateTimeField,
    FloatField,
    ForeignKey,
    PositiveIntegerField,
)

pytestmark = pytest.mark.django_db

_CHECKRUN_KINDS = {
    "hub_down",
    "restore_clean",
    "reaper",
    "pager",
    "cf_token_scope",
    "cert_expiry",
    "adopt",
    "ssh_rotate",
    "backup",
    "attack_playbook",
    "tailscale_devices",
    "aws_iam_scope",
    "aws_reaper",
    "partner_reaper",
    "intake_poll",
    "hub_dns01",
}

_OPERATIONLOCK_KINDS = {"deploy", "provision", "reconcile", "collect"}


def _target(slug="hm"):
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(name=slug, slug=slug)
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host=f"{slug}.example",
        ssh_user="deploy",
        ssh_key_ref="vault-owner-1",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


def _site(name="scale-ready"):
    from core.models import Project, Site

    project = Project.objects.create(name=name, slug=name)
    return Site.objects.create(
        project=project,
        name=name,
        exposure=Site.Exposure.MESH_ONLY,
    )


def test_site_scale_ready_defaults_false():
    """Site.scale_ready is fail-closed False; omitting it must not look ready.

    What would make this fail: no column, a True default, or a nullable field
    that treats missing as unknown instead of not-ready.
    """
    from core.models import Site

    field = Site._meta.get_field("scale_ready")
    assert isinstance(field, BooleanField)
    assert field.default is False
    assert field.null is False

    site = _site("scale-default")
    site.refresh_from_db()
    assert site.scale_ready is False


def test_host_metric_stores_ram_disk_load_cores():
    """HostMetric keeps ram/disk/load/cores (and nullable unused cpu) per target.

    What would make this fail: mapping onto collect_payload only, a unique-on-ts
    so a retry cannot land, a granularity/rollup column, missing (target, -ts),
    or a non-CASCADE FK that leaves orphan samples after a Target delete.
    """
    from core.models import HostMetric, Target

    target_field = HostMetric._meta.get_field("target")
    assert isinstance(target_field, ForeignKey)
    assert target_field.remote_field.model is Target
    assert target_field.remote_field.on_delete is CASCADE
    assert target_field.remote_field.related_name == "host_metrics"

    ts_field = HostMetric._meta.get_field("ts")
    assert isinstance(ts_field, DateTimeField)
    assert ts_field.db_index is True
    assert ts_field.unique is False

    for name in ("cpu", "ram", "disk", "load"):
        field = HostMetric._meta.get_field(name)
        assert isinstance(field, FloatField)
        assert field.null is True

    cores_field = HostMetric._meta.get_field("cores")
    assert isinstance(cores_field, PositiveIntegerField)
    assert cores_field.null is True

    names = {f.name for f in HostMetric._meta.get_fields()}
    assert "granularity" not in names
    assert not any(
        list(getattr(idx, "fields", [])) == ["target", "ts"]
        and getattr(idx, "unique", False)
        for idx in HostMetric._meta.indexes
    )
    assert any(list(idx.fields) == ["target", "-ts"] for idx in HostMetric._meta.indexes)
    assert not HostMetric._meta.unique_together
    assert not any(
        set(getattr(c, "fields", ())) & {"ts"}
        for c in HostMetric._meta.constraints
    )

    target = _target("hm-store")
    ts = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
    row = HostMetric.objects.create(
        target=target,
        ts=ts,
        cpu=None,
        ram=90.5,
        disk=41.0,
        load=2.25,
        cores=4,
    )
    row.refresh_from_db()
    assert row.target_id == target.pk
    assert row.ts == ts
    assert row.cpu is None
    assert row.ram == 90.5
    assert row.disk == 41.0
    assert row.load == 2.25
    assert row.cores == 4
    assert list(target.host_metrics.values_list("pk", flat=True)) == [row.pk]

    HostMetric.objects.create(
        target=target, ts=ts, cpu=None, ram=91.0, disk=42.0, load=2.5, cores=4,
    )
    assert HostMetric.objects.filter(target=target, ts=ts).count() == 2

    target.delete()
    assert not HostMetric.objects.filter(pk=row.pk).exists()


def test_phase6_wave_is_host_metric_and_scale_ready_only():
    """0014 adds HostMetric + Site.scale_ready. 0013 stays closed.

    What would make this fail: reopening 0013, a ScalePolicy table, a CheckRun
    or OperationLock kind, a data migration that backfills scale_ready, or
    Site.tier / Site.partner_id / Target.tier sneaking in with the wave.
    """
    from django.apps import apps

    from core import models as core_models
    from core.models import CheckRun, NetworkZone, OperationLock, Site, Target

    assert "tier" not in {f.name for f in Site._meta.get_fields()}
    assert "partner_id" not in {f.name for f in Site._meta.concrete_fields}
    assert "partner" not in {f.name for f in Site._meta.concrete_fields}
    assert "tier" not in {f.name for f in Target._meta.get_fields()}
    assert "kind" not in {f.name for f in NetworkZone._meta.get_fields()}
    assert not hasattr(core_models, "ScalePolicy")
    assert "ScalePolicy" not in {m.__name__ for m in apps.get_models()}
    assert set(CheckRun.Kind.values) == _CHECKRUN_KINDS
    assert set(OperationLock.Kind.values) == _OPERATIONLOCK_KINDS

    closed = importlib.import_module("core.migrations.0013_phase55").Migration
    assert closed.dependencies == [("core", "0012_phase5")]

    wave = importlib.import_module("core.migrations.0014_phase6").Migration
    assert wave.dependencies == [("core", "0013_phase55")]
    assert not any(isinstance(op, migrations.RunPython) for op in wave.operations)
    assert not any(isinstance(op, migrations.RunSQL) for op in wave.operations)
    assert not any(
        isinstance(op, migrations.AlterField)
        and getattr(op, "model_name", "") in {"checkrun", "operationlock"}
        for op in wave.operations
    )
    created = {
        op.name
        for op in wave.operations
        if isinstance(op, migrations.CreateModel)
    }
    assert created == {"HostMetric"}
    added = {
        (op.model_name, op.name)
        for op in wave.operations
        if isinstance(op, migrations.AddField)
    }
    assert added == {("site", "scale_ready")}
    host = next(op for op in wave.operations if isinstance(op, migrations.CreateModel))
    field_names = {name for name, _field in host.fields}
    assert field_names == {"id", "target", "ts", "cpu", "ram", "disk", "load", "cores"}
    assert ["target", "-ts"] in [list(idx.fields) for idx in host.options.get("indexes", [])]
    assert not host.options.get("unique_together")
    assert not host.options.get("constraints")
    assert not any(
        isinstance(op, (migrations.AddField, migrations.AlterField))
        and getattr(op, "model_name", "") in {"networkzone", "target", "checkrun", "operationlock"}
        for op in wave.operations
    )
