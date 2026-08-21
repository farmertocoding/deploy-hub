"""Deployment state machine skeleton (PIPE-D2 / REL-P3 / REL-A5)."""
import ast
import inspect
from pathlib import Path

import pytest

from core.models import NetworkZone, Project, Site, Target
from deploys.models import Deployment, DeploymentStep, Manifest
from vault import service as vault_service
from vault.models import Secret

pytestmark = pytest.mark.django_db

D2_DEPLOYMENT_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "rolled_back",
    "cancelled",
    "superseded",
}

D2_STEP_STATUSES = {"pending", "running", "succeeded", "failed", "skipped"}

D2_STEP_NAMES = [
    "build",
    "ship",
    "migrate",
    "start_green",
    "health_check",
    "dns",
    "route_tls",
    "smoke_test",
    "cutover",
]

ENV_MARKER = b"PIPELINE-ENV-SNAPSHOT-MARKER-do-not-log"


def _site_with_target(*, slug="pipe"):
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
    return site, target


def _queued_deployment(site, *, env_ref=None, version=1):
    manifest = Manifest.objects.create(
        site=site,
        version=version,
        body={"env_bundle_ref": env_ref},
    )
    return Deployment.objects.create(manifest=manifest)


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_statuses_match_pinned_enums():
    """Pinned §D2 enums, and begin_deploy persists all nine steps as pending.

    What would make this fail: a renamed status, a tenth step, or persisting
    steps out of seq / already running.
    """
    from deploys.pipeline import begin_deploy

    assert set(Deployment.Status.values) == D2_DEPLOYMENT_STATUSES
    assert set(DeploymentStep.Status.values) == D2_STEP_STATUSES
    assert list(DeploymentStep.Name.values) == D2_STEP_NAMES

    site, _ = _site_with_target()
    deployment = _queued_deployment(site)
    assert begin_deploy(deployment) is True
    deployment.refresh_from_db()
    rows = list(deployment.steps.order_by("seq"))
    assert [(s.seq, s.name, s.status) for s in rows] == [
        (i, name, DeploymentStep.Status.PENDING)
        for i, name in enumerate(D2_STEP_NAMES, start=1)
    ]
    assert deployment.status == Deployment.Status.RUNNING


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_resume_is_first_non_succeeded_step():
    """Resume pointer skips succeeded and skipped; a running/pending/failed step is next.

    What would make this fail: treating skipped as still-open, or resuming at
    the first pending after a running step.
    """
    from deploys.pipeline import begin_deploy, resume_step

    site, _ = _site_with_target(slug="resume")
    deployment = _queued_deployment(site)
    assert begin_deploy(deployment) is True
    by_name = {s.name: s for s in deployment.steps.all()}
    by_name["build"].status = DeploymentStep.Status.SUCCEEDED
    by_name["build"].save(update_fields=["status"])
    by_name["ship"].status = DeploymentStep.Status.SKIPPED
    by_name["ship"].save(update_fields=["status"])
    by_name["migrate"].status = DeploymentStep.Status.RUNNING
    by_name["migrate"].save(update_fields=["status"])

    pointer = resume_step(deployment)
    assert pointer is not None
    assert pointer.name == "migrate"
    assert pointer.seq == 3


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_rollback_is_a_new_deployment_row():
    """Rollback is a second Deployment row with rollback_of set; not an in-place edit.

    Row shape only — Task 13 executes rollback. What would make this fail:
    mutating the original row's status to rolled_back without a new pk.
    """
    site, _ = _site_with_target(slug="rollback")
    original = _queued_deployment(site)
    original.status = Deployment.Status.SUCCEEDED
    original.save(update_fields=["status"])

    rollback = Deployment.objects.create(
        manifest=original.manifest,
        status=Deployment.Status.QUEUED,
        rollback_of=original,
    )
    assert rollback.pk != original.pk
    assert rollback.rollback_of_id == original.pk
    original.refresh_from_db()
    assert original.status == Deployment.Status.SUCCEEDED
    assert original.rollbacks.get().pk == rollback.pk


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_env_snapshot_goes_through_vault(monkeypatch):
    """Env bytes come from vault.service.get; never task kwargs, artifacts, or logs.

    What would make this fail: copying bundle plaintext onto DeploymentArtifact
    or into Celery kwargs, or reading Secret.ciphertext by hand.
    """
    from pipeline_fakes import PipelineTransport

    from deploys import pipeline
    from deploys import tasks as deploy_tasks
    from deploys.models import DeploymentArtifact
    from deploys.pipeline import load_env_snapshot
    from deploys.tasks import run_deploy
    from providers.fakes import FakeDnsProvider

    site, _ = _site_with_target(slug="env")
    bundle = vault_service.put(
        kind=Secret.Kind.ENV_BUNDLE,
        owner_type="manifest",
        owner_id=f"{site.pk}:v1",
        plaintext=ENV_MARKER,
    )
    deployment = _queued_deployment(site, env_ref=bundle.pk)

    source = ast.parse(Path(inspect.getfile(deploy_tasks)).read_text(encoding="utf-8"))
    for node in ast.walk(source):
        if isinstance(node, ast.FunctionDef) and node.name == "run_deploy":
            assert [a.arg for a in node.args.args] == ["deployment_id"]
            break
    else:
        pytest.fail("run_deploy is missing from deploys.tasks")

    snapshot = load_env_snapshot(deployment)
    assert snapshot == ENV_MARKER
    Secret.objects.filter(pk=bundle.pk).update(last_used_at=None)

    fake = PipelineTransport()
    monkeypatch.setattr(pipeline, "_default_transport", lambda site: fake)
    monkeypatch.setattr(pipeline, "_default_dns", FakeDnsProvider)

    run_deploy.delay(deployment.pk)
    bundle.refresh_from_db()
    assert bundle.last_used_at is not None
    deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUCCEEDED
    for artifact in DeploymentArtifact.objects.filter(deployment=deployment):
        assert ENV_MARKER.decode() not in artifact.content
    for step in deployment.steps.all():
        assert ENV_MARKER.decode() not in step.log_text


@pytest.mark.req("REL-A5-POSTGRES-LOCKS")
@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_lock_serializes_two_deploys_same_site():
    """A second deploy for a running site supersedes at the lock boundary, then holds.

    Unique (scope, object_id, kind) — only one site-deploy lock exists. What would
    make this fail: two holders, leaving the old row running, or skipping Postgres
    OperationLock.
    """
    from core.models import OperationLock
    from deploys.pipeline import begin_deploy

    site, target = _site_with_target(slug="lock")
    first = _queued_deployment(site, version=1)
    second = _queued_deployment(site, version=2)

    assert begin_deploy(first) is True
    first.refresh_from_db()
    assert first.status == Deployment.Status.RUNNING
    site_lock = OperationLock.objects.get(
        scope=OperationLock.Scope.SITE,
        object_id=str(site.pk),
        kind=OperationLock.Kind.DEPLOY,
    )
    assert site_lock.holder == str(first.pk)
    assert OperationLock.objects.get(
        scope=OperationLock.Scope.TARGET,
        object_id=str(target.pk),
        kind=OperationLock.Kind.DEPLOY,
    ).holder == str(first.pk)

    assert begin_deploy(second) is True
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.status == Deployment.Status.SUPERSEDED
    assert second.status == Deployment.Status.RUNNING
    assert OperationLock.objects.filter(
        scope=OperationLock.Scope.SITE,
        object_id=str(site.pk),
        kind=OperationLock.Kind.DEPLOY,
    ).count() == 1
    assert OperationLock.objects.get(
        scope=OperationLock.Scope.SITE,
        object_id=str(site.pk),
        kind=OperationLock.Kind.DEPLOY,
    ).holder == str(second.pk)
    assert OperationLock.objects.get(
        scope=OperationLock.Scope.TARGET,
        object_id=str(target.pk),
        kind=OperationLock.Kind.DEPLOY,
    ).holder == str(second.pk)


@pytest.mark.req("PIPE-D2-STATE-MACHINE")
@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_execute_stops_when_superseded(monkeypatch):
    """An in-flight worker must not overwrite SUPERSEDED with SUCCEEDED.

    What would make this fail: execute finishing the remaining steps and
    writing succeeded after another deploy marked this row superseded.
    """
    from pipeline_fakes import PipelineTransport

    from deploys import pipeline
    from providers.fakes import FakeDnsProvider

    site, _ = _site_with_target(slug="exec-supersede")
    deployment = _queued_deployment(site)
    assert pipeline.begin_deploy(deployment) is True

    real_run = pipeline._run_step
    transport = PipelineTransport()
    dns = FakeDnsProvider()

    def run_then_supersede(dep, step, desired=None):
        real_run(dep, step, desired)
        Deployment.objects.filter(pk=dep.pk).update(
            status=Deployment.Status.SUPERSEDED,
        )

    monkeypatch.setattr(pipeline, "_run_step", run_then_supersede)
    result = pipeline.execute(deployment.pk, transport=transport, dns=dns)
    deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUPERSEDED
    assert result["status"] == Deployment.Status.SUPERSEDED
    assert deployment.steps.filter(
        status=DeploymentStep.Status.PENDING,
    ).count() == 8
    assert deployment.steps.get(name="build").status == DeploymentStep.Status.SUCCEEDED


@pytest.mark.req("REL-A5-POSTGRES-LOCKS")
@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_execute_releases_lock_if_post_success_save_raises(monkeypatch):
    """try/finally must drop deploy locks even if work after SUCCEEDED save raises.

    What would make this fail: releasing only on the happy return path, so a
    boom after status=succeeded leaves the site deploy lock held forever.
    """
    from pipeline_fakes import PipelineTransport, queued_deployment

    from core.models import OperationLock
    from deploys.pipeline import execute
    from providers.fakes import FakeDnsProvider

    _site, deployment = queued_deployment("lock-finally")
    real_save = Deployment.save

    def save(self, *args, **kwargs):
        real_save(self, *args, **kwargs)
        if self.status == Deployment.Status.SUCCEEDED:
            raise RuntimeError("post-success")

    monkeypatch.setattr(Deployment, "save", save)
    with pytest.raises(RuntimeError, match="post-success"):
        execute(
            deployment.pk, transport=PipelineTransport(), dns=FakeDnsProvider(),
        )
    assert not OperationLock.objects.filter(
        kind=OperationLock.Kind.DEPLOY, holder=str(deployment.pk),
    ).exists()
