"""Deployment liveness sweep (§C1).

Running pipeline tasks stamp Deployment.last_heartbeat (~30s cadence while a
step is in flight). This module notices death: a running row whose heartbeat
is older than 2 minutes is resumed (re-queued at the first pending/running
step) or aborted (status=failed) when nothing remains to resume.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from deploys.models import Deployment, DeploymentStep

STALE_AFTER = timedelta(minutes=2)


def sweep():
    """Act on stale running deployments. Returns {"resumed": [...], "aborted": [...]}."""
    cutoff = timezone.now() - STALE_AFTER
    stale_ids = list(
        Deployment.objects.filter(status=Deployment.Status.RUNNING)
        .filter(Q(last_heartbeat__isnull=True) | Q(last_heartbeat__lt=cutoff))
        .values_list("pk", flat=True)
    )
    resumed, aborted = [], []
    for pk in stale_ids:
        deployment = Deployment.objects.get(pk=pk)
        if _has_step_to_resume(deployment):
            from deploys.tasks import run_deploy

            run_deploy.delay(pk)
            resumed.append(pk)
        else:
            deployment.status = Deployment.Status.FAILED
            deployment.save(update_fields=["status"])
            from deploys.pipeline import release_deploy_locks

            release_deploy_locks(deployment)
            aborted.append(pk)
    return {"resumed": resumed, "aborted": aborted}


def _has_step_to_resume(deployment):
    return deployment.steps.filter(
        status__in=(
            DeploymentStep.Status.PENDING,
            DeploymentStep.Status.RUNNING,
        ),
    ).exists()
