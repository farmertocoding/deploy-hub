"""One SSH collector session per target per minute (REL-C3-ONE-COLLECTOR-SESSION)."""
import ast
import inspect
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.conf import settings

from core.transport import CommandResult, FakeTransport

CONTRACT_KEYS = {
    "schema_version",
    "target_id",
    "ts",
    "metrics",
    "containers",
    "log_chunk",
    "clock",
    "healthz",
}
LOG_CHUNK_KEYS = {"file", "inode", "offset", "bytes"}
HEALTHZ_KEYS = {"live", "ready", "checks"}


def _payload(target_id=42):
    return {
        "schema_version": 1,
        "target_id": target_id,
        "ts": "2026-08-21T04:13:00Z",
        "metrics": {"load1": 0.2, "mem_pct": 41.0, "disk_pct": 12.0},
        "containers": [{"name": "site-app-1", "state": "running"}],
        "log_chunk": {
            "file": "/var/log/caddy/access.log",
            "inode": 12345,
            "offset": 100,
            "bytes": "",
        },
        "clock": "2026-08-21T04:13:00Z",
        "healthz": {"live": True, "ready": True, "checks": {}},
    }


def _target(pk=42):
    return SimpleNamespace(pk=pk, id=pk)


class CollectorTransport(FakeTransport):
    """Canned collector JSON from the one script probe; test -f is not a session."""

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv and argv[0] == "test":
            remote = argv[-1]
            return CommandResult(argv, exit_code=0 if remote in self.files else 1)
        return CommandResult(argv, stdout=json.dumps(_payload()))

    def run(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("run", argv))
        return CommandResult(argv, stdout=json.dumps(_payload()))


def _noop(_seconds):
    return None


def _script_executions(transport):
    """Independent session-equivalents: probe/run except test -f.

    put lands the script on the same session and does not count. Two collect()
    calls must therefore be two script executions, not a third metrics/logs/clock
    argv.
    """
    n = 0
    for kind, payload in transport.calls:
        if kind not in ("probe", "run"):
            continue
        argv = payload
        if not isinstance(argv, list) or not argv:
            n += 1
            continue
        if argv[0] == "test":
            continue
        n += 1
    return n


@pytest.mark.req("REL-C3-ONE-COLLECTOR-SESSION")
def test_one_session_returns_full_contract():
    """One put + one probe of the collector script returns the pinned JSON.

    What would make this fail: a second argv for metrics/logs/clock, or dropping
    a contract key, or parsing something other than that one script's stdout.
    """
    from monitor.collector import collect
    from monitor.tasks import collect_all

    transport = CollectorTransport()
    result = collect(_target(), transport, sleep=_noop)

    assert set(result) == CONTRACT_KEYS
    assert set(result["log_chunk"]) == LOG_CHUNK_KEYS
    assert set(result["healthz"]) == HEALTHZ_KEYS
    assert _script_executions(transport) == 1
    puts = [c for c in transport.calls if c[0] == "put"]
    assert len(puts) == 1

    beat = {entry["task"] for entry in settings.CELERY_BEAT_SCHEDULE.values()}
    assert collect_all.name in beat
    schedule = next(
        entry["schedule"]
        for entry in settings.CELERY_BEAT_SCHEDULE.values()
        if entry["task"] == collect_all.name
    )
    assert float(schedule) == 60.0
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "probes"


@pytest.mark.req("REL-C3-ONE-COLLECTOR-SESSION")
def test_contract_has_metrics_containers_log_chunk_clock_healthz():
    """C3 fields are present; healthz is the pinned {live, ready, checks} object.

    What would make this fail: renaming a field, flattening healthz, or omitting
    log_chunk.inode/offset so the next minute cannot resume the file.
    """
    from monitor.collector import collect

    result = collect(_target(), CollectorTransport(), sleep=_noop)
    for key in ("metrics", "containers", "log_chunk", "clock", "healthz"):
        assert key in result
    assert result["healthz"]["live"] is True
    assert result["healthz"]["ready"] is True
    assert "checks" in result["healthz"]
    chunk = result["log_chunk"]
    assert chunk["file"]
    assert "inode" in chunk and "offset" in chunk and "bytes" in chunk


@pytest.mark.req("REL-C3-ONE-COLLECTOR-SESSION")
def test_jitter_is_stable_per_target():
    """jitter_s(target_id) is in 0..59 and repeats for the same id.

    What would make this fail: random.randint, Python's salted hash() across
    calls, or skipping sleep(jitter) so every target hits SSH on the same second.
    """
    from monitor.collector import collect, jitter_s

    assert jitter_s(1) == jitter_s(1)
    assert 0 <= jitter_s(1) <= 59
    assert 0 <= jitter_s(2) <= 59
    spread = {jitter_s(i) for i in range(1, 40)}
    assert len(spread) > 1

    slept = []
    collect(_target(7), CollectorTransport(), sleep=slept.append)
    assert slept == [jitter_s(7)]


@pytest.mark.req("REL-C3-ONE-COLLECTOR-SESSION")
def test_script_put_not_heredoc():
    """The on-target script lands via put; argv lists never carry the body.

    What would make this fail: run/probe of a shell string, cat <<EOF, or
    stuffing the script into bash -c.
    """
    from monitor import collector
    from monitor.collector import collect

    transport = CollectorTransport()
    collect(_target(), transport, sleep=_noop)

    puts = [remote for kind, remote in transport.calls if kind == "put"]
    assert puts, "expected transport.put of the collector script"
    remote = puts[0]
    payload = transport.files[remote]
    if isinstance(payload, (bytes, bytearray)):
        body = payload.decode()
    elif isinstance(payload, Path):
        body = payload.read_text(encoding="utf-8")
    else:
        body = str(payload)
    assert body.strip()
    assert "<<" not in body.splitlines()[0]

    for kind, argv in transport.calls:
        if kind not in ("run", "probe"):
            continue
        assert isinstance(argv, list), "argv must be a list — never a shell string"
        joined = " ".join(str(part) for part in argv)
        assert "<<" not in joined
        assert "cat >" not in joined
        for part in argv:
            assert body.strip() not in str(part)

    source = Path(inspect.getfile(collector)).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr not in {"probe", "run"}:
            continue
        for arg in node.args:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                raise AssertionError(
                    f"transport.{node.func.attr} passed a shell string: {arg.value!r}"
                )
            if isinstance(arg, ast.JoinedStr):
                raise AssertionError(
                    f"transport.{node.func.attr} passed an f-string argv"
                )


@pytest.mark.req("REL-C3-ONE-COLLECTOR-SESSION")
def test_two_collectors_do_not_open_three_ssh_sessions():
    """Two collect() calls on one Transport are two script executions, not three.

    What would make this fail: a third independent metrics/logs/clock argv, or
    constructing a new session per field. test -f after the first put is not a
    session.
    """
    from monitor.collector import collect

    transport = CollectorTransport()
    target = _target()
    first = collect(target, transport, sleep=_noop)
    second = collect(target, transport, sleep=_noop)
    assert set(first) == CONTRACT_KEYS
    assert set(second) == CONTRACT_KEYS
    assert _script_executions(transport) == 2
    assert _script_executions(transport) < 3
