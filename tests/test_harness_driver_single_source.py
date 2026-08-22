"""One Multipass driver (2.5 panel I4).

The prefix guard that keeps `multipass delete --purge` off non-test VMs must
exist exactly once, in product code, with the harness as a thin consumer.
"""
from __future__ import annotations

import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


def _python_roots():
    """Top-level python packages plus tests/ — same shape as the Makefile scan."""
    return sorted(
        p for p in REPO.iterdir() if p.is_dir() and (p / "__init__.py").exists()
    )


def test_multipass_argv_has_one_definition():
    """harness multipass re-exports monitor/reaper's driver primitives.

    What would make this fail: tests/harness/multipass.py growing its own
    require_t3_name / list / delete argv builders again — two prefix guards
    with already-divergent error handling, only one of which reviews see.
    """
    import monitor.reaper as product
    import tests.harness.multipass as harness

    for name in (
        "NAME_PREFIX",
        "T3NameError",
        "require_t3_name",
        "version_argv",
        "list_argv",
        "delete_purge_argv",
        "multipass_available",
        "delete_purge",
        "list_names",
    ):
        assert getattr(harness, name) is getattr(product, name), (
            f"tests.harness.multipass.{name} is not monitor.reaper.{name}"
        )

    needle = "def " + "require_t3_name("  # split so this file never matches itself
    definitions = []
    for root in _python_roots():
        for py in root.rglob("*.py"):
            if needle in py.read_text(encoding="utf-8"):
                definitions.append(str(py.relative_to(REPO)))
    assert definitions == ["monitor/reaper.py"], (
        f"the prefix guard must have one definition, found: {definitions}"
    )


def test_both_callers_use_the_same_guard():
    """Harness launch/exec and product delete refuse the same non-test name.

    What would make this fail: a harness-local guard class — a raise the
    product `except T3NameError` handlers would no longer catch, or a copy
    whose prefix could drift from the reaper's.
    """
    from monitor.reaper import T3NameError, delete_purge_argv
    from tests.harness.multipass import MultipassVM, exec_argv, launch_argv

    with pytest.raises(T3NameError):
        launch_argv("primary", cpus=1, mem="1G", disk="5G")
    with pytest.raises(T3NameError):
        exec_argv(MultipassVM(name="primary", ipv4="", user="deploy"), ["true"])
    with pytest.raises(T3NameError):
        delete_purge_argv("primary")
