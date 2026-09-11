"""Pipeline Celery tasks.

`run_deploy` and `sweep_stale_deployments` stay on the default `deploys`
queue. `poll_git` is routed to `control` so probes never hold the envelope
secret used to enqueue deploys.

Kwargs are ids only. Env bundle bytes stay inside vault.service.get / the
worker process; they never enter the broker payload.
"""
from celery import shared_task


def envelope_for_deploy(deployment_id):
    from core.task_envelope import wrap
    from deploys.models import Deployment

    dep = Deployment.objects.select_related("manifest__site__project").get(
        pk=deployment_id,
    )
    return wrap(
        task="deploys.tasks.run_deploy",
        workspace_id=dep.manifest.site.project.workspace_id,
        resource_type="Deployment",
        resource_id=deployment_id,
    )


def enqueue_run_deploy(deployment_id):
    run_deploy.delay(deployment_id, envelope_for_deploy(deployment_id))


def envelope_for_adopt(site_id, task):
    from core.models import Site
    from core.task_envelope import wrap

    site = Site.objects.select_related("project").get(pk=site_id)
    return wrap(
        task=task,
        workspace_id=site.project.workspace_id,
        resource_type="Site",
        resource_id=site_id,
    )


@shared_task
def run_deploy(deployment_id, envelope=None):
    from core.task_envelope import EnvelopeError, reauthorize
    from deploys.models import Deployment
    from deploys.pipeline import execute

    if envelope is None:
        return {"ok": False, "reason": "envelope"}
    dep = Deployment.objects.select_related("manifest__site__project").get(
        pk=deployment_id,
    )
    try:
        reauthorize(
            envelope,
            resource=dep,
            task="deploys.tasks.run_deploy",
            resource_id=str(deployment_id),
        )
    except EnvelopeError:
        return {"ok": False, "reason": "envelope"}
    return execute(deployment_id)


@shared_task
def sweep_stale_deployments():
    from deploys.heartbeat import sweep

    return sweep()


def envelope_for_poll_git():
    from core.task_envelope import wrap

    return wrap(
        task="deploys.tasks.poll_git",
        workspace_id=0,
        resource_type="fleet",
        resource_id="poll-git",
    )


@shared_task
def dispatch_poll_git():
    """Beat entry: sign, then poll. Unsigned ``poll_git`` is refused."""
    return poll_git(envelope=envelope_for_poll_git())


@shared_task
def poll_git(envelope=None):
    """Git polling lives on `control` so it can sign run_deploy."""
    from core.task_envelope import EnvelopeError, reauthorize
    from deploys.poller import poll

    if envelope is None:
        return {"ok": False, "reason": "envelope"}
    try:
        reauthorize(
            envelope,
            task="deploys.tasks.poll_git",
            resource_id="poll-git",
        )
    except EnvelopeError:
        return {"ok": False, "reason": "envelope"}
    return poll()


@shared_task
def reap_adopt_temps():
    """Beat `adopt-temp-reaper`: cleanup adopt temps older than 24 h."""
    from deploys.adopt_reaper import reap

    return reap()


@shared_task
def run_adopt(site_id, checkrun_id, live_compose_path="", envelope=None):
    """IDs + optional path only. Vault/SSH stay inside the worker."""
    from core.models import Site
    from core.task_envelope import EnvelopeError, reauthorize
    from deploys.adopt_service import execute_adopt

    if envelope is None:
        return {"ok": False, "reason": "envelope"}
    site = Site.objects.select_related("project").get(pk=site_id)
    try:
        reauthorize(
            envelope,
            resource=site,
            task="deploys.tasks.run_adopt",
            resource_id=str(site_id),
        )
    except EnvelopeError:
        return {"ok": False, "reason": "envelope"}
    return execute_adopt(site_id, checkrun_id, live_compose_path or None)


@shared_task
def cancel_adopt(site_id, checkrun_id, envelope=None):
    from core.models import Site
    from core.task_envelope import EnvelopeError, reauthorize
    from deploys.adopt_service import execute_cancel

    if envelope is None:
        return {"ok": False, "reason": "envelope"}
    site = Site.objects.select_related("project").get(pk=site_id)
    try:
        reauthorize(
            envelope,
            resource=site,
            task="deploys.tasks.cancel_adopt",
            resource_id=str(site_id),
        )
    except EnvelopeError:
        return {"ok": False, "reason": "envelope"}
    return execute_cancel(site_id, checkrun_id)
