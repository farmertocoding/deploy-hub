"""T1: shared hub-test-target launcher argv (no docker required)."""
from __future__ import annotations

import ast
import inspect
from pathlib import Path

TESTS = Path(__file__).resolve().parent


def test_hub_target_run_argv_never_binds_docker_sock():
    """The fixture's docker run argv never bind-mounts Hub docker.sock.

    What would make this fail: `-v /var/run/docker.sock` (or --volume/--mount of
    docker.sock) on the list `hub_target` actually runs, or a helper the fixture
    does not call.
    """
    from tests.harness.target import (
        IMAGE,
        SOCK,
        hub_target_run_argv,
        hub_target_session,
    )

    argv = hub_target_run_argv("hub-test-target-probe")
    assert isinstance(argv, list)
    assert argv
    assert all(isinstance(part, str) for part in argv)
    assert SOCK not in argv
    assert not any("docker.sock" in part for part in argv)
    assert "--privileged" in argv
    assert "--cgroupns=host" in argv
    assert "127.0.0.1::22" in argv
    assert IMAGE in argv
    assert IMAGE == "hub-test-target:local"
    assert "hub_target_run_argv" in inspect.getsource(hub_target_session)


def test_hub_target_removes_site_state_between_tests():
    """The per-test hub_target wrapper removes site-* containers and Caddy
    servers on teardown.

    Every T2 site publishes 127.0.0.1:20000 and a site-{slug} Caddy server on
    127.0.0.1:8088 inside the shared session target, so survivors from one test
    make the next test fail with "port is already allocated" on docker run
    (seen in the combined nightly run) or "caddy put failed" on the route PUT.

    What would make this fail: a session-only hub_target with no per-test
    cleanup, a wrapper that never calls the cleanup helpers, or a cleanup
    built from an interpolated shell string instead of an argv list.
    """
    from tests.harness.target import (
        hub_target,
        remove_site_caddy_servers,
        remove_site_containers,
    )

    wrapper_src = inspect.getsource(hub_target)
    assert "remove_site_containers" in wrapper_src
    assert "remove_site_caddy_servers" in wrapper_src
    assert "hub_target_session" in wrapper_src

    containers_src = inspect.getsource(remove_site_containers)
    assert "shell=True" not in containers_src
    assert "name=^site-" in containers_src
    assert '"docker", "rm", "-f"' in containers_src

    caddy_src = inspect.getsource(remove_site_caddy_servers)
    assert "shell=True" not in caddy_src
    assert 'startswith("site-")' in caddy_src
    assert '"DELETE"' in caddy_src


def test_t2_modules_share_one_hub_target_definition():
    """test_pipeline_sample_node_site has no docker run helper of its own.

    What would make this fail: a copied `hub_target` / `HubTarget` / `_docker`
    launcher in that module instead of importing `tests.harness.target`.
    """
    path = TESTS / "test_pipeline_sample_node_site.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    defined = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    defined |= {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert "hub_target" not in defined
    assert "_docker" not in defined
    assert "HubTarget" not in defined
    assert "--cgroupns=host" not in source

    from_harness = False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module in {
            "tests.harness.target",
            "harness.target",
        }:
            from_harness = True
        if isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if "pytest_plugins" not in names:
                continue
            for child in ast.walk(node.value):
                if (
                    isinstance(child, ast.Constant)
                    and isinstance(child.value, str)
                    and child.value in {"tests.harness.target", "harness.target"}
                ):
                    from_harness = True
    assert from_harness, "pipeline T2 must import the shared hub_target"
