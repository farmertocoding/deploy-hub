"""One SSH collector session per target per minute (REL-C3-ONE-COLLECTOR-SESSION)."""
import ast
import inspect
import json
import subprocess
import sys
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
PRODUCER = Path(__file__).resolve().parent.parent / "monitor" / "collect_once.py"
WRITABLE_REMOTE = "/home/deploy/.hub/collect-once"


def _target(pk=42):
    return SimpleNamespace(pk=pk, id=pk)


def _run_producer(tmp_path, target_id=42):
    """Execute collect_once.py against a temp log (no SSH). Returns (stdout, log)."""
    log = tmp_path / "access.log"
    log.write_bytes(b'{"status":200}\n')
    proc = subprocess.run(
        [sys.executable, str(PRODUCER), str(target_id), "0", str(log)],
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout, log


class CollectorTransport(FakeTransport):
    """One probe returns the producer script's real stdout; test -f is not a session."""

    def __init__(self, stdout=""):
        super().__init__()
        self._stdout = stdout

    def probe(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("probe", argv))
        if argv and argv[0] == "test":
            remote = argv[-1]
            return CommandResult(argv, exit_code=0 if remote in self.files else 1)
        return CommandResult(argv, stdout=self._stdout)

    def run(self, argv, *, timeout=60):
        if not isinstance(argv, (list, tuple)):
            raise TypeError("argv must be a list — never a shell string (§4.5)")
        argv = list(argv)
        self.calls.append(("run", argv))
        return CommandResult(argv, stdout=self._stdout)


def _transport(tmp_path, target_id=42):
    stdout, log = _run_producer(tmp_path, target_id)
    return CollectorTransport(stdout=stdout), log


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
        if argv[0] in {"test", "mkdir", "chmod"}:
            continue
        n += 1
    return n


def _assert_contract(payload, *, log=None):
    assert set(payload) == CONTRACT_KEYS
    assert set(payload["log_chunk"]) == LOG_CHUNK_KEYS
    assert set(payload["healthz"]) == HEALTHZ_KEYS
    if log is not None:
        assert payload["log_chunk"]["file"] == str(log)


@pytest.mark.req("REL-C3-ONE-COLLECTOR-SESSION")
def test_one_session_returns_full_contract(tmp_path):
    """One put + one probe of the collector script returns the pinned JSON.

    What would make this fail: a second argv for metrics/logs/clock, dropping
    a contract key from collect_once.py, or putting to a path deploy cannot SFTP.
    """
    from monitor.collector import collect
    from monitor.tasks import collect_all

    transport, log = _transport(tmp_path)
    result = collect(_target(), transport, sleep=_noop)

    _assert_contract(result, log=log)
    assert _script_executions(transport) == 1
    puts = [c for c in transport.calls if c[0] == "put"]
    assert len(puts) == 1
    assert puts[0][1] == WRITABLE_REMOTE

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
def test_contract_has_metrics_containers_log_chunk_clock_healthz(tmp_path):
    """C3 fields come from collect_once.py; healthz is {live, ready, checks}.

    What would make this fail: renaming a field in the producer, flattening
    healthz, or omitting log_chunk.inode/offset so the next minute cannot resume.
    """
    from monitor.collector import collect

    transport, log = _transport(tmp_path)
    result = collect(_target(), transport, sleep=_noop)
    for key in ("metrics", "containers", "log_chunk", "clock", "healthz"):
        assert key in result
    assert "live" in result["healthz"]
    assert "ready" in result["healthz"]
    assert "checks" in result["healthz"]
    chunk = result["log_chunk"]
    assert chunk["file"] == str(log)
    assert "inode" in chunk and "offset" in chunk and "bytes" in chunk
    assert '{"status":200}' in chunk["bytes"]


@pytest.mark.req("REL-C3-ONE-COLLECTOR-SESSION")
def test_jitter_is_stable_per_target(tmp_path):
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
    transport, _log = _transport(tmp_path, target_id=7)
    collect(_target(7), transport, sleep=slept.append)
    assert slept == [jitter_s(7)]


@pytest.mark.req("REL-C3-ONE-COLLECTOR-SESSION")
def test_script_put_not_heredoc(tmp_path):
    """The on-target script lands via put; argv lists never carry the body.

    What would make this fail: run/probe of a shell string, cat <<EOF,
    stuffing the script into bash -c, or putting to /usr/local/bin.
    """
    from monitor import collector
    from monitor.collector import collect

    transport, log = _transport(tmp_path)
    collect(_target(), transport, sleep=_noop)

    puts = [remote for kind, remote in transport.calls if kind == "put"]
    assert puts, "expected transport.put of the collector script"
    remote = puts[0]
    assert remote == WRITABLE_REMOTE
    payload = transport.files[remote]
    if isinstance(payload, (bytes, bytearray)):
        body = payload.decode()
    elif isinstance(payload, Path):
        body = payload.read_text(encoding="utf-8")
    else:
        body = str(payload)
    assert body.strip()
    assert "<<" not in body.splitlines()[0]

    put_script = tmp_path / "put-body.py"
    put_script.write_text(body, encoding="utf-8")
    produced = subprocess.run(
        [sys.executable, str(put_script), "42", "0", str(log)],
        check=True,
        capture_output=True,
        text=True,
    )
    _assert_contract(json.loads(produced.stdout), log=log)

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
def test_two_collectors_do_not_open_three_ssh_sessions(tmp_path):
    """Two collect() calls on one Transport are two script executions, not three.

    What would make this fail: a third independent metrics/logs/clock argv, or
    constructing a new session per field. test -f after the first put is not a
    session.
    """
    from monitor.collector import collect

    transport, log = _transport(tmp_path)
    target = _target()
    first = collect(target, transport, sleep=_noop)
    second = collect(target, transport, sleep=_noop)
    _assert_contract(first, log=log)
    _assert_contract(second, log=log)
    assert _script_executions(transport) == 2
    assert _script_executions(transport) < 3
