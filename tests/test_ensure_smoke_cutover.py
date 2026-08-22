"""ensure_smoke / ensure_cutover: ready gate, ws frame, stop-but-keep old (S4)."""
import json
from datetime import datetime, timezone

import pytest

from core.transport import CommandResult, FakeTransport

OLD = "site-app-3"
READY = {"live": True, "ready": True, "checks": {}}
NOT_READY = {"live": True, "ready": False, "checks": {"backfill_pct": 10}}


class ScriptedCurlTransport(FakeTransport):
    """T1: scripted probe-curl of the Caddy/healthz path."""

    def __init__(self, curl_results):
        super().__init__()
        self._curl = list(curl_results)

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv and argv[0] == "curl":
            if not self._curl:
                raise AssertionError("unexpected extra curl probe")
            return CommandResult(argv, **self._curl.pop(0))
        return CommandResult(argv)


class CutoverTransport(FakeTransport):
    """Records docker stop/rm; inspect reports Running until stop."""

    def __init__(self):
        super().__init__()
        self.stopped = []
        self.removed = []
        self.containers = {OLD: "running"}

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv[:2] == ["docker", "inspect"]:
            name = argv[-1]
            state = self.containers.get(name)
            if state is None:
                return CommandResult(argv, exit_code=1, stderr="Error: No such container")
            stdout = "true" if state == "running" else "false"
            return CommandResult(argv, stdout=stdout)
        return CommandResult(argv)

    def run(self, argv, *, timeout=60):
        result = super().run(argv, timeout=timeout)
        argv = list(argv)
        if argv[:2] == ["docker", "stop"] and len(argv) >= 3:
            self.stopped.append(argv[2])
            if argv[2] in self.containers:
                self.containers[argv[2]] = "exited"
        if argv[:2] == ["docker", "rm"]:
            self.removed.append(argv[-1])
        return result


def _curl_ok(payload):
    return {"exit_code": 0, "stdout": json.dumps(payload)}


def _assert_caddy_smoke_curl(transport, listen="127.0.0.1:443"):
    curls = [
        argv for kind, argv in transport.calls
        if kind == "probe" and isinstance(argv, list) and argv[:1] == ["curl"]
    ]
    assert curls, "expected probe curl of the Caddy ready path"
    assert any(listen in str(part) for argv in curls for part in argv), (
        f"curl argv must include Caddy listen {listen}, got {curls}"
    )
    if listen.endswith(":443"):
        assert any(
            any(isinstance(p, str) and p.startswith("https://") for p in argv)
            for argv in curls
        ), f"public :443 smoke must be HTTPS, got {curls}"
        assert any("-skf" in argv or "-k" in argv for argv in curls)
    assert all(kind == "probe" for kind, argv in transport.calls
               if isinstance(argv, list) and argv[:1] == ["curl"])
    inspects = [
        argv for kind, argv in transport.calls
        if isinstance(argv, list) and argv[:2] == ["docker", "inspect"]
    ]
    assert inspects == [], f"smoke must not docker-inspect, got {inspects}"


def _smoke_desired(transport, *, body=None, ws_fetch=None, healthz_fetch=None):
    desired = {
        "transport": transport,
        "site_slug": "app",
        "deployment_id": 4,
        "manifest_body": body if body is not None else {},
    }
    if ws_fetch is not None:
        desired["ws_fetch"] = ws_fetch
    if healthz_fetch is not None:
        desired["healthz_fetch"] = healthz_fetch
    return desired


def _cutover_desired(transport, *, ready, step=None):
    desired = {
        "transport": transport,
        "site_slug": "app",
        "deployment_id": 4,
        "manifest_body": {},
        "old_container": OLD,
        "ready": ready,
    }
    if step is not None:
        desired["step"] = step
    return desired


def _stop_argvs(transport):
    return [
        argv for kind, argv in transport.mutating_calls()
        if kind == "run" and isinstance(argv, list) and argv[:2] == ["docker", "stop"]
    ]


def _rm_argvs(transport):
    return [
        argv for kind, argv in transport.mutating_calls()
        if kind == "run" and isinstance(argv, list) and argv[:2] == ["docker", "rm"]
    ]


@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_smoke_sees_ready():
    """Smoke succeeds only when a probe curl of the Caddy listen reports ready.

    What would make this fail: treating live-but-not-ready as success, curling
    the container IP from docker inspect, or skipping the Caddy listen host:port.
    """
    from deploys.steps import ensure_smoke

    miss = ScriptedCurlTransport([_curl_ok(NOT_READY)])
    with pytest.raises(RuntimeError):
        ensure_smoke(_smoke_desired(miss))
    _assert_caddy_smoke_curl(miss)

    ok = ScriptedCurlTransport([_curl_ok(READY)])
    result = ensure_smoke(_smoke_desired(ok))
    assert result.get("status") != "failed"
    _assert_caddy_smoke_curl(ok)


@pytest.mark.req("PIPE-S4-READINESS-GATE")
def test_ws_smoke_when_manifest_declares_ws():
    """A Manifest that declares ws must also receive one T1 frame before passing.

    What would make this fail: skipping the frame receive when body has ws /
    websocket / healthz.ws, or opening a real network socket.
    """
    from deploys.steps import ensure_smoke

    for body in ({"ws": True}, {"websocket": True}, {"healthz": {"ws": True}}):
        frames = []

        def ws_fetch(captured=frames):
            captured.append("tick")
            return "tick"

        transport = ScriptedCurlTransport([_curl_ok(READY)])
        ensure_smoke(_smoke_desired(transport, body=body, ws_fetch=ws_fetch))
        assert frames == ["tick"], f"expected one frame for body={body}"

    skipped = []
    transport = ScriptedCurlTransport([_curl_ok(READY)])
    ensure_smoke(_smoke_desired(
        transport,
        body={},
        ws_fetch=lambda: skipped.append("nope") or "tick",
    ))
    assert skipped == []


@pytest.mark.req("PIPE-S4-READINESS-GATE")
@pytest.mark.django_db
def test_cutover_after_ready_not_before():
    """Cutover must refuse while not ready; when ready, stop the old container and keep it.

    What would make this fail: docker stop before ready, docker rm of the old
    container, or omitting the grace deadline on the step row.
    """
    from core.models import Project, Site
    from deploys.models import Deployment, DeploymentStep, Manifest
    from deploys.steps import ensure_cutover

    project = Project.objects.create(name="cut", slug="p-cut")
    from dns_fixtures import default_dns_zone

    site = Site.objects.create(project=project, name="cut",
                               dns_zone=default_dns_zone())
    manifest = Manifest.objects.create(site=site, version=1, body={})
    deployment = Deployment.objects.create(manifest=manifest)
    step = DeploymentStep.objects.create(
        deployment=deployment,
        seq=9,
        name=DeploymentStep.Name.CUTOVER,
    )

    blocked = CutoverTransport()
    with pytest.raises(RuntimeError):
        ensure_cutover(_cutover_desired(blocked, ready=False, step=step))
    assert _stop_argvs(blocked) == []
    assert blocked.stopped == []

    allowed = CutoverTransport()
    ensure_cutover(_cutover_desired(allowed, ready=True, step=step))
    stops = _stop_argvs(allowed)
    assert stops, f"expected docker stop {OLD}, got {allowed.mutating_calls()}"
    assert any(OLD in argv for argv in stops)
    assert _rm_argvs(allowed) == []
    assert allowed.removed == []

    step.refresh_from_db()
    deadline = (step.artifacts or {}).get("grace_deadline")
    assert deadline, "cutover must persist grace_deadline on step.artifacts"
    parsed = datetime.fromisoformat(deadline.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    assert parsed > datetime.now(timezone.utc)


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_second_cutover_skips_stop_when_old_already_stopped():
    """A second ensure_cutover of the same desired must not docker stop again.

    What would make this fail: always `docker stop` old_container without
    probing Running first, so a re-run of a stopped old is still mutating.
    """
    from deploys.steps import ensure_cutover

    transport = CutoverTransport()
    desired = _cutover_desired(transport, ready=True)
    ensure_cutover(desired)
    assert _stop_argvs(transport), transport.mutating_calls()
    transport.calls.clear()
    ensure_cutover(desired)
    assert transport.mutating_calls() == []
