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


def _sensitive_patterns():
    paths = yaml.safe_load(
        (REPO / "conformance" / "paths.yaml").read_text(encoding="utf-8"))
    return paths["sensitive"]


def _codeowners_lines():
    text = (REPO / ".github/CODEOWNERS").read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_core_ssh_py_is_on_sensitive_paths():
    """Phase 2.5 leftover: Fabric SshTransport + host-key pin was omitted from the
    human-merge glob. Membership is a parsed `sensitive:` entry, so a comment-only
    mention of `core/ssh.py` does not count. Exact membership, not Path.match:
    on versions without full_match, match("ssh.py") would accept core/ssh.py."""
    patterns = _sensitive_patterns()
    assert "core/ssh.py" in patterns, (
        f"core/ssh.py is not an exact sensitive-path entry in {patterns}")


def test_deletion_capable_reaper_is_on_sensitive_paths():
    """Panel S3: monitor/reaper.py composes `multipass delete --purge` argv —
    custody must match the harness driver it mirrors (tests/harness/**)."""
    assert "monitor/reaper.py" in _sensitive_patterns()


def test_codeowners_matches_paths_yaml_for_every_literal_entry():
    """Full paths.yaml ↔ CODEOWNERS parity for literal (non-glob) entries.

    Panel S3+I3: paths.yaml gained harness-custody entries with no CODEOWNERS
    counterpart, so "sensitive" and "human-merged" drifted apart — the single
    ssh.py spot-check could not see it. Every literal sensitive entry must
    have its exact `/<entry> @farmertocoding` owners line (comments never
    count); glob entries (`dir/**`) must have their `/dir/ @farmertocoding`
    directory line.
    """
    owners_lines = _codeowners_lines()
    missing = []
    for entry in _sensitive_patterns():
        if "*" in entry:
            # dir/** is owned by its directory line or any ancestor directory
            # line (.github/workflows/** is owned by `/.github/`).
            base = entry.split("*", 1)[0].rstrip("/")
            parts = base.split("/")
            wanted = [
                f"/{'/'.join(parts[: i + 1])}/ @farmertocoding"
                for i in range(len(parts))
            ]
        else:
            wanted = [f"/{entry} @farmertocoding"]
        if not any(w in owners_lines for w in wanted):
            missing.append(f"{entry} -> one of {wanted}")
    assert missing == [], (
        "sensitive paths.yaml entries with no CODEOWNERS owners line "
        f"(paths.yaml and CODEOWNERS have drifted): {missing}")


def test_codeowners_lists_core_ssh_py():
    """CODEOWNERS must list `/core/ssh.py @farmertocoding` as an owners line.
    Comments are skipped so a mention in a comment does not satisfy this."""
    owners_lines = _codeowners_lines()
    assert "/core/ssh.py @farmertocoding" in owners_lines, (
        "CODEOWNERS has no owners line `/core/ssh.py @farmertocoding`")
