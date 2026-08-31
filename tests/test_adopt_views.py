"""Live Site adopt HTTP (recommended-next-sequence Wave 2).

POST /api/v1/sites/{id}/adopt/ queues adopt_flow / cleanup. Celery args are
IDs plus an optional path. CheckRun.results stay the closed S2 schema.
"""
from __future__ import annotations

import pytest
from dns_fixtures import default_dns_zone

from core.models import CheckRun, Project, Site, Target
from deploys.models import Manifest

pytestmark = pytest.mark.django_db

ADOPT_KEYS = frozenset(
    {"schema_version", "site_id", "temp_name", "stage", "started_at"}
)
SENTINEL = "super-secret-adopt-token-do-not-leak"


@pytest.fixture
def auth_client(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return client


def _plant_account():
    zone = default_dns_zone()
    account = zone.account
    account.dns_token_ref = "dns-ref-adopt"
    account.origin_ca_key_ref = "oca-ref-adopt"
    account.save(update_fields=["dns_token_ref", "origin_ca_key_ref"])
    return zone


def _target(host="adopt-host.example.com"):
    from core.models import NetworkZone

    net, _ = NetworkZone.objects.get_or_create(name="adopt-net", slug="adopt-net")
    return Target.objects.create(zone=net, host=host)


def _site(*, mesh=False, plant=True, target=True):
    project = Project.objects.create(
        name="adopt-api", slug="adopt-api",
        source_kind=Project.Source.LOCAL_PATH, local_path="/tmp/adopt-api",
    )
    kwargs = {
        "project": project,
        "name": "shop",
        "primary_target": _target() if target else None,
        "proxied": True,
        "exposure": Site.Exposure.MESH_ONLY if mesh else Site.Exposure.PUBLIC,
    }
    if not mesh:
        kwargs["domain"] = "shop.example.com"
        kwargs["dns_zone"] = _plant_account() if plant else default_dns_zone()
    site = Site.objects.create(**kwargs)
    Manifest.objects.create(
        site=site, version=1,
        body={"git_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"},
    )
    return site


def _url(site):
    return f"/api/v1/sites/{site.pk}/adopt/"


def _queued(monkeypatch):
    calls = []

    def delay(*args):
        calls.append(args)
        return None

    monkeypatch.setattr("deploys.tasks.run_adopt.delay", delay)
    monkeypatch.setattr("deploys.tasks.cancel_adopt.delay", delay)
    return calls


def test_anonymous_start_is_rejected(client):
    site = _site()
    response = client.post(_url(site), {}, content_type="application/json")
    assert response.status_code in (401, 403)


def test_unknown_site_is_404(auth_client, monkeypatch):
    _queued(monkeypatch)
    response = auth_client.post("/api/v1/sites/99999/adopt/", {}, content_type="application/json")
    assert response.status_code == 404


def test_unknown_fields_and_conflict_are_400(auth_client, monkeypatch):
    _queued(monkeypatch)
    site = _site()
    extra = auth_client.post(
        _url(site), {"token": SENTINEL}, content_type="application/json",
    )
    assert extra.status_code == 400
    both = auth_client.post(
        _url(site),
        {"cancel": True, "live_compose_path": "/x.yml"},
        content_type="application/json",
    )
    assert both.status_code == 400
    assert SENTINEL not in extra.content.decode()


def test_start_returns_202_with_ids_and_queues_once(auth_client, monkeypatch):
    calls = _queued(monkeypatch)
    site = _site()
    response = auth_client.post(
        _url(site),
        {"live_compose_path": "/explicit/compose.yml"},
        content_type="application/json",
    )
    assert response.status_code == 202, response.content
    body = response.json()
    assert body["queued"] is True
    assert body["site_id"] == site.pk
    assert body["checkrun_id"]
    assert SENTINEL not in str(body)
    assert "token" not in body
    run = CheckRun.objects.get(pk=body["checkrun_id"])
    assert set(run.results) == ADOPT_KEYS
    assert calls[0][:3] == (site.pk, run.pk, "/explicit/compose.yml")
    assert calls[0][3]["sig"]


def test_duplicate_start_does_not_queue_again(auth_client, monkeypatch):
    calls = _queued(monkeypatch)
    site = _site()
    first = auth_client.post(_url(site), {}, content_type="application/json")
    second = auth_client.post(_url(site), {}, content_type="application/json")
    assert first.status_code == 202
    assert second.status_code == 200
    assert second.json()["checkrun_id"] == first.json()["checkrun_id"]
    assert second.json()["queued"] is False
    assert len(calls) == 1


def test_cancel_before_flip_queues_cleanup(auth_client, monkeypatch):
    calls = _queued(monkeypatch)
    site = _site()
    start = auth_client.post(_url(site), {}, content_type="application/json")
    run = CheckRun.objects.get(pk=start.json()["checkrun_id"])
    run.results = {
        "schema_version": 1,
        "site_id": site.pk,
        "temp_name": "shop-adopt-abcd1234.example.com",
        "stage": "verify",
        "started_at": run.results["started_at"],
    }
    run.save(update_fields=["results"])
    calls.clear()
    response = auth_client.post(
        _url(site), {"cancel": True}, content_type="application/json",
    )
    assert response.status_code == 202, response.content
    assert calls[0][:2] == (site.pk, run.pk)
    assert calls[0][2]["sig"]


def test_cancel_after_flip_is_409(auth_client, monkeypatch):
    _queued(monkeypatch)
    site = _site()
    start = auth_client.post(_url(site), {}, content_type="application/json")
    run = CheckRun.objects.get(pk=start.json()["checkrun_id"])
    run.results = {
        "schema_version": 1,
        "site_id": site.pk,
        "temp_name": "shop-adopt-abcd1234.example.com",
        "stage": "flip",
        "started_at": run.results["started_at"],
    }
    run.save(update_fields=["results"])
    response = auth_client.post(
        _url(site), {"cancel": True}, content_type="application/json",
    )
    assert response.status_code == 409
    assert "rollback" in response.json()["detail"]


def test_missing_primary_target_is_409(auth_client, monkeypatch):
    _queued(monkeypatch)
    site = _site(target=False)
    response = auth_client.post(_url(site), {}, content_type="application/json")
    assert response.status_code == 409
    assert CheckRun.objects.filter(kind=CheckRun.Kind.ADOPT).count() == 0


def test_missing_dns_token_is_503(auth_client, monkeypatch):
    _queued(monkeypatch)
    site = _site(plant=False)
    response = auth_client.post(_url(site), {}, content_type="application/json")
    assert response.status_code == 503
    assert "dns_token_ref" in response.json()["detail"]
    assert CheckRun.objects.filter(kind=CheckRun.Kind.ADOPT).count() == 0


def test_mesh_only_start_does_not_require_dns(auth_client, monkeypatch):
    calls = _queued(monkeypatch)
    site = _site(mesh=True)
    response = auth_client.post(_url(site), {}, content_type="application/json")
    assert response.status_code == 202, response.content
    assert calls[0][0] == site.pk


def test_project_row_emits_adopt_state(auth_client, monkeypatch):
    _queued(monkeypatch)
    site = _site()
    before = auth_client.get("/api/v1/projects/").json()
    row = next(p for p in before if p["slug"] == "adopt-api")["sites"][0]
    assert not row.get("adopt")
    auth_client.post(_url(site), {}, content_type="application/json")
    after = auth_client.get("/api/v1/projects/").json()
    row = next(p for p in after if p["slug"] == "adopt-api")["sites"][0]
    assert row["adopt"]["checkrun_id"]
    assert row["adopt"]["status"] == CheckRun.Status.RUNNING


def test_celery_args_are_ids_only():
    import ast
    from pathlib import Path

    source = Path("deploys/tasks.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name in {"run_adopt", "cancel_adopt"}:
            names = [a.arg for a in node.args.args]
            assert "site_id" in names
            assert "checkrun_id" in names
            assert "token" not in names
            assert "plaintext" not in names
