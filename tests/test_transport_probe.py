"""D-018: probe is read-only inspect; run/put stay the mutating seam."""
import pytest

from core.transport import FakeTransport

REQ_ARGLISTS = pytest.mark.req("VAL-45-SHELL-ARGLISTS")
REQ_IDEMPOTENT = pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")


@REQ_ARGLISTS
@REQ_IDEMPOTENT
def test_probe_rejects_shell_string():
    t = FakeTransport()
    with pytest.raises(TypeError):
        t.probe("docker inspect foo")


@REQ_ARGLISTS
@REQ_IDEMPOTENT
def test_probe_is_not_a_mutating_call():
    t = FakeTransport(responses={"docker": {"stdout": "running", "exit_code": 0}})
    result = t.probe(["docker", "inspect", "c1"])
    assert result.ok
    assert result.stdout == "running"
    assert t.calls == [("probe", ["docker", "inspect", "c1"])]
    assert t.mutating_calls() == []


@REQ_ARGLISTS
@REQ_IDEMPOTENT
def test_run_and_put_still_count_as_mutating():
    t = FakeTransport()
    t.run(["echo", "hello"])
    t.put(b"data", "/tmp/x")
    assert t.mutating_calls() == [
        ("run", ["echo", "hello"]),
        ("put", "/tmp/x"),
    ]


@REQ_ARGLISTS
@REQ_IDEMPOTENT
def test_recording_transport_mutating_calls_are_run_and_put():
    from core.transport import RecordingTransport

    rec = RecordingTransport(FakeTransport())
    rec.probe(["true"])
    rec.run(["echo", "hello"])
    rec.put(b"data", "/remote/f")
    rec.get("/remote/f")
    assert rec.mutating_calls() == [
        ("run", ["echo", "hello"]),
        ("put", "/remote/f"),
    ]


@REQ_ARGLISTS
@REQ_IDEMPOTENT
def test_get_is_not_mutating():
    t = FakeTransport()
    t.put(b"data", "/remote/f")
    assert t.get("/remote/f") == b"data"
    assert ("get", "/remote/f") in t.calls
    assert t.mutating_calls() == [("put", "/remote/f")]
