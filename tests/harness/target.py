"""Shared T2 hub-test-target launcher. Import from T2 modules; not conftest."""
from __future__ import annotations

import io
import json
import os
import pathlib
import shutil
import socket
import subprocess
import tempfile
import time
import uuid
from dataclasses import dataclass, field

import paramiko
import pytest
from paramiko import ECDSAKey

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
IMAGE_DIR = REPO / "images" / "hub-test-target"
IMAGE = "hub-test-target:local"
SOCK = "/var/run/docker.sock"
SAMPLE_NODE_SITE = REPO / "sample-node-site"
SAMPLE_NODE_SITE_DOCKERFILE = REPO / "images" / "sample-node-site" / "Dockerfile"
SAMPLE_NODE_SITE_IMAGE = "sample-node-site:t2"


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
    """Run docker with an argv list — never a shell string."""
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


def _image_in_target(container, tag):
    return _exec(
        container, ["docker", "image", "inspect", tag], timeout=30,
    ).returncode == 0


def host_build_image(tag, context, *, dockerfile=None, timeout=600):
    """docker build on the Hub host (overlay). Never on hub-test-target."""
    argv = ["build", "-t", tag]
    if dockerfile is not None:
        argv.extend(["-f", str(dockerfile)])
    argv.append(str(context))
    return _docker(argv, timeout=timeout, check=True)


def host_build_sample_node_site():
    """Build images/sample-node-site/Dockerfile against sample-node-site/."""
    host_build_image(
        SAMPLE_NODE_SITE_IMAGE,
        SAMPLE_NODE_SITE,
        dockerfile=SAMPLE_NODE_SITE_DOCKERFILE,
    )
    return SAMPLE_NODE_SITE_IMAGE


def load_image_into_target(container, image, tag=None, *, timeout=300):
    """Host docker save → cp → inner docker load → tag. No Hub sock bind.

    Target dockerd on vfs times out pulling registry-1.docker.io. The
    D-025 path is this load, not in-target npm ci.
    """
    tag = tag or image
    if _image_in_target(container, tag):
        return tag
    if image != tag and _image_in_target(container, image):
        _exec(container, ["docker", "tag", image, tag], timeout=30, check=True)
        return tag

    fd, tar_path = tempfile.mkstemp(prefix="hub-img-", suffix=".tar")
    os.close(fd)
    remote = f"/tmp/hub-load-{uuid.uuid4().hex[:8]}.tar"
    try:
        _docker(["save", "-o", tar_path, image], timeout=timeout, check=True)
        _docker(["cp", tar_path, f"{container}:{remote}"], timeout=timeout, check=True)
        _exec(container, ["docker", "load", "-i", remote], timeout=timeout, check=True)
        if tag != image:
            _exec(container, ["docker", "tag", image, tag], timeout=30, check=True)
        _exec(container, ["rm", "-f", remote], timeout=30)
    finally:
        try:
            os.unlink(tar_path)
        except OSError:
            pass
    return tag


def ensure_image_on_target(container, image, tag=None):
    """Host-build is the caller's job; this only loads/tags if the target misses."""
    return load_image_into_target(container, image, tag)


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
        f"waiting for {argv!r} in {container}: last exit={last.returncode if last else None} "
        f"stdout={last.stdout if last else ''} stderr={last.stderr if last else ''}"
    )


def hub_target_run_argv(name):
    """docker run argv for hub-test-target. Never binds Hub docker.sock."""
    return [
        "run",
        "-d",
        "--name",
        name,
        "--privileged",
        "--cgroupns=host",
        "-p",
        "127.0.0.1::22",
        IMAGE,
    ]


@dataclass(frozen=True)
class HubTarget:
    container: str
    host: str
    port: int
    user: str
    host_key_fingerprint: str
    client_key_pem: bytes = field(repr=False)


def remove_site_containers(container):
    """Remove leftover site-* containers inside the target between tests.

    Every T2 site publishes 127.0.0.1:20000 inside the shared target
    (deploys/steps.py internal_port default), so a survivor from one test makes
    the next test's docker run fail with "port is already allocated". Listing
    is tolerant — inner dockerd may not be active if the test deployed nothing
    — but a failed rm raises so a broken cleanup names itself instead of the
    next test.
    """
    listing = _exec(
        container,
        ["docker", "ps", "-aq", "--filter", "name=^site-"],
        timeout=60,
    )
    if listing.returncode != 0:
        return
    ids = listing.stdout.split()
    if ids:
        _exec(container, ["docker", "rm", "-f", *ids], timeout=60, check=True)


def remove_site_caddy_servers(container):
    """DELETE leftover site-* Caddy servers inside the target between tests.

    ensure_route_tls PUTs a per-slug server listening on the shared
    127.0.0.1:8088, so a survivor makes the next test's PUT fail ("caddy put
    failed": the listen address is already bound). Listing is tolerant — caddy
    admin may be unreachable if the test routed nothing — but a failed DELETE
    raises so a broken cleanup names itself instead of the next test.
    """
    listing = _exec(
        container,
        ["curl", "-sf", "http://127.0.0.1:2019/config/apps/http/servers"],
        timeout=30,
    )
    if listing.returncode != 0:
        return
    try:
        servers = json.loads(listing.stdout or "null") or {}
    except json.JSONDecodeError:
        return
    for server_id in servers:
        if server_id.startswith("site-"):
            _exec(
                container,
                [
                    "curl", "-sf", "-X", "DELETE",
                    f"http://127.0.0.1:2019/config/apps/http/servers/{server_id}",
                ],
                timeout=30,
                check=True,
            )


@pytest.fixture
def hub_target(hub_target_session):
    """Per-test view of the session target; isolates T2 tests from each other."""
    try:
        yield hub_target_session
    finally:
        remove_site_containers(hub_target_session.container)
        remove_site_caddy_servers(hub_target_session.container)


@pytest.fixture(scope="session")
def hub_target_session(tmp_path_factory):
    """One privileged systemd container. Does not bind the Hub docker.sock."""
    home = tmp_path_factory.mktemp("t2-home")
    (home / ".ssh").mkdir()
    previous_home = os.environ.get("HOME")
    os.environ["HOME"] = str(home)
    name = None
    try:
        build = _docker(
            ["build", "-t", IMAGE, str(IMAGE_DIR)],
            timeout=600,
        )
        if build.returncode != 0:
            raise AssertionError(
                f"hub-test-target image failed to build\n"
                f"stdout:\n{build.stdout}\nstderr:\n{build.stderr}"
            )

        name = f"hub-test-target-{uuid.uuid4().hex[:8]}"
        # Publish 22 on localhost only. Never `-v /var/run/docker.sock`.
        launched = _docker(
            hub_target_run_argv(name),
            timeout=60,
        )
        if launched.returncode != 0:
            raise AssertionError(
                f"docker run hub-test-target failed\n"
                f"stdout:\n{launched.stdout}\nstderr:\n{launched.stderr}"
            )

        port_line = _docker(["port", name, "22/tcp"], check=True).stdout.strip()
        # e.g. 127.0.0.1:55000
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
        pubkey = f"{key.get_name()} {key.get_base64()} t2-hub-test-target\n"
        _exec(
            name,
            ["tee", "/home/deploy/.ssh/authorized_keys"],
            stdin=pubkey,
            check=True,
        )
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


def _presented_fingerprint(host, port, user, pkey):
    """Learn the host key paramiko actually presents, then close. Pin that."""

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
                host,
                port=port,
                username=user,
                pkey=pkey,
                look_for_keys=False,
                allow_agent=False,
                timeout=5,
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
