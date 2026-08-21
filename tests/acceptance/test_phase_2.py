"""Phase 2 acceptance — each test is a literal transcription of one milestone clause
(review3 §Q4). check.py --phase 2 requires these green (or a WAIVERS.md line).

The Phase 2 milestone (design note §4): deploy sample-node-site through the real
pipeline to hub-test-target, twice, with resume-from-crash and rollback; volumes
survive. These tests transcribe the MUST clauses against FakeTransport / T1 so
the gate is executable on every push without docker. The T2 live path
(`tests/test_pipeline_sample_node_site.py::test_t2_execute_sample_node_site_twice`)
and the TAKKO real-world half are the demo record under conformance/demos/phase-2/.
"""
import subprocess

import pytest
from pipeline_fakes import (
    NPM_CI_DOCKERFILE,
    SAMPLE_NODE_SITE,
    PipelineTransport,
    fixture_body,
    queued_deployment,
)
from test_git_poller import TRIGGER_PATHS, WEBHOOK_NEEDLES, _route_strings

from core.models import Site
from deploys.models import Deployment, DeploymentArtifact, DeploymentStep
from deploys.pipeline import CRASH_AFTER_ENV, execute, rollback
from providers.fakes import FakeDnsProvider

pytestmark = [pytest.mark.acceptance(phase=2), pytest.mark.django_db]


def _run(deployment, transport, dns):
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


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.req("PIPE-N1-DEPLOY-STRATEGY")
def test_sample_node_site_deploys_to_hub_test_target():
    """T1 transcription of the MUST-demo first deploy: sample-node-site through
    execute() against FakeTransport (the T1 fixture). T2 — real SshTransport to
    hub-test-target — is the demo record, not this test body.
    """
    slug = "p2-first"
    _site, deployment = queued_deployment(slug, body=fixture_body(slug))
    transport = PipelineTransport()
    result = _run(deployment, transport, FakeDnsProvider())
    assert deployment.status == Deployment.Status.SUCCEEDED, result
    assert SAMPLE_NODE_SITE.is_dir()
    assert "npm ci" in NPM_CI_DOCKERFILE
    assert _site.deploy_strategy == Site.DeployStrategy.RECREATE


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_second_deploy_zero_mutating_calls():
    """A second execute of the same desired records zero run/put after calls.clear().

    What would make this fail: rebuilding the image, recreating the volume, or
    putting Caddy/runbook bytes again when the target already matches.
    """
    slug = "p2-twice"
    _site, deployment = queued_deployment(slug, body=fixture_body(slug))
    transport = PipelineTransport()
    dns = FakeDnsProvider()

    _run(deployment, transport, dns)
    assert deployment.status == Deployment.Status.SUCCEEDED

    transport.calls.clear()
    _requeue_pending(deployment)
    _run(deployment, transport, dns)
    assert deployment.status == Deployment.Status.SUCCEEDED
    assert transport.mutating_calls() == []


@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_resume_from_crash(monkeypatch):
    """HUB_TEST_CRASH_AFTER_STEP raises after ensure_*; a second execute resumes.

    What would make this fail: crashing before the step's ensure_*, marking
    that step succeeded, or the resume leaving the deployment short of succeeded.
    """
    slug = "p2-crash"
    _site, deployment = queued_deployment(slug, body=fixture_body(slug))
    transport = PipelineTransport()
    dns = FakeDnsProvider()

    monkeypatch.setenv(CRASH_AFTER_ENV, "4")
    with pytest.raises(RuntimeError, match=CRASH_AFTER_ENV):
        execute(deployment.pk, transport=transport, dns=dns)

    deployment.refresh_from_db()
    assert deployment.status != Deployment.Status.SUCCEEDED
    crashed = deployment.steps.get(seq=4)
    assert crashed.status != DeploymentStep.Status.SUCCEEDED
    for prior in deployment.steps.filter(seq__lt=4):
        assert prior.status == DeploymentStep.Status.SUCCEEDED, prior.name

    monkeypatch.delenv(CRASH_AFTER_ENV)
    _run(deployment, transport, dns)
    assert deployment.status == Deployment.Status.SUCCEEDED
    assert list(
        deployment.steps.order_by("seq").values_list("status", flat=True),
    ) == [DeploymentStep.Status.SUCCEEDED] * 9


@pytest.mark.req("REL-P4-ARTIFACT-SNAPSHOTS")
@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_rollback_reapplies_artifacts():
    """rollback() is a new Deployment whose artifact kinds and contents match.

    What would make this fail: mutating the original row, inventing a new
    dockerfile/caddy/dns/env/firewall set, or snapshotting only a subset.
    """
    slug = "p2-rb"
    _site, original = queued_deployment(slug, body=fixture_body(slug))
    transport = PipelineTransport()
    dns = FakeDnsProvider()
    _run(original, transport, dns)
    assert original.status == Deployment.Status.SUCCEEDED
    original_rows = list(
        DeploymentArtifact.objects.filter(deployment=original).order_by("kind"),
    )
    assert original_rows, "first deploy must snapshot artifacts before rollback"

    result = rollback(original.pk, transport=transport, dns=dns)
    original.refresh_from_db()
    created = Deployment.objects.get(rollback_of=original)

    assert created.pk != original.pk
    assert original.status == Deployment.Status.SUCCEEDED
    assert created.status == Deployment.Status.SUCCEEDED
    assert result["status"] == Deployment.Status.SUCCEEDED
    new_rows = list(
        DeploymentArtifact.objects.filter(deployment=created).order_by("kind"),
    )
    assert [(r.kind, r.content) for r in new_rows] == [
        (r.kind, r.content) for r in original_rows
    ]


@pytest.mark.req("PIPE-N5-VOLUMES-MODELED")
def test_named_volume_survives():
    """site-{slug}-data is still present after a second deploy; no volume rm.

    What would make this fail: docker volume rm on the second deploy, or a
    per-deployment volume name that the second row replaces.
    """
    slug = "p2-vol"
    site, first = queued_deployment(slug, body=fixture_body(slug))
    transport = PipelineTransport()
    dns = FakeDnsProvider()
    volume = f"site-{slug}-data"

    _run(first, transport, dns)
    assert volume in transport.volumes

    second = Deployment.objects.create(manifest=first.manifest)
    _run(second, transport, dns)
    assert second.status == Deployment.Status.SUCCEEDED
    assert volume in transport.volumes
    assert not any(
        isinstance(payload, list) and "volume" in payload and "rm" in payload
        for kind, payload in transport.mutating_calls()
        if kind == "run"
    )
    assert volume != f"site-{slug}-{first.pk}"
    assert volume != f"site-{slug}-{second.pk}"
    assert site.name == slug


@pytest.mark.req("SEC-B1-BUILD-OFFHUB")
def test_build_not_on_hub(monkeypatch):
    """docker build argv is Transport.run on the target; Hub has no docker.sock.

    What would make this fail: subprocess docker on the Hub, a Hub docker.sock
    bind in argv, or no docker build on the Transport.
    """
    real_run = subprocess.run

    def forbid_hub_docker(cmd, *args, **kwargs):
        tokens = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        joined = " ".join(str(t) for t in tokens)
        if "docker" in joined:
            raise AssertionError(f"Hub must not invoke local docker: {cmd!r}")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr(subprocess, "run", forbid_hub_docker)
    monkeypatch.setattr(subprocess, "Popen", forbid_hub_docker)

    slug = "p2-b1"
    _site, deployment = queued_deployment(slug, body=fixture_body(slug))
    transport = PipelineTransport()
    _run(deployment, transport, FakeDnsProvider())
    assert deployment.status == Deployment.Status.SUCCEEDED

    builds = [
        argv for kind, argv in transport.calls
        if kind == "run" and isinstance(argv, list)
        and argv and argv[0] == "docker" and "build" in argv
    ]
    assert builds, "expected docker build on Transport.run, not the Hub"
    sock = "/var/run/docker.sock"
    for kind, payload in transport.calls:
        blob = payload if isinstance(payload, str) else " ".join(str(p) for p in payload)
        assert sock not in blob, f"Hub docker.sock in {kind} {payload!r}"


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_mesh_only_skips_dns():
    """mesh_only must not list or upsert DNS — there is no public record to converge.

    What would make this fail: calling upsert_record when exposure is mesh_only
    on the Manifest body.
    """
    slug = "p2-mesh"
    site, deployment = queued_deployment(
        slug, body=fixture_body(slug, extra={"exposure": "mesh_only"}),
    )
    site.exposure = Site.Exposure.MESH_ONLY
    site.save(update_fields=["exposure"])
    transport = PipelineTransport()
    dns = FakeDnsProvider()

    _run(deployment, transport, dns)
    assert deployment.status == Deployment.Status.SUCCEEDED
    assert dns.zones == {}
    dns_step = deployment.steps.get(name=DeploymentStep.Name.DNS)
    assert dns_step.status == DeploymentStep.Status.SUCCEEDED


@pytest.mark.req("PIPE-M2-GIT-POLLING")
def test_no_webhook_route(client):
    """urlpatterns contain no github/webhook/gitea/deploy-hook path; candidates 404.

    What would make this fail: adding a Django webhook view, even behind auth.
    """
    offenders = [
        route for route in _route_strings()
        if any(needle in route for needle in WEBHOOK_NEEDLES)
    ]
    assert offenders == []
    for path in TRIGGER_PATHS:
        response = client.get(path)
        assert response.status_code == 404, f"{path} returned {response.status_code}"
