"""Mechanical teeth for process rules (review3 §Q6) — registered as PROC- reqs."""
import pathlib

import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent


@pytest.mark.req("PROC-FLAKE-CAP")
def test_flake_quarantine_cap():
    count = 0
    for py in (REPO / "tests").rglob("*.py"):
        count += py.read_text(encoding="utf-8").count("@pytest.mark.flaky_quarantine")
    assert count <= 5, f"flake quarantine cap exceeded: {count} > 5"
