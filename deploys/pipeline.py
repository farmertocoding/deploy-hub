"""Deployment state machine. Reads Manifest.body only — never scanner.

Lock boundary: OperationLock kind=deploy on the site and the target, holder =
the deployment id. A new deploy while one is running supersedes the old row
before taking the unique (scope, object_id, kind) lock.
"""
import os

from django.utils import timezone

from core import locks
from core.models import OperationLock
from deploys.models import Deployment, DeploymentStep

CRASH_AFTER_ENV = "HUB_TEST_CRASH_AFTER_STEP"


def resume_step(deployment):
    """First step whose status is not succeeded or skipped."""
    done = {DeploymentStep.Status.SUCCEEDED, DeploymentStep.Status.SKIPPED}
    for step in deployment.steps.order_by("seq"):
        if step.status not in done:
            return step
    return None


def persist_steps(deployment):
    """Create all nine named steps in seq order as pending, once."""
    if deployment.steps.exists():
        return
    for seq, name in enumerate(DeploymentStep.Name.values, start=1):
        DeploymentStep.objects.create(
            deployment=deployment,
            seq=seq,
            name=name,
            status=DeploymentStep.Status.PENDING,
        )


def release_deploy_locks(deployment):
    """Drop every deploy lock held by this deployment id."""
    holder = str(deployment.pk)
    rows = list(
        OperationLock.objects.filter(
            kind=OperationLock.Kind.DEPLOY, holder=holder,
        )
    )
    for row in rows:
        locks.release(row.scope, row.object_id, row.kind, holder=holder)


def touch_heartbeat(deployment):
    """Stamp Deployment.last_heartbeat; also touch held OperationLock rows."""
    now = timezone.now()
    Deployment.objects.filter(pk=deployment.pk).update(last_heartbeat=now)
    deployment.last_heartbeat = now
    holder = str(deployment.pk)
    site = deployment.manifest.site
    locks.heartbeat("site", site.pk, "deploy", holder=holder)
    if site.primary_target_id:
        locks.heartbeat("target", site.primary_target_id, "deploy", holder=holder)


def load_env_snapshot(deployment):
    """Decrypt the manifest env bundle via vault. Caller must not persist the bytes."""
    ref = (deployment.manifest.body or {}).get("env_bundle_ref")
    if not ref:
        return None
    from vault import service as vault_service
    from vault.models import Secret

    secret = Secret.objects.get(pk=ref)
    return vault_service.get(secret, reason=f"deploy {deployment.pk}")


def begin_deploy(deployment):
    """Acquire site+target deploy locks, persist steps, set running.

    Returns False (and does not start) if a lock cannot be taken.
    """
    site = deployment.manifest.site
    target = site.primary_target
    if target is None:
        return False

    _supersede_running(site, except_pk=deployment.pk)

    holder = str(deployment.pk)
    site_lock = locks.acquire("site", site.pk, "deploy", holder)
    if site_lock is None:
        return False
    target_lock = locks.acquire("target", target.pk, "deploy", holder)
    if target_lock is None:
        locks.release("site", site.pk, "deploy", holder=holder)
        return False

    persist_steps(deployment)
    deployment.status = Deployment.Status.RUNNING
    deployment.last_heartbeat = timezone.now()
    deployment.save(update_fields=["status", "last_heartbeat"])
    return True


def execute(deployment_id):
    """Run (or resume) a deployment. Task kwargs must stay ids-only."""
    deployment = Deployment.objects.select_related(
        "manifest__site__primary_target",
    ).get(pk=deployment_id)
    if deployment.status == Deployment.Status.QUEUED:
        if not begin_deploy(deployment):
            return {"started": False}
        deployment.refresh_from_db()
    if deployment.status != Deployment.Status.RUNNING:
        return {"started": False, "status": deployment.status}

    load_env_snapshot(deployment)
    touch_heartbeat(deployment)

    for step in deployment.steps.order_by("seq"):
        if step.status in (
            DeploymentStep.Status.SUCCEEDED,
            DeploymentStep.Status.SKIPPED,
        ):
            continue
        _run_step(deployment, step)

    deployment.status = Deployment.Status.SUCCEEDED
    deployment.save(update_fields=["status"])
    release_deploy_locks(deployment)
    return {"started": True, "status": Deployment.Status.SUCCEEDED}


def _supersede_running(site, *, except_pk):
    others = Deployment.objects.filter(
        manifest__site=site,
        status=Deployment.Status.RUNNING,
    ).exclude(pk=except_pk)
    for old in others:
        old.status = Deployment.Status.SUPERSEDED
        old.save(update_fields=["status"])
        release_deploy_locks(old)


def _run_step(deployment, step):
    step.status = DeploymentStep.Status.RUNNING
    step.started = timezone.now()
    step.save(update_fields=["status", "started"])
    touch_heartbeat(deployment)
    _crash_if_configured(step)
    # Skeleton: no docker / SSH. Task 9 lands ensure_build / ensure_ship.
    step.status = DeploymentStep.Status.SUCCEEDED
    step.finished = timezone.now()
    step.save(update_fields=["status", "finished"])
    touch_heartbeat(deployment)


def _crash_if_configured(step):
    """Kill-matrix hook. Task 13 parametrizes HUB_TEST_CRASH_AFTER_STEP."""
    flag = os.environ.get(CRASH_AFTER_ENV, "")
    if not flag:
        return
    if flag == step.name or flag == str(step.seq):
        raise RuntimeError(f"{CRASH_AFTER_ENV}={flag}")
