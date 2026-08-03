"""Mechanical teeth for process rules (review3 §Q6) — registered as PROC- reqs."""
import pathlib
import re

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent

# Decorator-anchored so mentions in strings/comments (incl. this file) don't count
# toward the cap (round-1 finding: the effective cap was 4, not the documented 5).
FLAKY_DECORATOR = re.compile(r"^\s*@pytest\.mark\.flaky_quarantine\b", re.M)


@pytest.mark.req("PROC-FLAKE-CAP")
def test_flake_quarantine_cap():
    count = 0
    for py in (REPO / "tests").rglob("*.py"):
        count += len(FLAKY_DECORATOR.findall(py.read_text(encoding="utf-8")))
    assert count <= 5, f"flake quarantine cap exceeded: {count} > 5"
