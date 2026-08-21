"""Idempotent pipeline steps. Shared with the reconciler.

Reads Manifest.body only — never scanner. Builds run on the target Transport,
never on the Hub docker daemon (§B1). Env files and vault markers stay out of
the shipped context.
"""
import hashlib
import io
import json
import os
import tarfile
import threading
import time
from datetime import timedelta
from pathlib import Path

HEARTBEAT_INTERVAL_S = 30
VAULT_CONTEXT_MARKERS = frozenset({
    b"VAULT-TEST-PLAINTEXT-MARKER-do-not-log",
    b"PIPELINE-ENV-SNAPSHOT-MARKER-do-not-log",
})


def image_tag(git_sha, manifest_body):
    """Deterministic tag: git sha plus a stable hash of canonical Manifest.body."""
    digest = hashlib.sha256(
        json.dumps(manifest_body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]
    return f"{git_sha}-{digest}"


def ensure_build(desired):
    """Probe the tag; on miss, put a vault-free context and docker build on the target."""
    transport = desired["transport"]
    body = desired["manifest_body"]
    tag = image_tag(desired["git_sha"], body)
    if _image_present(transport, tag):
        return {"status": "skipped", "tag": tag}

    archive = _context_tar(desired["source_dir"], _dockerfile_from_body(body))
    remote = desired.get("remote_context") or f"/tmp/hub-build/{tag}"
    tar_remote = f"{remote}.tar"
    transport.put(archive, tar_remote)
    heartbeat = desired.get("heartbeat")
    _run(transport, ["mkdir", "-p", remote], heartbeat)
    _run(transport, ["tar", "-xf", tar_remote, "-C", remote], heartbeat)
    result = _run(transport, ["docker", "build", "-t", tag, remote], heartbeat)
    if not result.ok:
        raise RuntimeError(f"docker build failed: {result.stderr}")
    return {"status": "built", "tag": tag}


def ensure_ship(desired):
    """Probe the tag; docker load after put of an image archive only on miss."""
    transport = desired["transport"]
    body = desired["manifest_body"]
    tag = image_tag(desired["git_sha"], body)
    if _image_present(transport, tag):
        return {"status": "skipped", "tag": tag}

    remote = desired.get("remote_context") or f"/tmp/hub-build/{tag}"
    archive_path = f"{remote}.image.tar"
    transport.put(desired.get("image_archive", b""), archive_path)
    result = _run(
        transport, ["docker", "load", "-i", archive_path], desired.get("heartbeat"),
    )
    if not result.ok:
        raise RuntimeError(f"docker load failed: {result.stderr}")
    return {"status": "shipped", "tag": tag}


def ensure_volume(desired):
    """Create per-Site docker volumes on miss; never delete."""
    transport = desired["transport"]
    slug = desired["site_slug"]
    body = desired.get("manifest_body") or {}
    heartbeat = desired.get("heartbeat")
    specs = _volume_specs(slug, body)
    for spec in specs:
        name = spec["name"]
        if _volume_present(transport, name):
            continue
        result = _run(transport, ["docker", "volume", "create", name], heartbeat)
        if not result.ok:
            raise RuntimeError(f"docker volume create failed: {result.stderr}")

    site = desired.get("site")
    if site is not None:
        from core.models import SiteVolume

        for spec in specs:
            SiteVolume.objects.update_or_create(
                site=site,
                name=spec["name"],
                defaults={
                    "container_path": spec["container_path"],
                    "backup_policy": spec["backup_policy"],
                },
            )
    return {"status": "ensured", "names": [spec["name"] for spec in specs]}


def ensure_volume_rollback(desired):
    """T1 refuse: rollback must not docker volume rm. Volumes are per-Site."""
    return {
        "status": "refused",
        "reason": "docker volume rm is not permitted",
        "site_slug": desired.get("site_slug"),
    }


def ensure_migrate(desired):
    """Backup then migrate/pre-cutover unless the step already succeeded."""
    from deploys.models import DeploymentStep

    transport = desired["transport"]
    body = desired.get("manifest_body") or {}
    heartbeat = desired.get("heartbeat")
    step = desired.get("step")
    if step is not None and step.status == DeploymentStep.Status.SUCCEEDED:
        return {"status": "skipped"}

    backup_argv = desired.get("backup_argv")
    if backup_argv is None:
        backup_argv = body.get("backup_argv")
    migrate_argv = desired.get("migrate_argv")
    if migrate_argv is None:
        migrate_argv = body.get("migrate_argv") or body.get("pre_cutover")

    if backup_argv:
        result = _run(transport, list(backup_argv), heartbeat)
        if not result.ok:
            raise RuntimeError(f"backup failed: {result.stderr}")
    if migrate_argv:
        result = _run(transport, list(migrate_argv), heartbeat)
        if not result.ok:
            raise RuntimeError(f"migrate failed: {result.stderr}")

    if step is not None:
        step.status = DeploymentStep.Status.SUCCEEDED
        step.save(update_fields=["status"])
    return {"status": "migrated"}


def ensure_start(desired):
    """Start the named green container; recreate stops the old writer first."""
    transport = desired["transport"]
    heartbeat = desired.get("heartbeat")
    name = _container_name(desired)
    running = _container_running(transport, name)
    if running is True:
        return {"status": "skipped", "name": name}

    if running is False:
        result = _run(transport, ["docker", "start", name], heartbeat)
        if not result.ok:
            raise RuntimeError(f"docker start failed: {result.stderr}")
        return {"status": "started", "name": name}

    strategy = _deploy_strategy(desired)
    if strategy == "recreate":
        site = desired.get("site")
        if site is not None:
            _set_maintenance_until(site, desired)
        old = desired.get("old_container")
        if old and old != name and _container_running(transport, old) is True:
            result = _run(transport, ["docker", "stop", old], heartbeat)
            if not result.ok:
                raise RuntimeError(f"docker stop failed: {result.stderr}")

    result = _run(transport, _docker_run_argv(desired, name), heartbeat)
    if not result.ok:
        raise RuntimeError(f"docker run failed: {result.stderr}")
    return {"status": "started", "name": name}


def ensure_health_check(desired):
    """Poll pinned /healthz JSON until ready; frozen checks fail immediately."""
    timeout = _warmup_timeout_s(desired)
    sleep = desired.get("sleep") or time.sleep
    now = desired.get("now") or time.monotonic
    interval = desired.get("poll_interval_s", 1)
    deadline = now() + timeout
    prev_checks = None
    while True:
        payload = _healthz_payload(desired)
        if payload.get("ready"):
            return {"status": "ready", "healthz": payload}
        checks = payload.get("checks")
        if prev_checks is not None and checks == prev_checks:
            raise RuntimeError("healthz checks frozen while not ready")
        prev_checks = checks
        if now() >= deadline:
            raise RuntimeError("warmup timeout: never ready")
        sleep(interval)


def _container_name(desired):
    return f"site-{desired['site_slug']}-{desired['deployment_id']}"


def _deploy_strategy(desired):
    body = desired.get("manifest_body") or {}
    if body.get("local_state") or body.get("exclusive_upstream"):
        return "recreate"
    if body.get("deploy_strategy"):
        return body["deploy_strategy"]
    site = desired.get("site")
    if site is not None:
        strategy = getattr(site, "deploy_strategy", None)
        if strategy:
            return strategy
    return "blue_green"


def _container_running(transport, name):
    result = transport.probe([
        "docker", "inspect", "--format", "{{.State.Running}}", name,
    ])
    if not result.ok:
        return None
    return result.stdout.strip().lower() in {"true", "running", "1"}


def _docker_run_argv(desired, name):
    argv = ["docker", "run", "-d", "--name", name]
    body = desired.get("manifest_body") or {}
    for spec in _volume_specs(desired["site_slug"], body):
        argv.extend(["-v", f"{spec['name']}:{spec['container_path']}"])
    argv.append(desired["image_tag"])
    return argv


def _set_maintenance_until(site, desired):
    from django.utils import timezone

    site.maintenance_until = timezone.now() + timedelta(seconds=_warmup_timeout_s(desired))
    if hasattr(site, "save"):
        site.save(update_fields=["maintenance_until"])


def _warmup_timeout_s(desired):
    body = desired.get("manifest_body") or {}
    if body.get("warmup_timeout_s") is not None:
        return int(body["warmup_timeout_s"])
    nested = (body.get("healthz") or {}).get("warmup_timeout_s")
    if nested is not None:
        return int(nested)
    site = desired.get("site")
    if site is not None and getattr(site, "warmup_timeout_s", None) is not None:
        return int(site.warmup_timeout_s)
    return 60


def _readiness_path(desired):
    body = desired.get("manifest_body") or {}
    if body.get("readiness_path"):
        return body["readiness_path"]
    nested = (body.get("healthz") or {}).get("readiness_path")
    if nested:
        return nested
    site = desired.get("site")
    if site is not None and getattr(site, "readiness_path", None):
        return site.readiness_path
    return "/healthz.ready"


def _healthz_payload(desired):
    fetch = desired.get("healthz_fetch")
    if fetch is not None:
        return fetch()
    transport = desired["transport"]
    name = _container_name(desired)
    path = _readiness_path(desired)
    ip_r = transport.probe([
        "docker", "inspect", "--format", "{{.NetworkSettings.IPAddress}}", name,
    ])
    ip = (ip_r.stdout or "").strip() or "127.0.0.1"
    result = transport.probe(["curl", "-sf", f"http://{ip}{path}"])
    if not result.ok or not (result.stdout or "").strip():
        return {"live": False, "ready": False, "checks": {}}
    return json.loads(result.stdout)


def _image_present(transport, tag):
    return transport.probe(["docker", "image", "inspect", tag]).ok


def _volume_present(transport, name):
    return transport.probe(["docker", "volume", "inspect", name]).ok


def _volume_specs(slug, body):
    """Always site-{slug}-data, then further Manifest volumes; names deduped."""
    default_name = f"site-{slug}-data"
    specs = []
    seen = set()

    def add(name, container_path, backup_policy):
        if name in seen:
            return
        seen.add(name)
        specs.append({
            "name": name,
            "container_path": container_path or "/data",
            "backup_policy": backup_policy or "none",
        })

    listed = body.get("volumes") or []
    match = next(
        (item for item in listed if isinstance(item, dict) and item.get("name") == default_name),
        {},
    )
    add(
        default_name,
        match.get("container_path"),
        match.get("backup_policy"),
    )
    for item in listed:
        if not isinstance(item, dict) or not item.get("name"):
            continue
        add(item.get("name"), item.get("container_path"), item.get("backup_policy"))
    return specs


def _run(transport, argv, heartbeat=None, timeout=3600):
    """transport.run, with optional heartbeat immediately before and on a 30s cadence."""
    if heartbeat is None:
        return transport.run(argv, timeout=timeout)
    heartbeat()
    done = threading.Event()

    def pulse():
        while not done.wait(HEARTBEAT_INTERVAL_S):
            heartbeat()

    threading.Thread(target=pulse, daemon=True).start()
    try:
        return transport.run(argv, timeout=timeout)
    finally:
        done.set()


def _dockerfile_from_body(manifest_body):
    template = manifest_body.get("dockerfile_template")
    if template:
        return template
    runtime = (manifest_body.get("runtime") or "").lower()
    if not runtime:
        kind = ((manifest_body.get("components") or {}).get("service") or {}).get("kind")
        runtime = (kind or "").lower()
    if runtime in {"python", "django"}:
        return (
            "FROM python:3.12-slim\n"
            "WORKDIR /app\n"
            "COPY requirements.txt .\n"
            "RUN pip install --require-hashes -r requirements.txt\n"
            "COPY . .\n"
            'CMD ["python", "-m", "app"]\n'
        )
    return (
        "FROM node:22-alpine\n"
        "WORKDIR /app\n"
        "COPY package.json package-lock.json* ./\n"
        "RUN npm ci\n"
        "COPY . .\n"
        'CMD ["node", "app.js"]\n'
    )


def _context_tar(source_dir, dockerfile_text):
    source = Path(source_dir)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        for dirpath, _dirnames, filenames in os.walk(source, followlinks=False):
            for filename in filenames:
                if filename == "Dockerfile" or _is_env_filename(filename):
                    continue
                path = Path(dirpath) / filename
                if path.is_symlink():
                    continue
                try:
                    data = path.read_bytes()
                except OSError:
                    continue
                if data in VAULT_CONTEXT_MARKERS:
                    continue
                _add_bytes(tf, path.relative_to(source).as_posix(), data)
        _add_bytes(tf, "Dockerfile", dockerfile_text.encode())
    return buf.getvalue()


def _is_env_filename(name):
    return name == ".env" or name.startswith(".env.") or name.endswith(".env")


def _add_bytes(tf, name, data):
    info = tarfile.TarInfo(name=name)
    info.size = len(data)
    tf.addfile(info, io.BytesIO(data))
