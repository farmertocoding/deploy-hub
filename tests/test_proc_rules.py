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


def test_codeowners_entries_all_appear_in_paths_yaml():
    """Custody parity is two-way (phase-3 Task 0; a 2.5 finding left it one-way).

    The forward test above proves every paths.yaml entry has a CODEOWNERS
    line. This is the reverse: every CODEOWNERS owners line must have a
    paths.yaml counterpart, so a path someone makes human-merge-only in
    CODEOWNERS alone cannot drift outside the sensitive-path check CI runs —
    the two lists must name the same custody set, from either end.
    """
    patterns = _sensitive_patterns()
    orphans = []
    for line in _codeowners_lines():
        entry = line.split()[0].lstrip("/")
        if entry.endswith("/"):
            # A directory line owns dir/**; its counterpart is any sensitive
            # entry under that directory (`.github/` is satisfied by
            # `.github/workflows/**`).
            covered = any(p.startswith(entry) for p in patterns)
        else:
            covered = entry in patterns or any(
                p.endswith("/**") and entry.startswith(p[:-2])
                for p in patterns)
        if not covered:
            orphans.append(line)
    assert orphans == [], (
        "CODEOWNERS owners lines with no paths.yaml counterpart "
        f"(custody parity is two-way): {orphans}")


def test_phase_3_sensitive_modules_are_listed():
    """Phase-3 custody set (Task 0): the pager publish path, the transcribed
    alert rules table, the cert-material push, and compose-aware adopt are all
    deletion/credential/edge-adjacent — each needs its paths.yaml entry AND its
    CODEOWNERS owners line before any task lands code there.
    """
    patterns = _sensitive_patterns()
    owners_lines = _codeowners_lines()
    for entry in (
        "monitor/pager.py",
        "monitor/alert_rules.py",
        "deploys/certs.py",
        "provision/adopt.py",
        "deploys/adopt_flow.py",
    ):
        assert entry in patterns, (
            f"{entry} is not a sensitive-path entry in conformance/paths.yaml")
        assert f"/{entry} @farmertocoding" in owners_lines, (
            f"CODEOWNERS has no owners line `/{entry} @farmertocoding`")


def test_codeowners_lists_core_ssh_py():
    """CODEOWNERS must list `/core/ssh.py @farmertocoding` as an owners line.
    Comments are skipped so a mention in a comment does not satisfy this."""
    owners_lines = _codeowners_lines()
    assert "/core/ssh.py @farmertocoding" in owners_lines, (
        "CODEOWNERS has no owners line `/core/ssh.py @farmertocoding`")
