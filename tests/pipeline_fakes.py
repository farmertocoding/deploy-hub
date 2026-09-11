"""T1 fixtures for the full pipeline. Does not change FakeTransport.

PipelineTransport itself lives in deploys/testing.py (2.5 panel I2): the
`--fake` worker child is product code and may not import from tests/, so the
double moved next to its product consumer and is re-exported here for the
suite's existing imports.
"""
from __future__ import annotations

from pathlib import Path

from deploys.testing import READY_JSON, PipelineTransport

__all__ = [
    "GIT_SHA",
    "NPM_CI_DOCKERFILE",
    "READY_JSON",
    "REPO",
    "SAMPLE_NODE_SITE",
    "PipelineTransport",
    "fixture_body",
    "queued_deployment",
]

REPO = Path(__file__).resolve().parent.parent
SAMPLE_NODE_SITE = REPO / "sample-node-site"
GIT_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

NPM_CI_DOCKERFILE = (
    "FROM node:22-alpine\n"
    "WORKDIR /app\n"
    "COPY package.json package-lock.json* ./\n"
    "RUN npm ci\n"
    "COPY . .\n"
    'CMD ["node", "app.js"]\n'
)


def fixture_body(slug, *, extra=None):
    body = {
        "git_sha": GIT_SHA,
        "source_dir": str(SAMPLE_NODE_SITE),
        "deploy_strategy": "recreate",
        "local_state": True,
        "runtime": "node",
        "domain": f"{slug}.example.test",
        "dns_zone": "example.test",
        "readiness_path": "/healthz.ready",
        "warmup_timeout_s": 5,
        "volumes": [{
            "name": f"site-{slug}-data",
            "container_path": "/data",
            "backup_policy": "directory_sync",
        }],
        "dockerfile_template": NPM_CI_DOCKERFILE,
    }
    if extra:
        body.update(extra)
    return body


def queued_deployment(slug, *, body=None):
    from dns_fixtures import default_dns_zone

    from core.models import NetworkZone, Project, Site, Target
    from deploys.models import Deployment, Manifest

    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    zone = NetworkZone.objects.create(name="lan", slug=f"lan-{slug}")
    target = Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref=f"vault-{slug}",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )
    site = Site.objects.create(
        project=project,
        name=slug,
        domain=f"{slug}.example.test",
        primary_target=target,
        dns_zone=default_dns_zone("example.test"),
        deploy_strategy=Site.DeployStrategy.RECREATE,
    )
    manifest = Manifest.objects.create(
        site=site,
        version=1,
        body=body if body is not None else fixture_body(slug),
    )
    return site, Deployment.objects.create(manifest=manifest)
