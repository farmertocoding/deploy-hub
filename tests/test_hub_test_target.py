"""T2: hub-test-target — real sshd, systemd PID 1, inner docker on vfs, no Hub sock.

Live tests skip only when docker is missing. `make test` does not collect this
file (see pytest_ignore_collect in conftest); `make test-t2` and an explicit
path do.
"""
from __future__ import annotations

import io
import json
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

REPO = pathlib.Path(__file__).resolve().parent.parent
IMAGE_DIR = REPO / "images" / "hub-test-target"
IMAGE = "hub-test-target:local"
DROPIN = "/etc/ssh/sshd_config.d/99-hub-hardening.conf"
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
    if not _docker_available():
        pytest.skip("docker is not available")

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
            [
                "run",
                "-d",
                "--name",
                name,
                "--privileged",
                "--cgroupns=host",
                "-p",
                "127.0.0.1::22",
                IMAGE,
            ],
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


def test_sshd_banner(hub_target):
    """Container sshd speaks SSH-2.0 on the published port.

    What would make this fail: no sshd, or a fake banner from a stub.
    """
    with socket.create_connection((hub_target.host, hub_target.port), timeout=5) as sock:
        banner = sock.recv(256).decode(errors="replace")
    assert banner.startswith("SSH-2.0")


def test_systemd_is_pid1_running(hub_target):
    """systemd is PID 1 and the system is running (D-015).

    What would make this fail: a non-systemd entrypoint, or a container that
    never reaches `systemctl is-system-running` → running.
    """
    comm = _exec(hub_target.container, ["cat", "/proc/1/comm"], check=True).stdout.strip()
    assert comm == "systemd"
    status = _exec(
        hub_target.container, ["systemctl", "is-system-running"], check=True
    ).stdout.strip()
    assert status == "running"


def test_sshd_t_and_dropin(hub_target):
    """HARD-R2 shape: sshd -t is clean and the hardening drop-in is installed.

    What would make this fail: missing drop-in, or sshd -t failing. Not a ufw test.
    """
    checked = _exec(hub_target.container, ["sshd", "-t"], check=True)
    assert checked.returncode == 0
    dropin = _exec(hub_target.container, ["cat", DROPIN], check=True).stdout
    assert "PasswordAuthentication no" in dropin
    assert "PermitRootLogin no" in dropin


def test_inner_docker_vfs_builds(hub_target):
    """Inner dockerd uses vfs and can docker build (D-015; overlay-on-overlay fails).

    What would make this fail: storage-driver overlay, or bind-mounting Hub's sock
    so 'inner' docker is actually the Hub's.
    """
    deadline = time.time() + 90
    _wait_exec(
        hub_target.container,
        ["systemctl", "is-active", "docker"],
        ready=lambda r: r.stdout.strip() == "active",
        deadline=deadline,
    )
    driver = _exec(
        hub_target.container,
        ["docker", "info", "--format", "{{.Driver}}"],
        timeout=30,
        check=True,
    ).stdout.strip()
    assert driver == "vfs"

    dockerfile = "FROM alpine:3.20\nCMD [\"echo\", \"built-inside\"]\n"
    _exec(hub_target.container, ["mkdir", "-p", "/tmp/t2-vfs-build"], check=True)
    _exec(
        hub_target.container,
        ["tee", "/tmp/t2-vfs-build/Dockerfile"],
        stdin=dockerfile,
        check=True,
    )
    built = _exec(
        hub_target.container,
        ["docker", "build", "-t", "t2-vfs-probe", "/tmp/t2-vfs-build"],
        timeout=180,
        check=True,
    )
    assert built.returncode == 0
    ran = _exec(
        hub_target.container,
        ["docker", "run", "--rm", "t2-vfs-probe"],
        timeout=60,
        check=True,
    )
    assert "built-inside" in ran.stdout


@pytest.mark.req("SEC-B1-BUILD-OFFHUB")
def test_hub_docker_sock_not_bound(hub_target):
    """Hub docker.sock is not mounted into the target (§B1 / D-015).

    What would make this fail: `-v /var/run/docker.sock` on docker run, or a
    FROM jrei/systemd-ubuntu pin (amd64-only, banned).
    """
    inspect = json.loads(
        _docker(["inspect", hub_target.container], check=True).stdout
    )[0]
    for mount in inspect.get("Mounts") or []:
        src = mount.get("Source") or ""
        dst = mount.get("Destination") or ""
        assert SOCK not in (src, dst)
        assert not src.endswith("docker.sock")
        assert not dst.endswith("docker.sock")
    for bind in inspect.get("HostConfig", {}).get("Binds") or []:
        assert SOCK not in bind
    dockerfile = (IMAGE_DIR / "Dockerfile").read_text()
    from_lines = [
        line.strip()
        for line in dockerfile.splitlines()
        if line.lstrip().upper().startswith("FROM")
    ]
    assert from_lines, "Dockerfile has no FROM"
    assert all("jrei/systemd-ubuntu" not in line for line in from_lines)


@pytest.mark.django_db
@pytest.mark.req("SEC-68-HOSTKEY-PINNING")
def test_ssh_transport_run_and_put_roundtrip(hub_target):
    """SshTransport talks to real sshd: run + SFTP put, with the pin matching.

    What would make this fail: AutoAddPolicy, a stubbed client, or put-via-heredoc.
    """
    from core.models import NetworkZone, Target
    from core.ssh import SshTransport
    from vault import service
    from vault.models import Secret

    owner_id = f"t2-ssh-{uuid.uuid4().hex[:12]}"
    zone = NetworkZone.objects.create(name="t2", slug=f"t2-{uuid.uuid4().hex[:8]}")
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

    transport = SshTransport(target)
    ident = transport.run(["id", "-un"])
    assert ident.ok, ident.stderr
    assert ident.stdout.strip() == hub_target.user

    remote = f"/tmp/hub-t2-{uuid.uuid4().hex[:8]}"
    payload = b"t2-roundtrip-bytes\n"
    transport.put(payload, remote, mode=0o644)
    assert transport.get(remote) == payload
