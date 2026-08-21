"""sample-node-site through the real pipeline: twice, volume, recreate (T1 + T2)."""
from __future__ import annotations

import io
import json
import os
import shutil
import socket
import subprocess
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from paramiko import ECDSAKey
from pipeline_fakes import (
    NPM_CI_DOCKERFILE,
    SAMPLE_NODE_SITE,
    PipelineTransport,
    fixture_body,
    queued_deployment,
)

from deploys.models import Deployment, DeploymentStep
from providers.fakes import FakeDnsProvider

pytestmark = pytest.mark.django_db

REPO = Path(__file__).resolve().parent.parent


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


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_deploy_twice_second_zero_mutating():
    """A second execute of the same desired records zero run/put after calls.clear().

    What would make this fail: rebuilding the image, recreating the volume, or
    putting Caddy/runbook bytes again when the target already matches.
    """
    slug = "twice"
    _site, deployment = queued_deployment(slug, body=fixture_body(slug))
    transport = PipelineTransport()
    dns = FakeDnsProvider()

    _execute(deployment, transport, dns)
    assert deployment.status == Deployment.Status.SUCCEEDED
    assert "npm ci" in NPM_CI_DOCKERFILE
    assert SAMPLE_NODE_SITE.is_dir()

    transport.calls.clear()
    _requeue_pending(deployment)
    _execute(deployment, transport, dns)
    assert deployment.status == Deployment.Status.SUCCEEDED
    assert transport.mutating_calls() == []


@pytest.mark.req("PIPE-N5-VOLUMES-MODELED")
def test_volume_survives_second_deploy():
    """site-{slug}-data is still present after a second deploy of the site.

    What would make this fail: docker volume rm on the second deploy, or a
    per-deployment volume name that the second row replaces.
    """
    slug = "vol2"
    site, first = queued_deployment(slug, body=fixture_body(slug))
    transport = PipelineTransport()
    dns = FakeDnsProvider()
    volume = f"site-{slug}-data"

    _execute(first, transport, dns)
    assert volume in transport.volumes

    second = Deployment.objects.create(manifest=first.manifest)
    _execute(second, transport, dns)
    assert second.status == Deployment.Status.SUCCEEDED
    assert volume in transport.volumes
    assert not any(
        isinstance(payload, list) and "volume" in payload and "rm" in payload
        for kind, payload in transport.mutating_calls()
        if kind == "run"
    )
    assert volume == f"site-{slug}-data"
    assert volume != f"site-{slug}-{first.pk}"
    assert volume != f"site-{slug}-{second.pk}"
    assert site.name == slug


@pytest.mark.req("PIPE-N1-DEPLOY-STRATEGY")
@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_recreate_old_writer_stopped_first():
    """Recreate stops the old writer before docker run of the new name; smoke before cutover.

    What would make this fail: docker run of green while the old container is
    still running, or cutover mutating before the smoke_test step has succeeded.
    """
    slug = "recreate"
    _site, first = queued_deployment(slug, body=fixture_body(slug))
    transport = PipelineTransport()
    dns = FakeDnsProvider()

    _execute(first, transport, dns)
    old = f"site-{slug}-{first.pk}"
    assert transport.containers.get(old) == "running"

    transport.calls.clear()
    second = Deployment.objects.create(manifest=first.manifest)
    _execute(second, transport, dns)
    green = f"site-{slug}-{second.pk}"

    runs = [
        argv for kind, argv in transport.mutating_calls()
        if kind == "run" and isinstance(argv, list)
    ]
    stop_at = [
        i for i, argv in enumerate(runs)
        if argv[:2] == ["docker", "stop"] and old in argv
    ]
    run_at = [
        i for i, argv in enumerate(runs)
        if argv[:2] == ["docker", "run"] and green in argv
    ]
    assert stop_at, f"expected docker stop {old}, got {runs}"
    assert run_at, f"expected docker run {green}, got {runs}"
    assert stop_at[0] < run_at[0]

    second.refresh_from_db()
    smoke = second.steps.get(name=DeploymentStep.Name.SMOKE_TEST)
    cutover = second.steps.get(name=DeploymentStep.Name.CUTOVER)
    assert smoke.status == DeploymentStep.Status.SUCCEEDED
    assert cutover.status == DeploymentStep.Status.SUCCEEDED
    assert smoke.finished is not None and cutover.started is not None
    assert smoke.finished <= cutover.started


# --- T2: real SshTransport against hub-test-target (copied helpers, not a plugin) ---

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


def _docker(argv, *, stdin=None, timeout=60, check=False):
    result = subprocess.run(
        ["docker", *argv],
        input=stdin,
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if check and result.returncode != 0:
        raise AssertionError(
            f"docker {argv!r} exited {result.returncode}\n"
            f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
        )
    return result


def _exec(container, argv, *, stdin=None, timeout=60, check=False):
    return _docker(
        ["exec", "-i", container, *argv],
        stdin=stdin,
        timeout=timeout,
        check=check,
    )


def _wait_tcp(host, port, *, deadline):
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=1) as sock:
                banner = sock.recv(256)
            if banner.startswith(b"SSH-2.0"):
                return banner
        except OSError:
            time.sleep(0.5)
    raise AssertionError(f"sshd did not listen on {host}:{port} before timeout")


def _wait_exec(container, argv, *, ready, deadline, timeout=30):
    last = None
    while time.time() < deadline:
        last = _exec(container, argv, timeout=timeout)
        if ready(last):
            return last
        time.sleep(1)
    raise AssertionError(
        f"waiting for {argv!r} in {container}: last exit={last.returncode if last else None}"
    )


def _presented_fingerprint(host, port, user, pkey):
    import paramiko

    class _Record(paramiko.MissingHostKeyPolicy):
        def __init__(self):
            self.key = None

        def missing_host_key(self, client, hostname, key):
            self.key = key
            client.get_host_keys().add(hostname, key.get_name(), key)

    policy = _Record()
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(policy)
    last = None
    deadline = time.time() + 30
    while time.time() < deadline:
        try:
            client.connect(
                host, port=port, username=user, pkey=pkey,
                look_for_keys=False, allow_agent=False, timeout=5,
            )
            client.close()
            break
        except paramiko.SSHException as exc:
            last = exc
            time.sleep(0.5)
    else:
        raise AssertionError(f"could not SSH to learn host key: {last}")
    if policy.key is None:
        raise AssertionError("sshd presented no host key")
    return policy.key.fingerprint


@dataclass(frozen=True)
class HubTarget:
    container: str
    host: str
    port: int
    user: str
    host_key_fingerprint: str
    client_key_pem: bytes = field(repr=False)


IMAGE_DIR = REPO / "images" / "hub-test-target"
IMAGE = "hub-test-target:local"

T2_SERVE_PY = """\
import json
from http.server import BaseHTTPRequestHandler, HTTPServer

BODY = json.dumps({"live": True, "ready": True, "checks": {}}).encode()


class H(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(BODY)))
        self.end_headers()
        self.wfile.write(BODY)

    def log_message(self, *args):
        pass


HTTPServer(("0.0.0.0", 80), H).serve_forever()
"""
T2_DOCKERFILE = """\
FROM alpine:3.20
WORKDIR /app
COPY package.json ./
COPY packages/server/src/index.ts ./src/index.ts
COPY serve.py /app/serve.py
RUN apk add --no-cache python3
EXPOSE 80
CMD ["python3", "/app/serve.py"]
"""


@pytest.fixture(scope="session")
def hub_target(tmp_path_factory):
    """One privileged systemd container. Does not bind the Hub docker.sock."""
    home = tmp_path_factory.mktemp("t2-pipe-home")
    (home / ".ssh").mkdir()
    previous_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    name = None
    try:
        build = _docker(["build", "-t", IMAGE, str(IMAGE_DIR)], timeout=600)
        if build.returncode != 0:
            raise AssertionError(
                f"hub-test-target image failed to build\n"
                f"stdout:\n{build.stdout}\nstderr:\n{build.stderr}"
            )
        name = f"hub-test-target-pipe-{uuid.uuid4().hex[:8]}"
        launched = _docker(
            [
                "run", "-d", "--name", name, "--privileged", "--cgroupns=host",
                "-p", "127.0.0.1::22", IMAGE,
            ],
            timeout=60,
        )
        if launched.returncode != 0:
            raise AssertionError(
                f"docker run hub-test-target failed\n"
                f"stdout:\n{launched.stdout}\nstderr:\n{launched.stderr}"
            )
        port_line = _docker(["port", name, "22/tcp"], check=True).stdout.strip()
        port = int(port_line.rsplit(":", 1)[1])
        deadline = time.time() + 120
        _wait_exec(
            name,
            ["systemctl", "is-system-running"],
            ready=lambda r: r.stdout.strip() in {"running", "degraded"},
            deadline=deadline,
        )
        _wait_tcp("127.0.0.1", port, deadline=deadline)
        key = ECDSAKey.generate()
        pem_buf = io.StringIO()
        key.write_private_key(pem_buf)
        client_pem = pem_buf.getvalue().encode()
        pubkey = f"{key.get_name()} {key.get_base64()} t2-pipeline\n"
        _exec(name, ["tee", "/home/deploy/.ssh/authorized_keys"], stdin=pubkey, check=True)
        _exec(name, ["chown", "deploy:deploy", "/home/deploy/.ssh/authorized_keys"], check=True)
        _exec(name, ["chmod", "600", "/home/deploy/.ssh/authorized_keys"], check=True)
        fingerprint = _presented_fingerprint("127.0.0.1", port, "deploy", key)
        yield HubTarget(
            container=name,
            host="127.0.0.1",
            port=port,
            user="deploy",
            host_key_fingerprint=fingerprint,
            client_key_pem=client_pem,
        )
    finally:
        if name is not None:
            _docker(["rm", "-f", name], timeout=60)
        if previous_home is None:
            os.environ.pop("HOME", None)
        else:
            os.environ["HOME"] = previous_home


@pytest.mark.t2
@pytest.mark.skipif(not _docker_available(), reason="docker is not available")
@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.req("PIPE-N5-VOLUMES-MODELED")
def test_t2_execute_sample_node_site_twice(hub_target, tmp_path):
    """execute + SshTransport deploys sample-node-site to hub-test-target twice.

    What would make this fail: Hub docker.sock, skipping T2, or a first deploy
    that never reaches succeeded. Uses a COPY-from-tree image (not npm ci).
    """
    from core.models import NetworkZone, Project, Site, Target
    from core.ssh import SshTransport
    from deploys.models import Manifest
    from deploys.pipeline import execute
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

    owner_id = f"t2-pipe-{uuid.uuid4().hex[:12]}"
    zone = NetworkZone.objects.create(name="t2", slug=f"t2-pipe-{uuid.uuid4().hex[:8]}")
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
    slug = f"t2s{uuid.uuid4().hex[:6]}"
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
        "internal_port": 20000,
        "caddy_listen": "127.0.0.1:8088",
    })
    manifest = Manifest.objects.create(site=site, version=1, body=body)
    first = Deployment.objects.create(manifest=manifest)

    try:
        result = execute(first.pk)
    except Exception as exc:
        ssh = SshTransport(target)
        name = f"site-{slug}-{first.pk}"
        ps = ssh.probe(["docker", "ps", "-a", "--format", "{{.Names}} {{.Status}}"])
        logs = ssh.probe(["docker", "logs", name])
        inspect_ip = ssh.probe([
            "docker", "inspect", "--format",
            "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}",
            name,
        ])
        caddy_cfg = ssh.probe(["curl", "-sS", "http://127.0.0.1:2019/config/"])
        smoke = ssh.probe([
            "curl", "-sS", "-D", "-", "-H", f"Host: {slug}.example.test",
            "http://127.0.0.1:8088/healthz.ready",
        ])
        direct = ssh.probe(["curl", "-sS", "http://127.0.0.1:20000/healthz.ready"])
        raise AssertionError(
            f"execute raised {exc!r}\nps={ps.stdout!r}\nlogs={logs.stdout!r} {logs.stderr!r}\n"
            f"ip={inspect_ip.stdout!r}\ndirect={direct.stdout!r} {direct.stderr!r}\n"
            f"smoke={smoke.stdout!r} {smoke.stderr!r}\ncaddy={(caddy_cfg.stdout or '')[:2000]!r}"
        ) from exc
    first.refresh_from_db()
    assert first.status == Deployment.Status.SUCCEEDED, result

    ssh = SshTransport(target)
    volume = f"site-{slug}-data"
    vol = ssh.probe(["docker", "volume", "inspect", volume])
    assert vol.ok, vol.stderr

    second = Deployment.objects.create(manifest=manifest)
    result2 = execute(second.pk)
    second.refresh_from_db()
    assert second.status == Deployment.Status.SUCCEEDED, result2
    vol2 = ssh.probe(["docker", "volume", "inspect", volume])
    assert vol2.ok, vol2.stderr
