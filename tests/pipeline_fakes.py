"""T1 composite Transport for the full pipeline. Does not change FakeTransport."""
from __future__ import annotations

import json
from pathlib import Path

from core.transport import CommandResult, FakeTransport

REPO = Path(__file__).resolve().parent.parent
SAMPLE_NODE_SITE = REPO / "sample-node-site"
GIT_SHA = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

READY_JSON = json.dumps({"live": True, "ready": True, "checks": {}})

NPM_CI_DOCKERFILE = (
    "FROM node:22-alpine\n"
    "WORKDIR /app\n"
    "COPY package.json package-lock.json* ./\n"
    "RUN npm ci\n"
    "COPY . .\n"
    'CMD ["node", "app.js"]\n'
)


class PipelineTransport(FakeTransport):
    """Tracks images, volumes, containers, and Caddy like the Task 9–12 doubles."""

    def __init__(self):
        super().__init__()
        self.images = set()
        self.volumes = set()
        self.containers = {}
        self.routes = {}
        self.container_ips = {}

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv[:3] == ["docker", "image", "inspect"] and len(argv) >= 4:
            tag = argv[3]
            if tag in self.images:
                return CommandResult(argv, exit_code=0, stdout=tag)
            return CommandResult(argv, exit_code=1, stderr="Error: No such image")
        if argv[:3] == ["docker", "volume", "inspect"] and len(argv) >= 4:
            name = argv[3]
            if name in self.volumes:
                return CommandResult(argv, exit_code=0, stdout=name)
            return CommandResult(argv, exit_code=1, stderr="Error: No such volume")
        if argv[:2] == ["docker", "inspect"]:
            return self._inspect_container(argv)
        if argv and argv[0] == "curl":
            return self._curl_probe(argv)
        if argv[:2] == ["test", "-f"] and len(argv) >= 3:
            path = argv[2]
            if path in self.files:
                return CommandResult(argv, exit_code=0)
            return CommandResult(argv, exit_code=1, stderr="No such file")
        return CommandResult(argv)

    def run(self, argv, *, timeout=60):
        result = super().run(argv, timeout=timeout)
        argv = list(argv)
        if argv and argv[0] == "docker" and "build" in argv and "-t" in argv:
            self.images.add(argv[argv.index("-t") + 1])
        if argv[:2] == ["docker", "load"]:
            pending = next(iter(self.images), None)
            if pending:
                self.images.add(pending)
        if argv[:3] == ["docker", "volume", "create"] and len(argv) >= 4:
            self.volumes.add(argv[3])
        if argv[:2] == ["docker", "run"]:
            name = _flag_value(argv, "--name")
            if name:
                self.containers[name] = "running"
                self.container_ips[name] = "10.0.0.9"
        if argv[:2] == ["docker", "start"] and len(argv) >= 3:
            self.containers[argv[2]] = "running"
        if argv[:2] == ["docker", "stop"] and len(argv) >= 3:
            name = argv[2]
            if name in self.containers:
                self.containers[name] = "exited"
        if argv[:2] == ["docker", "rm"]:
            self.containers.pop(argv[-1], None)
        if argv and argv[0] == "curl" and "PUT" in argv:
            route_id = _route_id_from_argv(argv)
            path = _data_binary_path(argv)
            if route_id and path:
                self.routes[route_id] = self.files.get(path, b"{}")
        return result

    def _inspect_container(self, argv):
        name = _inspect_target(argv)
        state = self.containers.get(name)
        if state is None:
            return CommandResult(argv, exit_code=1, stderr="Error: No such container")
        fmt = ""
        if "--format" in argv:
            fmt = argv[argv.index("--format") + 1]
        if "IPAddress" in fmt:
            return CommandResult(
                argv, exit_code=0, stdout=self.container_ips.get(name, "10.0.0.9"),
            )
        stdout = "true" if state == "running" else "false"
        return CommandResult(argv, exit_code=0, stdout=stdout)

    def _curl_probe(self, argv):
        route_id = _route_id_from_argv(argv)
        if route_id and "PUT" not in argv:
            raw = self.routes.get(route_id)
            if raw is None:
                return CommandResult(argv, exit_code=1, stderr="404")
            stdout = raw.decode() if isinstance(raw, (bytes, bytearray)) else raw
            return CommandResult(argv, stdout=stdout)
        if any(s == "running" for s in self.containers.values()):
            return CommandResult(argv, stdout=READY_JSON)
        return CommandResult(argv, exit_code=1, stderr="not ready")


def fixture_body(slug, *, extra=None):
    body = {
        "git_sha": GIT_SHA,
        "source_dir": str(SAMPLE_NODE_SITE),
        "deploy_strategy": "recreate",
        "local_state": True,
        "runtime": "node",
        "domain": f"{slug}.example.test",
        "dns_zone": "example.test",
        "readiness_path": "/healthz.ready",
        "warmup_timeout_s": 5,
        "volumes": [{
            "name": f"site-{slug}-data",
            "container_path": "/data",
            "backup_policy": "directory_sync",
        }],
        "dockerfile_template": NPM_CI_DOCKERFILE,
    }
    if extra:
        body.update(extra)
    return body


def queued_deployment(slug, *, body=None):
    from dns_fixtures import default_dns_zone

    from core.models import NetworkZone, Project, Site, Target
    from deploys.models import Deployment, Manifest

    project = Project.objects.create(name=slug, slug=f"p-{slug}")
    zone = NetworkZone.objects.create(name="lan", slug=f"lan-{slug}")
    target = Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref=f"vault-{slug}",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )
    site = Site.objects.create(
        project=project,
        name=slug,
        domain=f"{slug}.example.test",
        primary_target=target,
        dns_zone=default_dns_zone("example.test"),
        deploy_strategy=Site.DeployStrategy.RECREATE,
    )
    manifest = Manifest.objects.create(
        site=site,
        version=1,
        body=body if body is not None else fixture_body(slug),
    )
    return site, Deployment.objects.create(manifest=manifest)


def _flag_value(argv, flag):
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv):
            return argv[i + 1]
    return None


def _inspect_target(argv):
    for part in reversed(argv):
        if part.startswith("-") or part.startswith("{{") or part in {"docker", "inspect"}:
            continue
        return part
    return argv[-1]


def _route_id_from_argv(argv):
    for part in argv:
        text = str(part)
        if "/id/" in text or "/servers/" in text:
            return text.rstrip("/").rsplit("/", 1)[-1]
    return None


def _data_binary_path(argv):
    if "--data-binary" in argv:
        spec = argv[argv.index("--data-binary") + 1]
        return spec[1:] if spec.startswith("@") else spec
    return None
