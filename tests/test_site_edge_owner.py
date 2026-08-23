"""Site.edge_owner + CheckRun.Kind.ADOPT (phase 3b Task 1 / design note §2, §7 I-run).

One Site column records who owns Caddy. Adopt progress reuses CheckRun — a
Python kind and a closed results schema — so 0010 does not add a table or a
Site FK.
"""
import pytest
from django.core.exceptions import ValidationError
from django.db import migrations

pytestmark = pytest.mark.django_db

_ADOPT_RESULT_KEYS = frozenset(
    {"schema_version", "site_id", "temp_name", "stage", "started_at"}
)


def _project(slug):
    from core.models import Project

    return Project.objects.create(name=slug, slug=slug)


def _adopt_results(**overrides):
    payload = {
        "schema_version": 1,
        "site_id": 1,
        "temp_name": "",
        "stage": "verify",
        "started_at": "2026-08-23T00:00:00+00:00",
    }
    payload.update(overrides)
    return payload


def test_new_site_defaults_to_host_caddy():
    """Fresh Hub sites stay host_caddy — adopt writes site_caddy, not create.

    What would make this fail: a null default, a site_caddy default, or no
    edge_owner column so every new Site is silently unowned.
    """
    from core.models import Site

    site = Site.objects.create(
        project=_project("p3b-edge-default"),
        name="fresh",
        exposure=Site.Exposure.MESH_ONLY,
    )
    site.refresh_from_db()
    assert site.edge_owner == Site.EdgeOwner.HOST_CADDY
    assert site.edge_owner == "host_caddy"
    assert "tier" not in {f.name for f in Site._meta.get_fields()}


def test_edge_owner_rejects_unknown_value():
    """edge_owner is the closed pair {host_caddy, site_caddy}, not an image name.

    What would make this fail: a free-text CharField that accepts nginx/traefik
    (those are compose images, not ownership), or a third enum member.
    """
    from core.models import Site

    site = Site(
        project=_project("p3b-edge-reject"),
        name="ambiguous",
        exposure=Site.Exposure.MESH_ONLY,
        edge_owner="nginx",
    )
    with pytest.raises(ValidationError) as exc:
        site.full_clean()
    assert "edge_owner" in exc.value.message_dict
    assert set(Site.EdgeOwner.values) == {"host_caddy", "site_caddy"}


def test_checkrun_kind_adopt_saves_without_a_new_table():
    """kind=adopt persists on the existing CheckRun table; 0010 adds no model.

    What would make this fail: a new AdoptRun table, or 0010 AlterField-ing
    CheckRun.kind (choices are Python; CharField does not need a migration).
    """
    import importlib

    from django.db import connection

    from core.models import CheckRun

    tables_before = set(connection.introspection.table_names())
    run = CheckRun.objects.create(
        kind=CheckRun.Kind.ADOPT,
        status=CheckRun.Status.RUNNING,
        results=_adopt_results(),
    )
    run.refresh_from_db()
    assert run.kind == "adopt"
    assert CheckRun._meta.db_table in tables_before
    assert set(connection.introspection.table_names()) == tables_before

    Migration = importlib.import_module("core.migrations.0010_phase3b").Migration
    assert Migration.dependencies == [("core", "0009_phase3")]
    assert not any(isinstance(op, migrations.CreateModel) for op in Migration.operations)
    assert not any(
        isinstance(op, migrations.AlterField) and getattr(op, "model_name", "") == "checkrun"
        for op in Migration.operations
    )
    assert [
        (op.model_name, op.name)
        for op in Migration.operations
        if isinstance(op, migrations.AddField)
    ] == [("site", "edge_owner")]


def test_adopt_checkrun_results_require_site_id_and_closed_schema():
    """kind=adopt results keys are exactly the S2 set; site_id is required.

    What would make this fail: accepting the default {schema_version} payload,
    dropping site_id (the reaper's only Site pointer), or allowing extra keys
    that later become a token home (S4).
    """
    from core.models import CheckRun

    missing_site_id = _adopt_results()
    del missing_site_id["site_id"]
    with pytest.raises(ValidationError) as exc:
        CheckRun.objects.create(
            kind=CheckRun.Kind.ADOPT,
            status=CheckRun.Status.RUNNING,
            results=missing_site_id,
        )
    assert "results" in exc.value.message_dict

    extra_key = _adopt_results(token="must-not-persist")
    with pytest.raises(ValidationError) as exc:
        CheckRun.objects.create(
            kind=CheckRun.Kind.ADOPT,
            status=CheckRun.Status.RUNNING,
            results=extra_key,
        )
    assert "results" in exc.value.message_dict

    with pytest.raises(ValidationError):
        CheckRun.objects.create(
            kind=CheckRun.Kind.ADOPT,
            status=CheckRun.Status.RUNNING,
            results={"schema_version": 1},
        )

    run = CheckRun.objects.create(
        kind=CheckRun.Kind.ADOPT,
        status=CheckRun.Status.RUNNING,
        results=_adopt_results(site_id=42, temp_name="blog-adopt-deadbeef.example.com",
                               stage="temp_dns"),
    )
    run.refresh_from_db()
    assert set(run.results) == _ADOPT_RESULT_KEYS
    assert run.results["site_id"] == 42


def test_checkrun_has_no_site_fk():
    """site_id lives in results JSON. A Site FK would be a second identity.

    What would make this fail: adding site = ForeignKey(Site) on CheckRun,
    which 0010 is forbidden from shipping and which would force every drill
    kind to name a Site.
    """
    from django.db.models.fields.related import ForeignKey, ManyToOneRel

    from core.models import CheckRun, Site

    related = {
        field.related_model
        for field in CheckRun._meta.get_fields()
        if isinstance(field, (ForeignKey, ManyToOneRel)) and field.related_model is not None
    }
    assert Site not in related
    assert not any(field.name == "site" for field in CheckRun._meta.fields)
