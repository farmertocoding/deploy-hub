"""toxiproxy SSH timeout → heartbeat sweep resume (HARNESS-T3-TOXIPROXY)."""
from __future__ import annotations

import inspect
import os
import shutil
import subprocess
import sys
import time
from datetime import timedelta
from pathlib import Path

import pytest
from django.conf import settings
from django.core.management import call_command
from django.db import connections
from django.utils import timezone
from pipeline_fakes import PipelineTransport, queued_deployment

from deploys.models import Deployment, DeploymentStep
from providers.fakes import FakeDnsProvider
from tests.harness.target import SOCK, _docker_available

REPO = Path(__file__).resolve().parent.parent
STALE_AFTER = timedelta(minutes=2)
# Alpine T2 migrate (seq 3) finishes inside this window on a live SSH path.
# A 2s sleep is too short: migrate/start can still be in flight without a toxic.
STEP3_LIVE_BUDGET_S = 15

pytest_plugins = ["tests.harness.target"]


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
def toxiproxy_db_path(tmp_path_factory):
    return tmp_path_factory.mktemp("toxiproxy") / "hub.sqlite3"


@pytest.fixture(scope="module")
def toxiproxy_db_migrated(toxiproxy_db_path, django_db_blocker):
    original = settings.DATABASES["default"]["NAME"]
    with django_db_blocker.unblock():
        try:
            _prepare_file_db(toxiproxy_db_path)
            yield toxiproxy_db_path
        finally:
            _bind_database(original)


@pytest.fixture
def toxiproxy_db(toxiproxy_db_migrated, django_db_blocker):
    original = settings.DATABASES["default"]["NAME"]
    with django_db_blocker.unblock():
        _bind_database(toxiproxy_db_migrated)
        try:
            yield toxiproxy_db_migrated
        finally:
            connections.close_all()
            _bind_database(original)


def test_argv_never_a_shell_string():
    """docker run argv is a list; no shell string and no Hub docker.sock.

    What would make this fail: interpolating `docker run ...` as one string,
    subprocess shell=True, or `-v /var/run/docker.sock`.
    """
    from tests.harness.toxiproxy import IMAGE, start_toxiproxy, toxiproxy_run_argv

    argv = toxiproxy_run_argv("hub-toxiproxy-probe")
    assert isinstance(argv, list)
    assert argv
    assert all(isinstance(part, str) for part in argv)
    assert SOCK not in argv
    assert not any("docker.sock" in part for part in argv)
    assert "-p" in argv
    assert any(part.startswith("127.0.0.1::") for part in argv)
    assert IMAGE in argv
    src = inspect.getsource(start_toxiproxy)
    assert "shell=True" not in src
    assert "toxiproxy_run_argv" in src


@pytest.mark.django_db
def test_timeout_on_transport_is_not_a_succeeded_step():
    """FakeTransport timeout mid-step leaves that step non-succeeded.

    What would make this fail: treating a raised run() as a succeeded step so
    resume_step walks past the failure.
    """
    from deploys.pipeline import execute, resume_step

    class TimeoutTransport(PipelineTransport):
        def run(self, argv, *, timeout=60):
            if (
                isinstance(argv, (list, tuple))
                and argv
                and argv[0] == "docker"
                and "build" in argv
            ):
                raise TimeoutError("injected ssh timeout")
            return super().run(argv, timeout=timeout)

    _site, deployment = queued_deployment("t1-timeout")
    with pytest.raises(TimeoutError, match="injected ssh timeout"):
        execute(deployment.pk, transport=TimeoutTransport(), dns=FakeDnsProvider())

    deployment.refresh_from_db()
    assert deployment.status != Deployment.Status.SUCCEEDED
    pointer = resume_step(deployment)
    assert pointer is not None
    assert pointer.seq == 1
    assert pointer.name == DeploymentStep.Name.BUILD
    assert pointer.status != DeploymentStep.Status.SUCCEEDED
    for later in deployment.steps.filter(seq__gt=1):
        assert later.status == DeploymentStep.Status.PENDING, later.name


@pytest.mark.t2
@pytest.mark.skipif(not _docker_available(), reason="docker is not available")
def test_proxy_teardown_removes_container():
    """close() in finally docker-rm -f the toxiproxy container.

    What would make this fail: leaving the container after teardown, or
    removing it with a shell string.
    """
    from tests.harness.target import _docker
    from tests.harness.toxiproxy import start_toxiproxy

    proxy = start_toxiproxy()
    name = proxy.container
    try:
        inspect_run = _docker(["inspect", name])
        assert inspect_run.returncode == 0
        src = inspect.getsource(type(proxy).close)
        assert "shell=True" not in src
    finally:
        proxy.close()
    gone = _docker(["inspect", name])
    assert gone.returncode != 0


def _spawn_worker(pk, db_path):
    """Run worker_entry against the shared file db. Do not SIGKILL pytest."""
    # HUB_TEST_MODE gates the child's HUB_TEST_DATABASE rebind (2.5 panel I2),
    # and puts the child behind the §B9 wall — so the fixture zone becomes
    # purpose=test and is allowlisted. tests/ stays off the child's path —
    # worker_entry imports no test module.
    zone = Deployment.objects.get(pk=pk).manifest.site.primary_target.zone
    if zone.purpose != "test":
        zone.purpose = "test"
        zone.save(update_fields=["purpose"])
    connections.close_all()
    env = os.environ.copy()
    env["DJANGO_SETTINGS_MODULE"] = "hub.settings.dev"
    env["HUB_TEST_MODE"] = "1"
    env["HUB_TEST_ZONE_SLUGS"] = zone.slug
    env["HUB_TEST_DATABASE"] = str(db_path)
    env["CONFORMANCE_RUN_REPORT"] = "off"
    env.pop("HUB_TEST_CRASH_AFTER_STEP", None)
    env.pop("HUB_TEST_CRASH_SIGNAL", None)
    env["PYTHONPATH"] = os.pathsep.join([str(REPO), env.get("PYTHONPATH", "")])
    return subprocess.Popen(
        [sys.executable, "-m", "deploys.worker_entry", str(pk)],
        cwd=str(REPO),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )


def _assert_toxic_stalled_after_step_2(deployment, proc, *, budget_s=STEP3_LIVE_BUDGET_S):
    """After a live-path step-3 budget, the child must still be hung.

    What would make this fail: the toxic never stalling SSH, so seq>2 succeeds
    (or the child exits) inside the same window a healthy alpine migrate would.
    """
    deadline = time.time() + budget_s
    while time.time() < deadline:
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=5)
            raise AssertionError(
                f"worker exited {proc.returncode} during the live-path budget; "
                f"toxic did not stall SSH\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        time.sleep(0.2)
    connections.close_all()
    deployment.refresh_from_db()
    later = [
        (step.seq, step.name, step.status)
        for step in deployment.steps.filter(seq__gt=2)
        if step.status == DeploymentStep.Status.SUCCEEDED
    ]
    assert proc.poll() is None
    assert later == [], (
        f"seq>2 succeeded during the live-path budget; toxic did not stall SSH: {later}"
    )


def _wait_step_2_then_toxic(deployment, proc, proxy, *, deadline):
    """Arm the downstream timeout the instant seq 2 is succeeded."""
    while time.time() < deadline:
        connections.close_all()
        deployment.refresh_from_db()
        step = deployment.steps.filter(seq=2).first()
        if step is not None and step.status == DeploymentStep.Status.SUCCEEDED:
            proxy.toxic_timeout("hub-ssh")
            return
        if proc.poll() is not None:
            stdout, stderr = proc.communicate(timeout=5)
            raise AssertionError(
                f"worker exited {proc.returncode} before step 2 succeeded; "
                f"last={step.status if step else None}\nstdout:\n{stdout}\nstderr:\n{stderr}"
            )
        time.sleep(0.05)
    raise AssertionError("timed out waiting for step 2 before arming toxic")


@pytest.mark.t2
@pytest.mark.skipif(not _docker_available(), reason="docker is not available")
@pytest.mark.req("HARNESS-T3-TOXIPROXY")
def test_ssh_timeout_mid_deploy_resumes(hub_target, toxiproxy_db, tmp_path, monkeypatch):
    """SshTransport through toxiproxy: timeout after step 2, sweep resumes.

    What would make this fail: Hub docker.sock, skipping T2 when docker exists,
    SIGKILL before a live alpine migrate would have finished (toxic as scenery),
    marking the timed-out step succeeded, or a second execute that never
    reaches succeeded.
    """
    import json
    import uuid

    from pipeline_fakes import SAMPLE_NODE_SITE, fixture_body
    from test_pipeline_sample_node_site import T2_DOCKERFILE, T2_SERVE_PY

    from core.models import NetworkZone, Project, Site, Target
    from core.ssh import SshTransport
    from deploys import pipeline
    from deploys.models import Manifest
    from deploys.tasks import sweep_stale_deployments
    from tests.harness.target import _docker, _wait_exec
    from tests.harness.toxiproxy import reachable_upstream, start_toxiproxy
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
    proxy = start_toxiproxy()
    try:
        proxy.add_proxy("hub-ssh", upstream=reachable_upstream(hub_target))
        owner_id = f"t2-toxi-{uuid.uuid4().hex[:12]}"
        zone = NetworkZone.objects.create(
            name="t2-toxi", slug=f"t2-toxi-{uuid.uuid4().hex[:8]}",
        )
        target = Target.objects.create(
            zone=zone,
            kind=Target.Kind.SSH,
            host=f"{proxy.listen_host}:{proxy.listen_port}",
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
        slug = f"t2x{uuid.uuid4().hex[:6]}"
        project = Project.objects.create(name=slug, slug=f"p-{slug}")
        site = Site.objects.create(
            project=project,
            name=slug,
            domain=f"{slug}.example.test",
            primary_target=target,
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
            "internal_port": 80,
            "upstream": "127.0.0.1:20000",
            "caddy_listen": "127.0.0.1:8088",
            "warmup_timeout_s": 60,
            # Volume create + empty migrate finishes before a parent poll can
            # arm the toxic. This argv is a real SSH through the proxy so the
            # live-path budget is observable and the timeout can hold it.
            "backup_argv": ["sleep", "8"],
        })
        manifest = Manifest.objects.create(site=site, version=1, body=body)
        deployment = Deployment.objects.create(manifest=manifest)

        proc = _spawn_worker(deployment.pk, toxiproxy_db)
        try:
            _wait_step_2_then_toxic(
                deployment, proc, proxy, deadline=time.time() + 180,
            )
            _assert_toxic_stalled_after_step_2(deployment, proc)
            proc.kill()
            proc.communicate(timeout=10)
        finally:
            if proc.poll() is None:
                proc.kill()
                proc.communicate(timeout=10)

        connections.close_all()
        deployment.refresh_from_db()
        assert os.getpid() == parent_pid
        assert deployment.status != Deployment.Status.SUCCEEDED
        opened = [
            step for step in deployment.steps.order_by("seq")
            if step.status not in {
                DeploymentStep.Status.SUCCEEDED, DeploymentStep.Status.SKIPPED,
            }
        ]
        assert opened, "timeout left no resume pointer"
        assert opened[0].status != DeploymentStep.Status.SUCCEEDED
        assert all(
            step.status == DeploymentStep.Status.SUCCEEDED
            for step in deployment.steps.filter(seq__lte=2)
        )

        proxy.reset()
        assert deployment.status == Deployment.Status.RUNNING
        assert opened[0].status != DeploymentStep.Status.FAILED

        Deployment.objects.filter(pk=deployment.pk).update(
            last_heartbeat=timezone.now() - STALE_AFTER - timedelta(seconds=1),
        )
        monkeypatch.setattr(
            pipeline, "_default_transport",
            lambda site: SshTransport(site.primary_target),
        )
        result = sweep_stale_deployments()
        assert deployment.pk in result["resumed"]
        deployment.refresh_from_db()
        if deployment.status != Deployment.Status.SUCCEEDED:
            pipeline.execute(deployment.pk)
            deployment.refresh_from_db()
        assert deployment.status == Deployment.Status.SUCCEEDED
    finally:
        proxy.close()
