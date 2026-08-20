"""ensure_ship: docker image inspect via probe; load only on miss (D6 / SEC-B1)."""
import pytest
from test_ensure_build import GIT_SHA, StepTransport, _desired, _source_tree


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.req("SEC-B1-BUILD-OFFHUB")
def test_inspect_is_probe_not_run(tmp_path):
    """Image existence is transport.probe, never transport.run.

    What would make this fail: docker image inspect recorded as run (which
    would also make a second ship look mutating).
    """
    from deploys.steps import ensure_ship, image_tag

    transport = StepTransport()
    body = {"runtime": "node"}
    desired = _desired(_source_tree(tmp_path), transport, body=body)
    tag = image_tag(GIT_SHA, body)
    ensure_ship(desired)

    inspects = [
        (kind, argv) for kind, argv in transport.calls
        if kind in ("probe", "run") and "inspect" in argv
    ]
    assert inspects
    assert all(kind == "probe" for kind, argv in inspects)
    assert all(argv[:3] == ["docker", "image", "inspect"] for kind, argv in inspects)
    assert all(tag in argv for kind, argv in inspects)
    assert not any(
        kind == "run" and "inspect" in argv for kind, argv in transport.calls
    )


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_second_ship_zero_mutating_calls(tmp_path):
    """Same target after a successful build: ship inspects and skips.

    What would make this fail: inspect via run, or any run/put on the second
    ensure_ship (including docker load of an image that is already there).
    """
    from deploys.steps import ensure_build, ensure_ship, image_tag

    transport = StepTransport()
    body = {"runtime": "node"}
    desired = _desired(_source_tree(tmp_path), transport, body=body)
    tag = image_tag(GIT_SHA, body)

    ensure_build(desired)
    ensure_ship(desired)
    transport.calls.clear()
    ensure_ship(desired)

    assert transport.mutating_calls() == []
    assert transport.calls == [("probe", ["docker", "image", "inspect", tag])]
