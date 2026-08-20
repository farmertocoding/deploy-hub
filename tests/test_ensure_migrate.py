"""ensure_migrate: backup-guarded, rerunnable, skip when the step succeeded (D6)."""
import pytest

from core.transport import FakeTransport

BACKUP_ARGV = ["pg_dump", "-Fc", "appdb"]
MIGRATE_ARGV = ["python", "manage.py", "migrate", "--noinput"]
PRECUTOVER_ARGV = ["node", "scripts/pre-cutover.js"]


def _site_manifest_step(*, slug, body, step_status=None):
    from core.models import Project, Site
    from deploys.models import Deployment, DeploymentStep, Manifest

    project = Project.objects.create(name=slug, slug=f"p-mig-{slug}")
    site = Site.objects.create(project=project, name=slug)
    manifest = Manifest.objects.create(site=site, version=1, body=body)
    deployment = Deployment.objects.create(manifest=manifest)
    kwargs = {
        "deployment": deployment,
        "seq": 3,
        "name": DeploymentStep.Name.MIGRATE,
    }
    if step_status is not None:
        kwargs["status"] = step_status
    step = DeploymentStep.objects.create(**kwargs)
    return site, manifest, deployment, step


def _run_argvs(transport):
    return [argv for kind, argv in transport.calls if kind == "run"]


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.django_db
def test_migrate_is_rerunnable():
    """Migrate argv may run twice when no succeeded step record exists.

    What would make this fail: a Hub-side one-shot that refuses a second
    migrate, inventing a local subprocess, or skipping when the step is absent.
    """
    from core.models import Project, Site
    from deploys.models import Manifest
    from deploys.steps import ensure_migrate

    project = Project.objects.create(name="rerun", slug="p-mig-rerun")
    site = Site.objects.create(project=project, name="rerun")
    manifest = Manifest.objects.create(
        site=site,
        version=1,
        body={
            "backup_argv": BACKUP_ARGV,
            "pre_cutover": PRECUTOVER_ARGV,
        },
    )
    transport = FakeTransport()
    desired = {
        "transport": transport,
        "site_slug": "rerun",
        "manifest_body": manifest.body,
    }
    ensure_migrate(desired)
    ensure_migrate(desired)

    runs = _run_argvs(transport)
    assert runs.count(BACKUP_ARGV) == 2
    assert runs.count(PRECUTOVER_ARGV) == 2
    assert not any(kind == "run" and argv[:3] == ["docker", "volume", "rm"]
                   for kind, argv in transport.calls)


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.django_db
def test_backup_runs_if_step_did_not_succeed():
    """Crash mid-migrate (step not succeeded) takes a fresh backup first.

    What would make this fail: skipping backup when the step is pending or
    failed, or running migrate without backup_argv ahead of it.
    """
    from deploys.models import DeploymentStep
    from deploys.steps import ensure_migrate

    body = {
        "backup_argv": BACKUP_ARGV,
        "migrate_argv": MIGRATE_ARGV,
    }
    _site, _manifest, _deployment, step = _site_manifest_step(
        slug="crash",
        body=body,
        step_status=DeploymentStep.Status.RUNNING,
    )
    assert step.status != DeploymentStep.Status.SUCCEEDED

    transport = FakeTransport()
    ensure_migrate({
        "transport": transport,
        "site_slug": "crash",
        "manifest_body": body,
        "step": step,
        "backup_argv": BACKUP_ARGV,
        "migrate_argv": MIGRATE_ARGV,
    })

    runs = _run_argvs(transport)
    assert BACKUP_ARGV in runs
    assert MIGRATE_ARGV in runs
    assert runs.index(BACKUP_ARGV) < runs.index(MIGRATE_ARGV)

    transport.calls.clear()
    step.refresh_from_db()
    step.status = DeploymentStep.Status.FAILED
    step.save(update_fields=["status"])
    ensure_migrate({
        "transport": transport,
        "site_slug": "crash",
        "manifest_body": body,
        "step": step,
        "backup_argv": BACKUP_ARGV,
        "migrate_argv": MIGRATE_ARGV,
    })
    crash_runs = _run_argvs(transport)
    assert crash_runs[0] == BACKUP_ARGV
    assert MIGRATE_ARGV in crash_runs


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.django_db
def test_second_migrate_zero_mutating_calls():
    """A succeeded migrate step is a probe/no-op; second call mutates nothing.

    What would make this fail: inspect via run, re-running backup or migrate,
    or any put after the step is already succeeded.
    """
    from deploys.models import DeploymentStep
    from deploys.steps import ensure_migrate

    body = {
        "backup_argv": BACKUP_ARGV,
        "migrate_argv": MIGRATE_ARGV,
    }
    _site, _manifest, _deployment, step = _site_manifest_step(
        slug="skip",
        body=body,
        step_status=DeploymentStep.Status.PENDING,
    )
    transport = FakeTransport()
    desired = {
        "transport": transport,
        "site_slug": "skip",
        "manifest_body": body,
        "step": step,
    }
    ensure_migrate(desired)
    assert BACKUP_ARGV in _run_argvs(transport)
    assert MIGRATE_ARGV in _run_argvs(transport)
    step.refresh_from_db()
    assert step.status == DeploymentStep.Status.SUCCEEDED

    transport.calls.clear()
    ensure_migrate(desired)
    assert transport.mutating_calls() == []
    assert not any(
        kind == "run" and "inspect" in argv
        for kind, argv in transport.calls
        if isinstance(argv, list)
    )
