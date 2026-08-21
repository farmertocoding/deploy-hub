"""T2: hub-test-target — real sshd, systemd PID 1, inner docker on vfs, no Hub sock.

`make test` is `-m "not t2"` (T1-fast). The run-report records these nodeids as
skipped. `make test-t2` runs the t2 mark. Live bodies skip only if docker is missing.
"""
from __future__ import annotations

import json
import shutil
import socket
import subprocess
import time
import uuid

import pytest

pytest_plugins = ["tests.harness.target"]

DROPIN = "/etc/ssh/sshd_config.d/99-hub-hardening.conf"


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


pytestmark = [
    pytest.mark.t2,
    pytest.mark.skipif(not _docker_available(), reason="docker is not available"),
]


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
    from tests.harness.target import _exec

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
    from tests.harness.target import _exec

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
    from tests.harness.target import _exec, _wait_exec

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
    from tests.harness.target import IMAGE_DIR, SOCK, _docker

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
