"""Per-site deploy_policy auto|confirm|windowed (PIPE-N8-DEPLOY-POLICY)."""
import pytest

from core.models import AuditEvent, Project, Site
from deploys.models import Deployment, Manifest

pytestmark = pytest.mark.django_db

OLD_SHA = "aaa111old"
NEW_SHA = "bbb222new"


def _git_site(*, slug, policy, cron=""):
    project = Project.objects.create(
        name=slug,
        slug=f"p-{slug}",
        git_url="https://github.com/o/r.git",
        git_ref="main",
    )
    site = Site.objects.create(
        project=project,
        name=slug,
        deploy_policy=policy,
        deploy_window_cron=cron,
    )
    manifest = Manifest.objects.create(
        site=site, version=1, body={"git_sha": OLD_SHA, "keep": "yes"},
    )
    Deployment.objects.create(
        manifest=manifest, status=Deployment.Status.SUCCEEDED,
    )
    return site


def _patch_delay(monkeypatch):
    from deploys.tasks import run_deploy

    queued = []
    monkeypatch.setattr(run_deploy, "delay", lambda pk: queued.append(pk))
    return queued


@pytest.mark.req("PIPE-N8-DEPLOY-POLICY")
def test_confirm_does_not_auto_deploy(monkeypatch):
    """confirm records that an operator must act; it does not delay run_deploy.

    What would make this fail: treating confirm like auto, or creating a queued
    row that a worker would pick up.
    """
    from deploys.poller import poll

    queued = _patch_delay(monkeypatch)
    site = _git_site(slug="confirm", policy=Site.DeployPolicy.CONFIRM)

    poll(ls_remote=lambda url, ref: NEW_SHA)

    assert queued == []
    assert Deployment.objects.filter(manifest__site=site).count() == 1
    assert AuditEvent.objects.filter(action="deploy-confirm-required").exists()


@pytest.mark.req("PIPE-N8-DEPLOY-POLICY")
def test_windowed_outside_window_queues_waiting_notice(monkeypatch):
    """Outside the cron window a waiting notice is recorded and run_deploy is not delayed.

    What would make this fail: delaying anyway, or swallowing the new head with
    no deploy-waiting AuditEvent.
    """
    from deploys.poller import poll

    queued = _patch_delay(monkeypatch)
    _git_site(
        slug="window-out",
        policy=Site.DeployPolicy.WINDOWED,
        cron="0 9 * * 1-5",
    )

    poll(ls_remote=lambda url, ref: NEW_SHA, in_window=lambda cron, now: False)

    assert queued == []
    assert AuditEvent.objects.filter(action="deploy-waiting").exists()


@pytest.mark.req("PIPE-N8-DEPLOY-POLICY")
def test_auto_inside_window_enqueues(monkeypatch):
    """windowed policy inside the cron window behaves like auto: delay run_deploy.

    What would make this fail: refusing to enqueue when in_window is true, or
    copying the outside-window waiting path.
    """
    from deploys.poller import poll

    queued = _patch_delay(monkeypatch)
    _git_site(
        slug="window-in",
        policy=Site.DeployPolicy.WINDOWED,
        cron="* * * * *",
    )

    poll(ls_remote=lambda url, ref: NEW_SHA, in_window=lambda cron, now: True)

    assert len(queued) == 1
    created = Deployment.objects.get(pk=queued[0])
    assert created.status == Deployment.Status.QUEUED
    assert created.manifest.body["git_sha"] == NEW_SHA
    assert not AuditEvent.objects.filter(action="deploy-waiting").exists()
