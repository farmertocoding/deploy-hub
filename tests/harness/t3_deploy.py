"""T3 Multipass deploy helpers. One session VM; never bind Hub docker.sock.

Shared by tests/test_t3_ufw_truth.py and tests/test_t3_deploy.py via
pytest_plugins so a nightly run launches one VM, not two.

Tailscale cannot join a tailnet here (no test-plane auth key; §B9). Harden
uses the documented test-only env HUB_T3_UFW_ONLY=1 / HUB_T3_ALLOW_NO_MESH=1
so ufw+fail2ban still enable. That path does not prove HARD-V2.
"""
from __future__ import annotations

import io
import json
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import pytest
from paramiko import ECDSAKey

from tests.harness.multipass import (
    CLOUD_INIT,
    NAME_PREFIX,
    MultipassVM,
    exec,
    exec_result,
    info_ipv4,
    launch,
    transfer,
    wait_exec,
)
from tests.harness.reaper import reap_test_plane
from tests.harness.target import _presented_fingerprint

REPO = Path(__file__).resolve().parent.parent.parent
SAMPLE_SITE = REPO / "sample-site"
SAMPLE_NODE_SITE = REPO / "sample-node-site"
SCRIPTS = REPO / "scripts"
HARDEN_SH = SCRIPTS / "harden-ubuntu.sh"
VERIFY_SH = SCRIPTS / "verify-hardening.sh"
SOCK = "/var/run/docker.sock"
HUB_MESH_IP = "100.64.1.8"
DUMMY_MESH_NOTE = (
    "T3 Multipass has no tailnet; HUB_MESH_IP is a singular dummy for ignoreip"
)

# Delayed-ready + /data marker + one ws frame. The real sample-node-site
# process waits on a live CCXT feed; this image keeps the fixture tree as
# context and proves overlay2 + pipeline + Caddy on the VM.
NODE_SITE_DOCKERFILE = """\
FROM node:22-bookworm-slim
WORKDIR /app
COPY package.json ./
RUN printf '%s\\n' \
  'const http = require("http");' \
  'const fs = require("fs");' \
  'const started = Date.now();' \
  'const delayMs = Number(process.env.DELAYED_READY_MS || "2000");' \
  'const port = Number(process.env.PORT || "8080");' \
  'try { fs.mkdirSync("/data", { recursive: true });' \
  '  if (!fs.existsSync("/data/marker")) {' \
  '    fs.writeFileSync("/data/marker", process.env.T3_MARKER || "v1");' \
  '  }' \
  '} catch (e) {}' \
  'function ready() { return Date.now() - started >= delayMs; }' \
  'function health() {' \
  '  return JSON.stringify({' \
  '    live: true,' \
  '    ready: ready(),' \
  '    checks: { uptime_s: (Date.now() - started) / 1000, delayed_ready_ms: delayMs }' \
  '  });' \
  '}' \
  'const server = http.createServer((req, res) => {' \
  '  const url = req.url.split("?")[0];' \
  '  if (url === "/healthz" || url === "/healthz.ready") {' \
  '    const body = health();' \
  '    res.writeHead(200, { "Content-Type": "application/json" });' \
  '    res.end(body);' \
  '    return;' \
  '  }' \
  '  res.writeHead(404);' \
  '  res.end();' \
  '});' \
  'server.on("upgrade", (req, socket) => {' \
  '  const url = (req.url || "").split("?")[0];' \
  '  if (url !== "/ws" && url !== "/ws/levels") { socket.destroy(); return; }' \
  '  const key = req.headers["sec-websocket-key"];' \
  '  if (!key) { socket.destroy(); return; }' \
  '  const crypto = require("crypto");' \
  '  const accept = crypto.createHash("sha1")' \
  '    .update(key + "258EAFA5-E914-47DA-95CA-C5AB0DC85B11")' \
  '    .digest("base64");' \
  '  socket.write(' \
  '    "HTTP/1.1 101 Switching Protocols\\r\\n" +' \
  '    "Upgrade: websocket\\r\\n" +' \
  '    "Connection: Upgrade\\r\\n" +' \
  '    "Sec-WebSocket-Accept: " + accept + "\\r\\n\\r\\n"' \
  '  );' \
  '  const payload = Buffer.from(JSON.stringify({ type: "snapshot", levels: [] }));' \
  '  const header = Buffer.alloc(2);' \
  '  header[0] = 0x81;' \
  '  header[1] = payload.length;' \
  '  socket.write(Buffer.concat([header, payload]));' \
  '});' \
  'server.listen(port, "0.0.0.0");' \
  > /app/serve.js
EXPOSE 8080
CMD ["node", "/app/serve.js"]
"""

WS_CLIENT_PY = b"""\
import base64
import os
import socket
import sys


def main(host, port, path, server_name):
    key = base64.b64encode(os.urandom(16)).decode()
    req = (
        f"GET {path} HTTP/1.1\\r\\n"
        f"Host: {server_name}\\r\\n"
        f"Upgrade: websocket\\r\\n"
        f"Connection: Upgrade\\r\\n"
        f"Sec-WebSocket-Key: {key}\\r\\n"
        f"Sec-WebSocket-Version: 13\\r\\n"
        f"\\r\\n"
    )
    with socket.create_connection((host, int(port)), timeout=10) as sock:
        sock.sendall(req.encode())
        header = b""
        while b"\\r\\n\\r\\n" not in header:
            chunk = sock.recv(4096)
            if not chunk:
                break
            header += chunk
        if b"\\r\\n\\r\\n" not in header:
            sys.stderr.write("no websocket handshake\\n")
            return 2
        head, rest = header.split(b"\\r\\n\\r\\n", 1)
        if b"101" not in head.split(b"\\r\\n", 1)[0]:
            sys.stderr.write(head.decode("latin1", "replace") + "\\n")
            return 2
        data = rest
        while len(data) < 2:
            more = sock.recv(4096)
            if not more:
                break
            data += more
        if len(data) < 2:
            return 3
        opcode = data[0] & 0x0F
        ln = data[1] & 0x7F
        idx = 2
        if ln == 126:
            while len(data) < 4:
                data += sock.recv(4096)
            ln = int.from_bytes(data[2:4], "big")
            idx = 4
        elif ln == 127:
            while len(data) < 10:
                data += sock.recv(4096)
            ln = int.from_bytes(data[2:10], "big")
            idx = 10
        while len(data) < idx + ln:
            more = sock.recv(4096)
            if not more:
                break
            data += more
        payload = data[idx : idx + ln]
        sys.stdout.write(payload.decode("utf-8", "replace"))
        return 0 if opcode == 1 and payload else 1


if __name__ == "__main__":
    sys.exit(main(*sys.argv[1:4], sys.argv[4] if len(sys.argv) > 4 else sys.argv[1]))
"""


@dataclass
class T3VM:
    name: str
    ipv4: str
    user: str
    host_key_fingerprint: str
    client_key_pem: bytes = field(repr=False)
    ssh_from: str = ""
    provision_result: object = None
    hardened: bool = False
    harden_result: object = None

    def mp(self):
        return MultipassVM(name=self.name, ipv4=self.ipv4, user=self.user)


def sample_site_available():
    return SAMPLE_SITE.is_dir() and (SAMPLE_SITE / "Dockerfile").is_file()


def sample_site_missing_reason():
    return "sample-site/ is not on this worktree (sibling Task 5)"


def allow_test_zone(settings, slug):
    settings.HUB_TEST_MODE = True
    slugs = list(getattr(settings, "HUB_TEST_ZONE_SLUGS", None) or [])
    if slug not in slugs:
        settings.HUB_TEST_ZONE_SLUGS = [*slugs, slug]


def _write_lease(name):
    root = REPO / "tmp"
    root.mkdir(exist_ok=True)
    path = root / ".t3-lease"
    existing = path.read_text(encoding="utf-8") if path.is_file() else ""
    if name not in existing.splitlines():
        path.write_text(existing + name + "\n", encoding="utf-8")


def _clear_lease():
    """Drop the lease after a successful reap.

    reap_test_plane deletes every listed AND leased hub-t3-* name, so once it
    returns without raising, every leased name is gone and keeping the file
    only poisons later runs (reap re-deleting ghosts; the hermetic T1 reaper
    tests read the default lease root). A failed reap keeps the lease — that
    is the file's whole job.
    """
    path = REPO / "tmp" / ".t3-lease"
    if path.is_file():
        path.unlink()


def _mp_exec(vm, argv, *, timeout=300):
    return exec(vm.mp(), argv, timeout=timeout)


def _mp_result(vm, argv, *, timeout=120):
    return exec_result(vm.mp(), argv, timeout=timeout)


def guest_gateway_ipv4(vm):
    result = _mp_result(
        vm,
        ["ip", "-4", "route", "show", "default"],
        timeout=30,
    )
    parts = (result.stdout or "").split()
    if "via" in parts:
        return parts[parts.index("via") + 1]
    return ""


def install_authorized_keys(vm, pubkey_text):
    """Append the session key; never replace an authorized_keys file.

    `install` clobbered /home/ubuntu/.ssh/authorized_keys — the file carrying
    the key multipass itself injected — so every later `multipass exec` failed
    with "Access denied for 'publickey'" and the session was unreachable the
    moment this ran (FIX-0: masked until the Local Network block was lifted).
    The guest-side sh -c is data in an exec argv list, not a host shell string.
    """
    local = REPO / "tmp" / f"{vm.name}.pub"
    local.parent.mkdir(exist_ok=True)
    local.write_text(pubkey_text, encoding="utf-8")
    transfer(str(local), f"{vm.name}:/tmp/t3.pub")
    for dest, owner in (
        ("/home/deploy/.ssh/authorized_keys", "deploy"),
        ("/home/ubuntu/.ssh/authorized_keys", "ubuntu"),
        ("/root/.ssh/authorized_keys", "root"),
    ):
        home_ssh = str(Path(dest).parent)
        script = (
            f"mkdir -p {home_ssh} && touch {dest} && "
            f"cat /tmp/t3.pub >> {dest} && "
            f"chown {owner}:{owner} {dest} && chmod 600 {dest}"
        )
        _mp_exec(vm, ["sudo", "sh", "-c", script], timeout=30)


def install_guest_docker(vm):
    _mp_exec(vm, ["sudo", "apt-get", "update"], timeout=300)
    _mp_exec(
        vm,
        [
            "sudo",
            "env",
            "DEBIAN_FRONTEND=noninteractive",
            "apt-get",
            "install",
            "-y",
            "docker.io",
            "python3",
        ],
        timeout=600,
    )
    _mp_exec(vm, ["sudo", "usermod", "-aG", "docker", "deploy"], timeout=30)
    _mp_exec(vm, ["sudo", "systemctl", "enable", "--now", "docker"], timeout=120)
    wait_exec(
        vm.mp(),
        ["sudo", "docker", "info"],
        ready=lambda r: getattr(r, "returncode", 1) == 0,
        deadline=time.time() + 90,
        timeout=20,
    )


CADDY_VERSION = "2.8.4"
CADDY_UNIT = REPO / "images" / "hub-test-target" / "caddy.service"
T3_CADDYFILE = '{\n\tauto_https off\n}\n:80 {\n\trespond "hub-t3-vm" 200\n}\n'


def install_guest_caddy(vm):
    """Caddy binary + unit on the VM, mirroring images/hub-test-target.

    caddy is not in the jammy archive (harden-ubuntu.sh tolerates that with
    `ensure_pkg caddy || true`), and the pipeline's route step PUTs against
    the admin API on 127.0.0.1:2019 — so the harness installs the same
    GitHub-release binary the T2 image records. Runs after provision_host so
    the fresh-host probe still sees port 80 free.
    """
    arch = (_mp_result(vm, ["dpkg", "--print-architecture"], timeout=30).stdout or "").strip()
    url = (
        "https://github.com/caddyserver/caddy/releases/download/"
        f"v{CADDY_VERSION}/caddy_{CADDY_VERSION}_linux_{arch}.tar.gz"
    )
    _mp_exec(
        vm,
        ["sudo", "sh", "-c",
         f"curl -fsSL {url} | tar -xz -C /usr/local/bin caddy "
         f"&& chmod +x /usr/local/bin/caddy && mkdir -p /etc/caddy"],
        timeout=300,
    )
    local_caddyfile = REPO / "tmp" / f"{vm.name}.Caddyfile"
    local_caddyfile.parent.mkdir(exist_ok=True)
    local_caddyfile.write_text(T3_CADDYFILE, encoding="utf-8")
    transfer(str(local_caddyfile), f"{vm.name}:/tmp/Caddyfile")
    transfer(str(CADDY_UNIT), f"{vm.name}:/tmp/caddy.service")
    _mp_exec(vm, ["sudo", "install", "-m", "0644", "/tmp/Caddyfile", "/etc/caddy/Caddyfile"],
             timeout=30)
    _mp_exec(
        vm,
        ["sudo", "install", "-m", "0644", "/tmp/caddy.service",
         "/etc/systemd/system/caddy.service"],
        timeout=30,
    )
    _mp_exec(vm, ["sudo", "systemctl", "daemon-reload"], timeout=60)
    _mp_exec(vm, ["sudo", "systemctl", "enable", "--now", "caddy"], timeout=120)
    wait_exec(
        vm.mp(),
        ["curl", "-sf", "http://127.0.0.1:2019/config/"],
        ready=lambda r: getattr(r, "returncode", 1) == 0,
        deadline=time.time() + 60,
        timeout=15,
    )


def transfer_scripts(vm):
    transfer(str(HARDEN_SH), f"{vm.name}:/tmp/harden-ubuntu.sh")
    transfer(str(VERIFY_SH), f"{vm.name}:/tmp/verify-hardening.sh")
    _mp_exec(
        vm,
        ["sudo", "install", "-m", "0755", "/tmp/harden-ubuntu.sh",
         "/usr/local/sbin/harden-ubuntu.sh"],
        timeout=30,
    )
    _mp_exec(
        vm,
        ["sudo", "install", "-m", "0755", "/tmp/verify-hardening.sh",
         "/usr/local/sbin/verify-hardening.sh"],
        timeout=30,
    )


def harden_target_profile(vm):
    """PROFILE=target via transferred scripts. Test-only mesh skip; not HARD-V2."""
    transfer_scripts(vm)
    ssh_from = vm.ssh_from or guest_gateway_ipv4(vm)
    vm.ssh_from = ssh_from
    argv = [
        "sudo",
        "env",
        "PROFILE=target",
        "HUB_TEST_MODE=1",
        f"HUB_MESH_IP={HUB_MESH_IP}",
        "HUB_T3_UFW_ONLY=1",
        "HUB_T3_ALLOW_NO_MESH=1",
        "HUB_CONFIRM_LOCAL=0",
        f"HUB_T3_SSH_FROM={ssh_from}",
        "/usr/local/sbin/harden-ubuntu.sh",
    ]
    vm.harden_result = _mp_exec(vm, argv, timeout=600)
    return vm.harden_result


def enroll_target(vm, settings, *, slug=None):
    from core.models import NetworkZone, Target
    from vault import service
    from vault.models import Secret

    slug = slug or f"t3z-{uuid.uuid4().hex[:8]}"
    allow_test_zone(settings, slug)
    zone = NetworkZone.objects.create(name=slug, slug=slug, purpose="test")
    owner = f"t3-{uuid.uuid4().hex[:12]}"
    target = Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host=vm.ipv4,
        ssh_user=vm.user,
        ssh_key_ref=owner,
        host_key_fingerprint=vm.host_key_fingerprint,
        lifecycle=Target.Lifecycle.EPHEMERAL,
        status=Target.Status.READY,
    )
    service.put(
        kind=Secret.Kind.SSH_PRIVATE_KEY,
        owner_type="target",
        owner_id=owner,
        plaintext=vm.client_key_pem,
    )
    return target


def ssh_transport(target):
    from core.ssh import SshTransport

    return SshTransport(target)


def ensure_provisioned_and_hardened(vm, settings):
    """Fresh-host provision once, then caddy, then harden. Any test order.

    Caddy comes after provision_host on purpose: the fresh-host probe refuses
    a target whose port 80 is already occupied.
    """
    if vm.provision_result is None:
        from provision.service import provision_host

        target = enroll_target(vm, settings)
        vm.provision_result = provision_host(target, ssh_transport(target))
        install_guest_caddy(vm)
    if not vm.hardened:
        harden_target_profile(vm)
        vm.hardened = True
    return vm.provision_result


def sample_site_body(slug, *, source_dir=None):
    dockerfile = (SAMPLE_SITE / "Dockerfile").read_text(encoding="utf-8")
    return {
        "git_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "source_dir": str(source_dir or SAMPLE_SITE),
        "deploy_strategy": "recreate",
        "local_state": True,
        # sample-site/config/settings.py hard-fails without DJANGO_SECRET_KEY
        # (os.environ[...]). queued_site freezes this into a vault env bundle
        # the way wizard.materialize does; the value never enters the manifest.
        "env": {"DJANGO_SECRET_KEY": f"t3-{uuid.uuid4().hex}"},
        "runtime": "django",
        "exposure": "mesh_only",
        "domain": f"{slug}.example.test",
        "dns_zone": "example.test",
        "readiness_path": "/healthz.ready",
        "warmup_timeout_s": 60,
        "internal_port": 8000,
        "caddy_listen": "127.0.0.1:8088",
        "docker_run_extra": ["-p", "127.0.0.1:8000:8000"],
        "volumes": [{
            "name": f"site-{slug}-data",
            "container_path": "/data",
            "backup_policy": "directory_sync",
        }],
        "dockerfile_template": dockerfile,
    }


def node_site_body(slug, *, source_dir=None):
    return {
        "git_sha": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "source_dir": str(source_dir or SAMPLE_NODE_SITE),
        "deploy_strategy": "recreate",
        "local_state": True,
        "runtime": "node",
        "exposure": "mesh_only",
        "domain": f"{slug}.example.test",
        "dns_zone": "example.test",
        "readiness_path": "/healthz.ready",
        "warmup_timeout_s": 60,
        "internal_port": 8080,
        "caddy_listen": "127.0.0.1:8089",
        "docker_run_extra": ["-p", "127.0.0.1:8080:8080"],
        "ws": True,
        "volumes": [{
            "name": f"site-{slug}-data",
            "container_path": "/data",
            "backup_policy": "directory_sync",
        }],
        "dockerfile_template": NODE_SITE_DOCKERFILE,
    }


def _vault_env_bundle(site, body):
    """Freeze `body["env"]` into a vault env bundle, as wizard.materialize does.

    Env VALUES never enter the persisted manifest body (round-1 F1): the body
    keeps env_bundle_ref + the names, the pipeline decrypts the bundle via
    `deploys.pipeline.load_env_snapshot` and ships it as a 0600 env file.
    """
    values = body.get("env")
    if not isinstance(values, dict) or not values:
        return body
    from vault import service as vault_service
    from vault.models import Secret

    bundle = vault_service.put(
        kind=Secret.Kind.ENV_BUNDLE,
        owner_type="manifest",
        owner_id=f"{site.pk}:v1",
        plaintext=json.dumps(values, sort_keys=True).encode("utf-8"),
    )
    body = dict(body)
    del body["env"]
    body["env_names"] = sorted(values)
    body["env_bundle_ref"] = bundle.pk
    return body


def queued_site(vm, settings, *, slug, body):
    from core.models import Project, Site
    from deploys.models import Deployment, Manifest

    target = enroll_target(vm, settings)
    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    site = Site.objects.create(
        project=project,
        name=slug,
        domain=f"{slug}.example.test",
        primary_target=target,
        exposure="mesh_only",
        deploy_strategy=Site.DeployStrategy.RECREATE,
        readiness_path="/healthz.ready",
        warmup_timeout_s=60,
    )
    body = _vault_env_bundle(site, body)
    manifest = Manifest.objects.create(site=site, version=1, body=body)
    return site, target, Deployment.objects.create(manifest=manifest)


def execute_deployment(deployment, target):
    from deploys.pipeline import execute
    from providers.fakes import FakeDnsProvider

    result = execute(
        deployment.pk,
        transport=ssh_transport(target),
        dns=FakeDnsProvider(),
    )
    deployment.refresh_from_db()
    return result


def http_ready(target, *, domain, listen, path="/healthz.ready"):
    transport = ssh_transport(target)
    url = f"http://{listen}{path}"
    result = transport.probe(["curl", "-sf", "-H", f"Host: {domain}", url])
    if not result.ok or not (result.stdout or "").strip():
        return {"live": False, "ready": False, "raw": result.stdout, "err": result.stderr}
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {"live": False, "ready": False, "raw": result.stdout}
    payload["raw"] = result.stdout
    return payload


def ws_frame_through_caddy(vm, target, *, listen, path, domain):
    """One ws:// frame through on-VM Caddy. Not Cloudflare."""
    transport = ssh_transport(target)
    transport.put(WS_CLIENT_PY, "/tmp/t3-ws.py", mode=0o644)
    host, port = listen.split(":")
    result = transport.probe(["python3", "/tmp/t3-ws.py", host, port, path, domain])
    if not result.ok:
        raise AssertionError(
            f"ws frame failed: stdout={result.stdout!r} stderr={result.stderr!r}"
        )
    return result.stdout


def volume_marker(target, volume):
    transport = ssh_transport(target)
    result = transport.probe([
        "docker", "run", "--rm", "-v", f"{volume}:/data",
        "node:22-bookworm-slim", "cat", "/data/marker",
    ])
    return result


def assert_not_hub_test_target(vm):
    assert vm.name.startswith(NAME_PREFIX), vm.name
    assert "hub-test-target" not in vm.name
    host = _mp_result(vm, ["hostname"], timeout=30)
    assert "hub-test-target" not in (host.stdout or "")
    virt = _mp_result(vm, ["systemd-detect-virt"], timeout=30)
    text = (virt.stdout or "").strip().lower()
    assert text in {"kvm", "qemu", "qemu-kvm", "microsoft"} or "multipass" in text, text
    assert text != "docker"


def assert_hub_docker_sock_absent(vm):
    assert SOCK not in CLOUD_INIT
    assert "docker.sock" not in CLOUD_INIT
    mounted = _mp_result(
        vm,
        ["findmnt", "-n", "-o", "FSTYPE,SOURCE", "/var/run/docker.sock"],
        timeout=30,
    )
    out = f"{mounted.stdout or ''} {mounted.stderr or ''}".lower()
    assert "bind" not in out
    assert "/host" not in out
    assert "hub" not in out


@pytest.fixture(scope="session")
def t3_vm():
    """One Multipass Ubuntu VM for the T3 session. Never hub-test-target."""
    name = f"hub-t3-sess-{uuid.uuid4().hex[:8]}"
    _write_lease(name)
    key = ECDSAKey.generate()
    pem_buf = io.StringIO()
    key.write_private_key(pem_buf)
    client_pem = pem_buf.getvalue().encode()
    pubkey = f"{key.get_name()} {key.get_base64()} t3-multipass\n"
    launched = None
    try:
        launched = launch(name, cpus=2, mem="2G", disk="20G")
        ipv4 = launched.ipv4 or info_ipv4(name)
        deadline = time.time() + 180
        while not ipv4 and time.time() < deadline:
            time.sleep(3)
            ipv4 = info_ipv4(name)
        if not ipv4:
            raise AssertionError(f"multipass {name} has no ipv4")
        vm = T3VM(
            name=name,
            ipv4=ipv4,
            user="deploy",
            host_key_fingerprint="pending",
            client_key_pem=client_pem,
        )
        wait_exec(
            vm.mp(),
            ["systemctl", "is-system-running"],
            ready=lambda r: (r.stdout or "").strip() in {"running", "degraded"},
            deadline=time.time() + 180,
            timeout=20,
        )
        wait_exec(
            vm.mp(),
            ["systemctl", "is-active", "ssh"],
            ready=lambda r: (r.stdout or "").strip() == "active",
            deadline=time.time() + 120,
            timeout=15,
        )
        install_authorized_keys(vm, pubkey)
        vm.host_key_fingerprint = _presented_fingerprint(ipv4, 22, "deploy", key)
        vm.ssh_from = guest_gateway_ipv4(vm)
        install_guest_docker(vm)
        assert_not_hub_test_target(vm)
        yield vm
    finally:
        reap_test_plane()
        _clear_lease()


def remove_site_containers(vm):
    """Remove leftover site-* containers on the session VM between tests.

    The T2 fix (286c9ea) for the shared hub-test-target, ported to T3: every
    node-site body publishes 127.0.0.1:8080 and `--restart unless-stopped`
    even resurrects a stopped survivor, so the next test's docker run fails
    with "port is already allocated". Listing is tolerant — docker may not be
    installed yet if the test deployed nothing — but a failed rm raises so a
    broken cleanup names itself instead of the next test.
    """
    listing = _mp_result(
        vm,
        ["sudo", "docker", "ps", "-aq", "--filter", "name=^site-"],
        timeout=60,
    )
    if listing.returncode != 0:
        return
    ids = (listing.stdout or "").split()
    if ids:
        _mp_exec(vm, ["sudo", "docker", "rm", "-f", *ids], timeout=120)


def remove_site_caddy_servers(vm):
    """DELETE leftover site-* Caddy servers on the session VM between tests.

    ensure_route_tls PUTs a per-slug server on the shared 127.0.0.1:8089
    (node) / :8088 (django) listen, so a survivor makes the next test's PUT
    fail ("caddy put failed": listen address already bound). Same tolerance
    contract as remove_site_containers.
    """
    listing = _mp_result(
        vm,
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
            _mp_exec(
                vm,
                [
                    "curl", "-sf", "-X", "DELETE",
                    f"http://127.0.0.1:2019/config/apps/http/servers/{server_id}",
                ],
                timeout=30,
            )


@pytest.fixture
def t3_ready(t3_vm, db, settings):
    """Provision (first caller) then harden; per-test view of the session VM.

    Shared across Task 10 and 11. Teardown removes site-* containers and
    Caddy servers so tests never collide on the shared ports (QE F4).
    """
    ensure_provisioned_and_hardened(t3_vm, settings)
    try:
        yield t3_vm
    finally:
        remove_site_containers(t3_vm)
        remove_site_caddy_servers(t3_vm)
