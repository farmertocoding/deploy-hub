"""Deployment liveness sweep (§C1).

Running pipeline tasks stamp Deployment.last_heartbeat (~30s cadence while a
step is in flight). This module notices death: a running row whose heartbeat
is older than 2 minutes is claimed (heartbeat stamped) then resumed, finalized
as succeeded when every step is done, or aborted when a failed step remains.
"""
from datetime import timedelta

from django.db.models import Q
from django.utils import timezone

from deploys.models import Deployment, DeploymentStep
from deploys.pipeline import release_deploy_locks, resume_step, touch_heartbeat

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
        deployment = Deployment.objects.select_related("manifest__site").get(pk=pk)
        pointer = resume_step(deployment)
        if pointer is None:
            deployment.status = Deployment.Status.SUCCEEDED
            deployment.save(update_fields=["status"])
            release_deploy_locks(deployment)
            continue
        if pointer.status == DeploymentStep.Status.FAILED:
            deployment.status = Deployment.Status.FAILED
            deployment.save(update_fields=["status"])
            release_deploy_locks(deployment)
            aborted.append(pk)
            continue
        touch_heartbeat(deployment)
        from deploys.tasks import run_deploy

        run_deploy.delay(pk)
        resumed.append(pk)
    return {"resumed": resumed, "aborted": aborted}
