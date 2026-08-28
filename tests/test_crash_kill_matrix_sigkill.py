"""SIGKILL worker-death kill-matrix (REL-P3-WORKER-DEATH).

The Phase 2 in-process RuntimeError hook stays on REL-P3-RESUMABLE-DEPLOYS.
This module SIGKILLs a `python -m deploys.worker_entry` child, never pytest.
"""
from __future__ import annotations

import os
import shutil
import signal
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.utils import timezone
from pipeline_fakes import PipelineTransport, queued_deployment

from deploys.models import Deployment, DeploymentStep
from providers.fakes import FakeDnsProvider, FakeOriginCertIssuer

REPO = Path(__file__).resolve().parent.parent
STEP_NAMES = list(DeploymentStep.Name.values)
STALE_AFTER = timedelta(minutes=2)

pytest_plugins = ["tests.harness.target"]


def _docker_available():
    if shutil.which("docker") is None:
        return False
    probe = subprocess.run(
        ["docker", "info"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
    )
    return probe.returncode == 0


def _bind_database(name):
    settings.DATABASES["default"]["NAME"] = str(name)
    connections.databases["default"]["NAME"] = str(name)
    connections.close_all()


def _prepare_file_db(path):
    _bind_database(path)
    call_command("migrate", verbosity=0, interactive=False)
    connections["default"].cursor().execute("PRAGMA journal_mode=WAL;")
    connections.close_all()


@pytest.fixture(scope="module")
def sigkill_db_path(tmp_path_factory):
    return tmp_path_factory.mktemp("sigkill") / "hub.sqlite3"


@pytest.fixture(scope="module")
def sigkill_db_migrated(sigkill_db_path, django_db_blocker):
    original = settings.DATABASES["default"]["NAME"]
    with django_db_blocker.unblock():
        try:
            _prepare_file_db(sigkill_db_path)
            yield sigkill_db_path
        finally:
            _bind_database(original)


@pytest.fixture
def sigkill_db(sigkill_db_migrated, django_db_blocker):
    original = settings.DATABASES["default"]["NAME"]
    with django_db_blocker.unblock():
        _bind_database(sigkill_db_migrated)
        try:
            yield sigkill_db_migrated
        finally:
            connections.close_all()
            _bind_database(original)


def _spawn_worker(pk, db_path, *, fake=True, crash_after, timeout=30):
    """Run worker_entry in a child. Do not SIGKILL from this parent."""
    zone = _declare_test_zone(pk)
    connections.close_all()
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "hub.settings.dev"
    # The child rebinds only under HUB_TEST_MODE (2.5 panel I2); this parent is
    # the test plane, so it declares it and allowlists the fixture zone for the
    # §B9 wall. tests/ stays off the child's path — worker_entry no longer
    # imports from the test tree.
    env["HUB_TEST_MODE"] = "1"
    env["HUB_TEST_ZONE_SLUGS"] = zone.slug
    env["HUB_TEST_DATABASE"] = str(db_path)
    env["HUB_TEST_CRASH_AFTER_STEP"] = str(crash_after)
    env["HUB_TEST_CRASH_SIGNAL"] = "SIGKILL"
    env["CONFORMANCE_RUN_REPORT"] = "off"
    if not fake:
        env["HUB_TEST_FAKE_DNS"] = "1"
    env["PYTHONPATH"] = os.pathsep.join([str(REPO), env.get("PYTHONPATH", "")])
    cmd = [sys.executable, "-m", "deploys.worker_entry", str(pk)]
    if fake:
        cmd.append("--fake")
    proc = subprocess.Popen(
        cmd, cwd=str(REPO), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate(timeout=5)
        raise
    if proc.returncode != -signal.SIGKILL and (stdout or stderr):
        sys.stderr.write(stdout or "")
        sys.stderr.write(stderr or "")
    return proc.returncode


def _declare_test_zone(pk):
    """Flip the fixture zone to purpose=test so the test-mode child may deploy to it."""
    zone = Deployment.objects.get(pk=pk).manifest.site.primary_target.zone
    if zone.purpose != "test":
        zone.purpose = "test"
        zone.save(update_fields=["purpose"])
    return zone


def _assert_crashed_mid_pipeline(deployment, seq):
    deployment.refresh_from_db()
    assert deployment.status != Deployment.Status.SUCCEEDED
    crashed = deployment.steps.get(seq=seq)
    assert crashed.status != DeploymentStep.Status.SUCCEEDED
    assert crashed.name == STEP_NAMES[seq - 1]
    for prior in deployment.steps.filter(seq__lt=seq):
        assert prior.status == DeploymentStep.Status.SUCCEEDED, prior.name
    for later in deployment.steps.filter(seq__gt=seq):
        assert later.status == DeploymentStep.Status.PENDING, later.name


@pytest.mark.req("REL-P3-WORKER-DEATH")
@pytest.mark.parametrize("seq", range(1, 10))
def test_sigkill_after_step_n_child_dies_parent_survives(seq, sigkill_db):
    """HUB_TEST_CRASH_SIGNAL=SIGKILL kills the worker child after ensure_*; pytest lives.

    What would make this fail: raising RuntimeError in-process (exit 1), SIGKILL of
    pytest, marking the crashed step succeeded, or skipping ensure_* before the hook.
    """
    parent_pid = os.getpid()
    slug = f"sigkill-{seq}"
    _site, deployment = queued_deployment(slug)
    rc = _spawn_worker(deployment.pk, sigkill_db, crash_after=seq)
    connections.close_all()

    assert os.getpid() == parent_pid
    assert rc == -signal.SIGKILL
    _assert_crashed_mid_pipeline(deployment, seq)


@pytest.mark.req("REL-P3-WORKER-DEATH")
def test_heartbeat_sweep_resumes_sigkilled_child(sigkill_db, monkeypatch):
    """Stale last_heartbeat after SIGKILL: sweep re-queues execute to succeeded.

    What would make this fail: leaving the row running, aborting a resumable
    pointer, or a second execute that never reaches succeeded.
    """
    from deploys import pipeline
    from deploys.tasks import sweep_stale_deployments

    parent_pid = os.getpid()
    slug = "sigkill-sweep"
    _site, deployment = queued_deployment(slug)
    rc = _spawn_worker(deployment.pk, sigkill_db, crash_after=1)
    connections.close_all()
    assert os.getpid() == parent_pid
    assert rc == -signal.SIGKILL
    _assert_crashed_mid_pipeline(deployment, 1)

    Deployment.objects.filter(pk=deployment.pk).update(
        last_heartbeat=timezone.now() - STALE_AFTER - timedelta(seconds=1),
    )
    monkeypatch.setattr(pipeline, "_default_transport", lambda site: PipelineTransport())
    monkeypatch.setattr(pipeline, "_default_dns", FakeDnsProvider)
    monkeypatch.setattr(
        pipeline, "resolve_production_seams",
        lambda site: (FakeDnsProvider(), FakeOriginCertIssuer()),
    )

    result = sweep_stale_deployments()
    assert deployment.pk in result["resumed"]
    deployment.refresh_from_db()
    if deployment.status != Deployment.Status.SUCCEEDED:
        pipeline.execute(
            deployment.pk,
            transport=PipelineTransport(),
            dns=FakeDnsProvider(),
        )
        deployment.refresh_from_db()

    assert deployment.status == Deployment.Status.SUCCEEDED
    assert list(
        deployment.steps.order_by("seq").values_list("status", flat=True),
    ) == [DeploymentStep.Status.SUCCEEDED] * 9


@pytest.mark.django_db
@pytest.mark.req("REL-P3-WORKER-DEATH")
def test_runtimeerror_hook_still_raises_in_process(monkeypatch):
    """HUB_TEST_CRASH_AFTER_STEP without SIGKILL still raises RuntimeError in-process.

    What would make this fail: replacing the Phase 2 hook with os.kill when
    HUB_TEST_CRASH_SIGNAL is unset, or catching the RuntimeError inside execute.
    """
    from deploys.pipeline import CRASH_AFTER_ENV, execute

    monkeypatch.delenv("HUB_TEST_CRASH_SIGNAL", raising=False)
    monkeypatch.setenv(CRASH_AFTER_ENV, "1")
    _site, deployment = queued_deployment("re-hook")
    with pytest.raises(RuntimeError, match=CRASH_AFTER_ENV):
        execute(deployment.pk, transport=PipelineTransport(), dns=FakeDnsProvider())
    deployment.refresh_from_db()
    assert deployment.status != Deployment.Status.SUCCEEDED
    assert deployment.steps.get(seq=1).status != DeploymentStep.Status.SUCCEEDED


@pytest.mark.t2
@pytest.mark.skipif(not _docker_available(), reason="docker is not available")
@pytest.mark.req("REL-P3-WORKER-DEATH")
def test_t2_sigkill_worker_resumes_on_hub_test_target(
    hub_target, sigkill_db, tmp_path, monkeypatch,
):
    """SshTransport child SIGKILL after step 4; sweep + execute reaches succeeded.

    What would make this fail: SIGKILL of pytest, Hub docker.sock, or a resume
    that never reaches succeeded on hub-test-target.
    """
    import json
    import shutil
    import time
    import uuid

    from pipeline_fakes import SAMPLE_NODE_SITE, fixture_body
    from test_pipeline_sample_node_site import T2_DOCKERFILE, T2_SERVE_PY

    from core.models import NetworkZone, Project, Site, Target
    from core.ssh import SshTransport
    from deploys import pipeline
    from deploys.models import Manifest
    from deploys.tasks import sweep_stale_deployments
    from tests.harness.target import _docker, _wait_exec
    from vault import service
    from vault.models import Secret

    _wait_exec(
        hub_target.container,
        ["systemctl", "is-active", "docker"],
        ready=lambda r: r.stdout.strip() == "active",
        deadline=time.time() + 90,
    )
    _wait_exec(
        hub_target.container,
        ["systemctl", "is-active", "caddy"],
        ready=lambda r: r.stdout.strip() == "active",
        deadline=time.time() + 60,
    )
    inspect = json.loads(_docker(["inspect", hub_target.container], check=True).stdout)[0]
    for mount in inspect.get("Mounts") or []:
        src = mount.get("Source") or ""
        dst = mount.get("Destination") or ""
        assert "/var/run/docker.sock" not in (src, dst)

    parent_pid = os.getpid()
    owner_id = f"t2-sigkill-{uuid.uuid4().hex[:12]}"
    zone = NetworkZone.objects.create(
        name="t2-sigkill", slug=f"t2-sigkill-{uuid.uuid4().hex[:8]}",
    )
    target = Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host=f"{hub_target.host}:{hub_target.port}",
        ssh_user=hub_target.user,
        ssh_key_ref=owner_id,
        host_key_fingerprint=hub_target.host_key_fingerprint,
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )
    service.put(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_type="target",
        owner_id=owner_id,
        plaintext=hub_target.client_key_pem,
    )
    slug = f"t2k{uuid.uuid4().hex[:6]}"
    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    from dns_fixtures import default_dns_zone

    site = Site.objects.create(
        project=project,
        name=slug,
        domain=f"{slug}.example.test",
        primary_target=target,
        dns_zone=default_dns_zone(),
        deploy_strategy=Site.DeployStrategy.RECREATE,
        readiness_path="/healthz.ready",
        warmup_timeout_s=30,
    )
    ctx = tmp_path / "src"
    shutil.copytree(
        SAMPLE_NODE_SITE, ctx, ignore=shutil.ignore_patterns(".git", "node_modules"),
    )
    (ctx / "serve.py").write_text(T2_SERVE_PY)
    body = fixture_body(slug, extra={
        "source_dir": str(ctx),
        "dockerfile_template": T2_DOCKERFILE,
        "docker_run_extra": ["-p", "127.0.0.1:20000:80"],
        # Health curls container_ip:internal_port; T2_SERVE_PY listens on 80.
        # Caddy on the target host proxies the published 20000 mapping.
        "internal_port": 80,
        "upstream": "127.0.0.1:20000",
        "caddy_listen": "127.0.0.1:8088",
        "warmup_timeout_s": 60,
    })
    manifest = Manifest.objects.create(site=site, version=1, body=body)
    deployment = Deployment.objects.create(manifest=manifest)

    rc = _spawn_worker(
        deployment.pk, sigkill_db, fake=False, crash_after=4, timeout=240,
    )
    connections.close_all()
    assert os.getpid() == parent_pid
    assert rc == -signal.SIGKILL
    _assert_crashed_mid_pipeline(deployment, 4)

    Deployment.objects.filter(pk=deployment.pk).update(
        last_heartbeat=timezone.now() - STALE_AFTER - timedelta(seconds=1),
    )
    monkeypatch.setattr(
        pipeline, "_default_transport",
        lambda site: SshTransport(site.primary_target),
    )
    monkeypatch.setattr(
        pipeline, "resolve_production_seams",
        lambda site: (FakeDnsProvider(), FakeOriginCertIssuer()),
    )
    result = sweep_stale_deployments()
    assert deployment.pk in result["resumed"]
    deployment.refresh_from_db()
    if deployment.status != Deployment.Status.SUCCEEDED:
        pipeline.execute(
            deployment.pk, dns=FakeDnsProvider(),
            cert_issuer=FakeOriginCertIssuer(),
        )
        deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUCCEEDED
