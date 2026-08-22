"""sample-site through the real pipeline: twice, zero mutating (T1)."""
from __future__ import annotations

from pathlib import Path

import pytest
from pipeline_fakes import PipelineTransport, queued_deployment

from deploys.models import Deployment, DeploymentStep

REPO = Path(__file__).resolve().parent.parent
SAMPLE_SITE = REPO / "sample-site"

pytestmark = pytest.mark.django_db


def _execute(deployment, transport, dns):
    from deploys.pipeline import execute

    result = execute(deployment.pk, transport=transport, dns=dns)
    deployment.refresh_from_db()
    return result


def _requeue_pending(deployment):
    deployment.status = Deployment.Status.QUEUED
    deployment.save(update_fields=["status"])
    for step in deployment.steps.all():
        step.status = DeploymentStep.Status.PENDING
        step.started = None
        step.finished = None
        step.save(update_fields=["status", "started", "finished"])


def _sample_site_body(slug):
    dockerfile = (SAMPLE_SITE / "Dockerfile").read_text(encoding="utf-8")
    return {
        "git_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "source_dir": str(SAMPLE_SITE),
        "deploy_strategy": "recreate",
        "local_state": True,
        "runtime": "django",
        "domain": f"{slug}.example.test",
        "dns_zone": "example.test",
        "readiness_path": "/healthz.ready",
        "warmup_timeout_s": 5,
        "volumes": [{
            "name": f"site-{slug}-data",
            "container_path": "/data",
            "backup_policy": "directory_sync",
        }],
        "dockerfile_template": dockerfile,
    }


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_t1_deploy_sample_site_twice_zero_mutating():
    """A second execute of the same desired records zero run/put after calls.clear().

    What would make this fail: rebuilding the image, recreating the volume, or
    putting Caddy/runbook bytes again when the target already matches.
    """
    from providers.fakes import FakeDnsProvider

    slug = "sitetwice"
    assert SAMPLE_SITE.is_dir()
    _site, deployment = queued_deployment(slug, body=_sample_site_body(slug))
    transport = PipelineTransport()
    dns = FakeDnsProvider()

    _execute(deployment, transport, dns)
    assert deployment.status == Deployment.Status.SUCCEEDED
    dockerfile = (SAMPLE_SITE / "Dockerfile").read_text(encoding="utf-8")
    assert (
        "pip install --require-hashes" in dockerfile
        or "uv sync --frozen" in dockerfile
        or "npm ci" in dockerfile
    )

    transport.calls.clear()
    _requeue_pending(deployment)
    _execute(deployment, transport, dns)
    assert deployment.status == Deployment.Status.SUCCEEDED
    assert transport.mutating_calls() == []
