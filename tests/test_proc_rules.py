"""Mechanical teeth for process rules (review3 §Q6) — registered as PROC- reqs."""
import pathlib
import re

import pytest
import yaml

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


def test_core_ssh_py_is_on_sensitive_paths():
    """Phase 2.5 leftover: Fabric SshTransport + host-key pin was omitted from
    the human-merge glob. Matched the way the guard matches (R7-9): yaml.safe_load
    plus PurePosixPath, so a comment-only mention of core/ssh.py does not count."""
    paths = yaml.safe_load(
        (REPO / "conformance" / "paths.yaml").read_text(encoding="utf-8"))
    patterns = paths["sensitive"]
    target = pathlib.PurePosixPath("core/ssh.py")
    assert any(target.full_match(p) if hasattr(target, "full_match")
               else target.match(p) for p in patterns), (
        f"core/ssh.py is matched by no sensitive-path glob in {patterns}")


def test_codeowners_lists_core_ssh_py():
    """CODEOWNERS must list `/core/ssh.py @farmertocoding` as an owners line.
    Comments are skipped so a mention in a comment does not satisfy this."""
    text = (REPO / ".github/CODEOWNERS").read_text(encoding="utf-8")
    owners_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    assert "/core/ssh.py @farmertocoding" in owners_lines, (
        "CODEOWNERS has no owners line `/core/ssh.py @farmertocoding`")
