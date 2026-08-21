"""Shared T2 hub-test-target launcher. Import from T2 modules; not conftest."""
from __future__ import annotations

import io
import os
import pathlib
import shutil
import socket
import subprocess
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


@pytest.fixture(scope="session")
def hub_target(tmp_path_factory):
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
