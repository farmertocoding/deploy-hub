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


def _image_present(transport, tag):
    return transport.probe(["docker", "image", "inspect", tag]).ok


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
