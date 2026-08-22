"""Smallest HTTP for site.rollback → deploys.pipeline.rollback (phase-exit I4)."""
import pytest
from pipeline_fakes import queued_deployment

from deploys.models import Deployment

pytestmark = pytest.mark.django_db

ROLLBACK = "/api/v1/sites/{}/rollback/"


def _enrolled_client(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(
        user=User.objects.get(username="joseph"), name="phone", confirmed=True,
    )
    client.login(username="joseph", password="a-long-dev-password")


def test_site_rollback_http_calls_pipeline_rollback(client, monkeypatch):
    """POST /sites/<id>/rollback/ calls pipeline.rollback(pk) with ids only.

    What would make this fail: inventing a second rollback engine, putting
    secrets in kwargs, or a route that never reaches deploys.pipeline.rollback.
    """
    from deploys import views as deploy_views

    site, original = queued_deployment("rb-http")
    original.status = Deployment.Status.SUCCEEDED
    original.save(update_fields=["status"])
    called = []

    def fake_rollback(deployment_id, **kwargs):
        assert kwargs == {}, f"rollback kwargs must stay empty, got {kwargs}"
        called.append(deployment_id)
        created = Deployment.objects.create(
            manifest=original.manifest,
            status=Deployment.Status.SUCCEEDED,
            rollback_of=original,
        )
        return {"started": True, "status": created.status}

    monkeypatch.setattr(deploy_views, "rollback", fake_rollback)
    _enrolled_client(client)

    response = client.post(ROLLBACK.format(site.pk), content_type="application/json")
    assert response.status_code == 201, response.content
    assert called == [original.pk]
    body = response.json()
    assert body["original_id"] == original.pk
    assert body["deployment_id"] != original.pk


def test_site_rollback_http_refuses_without_a_succeeded_deploy(client):
    """No succeeded row: 409, not a new engine and not a 500."""
    site, queued = queued_deployment("rb-none")
    assert queued.status == Deployment.Status.QUEUED
    _enrolled_client(client)
    response = client.post(ROLLBACK.format(site.pk), content_type="application/json")
    assert response.status_code == 409
    assert Deployment.objects.filter(rollback_of=queued).count() == 0


def test_site_rollback_http_kwargs_are_ids_only():
    """The view source must call rollback with the deployment pk only."""
    import inspect

    from deploys import views

    source = inspect.getsource(views.SiteRollbackView)
    assert "rollback(" in source
    assert "token" not in source.lower()
    assert "secret" not in source.lower()
