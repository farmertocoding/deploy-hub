"""SEC-69 exhaust gate: captured pytest stdout/stderr/log and Celery kwargs.

C9: this is captured exhaust, not `make log-scrub`. log-scrub stays the
source scan for `SECRET_KEY\\s*=` in first-party Python.
"""
import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

pytestmark = pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")


def _exhaust():
    existing = sys.modules.get("hub_exhaust")
    if existing is not None:
        return existing
    path = REPO / "scripts_dev" / "exhaust.py"
    spec = importlib.util.spec_from_file_location("hub_exhaust", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hub_exhaust"] = mod
    spec.loader.exec_module(mod)
    return mod


def test_exhaust_gate_flags_plaintext_in_captured_output():
    """A vault plaintext marker in pytest stdout, stderr, or log capture is a leak.

    What would make this fail: scanning source files instead of captured
    exhaust, or ignoring one of stdout / stderr / the log capture.
    """
    exhaust = _exhaust()
    marker = exhaust.VAULT_PLAINTEXT_MARKER
    assert exhaust.captured_leaks(stdout=f"debug {marker}", stderr="", log="")
    assert exhaust.captured_leaks(stdout="", stderr=marker, log="")
    assert exhaust.captured_leaks(stdout="", stderr="", log=f"INFO {marker}")
    assert not exhaust.captured_leaks(stdout="ok", stderr="ok", log="ok")


def test_exhaust_gate_flags_plaintext_in_celery_kwargs():
    """A vault plaintext marker in Celery args/kwargs is a leak.

    What would make this fail: scanning only string kwargs and missing a
    nested dict or a bytes arg, or wrapping pickle instead of the payload.
    """
    exhaust = _exhaust()
    marker = exhaust.VAULT_PLAINTEXT_MARKER
    assert exhaust.celery_kwargs_leaks(args=(marker,), kwargs={})
    assert exhaust.celery_kwargs_leaks(args=(), kwargs={"password": marker})
    assert exhaust.celery_kwargs_leaks(
        args=(), kwargs={"nested": {"x": marker.encode("utf-8")}}
    )
    assert not exhaust.celery_kwargs_leaks(args=("site:1",), kwargs={"owner_id": 7})

    from realtime.tasks import demo_stream_logs

    with pytest.raises(exhaust.ExhaustLeak, match="Celery"):
        demo_stream_logs.delay("exhaust-job", marker)
