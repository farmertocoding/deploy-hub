"""Pipeline Celery tasks.

`run_deploy` and `sweep_stale_deployments` stay on the default `deploys`
queue. `poll_git` is routed to `probes` (git polling is not a pipeline worker).

Kwargs are ids only. Env bundle bytes stay inside vault.service.get / the
worker process; they never enter the broker payload.
"""
from celery import shared_task


@shared_task
def run_deploy(deployment_id):
    from deploys.pipeline import execute

    return execute(deployment_id)


@shared_task
def sweep_stale_deployments():
    from deploys.heartbeat import sweep

    return sweep()


@shared_task
def poll_git():
    """Beat entry: git polling lives on `probes`, not the deploys worker."""
    from deploys.poller import poll

    return poll()


@shared_task
def reap_adopt_temps():
    """Beat `adopt-temp-reaper`: cleanup adopt temps older than 24 h."""
    from deploys.adopt_reaper import reap

    return reap()


@shared_task
def run_adopt(site_id, checkrun_id, live_compose_path=""):
    """IDs + optional path only. Vault/SSH stay inside the worker."""
    from deploys.adopt_service import execute_adopt

    return execute_adopt(site_id, checkrun_id, live_compose_path or None)


@shared_task
def cancel_adopt(site_id, checkrun_id):
    from deploys.adopt_service import execute_cancel

    return execute_cancel(site_id, checkrun_id)
