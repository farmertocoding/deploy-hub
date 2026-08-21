"""Phase 2 round-6 design reset: one listen port for docker run and step 5.

Collector already curls $PORT. Pipeline ensure_health_check must use the same
listen _docker_run_argv just emitted, never implicit :80.
"""
import json

import pytest
from test_ensure_start import IMAGE_TAG, StartTransport, _inspect_target

from core.transport import CommandResult

LISTEN = 24680
CONTAINER_IP = "192.0.2.10"


def _docker_runs(transport):
    return [
        argv for kind, argv in transport.calls
        if kind == "run" and argv[:2] == ["docker", "run"]
    ]


def _port_envs(argv):
    return [
        argv[i + 1]
        for i, part in enumerate(argv[:-1])
        if part == "-e" and str(argv[i + 1]).startswith("PORT=")
    ]


def _listen_from_docker_run(transport):
    runs = _docker_runs(transport)
    assert runs, transport.calls
    port_vals = _port_envs(runs[0])
    assert port_vals, runs[0]
    raw = str(port_vals[0]).split("=", 1)[1]
    assert raw.isdigit(), runs[0]
    return int(raw)


class ListenPortHealthTransport(StartTransport):
    """ensure_start + inspect IP + recorded curl. URL is not ignored.

    Curl succeeds only when the argv URL includes the listen PORT docker run
    emitted (or 127.0.0.1:{listen} when inspect IP is empty). Wrong-port stubs
    that always return ready would hide the round-6 hole.
    """

    def __init__(self, *, container_ip=CONTAINER_IP):
        super().__init__()
        self.container_ip = container_ip
        self.curl_probes = []
        self.listen_port = None

    def run(self, argv, *, timeout=60):
        result = super().run(argv, timeout=timeout)
        argv = list(argv)
        if argv[:2] == ["docker", "run"]:
            ports = _port_envs(argv)
            if ports:
                raw = str(ports[0]).split("=", 1)[1]
                if raw.isdigit():
                    self.listen_port = int(raw)
        return result

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        if argv and argv[0] == "curl":
            self.calls.append(("probe", argv))
            self.curl_probes.append(argv)
            url = argv[-1] if argv else ""
            host = self.container_ip or "127.0.0.1"
            if self.listen_port is None:
                return CommandResult(argv, exit_code=1, stderr="no listen port")
            want = f"http://{host}:{self.listen_port}/"
            if want not in url:
                return CommandResult(argv, exit_code=1, stderr=f"wrong health url {url}")
            body = json.dumps({"live": True, "ready": True, "checks": {}})
            return CommandResult(argv, stdout=body)
        if argv[:2] == ["docker", "inspect"] and any(
            "IPAddress" in str(part) for part in argv
        ):
            self.calls.append(("probe", argv))
            name = _inspect_target(argv)
            if name not in self.containers:
                return CommandResult(argv, exit_code=1, stderr="Error: No such container")
            return CommandResult(argv, stdout=self.container_ip)
        return super().probe(argv, timeout=timeout)


def _desired(transport, *, extra=None, body=None):
    desired = {
        "transport": transport,
        "site_slug": "r6port",
        "deployment_id": 6,
        "manifest_body": body if body is not None else {"warmup_timeout_s": 0},
        "image_tag": IMAGE_TAG,
        "internal_port": LISTEN,
        "sleep": lambda _s: None,
        "poll_interval_s": 0,
    }
    if extra:
        desired.update(extra)
    return desired


@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_health_check_curls_listen_port_from_docker_run():
    """Step 5 must curl the same PORT docker run just set, not implicit :80.

    What would make this fail: ensure_health_check curling http://{ip}/ (port 80)
    or :18080 after _docker_run_argv emitted -e PORT=24680, or skipping curl via
    healthz_fetch.
    """
    from deploys.steps import ensure_health_check, ensure_start

    transport = ListenPortHealthTransport(container_ip=CONTAINER_IP)
    desired = _desired(transport)
    assert "healthz_fetch" not in desired

    ensure_start(desired)
    listen = _listen_from_docker_run(transport)
    assert listen == LISTEN
    assert listen != 80
    assert listen != 18080

    result = ensure_health_check(desired)
    assert result["status"] == "ready"
    assert transport.curl_probes, transport.calls
    urls = " ".join(str(part) for argv in transport.curl_probes for part in argv)
    assert f"http://{CONTAINER_IP}:{listen}/" in urls


def test_health_check_curls_loopback_listen_when_inspect_ip_empty():
    """Empty inspect IP must still use listen, not implicit 127.0.0.1:80.

    What would make this fail: falling back to internal_port or 80 instead of
    the PORT _docker_run_argv emitted from Manifest body port.
    """
    from deploys.steps import ensure_health_check, ensure_start

    transport = ListenPortHealthTransport(container_ip="")
    desired = _desired(
        transport,
        extra={"internal_port": None},
        body={"warmup_timeout_s": 0, "port": 25000},
    )
    assert "healthz_fetch" not in desired

    ensure_start(desired)
    listen = _listen_from_docker_run(transport)
    assert listen == 25000
    assert listen != 80
    assert listen != 18080

    result = ensure_health_check(desired)
    assert result["status"] == "ready"
    assert transport.curl_probes, transport.calls
    urls = " ".join(str(part) for argv in transport.curl_probes for part in argv)
    assert f"http://127.0.0.1:{listen}/" in urls
