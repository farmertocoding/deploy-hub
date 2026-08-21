"""Toxiproxy launcher for SSH-path fault injection. T2 modules import this."""
from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass

from tests.harness.target import _docker

IMAGE = "ghcr.io/shopify/toxiproxy"
FALLBACK_IMAGE = "shopify/toxiproxy"
API_CONTAINER_PORT = 8474
DATA_CONTAINER_PORT = 2222


def toxiproxy_run_argv(name, *, image=IMAGE):
    """docker run argv for toxiproxy. Never a shell string; never binds docker.sock."""
    return [
        "run",
        "-d",
        "--name",
        name,
        "-p",
        f"127.0.0.1::{API_CONTAINER_PORT}",
        "-p",
        f"127.0.0.1::{DATA_CONTAINER_PORT}",
        "--add-host",
        "host.docker.internal:host-gateway",
        image,
    ]


def _published_port(container, container_port):
    line = _docker(["port", container, f"{container_port}/tcp"], check=True).stdout.strip()
    for row in line.splitlines():
        if row.startswith("127.0.0.1:"):
            return int(row.rsplit(":", 1)[1])
    return int(line.rsplit(":", 1)[1])


def _wait_api(host, port, *, deadline):
    last = None
    url = f"http://{host}:{port}/version"
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=1) as resp:
                if 200 <= resp.status < 300:
                    return
        except OSError as exc:
            last = exc
        time.sleep(0.2)
    raise AssertionError(f"toxiproxy API did not listen on {host}:{port}: {last}")


def _container_ip(inspect):
    nets = inspect.get("NetworkSettings") or {}
    ip = nets.get("IPAddress") or ""
    if ip:
        return ip
    for net in (nets.get("Networks") or {}).values():
        candidate = (net or {}).get("IPAddress") or ""
        if candidate:
            return candidate
    return ""


def reachable_upstream(hub_target):
    """Address the toxiproxy container can use to reach hub_target's sshd.

    Host-published 127.0.0.1:port is the pytest/SshTransport view; inside the
    proxy container that loopback is the proxy itself.
    """
    inspect = json.loads(_docker(["inspect", hub_target.container], check=True).stdout)[0]
    ip = _container_ip(inspect)
    if ip:
        return f"{ip}:22"
    host = hub_target.host
    if host in {"127.0.0.1", "localhost", "::1"}:
        return f"host.docker.internal:{hub_target.port}"
    return f"{host}:{hub_target.port}"


@dataclass
class Toxiproxy:
    container: str
    api_host: str
    api_port: int
    listen_host: str
    listen_port: int
    data_container_port: int = DATA_CONTAINER_PORT

    def api(self, method, path, body=None):
        url = f"http://{self.api_host}:{self.api_port}{path}"
        data = None
        headers = {}
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(url, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode()
            raise AssertionError(f"{method} {path} -> {exc.code}: {detail}") from exc
        if not raw:
            return {}
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            return {"raw": raw.decode()}

    def add_proxy(self, name, *, upstream):
        return self.api("POST", "/proxies", {
            "name": name,
            "listen": f"0.0.0.0:{self.data_container_port}",
            "upstream": upstream,
            "enabled": True,
        })

    def toxic_timeout(self, proxy_name, *, stream="downstream", timeout_ms=0):
        return self.api("POST", f"/proxies/{proxy_name}/toxics", {
            "name": "timeout",
            "type": "timeout",
            "stream": stream,
            "attributes": {"timeout": timeout_ms},
        })

    def reset(self):
        return self.api("POST", "/reset")

    def close(self):
        _docker(["rm", "-f", self.container], timeout=60)


def start_toxiproxy():
    """Start toxiproxy via argv docker run. Caller must close() in finally."""
    name = f"hub-toxiproxy-{uuid.uuid4().hex[:8]}"
    launched = _docker(toxiproxy_run_argv(name), timeout=180)
    if launched.returncode != 0:
        _docker(["rm", "-f", name], timeout=60)
        launched = _docker(
            toxiproxy_run_argv(name, image=FALLBACK_IMAGE),
            timeout=180,
        )
    if launched.returncode != 0:
        raise AssertionError(
            f"docker run toxiproxy failed\n"
            f"stdout:\n{launched.stdout}\nstderr:\n{launched.stderr}"
        )
    try:
        api_port = _published_port(name, API_CONTAINER_PORT)
        listen_port = _published_port(name, DATA_CONTAINER_PORT)
        _wait_api("127.0.0.1", api_port, deadline=time.time() + 30)
        return Toxiproxy(
            container=name,
            api_host="127.0.0.1",
            api_port=api_port,
            listen_host="127.0.0.1",
            listen_port=listen_port,
        )
    except Exception:
        _docker(["rm", "-f", name], timeout=60)
        raise
