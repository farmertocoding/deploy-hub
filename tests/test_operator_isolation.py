"""Operator /api/v1/* is workspace-scoped. HUD isolation is not the only choke.

What would make these fail: get_object_or_404(Model, pk=pk) on a fleet object,
or a mutation that ignores ACTION_CAPABILITY / RequireRecentTouch.
"""
import json

import pytest
from django.test import RequestFactory

from core.models import (
    DnsAccount,
    Finding,
    NetworkZone,
    Partner,
    Project,
    Site,
    Target,
    Workspace,
    WorkspaceMembership,
)

pytestmark = pytest.mark.django_db


def _user(django_user_model, username, *, staff=False):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(
        username=username, password="pw-1234567890", is_staff=staff,
    )
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    return user


def _workspace(slug):
    return Workspace.objects.create(name=slug.title(), slug=slug)


def _membership(workspace, user, role):
    return WorkspaceMembership.objects.create(
        workspace=workspace, user=user, role=role,
    )


def _fleet(workspace, prefix):
    zone = NetworkZone.objects.create(
        workspace=workspace, name=f"{prefix}-net", slug=f"{prefix}-net",
    )
    target = Target.objects.create(
        zone=zone, host=f"{prefix}.example.test", status="ready",
    )
    project = Project.objects.create(
        workspace=workspace, name=f"{prefix}-app", slug=f"{prefix}-app",
    )
    site = Site.objects.create(
        project=project, name=f"{prefix}-site", exposure="mesh_only",
        primary_target=target,
    )
    finding = Finding.objects.create(
        workspace=workspace, source_engine="test", severity="p1",
        entity=f"{prefix}-site", title=f"{prefix} finding",
        body="why", fix_action="fix", fingerprint=f"{prefix}-finding",
    )
    partner = Partner.objects.create(
        workspace=workspace, name=f"{prefix} partner", slug=f"{prefix}-partner",
    )
    account = DnsAccount.objects.create(
        workspace=workspace, provider="cloudflare", label=f"{prefix}-dns",
    )
    return {
        "zone": zone, "target": target, "project": project, "site": site,
        "finding": finding, "partner": partner, "account": account,
    }


@pytest.fixture
def split(client, django_user_model):
    user = _user(django_user_model, "split-op")
    alpha = _workspace("alpha")
    beta = _workspace("beta")
    _membership(alpha, user, "owner")
    _membership(beta, user, "viewer")
    client.force_login(user)
    return {
        "user": user,
        "alpha": alpha,
        "beta": beta,
        "a": _fleet(alpha, "alpha"),
        "b": _fleet(beta, "beta"),
    }


def _headers(slug):
    return {"HTTP_X_WORKSPACE": slug}


def test_operator_lists_do_not_leak_the_other_workspace(client, split):
    a, b = split["a"], split["b"]
    projects = client.get("/api/v1/projects/", **_headers("alpha")).json()
    names = {row["name"] for row in projects}
    assert a["project"].name in names
    assert b["project"].name not in names

    targets = client.get("/api/v1/targets/", **_headers("alpha")).json()
    hosts = {row["host"] for row in targets}
    assert a["target"].host in hosts
    assert b["target"].host not in hosts

    findings = client.get("/api/v1/findings/", **_headers("alpha")).json()["data"]
    titles = {row["title"] for row in findings}
    assert a["finding"].title in titles
    assert b["finding"].title not in titles

    partners = client.get("/api/v1/partners/", **_headers("alpha")).json()["partners"]
    slugs = {row["slug"] for row in partners}
    assert a["partner"].slug in slugs
    assert b["partner"].slug not in slugs


def test_operator_object_routes_404_across_workspaces(client, split):
    b = split["b"]
    headers = _headers("alpha")
    assert client.get(f"/api/v1/sites/{b['site'].pk}/wizard/", **headers).status_code == 404
    assert client.get(f"/api/v1/sites/{b['site'].pk}/env/", **headers).status_code == 404
    assert client.get(f"/api/v1/findings/{b['finding'].pk}/", **headers).status_code == 404
    assert client.get(f"/api/v1/partners/{b['partner'].pk}/", **headers).status_code == 404
    assert client.get(f"/api/v1/targets/{b['target'].pk}/", **headers).status_code == 404
    readiness = f"/api/v1/projects/{b['project'].pk}/readiness/"
    assert client.get(readiness, **headers).status_code == 404


def test_operator_mutations_404_or_403_on_foreign_and_viewer_workspace(client, split):
    from tests.conftest import t1_ready_session

    b = split["b"]
    t1_ready_session(client, split["user"])
    payload = json.dumps({"env": {"X": "1"}})
    foreign = client.put(
        f"/api/v1/sites/{b['site'].pk}/env/",
        data=payload, content_type="application/json", **_headers("alpha"),
    )
    assert foreign.status_code == 404, foreign.content
    viewer = client.put(
        f"/api/v1/sites/{b['site'].pk}/env/",
        data=payload, content_type="application/json", **_headers("beta"),
    )
    assert viewer.status_code == 403, viewer.content

    delete = client.post(
        f"/api/v1/targets/{b['target'].pk}/delete/",
        data=json.dumps({"confirm_name": b["target"].host}),
        content_type="application/json",
        **_headers("beta"),
    )
    assert delete.status_code == 403, delete.content
    assert Target.objects.filter(pk=b["target"].pk).exists()

    plant = client.post(
        f"/api/v1/dns-accounts/{b['account'].pk}/origin-ca-plant/",
        data=json.dumps({"path": "/etc/deploy-hub/origin-ca/x"}),
        content_type="application/json",
        **_headers("alpha"),
    )
    assert plant.status_code == 404, plant.content


def test_map_snapshot_is_workspace_scoped(client, split):
    body = client.get("/api/v1/map/", **_headers("alpha")).json()["data"]
    labels = {node["label"] for node in body["nodes"]}
    assert split["a"]["target"].host in labels
    assert split["b"]["target"].host not in labels


def test_wizard_project_create_does_not_fall_back_to_default(client, split):
    r = client.post(
        "/api/v1/projects/",
        data=json.dumps({
            "name": "nope",
            "slug": "nope",
            "local_path": "/tmp/nope",
        }),
        content_type="application/json",
        **_headers("beta"),
    )
    assert r.status_code == 403, r.content
    assert not Project.objects.filter(slug="nope").exists()


def test_kill_switch_does_not_toggle_on_retry(client, django_user_model):
    from core.partner_views import partner_api_enabled, set_partner_api_enabled
    from tests.conftest import t1_ready_session

    user = django_user_model.objects.create_superuser(
        "owner-ks", password="pw-1234567890",
    )
    from django_otp.plugins.otp_totp.models import TOTPDevice
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    t1_ready_session(client, user)
    set_partner_api_enabled(False)
    url = "/api/v1/partner-api/kill-switch/"
    enable = client.post(
        url, data=json.dumps({"confirm_name": "partner-api", "enabled": True}),
        content_type="application/json",
    )
    assert enable.status_code == 200, enable.content
    assert partner_api_enabled() is True
    again = client.post(
        url, data=json.dumps({"confirm_name": "partner-api", "enabled": True}),
        content_type="application/json",
    )
    assert again.status_code == 409, again.content
    assert partner_api_enabled() is True
    disable = client.post(
        url, data=json.dumps({"confirm_name": "partner-api", "enabled": False}),
        content_type="application/json",
    )
    assert disable.status_code == 200, disable.content
    retry_disable = client.post(
        url, data=json.dumps({"confirm_name": "partner-api", "enabled": False}),
        content_type="application/json",
    )
    assert retry_disable.status_code == 409, retry_disable.content
    assert partner_api_enabled() is False
    set_partner_api_enabled(False)


def test_refuse_cap_fails_closed_on_unmapped_action(django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.hud.common import refuse_cap

    user = django_user_model.objects.create_superuser(
        "cap", password="pw-1234567890",
    )
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    factory = RequestFactory()
    request = factory.post("/api/v1/hud/targets/commands/")
    request.user = user
    denied = refuse_cap(request, "not.a.real.action")
    assert denied is not None
    assert denied.status_code == 403


def test_saved_dns_account_workspace_fk_points_at_a_real_row():
    from core.models import Workspace, default_workspace, default_workspace_id

    default_workspace()
    pk = default_workspace_id()
    assert Workspace.objects.filter(pk=pk, slug="default").exists()
    DnsAccount.objects.create(provider="cloudflare", label="fk-check")
    row = DnsAccount.objects.get(label="fk-check")
    assert row.workspace_id == pk
    assert Workspace.objects.filter(pk=row.workspace_id).exists()


def test_default_workspace_is_pk_1_after_sqlite_sequence_advances():
    """Field defaults are the constant 1, not whatever slug=default got.

    mutmut runs a second in-process pytest session against a flushed SQLite
    file whose autoincrement is already past 1. get_or_create(slug="default")
    then inserts pk=N, Project.workspace_id stays 1, and audit() DoesNotExist.

    What would make this fail: default_workspace() keying only on slug.
    """
    from django.db import connection

    from core.models import default_workspace, default_workspace_id

    Workspace.objects.all().delete()
    other = Workspace.objects.create(slug="not-default", name="other")
    Workspace.objects.filter(pk=other.pk).delete()
    if connection.vendor == "sqlite":
        with connection.cursor() as cursor:
            cursor.execute("DELETE FROM sqlite_sequence WHERE name = %s", ["core_workspace"])
            cursor.execute(
                "INSERT INTO sqlite_sequence (name, seq) VALUES (%s, %s)",
                ["core_workspace", 40],
            )

    workspace = default_workspace()
    assert workspace.pk == default_workspace_id() == 1
    project = Project.objects.create(name="seq-adv", slug="seq-adv")
    assert project.workspace_id == 1
    assert project.workspace.pk == 1
    from core.audit import audit

    audit("wizard_answers_saved", project, source="api")
