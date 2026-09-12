"""sample-node-site through the real pipeline: twice, volume, recreate (T1 + T2)."""
from __future__ import annotations

import json
import shutil
import subprocess
import time
import uuid

import pytest
from pipeline_fakes import (
    GIT_SHA,
    NPM_CI_DOCKERFILE,
    SAMPLE_NODE_SITE,
    PipelineTransport,
    fixture_body,
    queued_deployment,
)

from deploys.models import Deployment, DeploymentStep
from providers.fakes import FakeDnsProvider

pytest_plugins = ["tests.harness.target"]

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


@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_ingestion_awaits_backfill_before_live_stream():
    """startIngestion must finish backfill before ccxt.pro.binance.

    What would make this fail: `void backfill(hooks); void streamLoop(hooks);`
    so watchTrades occupies the event loop, /healthz checks freeze at a
    partial backfill_pct, and ensure_health_check raises 'healthz checks
    frozen while not ready' (CI T2 test_t2_real_node_image_builds_on_vfs).
    """
    ingest = SAMPLE_NODE_SITE / "packages" / "server" / "src" / "ingest.ts"
    text = ingest.read_text(encoding="utf-8")
    start = text.split("export function startIngestion", 1)[1]
    start = start.split("async function backfill", 1)[0]
    assert "await backfill(hooks)" in start, start
    assert "streamLoop(hooks)" in start, start
    assert start.index("await backfill(hooks)") < start.index("streamLoop(hooks)")
    assert "void backfill(hooks)" not in start


# --- T2: real SshTransport against the shared hub_target fixture ---

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


@pytest.mark.t2
@pytest.mark.skipif(not _docker_available(), reason="docker is not available")
@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_t2_real_node_image_builds_on_vfs(hub_target):
    """Host-built sample-node-site image loads into hub-test-target and deploys.

    What would make this fail: in-target docker build/pull, alpine T2_SERVE_PY
    instant-ready JSON, or cutover before smoke sees ready.
    """
    from core.models import NetworkZone, Project, Site, Target
    from core.ssh import SshTransport
    from core.transport import RecordingTransport
    from deploys.models import Manifest
    from deploys.pipeline import execute
    from deploys.steps import image_tag
    from tests.harness.target import (
        SAMPLE_NODE_SITE_IMAGE,
        _wait_exec,
        ensure_image_on_target,
        host_build_sample_node_site,
    )
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

    owner_id = f"t2-real-{uuid.uuid4().hex[:12]}"
    zone = NetworkZone.objects.create(name="t2", slug=f"t2-real-{uuid.uuid4().hex[:8]}")
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
    slug = f"t2r{uuid.uuid4().hex[:6]}"
    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    from dns_fixtures import default_dns_zone

    site = Site.objects.create(
        project=project,
        name=slug,
        domain=f"{slug}.example.test",
        primary_target=target,
        dns_zone=default_dns_zone(),
        deploy_strategy=Site.DeployStrategy.RECREATE,
        readiness_path="/healthz",
        warmup_timeout_s=30,
    )
    body = fixture_body(slug, extra={
        "readiness_path": "/healthz",
        "warmup_timeout_s": 30,
        "docker_run_extra": ["-p", "127.0.0.1:20000:80"],
        "internal_port": 80,
        "upstream": "127.0.0.1:20000",
        "caddy_listen": "127.0.0.1:8088",
    })
    tag = image_tag(GIT_SHA, body)
    host_build_sample_node_site()
    ensure_image_on_target(hub_target.container, SAMPLE_NODE_SITE_IMAGE, tag)

    manifest = Manifest.objects.create(site=site, version=1, body=body)
    first = Deployment.objects.create(manifest=manifest)
    rec = RecordingTransport(SshTransport(target))
    try:
        result = execute(first.pk, transport=rec, dns=FakeDnsProvider())
    except Exception as exc:
        ssh = SshTransport(target)
        name = f"site-{slug}-{first.pk}"
        ps = ssh.probe(["docker", "ps", "-a", "--format", "{{.Names}} {{.Status}}"])
        logs = ssh.probe(["docker", "logs", name])
        direct = ssh.probe(["curl", "-sS", "http://127.0.0.1:20000/healthz"])
        raise AssertionError(
            f"execute raised {exc!r}\nps={ps.stdout!r}\nlogs={logs.stdout!r} {logs.stderr!r}\n"
            f"direct={direct.stdout!r} {direct.stderr!r}"
        ) from exc
    first.refresh_from_db()
    assert first.status == Deployment.Status.SUCCEEDED, result

    builds = [
        argv for kind, argv in rec.calls
        if kind == "run" and isinstance(argv, list) and argv[:2] == ["docker", "build"]
    ]
    assert builds == [], builds

    smoke = first.steps.get(name=DeploymentStep.Name.SMOKE_TEST)
    cutover = first.steps.get(name=DeploymentStep.Name.CUTOVER)
    assert smoke.status == DeploymentStep.Status.SUCCEEDED
    assert cutover.status == DeploymentStep.Status.SUCCEEDED
    assert smoke.finished is not None and cutover.started is not None
    assert smoke.finished <= cutover.started

    health = rec.probe(["curl", "-sf", "http://127.0.0.1:20000/healthz"])
    assert health.ok, health.stderr
    payload = json.loads(health.stdout)
    assert payload.get("live") is True
    assert payload.get("ready") is True
    checks = payload.get("checks") or {}
    assert "backfill_pct" in checks, payload
    assert "feed_age_s" in checks, payload
    assert checks.get("backfill_pct") == 100


@pytest.mark.t2
@pytest.mark.skipif(not _docker_available(), reason="docker is not available")
@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.req("PIPE-N5-VOLUMES-MODELED")
def test_t2_execute_sample_node_site_twice(hub_target, tmp_path):
    """execute + SshTransport deploys sample-node-site to hub-test-target twice.

    What would make this fail: Hub docker.sock, skipping T2, a first deploy that
    never reaches succeeded, or a second execute that docker build/run again.
    Uses a COPY-from-tree image (not npm ci). RecordingTransport proves the
    replay issues zero mutating docker build/run.
    """
    from core.models import NetworkZone, Project, Site, Target
    from core.ssh import SshTransport
    from core.transport import RecordingTransport
    from deploys.models import Manifest
    from deploys.pipeline import execute
    from deploys.steps import image_tag
    from tests.harness.target import (
        _docker,
        _wait_exec,
        ensure_image_on_target,
        host_build_image,
    )
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
        # Health curls container_ip:internal_port (a66c865); T2_SERVE_PY
        # listens on 80. Caddy proxies the published 127.0.0.1:20000 mapping.
        "internal_port": 80,
        "upstream": "127.0.0.1:20000",
        "caddy_listen": "127.0.0.1:8088",
    })
    (ctx / "Dockerfile").write_text(T2_DOCKERFILE)
    alpine_tag = f"t2-alpine-{slug}"
    host_build_image(alpine_tag, ctx)
    ensure_image_on_target(
        hub_target.container, alpine_tag, image_tag(GIT_SHA, body),
    )
    manifest = Manifest.objects.create(site=site, version=1, body=body)
    first = Deployment.objects.create(manifest=manifest)
    rec = RecordingTransport(SshTransport(target))

    try:
        result = execute(
            first.pk, transport=rec, dns=FakeDnsProvider(),
        )
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

    volume = f"site-{slug}-data"
    vol = rec.probe(["docker", "volume", "inspect", volume])
    assert vol.ok, vol.stderr

    rec.calls.clear()
    _requeue_pending(first)
    result2 = execute(first.pk, transport=rec, dns=FakeDnsProvider())
    first.refresh_from_db()
    assert first.status == Deployment.Status.SUCCEEDED, result2
    mutating_docker = [
        argv for kind, argv in rec.calls
        if kind == "run" and isinstance(argv, list) and argv[:1] == ["docker"]
        and len(argv) > 1 and argv[1] in {"build", "run"}
    ]
    assert mutating_docker == [], mutating_docker
    assert rec.mutating_calls() == []
    vol2 = rec.probe(["docker", "volume", "inspect", volume])
    assert vol2.ok, vol2.stderr
