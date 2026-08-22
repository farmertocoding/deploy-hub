"""The `--fake` pipeline transport for worker children (2.5 panel I2).

`deploys.worker_entry --fake` needs a no-SSH Transport, and a product entry
point may not import from tests/ — the old sys.path insert reached
tests/pipeline_fakes.py invisibly to the import-rule gate. The double lives
here, next to its only product consumer, built on core.transport.FakeTransport
exactly like the Task 9–12 doubles. tests/pipeline_fakes.py re-exports it for
the T1 suite.
"""
from __future__ import annotations

import json

from core.transport import CommandResult, FakeTransport

READY_JSON = json.dumps({"live": True, "ready": True, "checks": {}})


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
        cmd = argv[1:] if argv and argv[0] == "sudo" else argv
        if cmd[:2] == ["test", "-f"] and len(cmd) >= 3:
            path = cmd[2]
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
