"""Heartbeat sweep for running deployments (REL-C1 / REL-P3)."""
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from core.models import NetworkZone, Project, Site, Target
from deploys.models import Deployment, DeploymentStep, Manifest

pytestmark = pytest.mark.django_db

STALE_AFTER = timedelta(minutes=2)


def _running_deployment(*, slug, heartbeat, step_statuses):
    project = Project.objects.create(name="p", slug=f"p-{slug}")
    zone = NetworkZone.objects.create(name="lan", slug=f"lan-{slug}")
    target = Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref="vault-owner-1",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )
    site = Site.objects.create(
        project=project, name=slug, primary_target=target,
    )
    manifest = Manifest.objects.create(site=site, version=1, body={})
    deployment = Deployment.objects.create(
        manifest=manifest,
        status=Deployment.Status.RUNNING,
        last_heartbeat=heartbeat,
    )
    for seq, name in enumerate(DeploymentStep.Name.values, start=1):
        status = step_statuses.get(name, DeploymentStep.Status.PENDING)
        DeploymentStep.objects.create(
            deployment=deployment, seq=seq, name=name, status=status,
        )
    return deployment


def _beat_sweep_task_names():
    return {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}


@pytest.mark.req("REL-C1-HEARTBEAT-SWEEP")
@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_stale_running_is_resumed_or_aborted():
    """Stale last_heartbeat (>2 min): resume if a pending/running step remains, else abort.

    What would make this fail: leaving a stale row running, or aborting one that
    still has a step to resume.
    """
    from deploys.heartbeat import sweep

    assert "deploys.tasks.sweep_stale_deployments" in _beat_sweep_task_names()

    stale_at = timezone.now() - STALE_AFTER - timedelta(seconds=1)
    resumable = _running_deployment(
        slug="stale-resume",
        heartbeat=stale_at,
        step_statuses={
            "build": DeploymentStep.Status.SUCCEEDED,
            "ship": DeploymentStep.Status.PENDING,
        },
    )
    abortable = _running_deployment(
        slug="stale-abort",
        heartbeat=stale_at,
        step_statuses={
            name: DeploymentStep.Status.SUCCEEDED
            for name in DeploymentStep.Name.values
        },
    )

    result = sweep()
    resumable.refresh_from_db()
    abortable.refresh_from_db()

    assert abortable.status == Deployment.Status.FAILED
    assert abortable.pk in result["aborted"]
    assert resumable.pk in result["resumed"]
    # Eager Celery runs the re-queued task inline; remaining no-op steps finish.
    assert resumable.status == Deployment.Status.SUCCEEDED
    assert resumable.steps.get(name="ship").status == DeploymentStep.Status.SUCCEEDED


@pytest.mark.req("REL-C1-HEARTBEAT-SWEEP")
def test_fresh_heartbeat_is_left_alone():
    """A running deploy whose heartbeat is newer than 2 min is not resumed or aborted.

    What would make this fail: sweeping a live worker and finishing (or failing)
    a deploy that is still heartbeating.
    """
    from deploys.heartbeat import sweep

    fresh = _running_deployment(
        slug="fresh",
        heartbeat=timezone.now(),
        step_statuses={"build": DeploymentStep.Status.PENDING},
    )
    result = sweep()
    fresh.refresh_from_db()
    assert fresh.status == Deployment.Status.RUNNING
    assert fresh.steps.get(name="build").status == DeploymentStep.Status.PENDING
    assert fresh.pk not in result["resumed"]
    assert fresh.pk not in result["aborted"]
    assert fresh.steps.filter(status=DeploymentStep.Status.SUCCEEDED).count() == 0
