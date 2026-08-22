"""T1: Multipass skip cannot green a tier:t3 req (D-023 / D-024)."""
from __future__ import annotations

import ast
import pathlib
import subprocess

import gates
import pytest
from test_conformance_gate import (
    T3_MARKED_TEST,
    _req,
    run_check,
    status_of,
    write_repo,
)

REPO = pathlib.Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"

HOST_WITHOUT_MULTIPASS_WAIVER = (
    "WAIVED: FIX-T3-SKIP+host-without-multipass — host-without-multipass planted "
    "for the anti-silent-green probe (2026-08-22)\n"
)

HOST_WITHOUT_MULTIPASS_REQ_WAIVER = (
    "WAIVED: FIX-T3-SKIP — host-without-multipass planted to prove the helper "
    "(2026-08-22)\n"
)


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_t3_marker_registered(pytestconfig):
    """pytest must know the `t3` mark so `@pytest.mark.t3` is not unknown.

    What would make this fail: dropping the t3 line from pyproject.toml markers.
    """
    markers = pytestconfig.getini("markers")
    names = [entry.split(":", 1)[0].split("(", 1)[0].strip() for entry in markers]
    assert "t3" in names, f"t3 is not a registered pytest mark: {markers}"


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_make_test_deselects_t3():
    """`make test` stays T1: `-m "not t2 and not t3"`.

    What would make this fail: the default test recipe collecting t3, which
    would pull Multipass into review-round / Cloud Agent.
    """
    recipe = gates.recipe(REPO, "test")
    assert recipe, "Makefile has no `test` recipe"
    assert "not t2 and not t3" in recipe, recipe


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_t3_only_req_is_skipped_only_not_verified(tmp_path):
    """A `tier: t3` req whose only test is skipped is skipped-only, never verified.

    What would make this fail: counting skip as a pass, or a T1 sibling greening
    the id. Reuses the Task 0 throwaway-tree helpers.
    """
    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T3-SKIP", tier="t3")],
        tests_src={
            "tests/test_live.py": T3_MARKED_TEST.format(
                rid="FIX-T3-SKIP", name="test_live"
            )
        },
        outcomes={"tests/test_live.py::test_live": "skipped"},
    )
    res = run_check(root)
    assert res.returncode != 0, (
        f"a skipped-only tier:t3 req went green:\n{res.stdout}{res.stderr}"
    )
    assert status_of(root, "FIX-T3-SKIP") == "skipped-only"
    assert status_of(root, "FIX-T3-SKIP") != "verified"


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_host_without_multipass_waiver_does_not_verify_when_multipass_present(
    tmp_path, monkeypatch
):
    """A planted host-without-multipass waiver must not verify tier:t3 when Multipass is here.

    What would make this fail: treating the waiver as enough whenever it is
    planted, even if `multipass_available()` is True (silent green / D-024).
    Do not add this waiver to the real WAIVERS.md (Task 16).
    """
    from tests.harness.multipass import (
        multipass_available,
        version_argv,
        waiver_illegal_if,
    )

    assert version_argv() == ["multipass", "version"]

    recorded = {}
    real_run = subprocess.run

    def fake_run(argv, **kwargs):
        argv = list(argv)
        if argv[:2] == ["multipass", "version"]:
            recorded["argv"] = argv
            recorded["timeout"] = kwargs.get("timeout")
            return subprocess.CompletedProcess(argv, 0, "", "")
        return real_run(argv, **kwargs)

    # multipass_available is defined in monitor/reaper.py (panel I4: one
    # driver); the harness re-exports it and no longer imports subprocess
    # itself. Patching the shared subprocess module covers the defining module.
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert multipass_available() is True
    assert recorded["argv"] == ["multipass", "version"]
    assert recorded["timeout"] == 5

    assert waiver_illegal_if(lambda: True) is True
    assert waiver_illegal_if(multipass_available) is True
    assert waiver_illegal_if(lambda: False) is False

    root = write_repo(
        tmp_path,
        reqs=[_req("FIX-T3-SKIP", tier="t3")],
        tests_src={
            "tests/test_live.py": T3_MARKED_TEST.format(
                rid="FIX-T3-SKIP", name="test_live"
            )
        },
        outcomes={"tests/test_live.py::test_live": "skipped"},
        waivers=HOST_WITHOUT_MULTIPASS_WAIVER,
    )
    res = run_check(root)
    assert res.returncode != 0, (
        f"a host-without-multipass fingerprint verified a skipped tier:t3 req:\n"
        f"{res.stdout}{res.stderr}"
    )
    assert status_of(root, "FIX-T3-SKIP") == "skipped-only"
    assert status_of(root, "FIX-T3-SKIP") != "verified"

    # A req-id waiver would silence check.py. The helper still refuses, so that
    # green is illegal while Multipass is present.
    greener = write_repo(
        tmp_path / "greener",
        reqs=[_req("FIX-T3-SKIP", tier="t3")],
        tests_src={
            "tests/test_live.py": T3_MARKED_TEST.format(
                rid="FIX-T3-SKIP", name="test_live"
            )
        },
        outcomes={"tests/test_live.py::test_live": "skipped"},
        waivers=HOST_WITHOUT_MULTIPASS_REQ_WAIVER,
    )
    naive = run_check(greener)
    assert naive.returncode == 0, naive.stdout + naive.stderr
    assert status_of(greener, "FIX-T3-SKIP") != "verified"
    assert waiver_illegal_if(lambda: True) is True


@pytest.mark.req("HARNESS-T3-SKIP-POLICY")
def test_t3_skipif_does_not_use_pytest_skip_in_t1_modules():
    """T1 modules must not `pytest.skip` / `skipif` on Multipass.

    `@pytest.mark.t3` + skipif belongs only on T3 modules (Task 10+). What
    would make this fail: a T1 test calling skip/skipif on multipass_available,
    so a Darwin Cloud Agent silently drops T3-shaped work.
    """
    from tests.harness.multipass import multipass_available

    assert callable(multipass_available)

    offenders = []
    for path in sorted(TESTS.rglob("*.py")):
        if path.name == "conftest.py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        inherited = _pytestmark_names(tree)
        if "t3" in inherited:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            marks = inherited | _decorator_mark_names(node)
            if "t3" in marks:
                continue
            if _skips_on_multipass(node):
                offenders.append(f"{path.relative_to(REPO)}::{node.name}")

    assert not offenders, (
        "T1 tests must not skip on Multipass (T3 skipif belongs on @pytest.mark.t3 "
        f"modules only): {offenders}"
    )


def _mark_name(expr):
    target = expr.func if isinstance(expr, ast.Call) else expr
    parts = []
    while isinstance(target, ast.Attribute):
        parts.append(target.attr)
        target = target.value
    if isinstance(target, ast.Name):
        parts.append(target.id)
    if parts and "mark" in parts:
        return parts[0]
    return None


def _decorator_mark_names(node):
    names = set()
    for dec in node.decorator_list:
        name = _mark_name(dec)
        if name:
            names.add(name)
    return names


def _pytestmark_names(tree):
    names = set()
    for stmt in tree.body:
        if not isinstance(stmt, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "pytestmark" for t in stmt.targets):
            continue
        value = stmt.value
        elts = value.elts if isinstance(value, (ast.List, ast.Tuple)) else [value]
        for elt in elts:
            name = _mark_name(elt)
            if name:
                names.add(name)
    return names


def _skips_on_multipass(fn_node):
    for dec in fn_node.decorator_list:
        if _mark_name(dec) in {"skip", "skipif"} and _mentions_multipass(dec):
            return True
    for node in ast.walk(fn_node):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Attribute) and func.attr == "skip":
            if _mentions_multipass(node):
                return True
        if isinstance(func, ast.Attribute) and func.attr == "skipif":
            if _mentions_multipass(node):
                return True
    return False


def _mentions_multipass(node):
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and "multipass" in child.id.lower():
            return True
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if "multipass" in child.value.lower():
                return True
    return False
