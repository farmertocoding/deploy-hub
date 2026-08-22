"""Heartbeat sweep for running deployments (REL-C1 / REL-P3)."""
from datetime import timedelta

import pytest
from django.conf import settings
from django.utils import timezone

from core.models import NetworkZone, Project, Site, Target
from deploys.models import Deployment, DeploymentStep, Manifest

pytestmark = pytest.mark.django_db

STALE_AFTER = timedelta(minutes=2)


def _running_deployment(*, slug, heartbeat, step_statuses):
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
    from dns_fixtures import default_dns_zone

    site = Site.objects.create(
        project=project, name=slug, primary_target=target,
        dns_zone=default_dns_zone(),
    )
    manifest = Manifest.objects.create(site=site, version=1, body={})
    deployment = Deployment.objects.create(
        manifest=manifest,
        status=Deployment.Status.RUNNING,
        last_heartbeat=heartbeat,
    )
    for seq, name in enumerate(DeploymentStep.Name.values, start=1):
        status = step_statuses.get(name, DeploymentStep.Status.PENDING)
        DeploymentStep.objects.create(
            deployment=deployment, seq=seq, name=name, status=status,
        )
    return deployment


def _beat_sweep_task_names():
    return {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}


@pytest.mark.req("REL-C1-HEARTBEAT-SWEEP")
@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_stale_running_is_resumed_or_aborted(monkeypatch):
    """Stale last_heartbeat (>2 min): resume if a pending/running step remains, else abort.

    What would make this fail: leaving a stale row running, or aborting one that
    still has a step to resume.
    """
    from pipeline_fakes import PipelineTransport

    from deploys import pipeline
    from deploys.heartbeat import sweep
    from providers.fakes import FakeDnsProvider

    monkeypatch.setattr(pipeline, "_default_transport", lambda site: PipelineTransport())
    monkeypatch.setattr(pipeline, "_default_dns", FakeDnsProvider)

    assert "deploys.tasks.sweep_stale_deployments" in _beat_sweep_task_names()

    stale_at = timezone.now() - STALE_AFTER - timedelta(seconds=1)
    resumable = _running_deployment(
        slug="stale-resume",
        heartbeat=stale_at,
        step_statuses={
            "build": DeploymentStep.Status.SUCCEEDED,
            "ship": DeploymentStep.Status.PENDING,
        },
    )
    finished = _running_deployment(
        slug="stale-finished",
        heartbeat=stale_at,
        step_statuses={
            name: DeploymentStep.Status.SUCCEEDED
            for name in DeploymentStep.Name.values
        },
    )
    abortable = _running_deployment(
        slug="stale-abort",
        heartbeat=stale_at,
        step_statuses={
            **{
                name: DeploymentStep.Status.SKIPPED
                for name in DeploymentStep.Name.values
            },
            "build": DeploymentStep.Status.SUCCEEDED,
            "ship": DeploymentStep.Status.FAILED,
        },
    )

    result = sweep()
    resumable.refresh_from_db()
    finished.refresh_from_db()
    abortable.refresh_from_db()

    assert finished.status == Deployment.Status.SUCCEEDED
    assert finished.pk not in result["aborted"]
    assert finished.pk not in result["resumed"]
    assert abortable.status == Deployment.Status.FAILED
    assert abortable.pk in result["aborted"]
    assert resumable.pk in result["resumed"]
    # Eager Celery runs the re-queued task inline; remaining no-op steps finish.
    assert resumable.status == Deployment.Status.SUCCEEDED
    assert resumable.steps.get(name="ship").status == DeploymentStep.Status.SUCCEEDED


@pytest.mark.req("REL-C1-HEARTBEAT-SWEEP")
def test_fresh_heartbeat_is_left_alone():
    """A running deploy whose heartbeat is newer than 2 min is not resumed or aborted.

    What would make this fail: sweeping a live worker and finishing (or failing)
    a deploy that is still heartbeating.
    """
    from deploys.heartbeat import sweep

    fresh = _running_deployment(
        slug="fresh",
        heartbeat=timezone.now(),
        step_statuses={"build": DeploymentStep.Status.PENDING},
    )
    result = sweep()
    fresh.refresh_from_db()
    assert fresh.status == Deployment.Status.RUNNING
    assert fresh.steps.get(name="build").status == DeploymentStep.Status.PENDING
    assert fresh.pk not in result["resumed"]
    assert fresh.pk not in result["aborted"]
    assert fresh.steps.filter(status=DeploymentStep.Status.SUCCEEDED).count() == 0


@pytest.mark.req("REL-C1-HEARTBEAT-SWEEP")
@pytest.mark.req("REL-P3-RESUMABLE-DEPLOYS")
def test_sweep_stamps_heartbeat_before_requeue(monkeypatch):
    """Claim the stale row before delay so the next Beat tick does not enqueue again.

    What would make this fail: delay() with last_heartbeat still stale, so a
    second sweep (real broker, 30s Beat) queues a second worker.
    """
    from deploys.heartbeat import sweep
    from deploys.tasks import run_deploy

    queued = []
    monkeypatch.setattr(run_deploy, "delay", lambda pk: queued.append(pk))

    stale_at = timezone.now() - STALE_AFTER - timedelta(seconds=1)
    deployment = _running_deployment(
        slug="claim",
        heartbeat=stale_at,
        step_statuses={"build": DeploymentStep.Status.PENDING},
    )

    first = sweep()
    deployment.refresh_from_db()
    assert first["resumed"] == [deployment.pk]
    assert queued == [deployment.pk]
    assert deployment.status == Deployment.Status.RUNNING
    assert deployment.last_heartbeat is not None
    assert deployment.last_heartbeat > stale_at
    assert timezone.now() - deployment.last_heartbeat < STALE_AFTER

    queued.clear()
    second = sweep()
    assert deployment.pk not in second["resumed"]
    assert queued == []


@pytest.mark.req("REL-C1-HEARTBEAT-SWEEP")
@pytest.mark.req("PIPE-D2-STATE-MACHINE")
def test_sweep_does_not_clobber_superseded(monkeypatch):
    """A stale row superseded after the snapshot must stay superseded.

    What would make this fail: sweep writing succeeded/failed, or claiming
    heartbeat and delay(), after another deploy marked the row superseded.
    """
    from deploys import heartbeat
    from deploys.tasks import run_deploy

    queued = []
    monkeypatch.setattr(run_deploy, "delay", lambda pk: queued.append(pk))

    stale_at = timezone.now() - STALE_AFTER - timedelta(seconds=1)
    finished = _running_deployment(
        slug="sup-finished",
        heartbeat=stale_at,
        step_statuses={
            name: DeploymentStep.Status.SUCCEEDED
            for name in DeploymentStep.Name.values
        },
    )
    abortable = _running_deployment(
        slug="sup-abort",
        heartbeat=stale_at,
        step_statuses={
            **{
                name: DeploymentStep.Status.SKIPPED
                for name in DeploymentStep.Name.values
            },
            "build": DeploymentStep.Status.SUCCEEDED,
            "ship": DeploymentStep.Status.FAILED,
        },
    )
    resumable = _running_deployment(
        slug="sup-resume",
        heartbeat=stale_at,
        step_statuses={"build": DeploymentStep.Status.PENDING},
    )

    real_sr = heartbeat.Deployment.objects.select_related

    def select_related_then_supersede(*args, **kwargs):
        qs = real_sr(*args, **kwargs)
        orig_get = qs.get

        def get(*a, **kw):
            Deployment.objects.filter(pk=kw["pk"]).update(
                status=Deployment.Status.SUPERSEDED,
            )
            return orig_get(*a, **kw)

        qs.get = get
        return qs

    monkeypatch.setattr(
        heartbeat.Deployment.objects, "select_related", select_related_then_supersede,
    )

    result = heartbeat.sweep()
    for row in (finished, abortable, resumable):
        row.refresh_from_db()
        assert row.status == Deployment.Status.SUPERSEDED
        assert row.pk not in result["resumed"]
        assert row.pk not in result["aborted"]
    assert queued == []
    assert resumable.last_heartbeat == stale_at


@pytest.mark.req("REL-C1-HEARTBEAT-SWEEP")
def test_touch_heartbeat_swallows_sqlite_operational_error(monkeypatch):
    """SQLite table-lock during a pulse is closed and swallowed.

    What would make this fail: letting OperationalError escape on sqlite, or
    treating every backend as sqlite.
    """
    from django.db import connection
    from django.db.utils import OperationalError

    from deploys.pipeline import touch_heartbeat

    deployment = _running_deployment(
        slug="hb-sqlite",
        heartbeat=timezone.now(),
        step_statuses={"build": DeploymentStep.Status.RUNNING},
    )

    class BoomQS:
        def update(self, **_kw):
            raise OperationalError("database table is locked")

    class BoomManager:
        def filter(self, **_kw):
            return BoomQS()

    monkeypatch.setattr("deploys.pipeline.Deployment.objects", BoomManager())
    monkeypatch.setattr(connection, "vendor", "sqlite")
    touch_heartbeat(deployment)


@pytest.mark.req("REL-C1-HEARTBEAT-SWEEP")
def test_touch_heartbeat_reraises_postgres_operational_error(monkeypatch):
    """A failed pulse on Postgres must raise so the sweep can see a miss, not silence.

    What would make this fail: catching OperationalError for every vendor.
    """
    from django.db import connection
    from django.db.utils import OperationalError

    from deploys.pipeline import touch_heartbeat

    deployment = _running_deployment(
        slug="hb-pg",
        heartbeat=timezone.now(),
        step_statuses={"build": DeploymentStep.Status.RUNNING},
    )

    class BoomQS:
        def update(self, **_kw):
            raise OperationalError("connection already closed")

    class BoomManager:
        def filter(self, **_kw):
            return BoomQS()

    monkeypatch.setattr("deploys.pipeline.Deployment.objects", BoomManager())
    monkeypatch.setattr(connection, "vendor", "postgresql")
    with pytest.raises(OperationalError):
        touch_heartbeat(deployment)
