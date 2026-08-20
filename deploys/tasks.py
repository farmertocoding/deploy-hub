"""Pipeline Celery tasks. Queue is the default `deploys` — not probes.

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
