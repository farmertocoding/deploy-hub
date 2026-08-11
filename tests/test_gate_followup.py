"""The round-5 follow-up list: N1, N3, the two deferrals, and D-010 item 2.

Round 5 closed ten findings and wrote down five things it deliberately did not close.
Four of them are here (the fifth, N2 — a wired-in no-op target still resolves as a gate —
is documented in three places and left alone); the fifth test group is item 2 of the
D-010 scanner follow-up list, which is the same defect class as N1 and belongs with it.

  N1   `check.py` and `tests/test_gate_parity.py` each answered "does CI invoke this
       gate?", at different strictnesses. That is R4-8's own defect — one rule, two
       declarations, drifting — reproduced inside the machinery built to kill it.
  N3   The `if:` ban has no escape hatch, so D-001's PR-only `sensitive-path-guard` has
       no legal shape once it stops being an echo.
  D1   `text_hash` pins only the first `§` of a multi-section `source:`.
  D2   The run report is bound to `git rev-parse HEAD`, not to the working tree.
  W    A malformed `WAIVERS.md` line evaporates in silence, waiving nothing.

Behavioural assertions drive `check.py` as a subprocess against a throwaway tree, for
the reason `test_conformance_gate.py` states: the property under test is how the gate
behaves *when actually invoked*.
"""
import ast
import hashlib
import json
import pathlib
import re
import subprocess

import gates
import pytest
from test_conformance_gate import (
    REPO,
    head_sha,
    matrix,
    run_check,
    status_of,
    write_repo,
)

CHECK_PY = REPO / "conformance" / "check.py"
PARITY_PY = REPO / "tests" / "test_gate_parity.py"


# ── shared fixtures ─────────────────────────────────────────────────────────

GATED_MAKEFILE = (
    ".PHONY: lint test conformance review-round\n"
    "review-round: lint test conformance\n"
    "\t@echo gates green\n"
    "lint:\n\t@true\n"
    "test:\n\t@true\n"
    "conformance:\n\t@true\n"
)

HONEST_WORKFLOW = """\
name: push-checks
on: [push, pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - name: lint gate
        run: make lint
      - name: unit tests
        run: make test
      - name: conformance gate
        run: make conformance
"""


def _gate_req(rid="PROC-EXAMPLE-GATE", **kw):
    req = {"id": rid, "phase": 1, "verify": "checklist",
           "source": "build-process.md §4",
           "text": "A checklist requirement that exists purely for this fixture.",
           "gate": "lint"}
    req.update(kw)
    return req


def _top_level_definitions(path):
    """{name: source} for every top-level assignment and function def in a module."""
    source = pathlib.Path(path).read_text(encoding="utf-8")
    tree = ast.parse(source)
    out = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names = [node.name]
        elif isinstance(node, ast.Assign):
            names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        else:
            continue
        for name in names:
            out[name] = ast.get_source_segment(source, node) or ""
    return out


# Names conformance/gates.py owns. A consumer may bind one of these to a delegating
# wrapper; it may not define one that never reaches `gates`.
GATES_OWNED = frozenset({
    "MAKE_CALL_RE", "BARE_MAKE_RE", "SHELL_JOINERS", "WAIVER_RE",
    "makefile_targets", "phony_targets", "_phony_targets",
    "review_round_prerequisites", "_review_round_prerequisites",
    "workflow_invoked_targets", "ci_gate_invocations",
    "gate_step_violations", "bare_make_target", "_bare_make_target",
    "waived_ids", "_waived_fingerprints", "parse_waivers", "tree_fingerprint",
    "_guard_problem", "_run_commands", "_strip_comment",
})


def _reimplemented(path):
    """Owned names this module defines without ever calling through to `gates`."""
    return sorted(name for name, src in _top_level_definitions(path).items()
                  if name in GATES_OWNED and "gates." not in src)


def _imports_gates(path):
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and any(a.name == "gates" for a in node.names):
            return True
        if isinstance(node, ast.ImportFrom) and node.module == "gates":
            return True
    return False


# ── N1: one implementation of "does CI invoke this gate?" ───────────────────

NEUTERED_WORKFLOW = """\
name: push-checks
on: [push, pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - name: lint gate
        continue-on-error: true
        run: make lint
      - name: unit tests
        run: make test
      - name: conformance gate
        run: make conformance
"""


def test_issue_n1_a_swallowed_ci_step_does_not_prove_a_gate_runs(tmp_path):
    """`gate: lint` may not resolve on a step whose verdict CI throws away.

    Round-5 F3 established that a `gate:` value must name a Makefile target that a
    review round runs and that CI invokes — because naming a gate is not running it.
    N1 is the same sentence one step further: `check.py::workflow_invoked_targets`
    accepted the substring `make lint` anywhere in any `run:`, including a step
    carrying `continue-on-error: true`, which `tests/test_gate_parity.py` had rejected
    as neutered since round-5 F2. So the requirement read `verified` on a gate whose
    result CI discards, and the two files disagreed in writing about the same workflow.
    """
    root = write_repo(
        tmp_path / "neutered", reqs=[_gate_req()], makefile=GATED_MAKEFILE,
        workflows={"push-checks.yml": NEUTERED_WORKFLOW},
    )
    result = run_check(root)
    assert result.returncode == 1, (
        "check.py accepted `gate: lint` although the only CI step invoking it carries "
        f"`continue-on-error: true`:\n{result.stdout}{result.stderr}")
    assert status_of(root, "PROC-EXAMPLE-GATE") == "uncovered"
    assert "continue-on-error" in result.stdout, (
        "the failure does not say why the gate did not resolve — the reviewer has to "
        f"guess which of the three conditions failed:\n{result.stdout}")

    # And the honest form of the same workflow still resolves, so this is a real
    # discrimination and not a check that rejects everything.
    ok = write_repo(
        tmp_path / "honest", reqs=[_gate_req()], makefile=GATED_MAKEFILE,
        workflows={"push-checks.yml": HONEST_WORKFLOW},
    )
    result_ok = run_check(ok)
    assert result_ok.returncode == 0, f"{result_ok.stdout}{result_ok.stderr}"
    assert status_of(ok, "PROC-EXAMPLE-GATE") == "verified"


@pytest.mark.parametrize("neutering,token", [
    ("        run: make lint && echo ok || true\n", "&&"),
    ("        if: github.ref == 'refs/heads/main'\n        run: make lint\n", "if"),
    ("        run: make lint --keep-going\n", "--keep-going"),
])
def test_issue_n1_check_py_agrees_with_the_parity_test_on_every_neutering(
        tmp_path, neutering, token):
    """Whatever the parity test calls neutered, `check.py` must too — by construction.

    One implementation means the two cannot be enumerated separately: each shape below
    was rejected by `gate_step_violations` and accepted by `check.py`.
    """
    workflow = (
        "name: push-checks\non: [push, pull_request]\njobs:\n  gates:\n"
        "    runs-on: ubuntu-latest\n    steps:\n      - name: lint gate\n"
        + neutering +
        "      - name: unit tests\n        run: make test\n"
        "      - name: conformance gate\n        run: make conformance\n"
    )
    root = write_repo(
        tmp_path, reqs=[_gate_req()], makefile=GATED_MAKEFILE,
        workflows={"push-checks.yml": workflow},
    )
    wf = root / ".github/workflows/push-checks.yml"
    required = gates.review_round_prerequisites(root)
    violations = gates.gate_step_violations(wf, required, gates.pr_only_gates(root))
    assert violations, f"fixture is wrong: {token} was not treated as a neutering"

    result = run_check(root)
    assert result.returncode == 1, (
        f"gate_step_violations rejects this step ({violations}) but check.py accepted "
        f"the gate it invokes — the two answers have drifted again:\n{result.stdout}")


def test_issue_n1_neither_consumer_re_derives_the_gate_machinery():
    """The structural half: one module owns these questions, and both callers import it.

    A behavioural test can only catch the divergences someone thought to enumerate.
    This one catches the next copy at the moment it is written.

    A *delegating* definition is fine — `SHELL_JOINERS = gates.SHELL_JOINERS`, or a
    wrapper that fills in this file's `REQUIRED_TARGETS` and calls through, keeps the
    rule in one place while letting the caller read naturally. What is banned is a
    definition of an owned name that never reaches `gates`: that is a second
    implementation, and a second implementation is what drifted.
    """
    for path in (CHECK_PY, PARITY_PY):
        rel = path.relative_to(REPO)
        assert _imports_gates(path), (
            f"{rel} does not import conformance/gates.py — the gate machinery is "
            f"declared once and imported, never re-derived (N1)")
        reimplemented = _reimplemented(path)
        assert not reimplemented, (
            f"{rel} defines {reimplemented} without delegating to conformance/gates.py, "
            f"which owns them. Two implementations of one rule is the R4-8 defect class; "
            f"call through instead")


def test_issue_n1_the_re_implementation_check_would_fire(tmp_path):
    """Negative control for the test above.

    Round-5 F-2/F-3 were two enforcement tests that could not fail, and the D-010
    verifier caught a third. An assertion that only ever runs against a tree already
    arranged to satisfy it proves nothing, so run the same predicate over a module that
    imports `gates` and then re-implements one of its rules anyway — the exact shape the
    ban exists to catch — and over one that delegates.
    """
    copy = tmp_path / "copycat.py"
    copy.write_text(
        "import gates\n\n"
        "SHELL_JOINERS = gates.SHELL_JOINERS\n\n\n"
        "def gate_step_violations(workflow, required):\n"
        "    return ['a second opinion nobody asked for']\n",
        encoding="utf-8")
    assert _reimplemented(copy) == ["gate_step_violations"], (
        "a verbatim second implementation was accepted, so the ban is decorative")

    delegate = tmp_path / "delegate.py"
    delegate.write_text(
        "import gates\n\n"
        "SHELL_JOINERS = gates.SHELL_JOINERS\n\n\n"
        "def gate_step_violations(workflow):\n"
        "    return gates.gate_step_violations(workflow, {'lint'})\n",
        encoding="utf-8")
    assert _reimplemented(delegate) == [], (
        "a delegating wrapper was rejected — the ban is on second implementations, not "
        "on naming things after what they call")


# ── N3: the `if:` ban needs a declared, narrow escape hatch ─────────────────

PR_ONLY_MAKEFILE = (
    ".PHONY: lint test conformance sensitive-paths review-round\n"
    "PR_ONLY_GATES := sensitive-paths\n"
    "review-round: lint test conformance sensitive-paths\n"
    "\t@echo gates green\n"
    "lint:\n\t@true\n"
    "test:\n\t@true\n"
    "conformance:\n\t@true\n"
    "sensitive-paths:\n\t@true\n"
)


def _pr_workflow(if_expr="github.event_name == 'pull_request'", on="[push, pull_request]"):
    return (
        f"name: push-checks\non: {on}\njobs:\n"
        "  gates:\n    runs-on: ubuntu-latest\n    steps:\n"
        "      - name: lint gate\n        run: make lint\n"
        "      - name: unit tests\n        run: make test\n"
        "      - name: conformance gate\n        run: make conformance\n"
        "  sensitive-path-guard:\n    runs-on: ubuntu-latest\n"
        f"    if: {if_expr}\n    steps:\n"
        "      - name: sensitive paths\n        run: make sensitive-paths\n"
    )


def test_issue_n3_a_declared_pr_only_gate_may_be_conditional(tmp_path):
    """D-001's guard compares a branch to its merge base; on `push` there is nothing to
    compare. Round 5 banned `if:` on any gate step outright, which leaves that gate no
    legal shape at all — run it on push and it is meaningless, guard it and the parity
    check calls it neutered. The exemption is declared in the Makefile, next to the gate
    list itself, so it shows up in the diff that spends it.
    """
    root = write_repo(
        tmp_path, reqs=[_gate_req(gate="sensitive-paths")], makefile=PR_ONLY_MAKEFILE,
        workflows={"push-checks.yml": _pr_workflow()},
    )
    wf = root / ".github/workflows/push-checks.yml"
    violations = gates.gate_step_violations(
        wf, gates.review_round_prerequisites(root), gates.pr_only_gates(root))
    assert violations == [], (
        "a gate declared PR-only in the Makefile and scoped with the one permitted "
        "expression was still reported as neutered:\n" + "\n".join(violations))

    result = run_check(root)
    assert result.returncode == 0, f"{result.stdout}{result.stderr}"
    assert status_of(root, "PROC-EXAMPLE-GATE") == "verified"


def test_issue_n3_an_undeclared_gate_may_not_be_conditional(tmp_path):
    """Without the declaration the ban stands — otherwise the hatch is just a hole."""
    makefile = PR_ONLY_MAKEFILE.replace("PR_ONLY_GATES := sensitive-paths\n", "")
    root = write_repo(
        tmp_path, reqs=[_gate_req(gate="sensitive-paths")], makefile=makefile,
        workflows={"push-checks.yml": _pr_workflow()},
    )
    wf = root / ".github/workflows/push-checks.yml"
    violations = gates.gate_step_violations(
        wf, gates.review_round_prerequisites(root), gates.pr_only_gates(root))
    assert any("PR_ONLY_GATES" in v for v in violations), (
        "an `if:` on an undeclared gate was allowed, or the message does not tell the "
        "author how to declare it:\n" + "\n".join(violations))
    assert run_check(root).returncode == 1


@pytest.mark.parametrize("if_expr", [
    "github.ref == 'refs/heads/main'",
    "success()",
    "github.event_name == 'pull_request' && github.actor != 'dependabot[bot]'",
])
def test_issue_n3_a_pr_only_gate_may_not_carry_an_arbitrary_if(tmp_path, if_expr):
    """The exemption scopes a gate to pull requests. It is not `if:` re-opened."""
    root = write_repo(
        tmp_path, reqs=[_gate_req(gate="sensitive-paths")], makefile=PR_ONLY_MAKEFILE,
        workflows={"push-checks.yml": _pr_workflow(if_expr=if_expr)},
    )
    wf = root / ".github/workflows/push-checks.yml"
    violations = gates.gate_step_violations(
        wf, gates.review_round_prerequisites(root), gates.pr_only_gates(root))
    assert any("PR-scoping" in v for v in violations), (
        f"`if: {if_expr}` was accepted on a PR-only gate:\n" + "\n".join(violations))


def test_issue_n3_a_pr_only_gate_in_a_push_only_workflow_never_runs(tmp_path):
    """Scoping a gate to pull requests inside a workflow that has no `pull_request`
    trigger does not scope it — it deletes it."""
    root = write_repo(
        tmp_path, reqs=[_gate_req(gate="sensitive-paths")], makefile=PR_ONLY_MAKEFILE,
        workflows={"push-checks.yml": _pr_workflow(on="[push]")},
    )
    wf = root / ".github/workflows/push-checks.yml"
    violations = gates.gate_step_violations(
        wf, gates.review_round_prerequisites(root), gates.pr_only_gates(root))
    assert any("pull_request" in v and "never runs" in v for v in violations), (
        "a PR-scoped gate in a push-only workflow was accepted:\n" + "\n".join(violations))


def test_issue_n3_an_empty_pr_only_declaration_declares_nothing():
    """`PR_ONLY_GATES :=` with no value must yield the empty set — and this repo ships
    exactly that, so the assertion is against the live Makefile as well as a fixture.

    Found by `pr_only_declaration_problems` on its first honest run: the reader used
    `\\s*` around the `=`, and `\\s` matches newlines, so an empty declaration ran on
    into the blank line and read the *next comment line* as its value. Every word of a
    prose comment then arrived as a declared PR-only gate.
    """
    empty = ("PR_ONLY_GATES :=\n"
             "\n"
             "# §4.5 pipeline: serializers → OpenAPI → generated TS types (D-002).\n"
             "generate-client:\n\t@true\n"
             "review-round: lint\n\t@true\n")
    assert gates.pr_only_gates(text=empty) == set(), (
        "an empty declaration picked up the following lines: "
        f"{sorted(gates.pr_only_gates(text=empty))}")

    assert gates.pr_only_gates(text="PR_ONLY_GATES := a b\n") == {"a", "b"}
    assert gates.pr_only_gates(text="review-round: lint\n") == set()
    assert gates.pr_only_declaration_problems(REPO) == [], (
        "the live Makefile's PR_ONLY_GATES declaration does not parse to real gates: "
        + "\n  ".join(gates.pr_only_declaration_problems(REPO)))


def test_issue_n3_pr_only_gates_may_only_name_a_real_gate(tmp_path):
    """A declaration naming something `review-round` does not run is dead text that
    reads like an enforced exemption."""
    makefile = PR_ONLY_MAKEFILE.replace(
        "PR_ONLY_GATES := sensitive-paths", "PR_ONLY_GATES := sensitive-paths typo-gate")
    root = write_repo(
        tmp_path, reqs=[_gate_req(gate="sensitive-paths")], makefile=makefile,
        workflows={"push-checks.yml": _pr_workflow()},
    )
    problems = gates.pr_only_declaration_problems(root)
    assert any("typo-gate" in p for p in problems), problems
    result = run_check(root)
    assert result.returncode == 1 and "typo-gate" in result.stdout, (
        f"check.py did not surface a dead PR_ONLY_GATES entry:\n{result.stdout}")


# ── D-010 item 2: a malformed waiver line must be loud ──────────────────────

GOOD_WAIVER = "WAIVED: PROC-EXAMPLE-GATE — no gate exists on this tree yet (2026-08-11)\n"


@pytest.mark.parametrize("bad,needle", [
    ("WAIVED: PROC-EXAMPLE-GATE - hyphen instead of an em dash (2026-08-11)\n",
     "em dash"),
    ("WAIVED: PROC-EXAMPLE-GATE — dated (2026-08-11) mid-sentence, then more prose\n",
     "must END with the date"),
    ("WAIVED: PROC-EXAMPLE-GATE — no date at all\n", "must END with the date"),
])
def test_issue_d010_2_an_unparseable_waiver_line_is_a_gate_failure(tmp_path, bad, needle):
    """A line that waives nothing must say so, naming itself.

    The D-010 verifier hit this during that very PR: the Architect's waiver text,
    transcribed verbatim, stopped parsing and the gate failed with "no marker" rather
    than "WAIVERS.md line N is unparseable". A typo'd fingerprint waives nothing,
    forever, in silence — and the second case here is worse than silence, because the
    line does contain a date and reads to a human as a waiver in force.
    """
    root = write_repo(tmp_path, reqs=[_gate_req(gate=None)], waivers=bad,
                      makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW})
    result = run_check(root)
    assert result.returncode == 1, (
        f"an unparseable waiver line was dropped in silence:\n{result.stdout}")
    assert "unparseable waiver" in result.stdout and needle in result.stdout, (
        f"the failure does not name the defect ({needle!r}):\n{result.stdout}")
    assert "WAIVERS.md:1" in result.stdout, (
        f"the failure does not name the line:\n{result.stdout}")


def test_issue_d010_2_a_well_formed_waiver_still_waives(tmp_path):
    """The strictness has to be worth something: the correct form still works."""
    root = write_repo(tmp_path, reqs=[_gate_req(gate=None)], waivers=GOOD_WAIVER,
                      makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW})
    result = run_check(root)
    assert result.returncode == 0, f"{result.stdout}{result.stderr}"
    assert status_of(root, "PROC-EXAMPLE-GATE") == "uncovered"  # uncovered, but waived


def test_issue_d010_2_a_waiver_naming_an_unknown_requirement_id_is_a_gate_failure(tmp_path):
    """`WAIVED: SEC-B4-REDIS-CROWNJEWEL` waives nothing and looks like it waives
    something. Fingerprints that are not requirement ids (paths, artifact trees) are
    untouched — only strings shaped like a registry id are held to the registry."""
    waivers = (GOOD_WAIVER
               + "WAIVED: PROC-EXAMPLE-TYPO — id that is not in the registry (2026-08-11)\n"
               + "WAIVED: conformance/demos/phase-1+unread — not an id at all (2026-08-11)\n")
    root = write_repo(tmp_path, reqs=[_gate_req(gate=None)], waivers=waivers,
                      makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW})
    result = run_check(root)
    assert result.returncode == 1
    assert "PROC-EXAMPLE-TYPO" in result.stdout, result.stdout
    assert "phase-1+unread" not in result.stdout, (
        "a non-id fingerprint was held to the registry — path- and artifact-shaped "
        f"fingerprints are legitimate:\n{result.stdout}")


def test_issue_d010_2_the_live_waivers_file_parses_completely():
    """Every `WAIVED:` line in this repo's WAIVERS.md is in force, or the file is red.

    This is the test that catches the divergence in the tree rather than in a fixture:
    `SCAN-M4-EXPOSURE-AUTH` parsed under check.py's un-anchored regex (matching a
    `(2026-08-11)` in the middle of its prose) and *not* under the parity test's
    anchored one, so the two files disagreed about whether it was waived at all.
    """
    waivers, problems = gates.parse_waivers(REPO)
    assert not problems, "WAIVERS.md has lines that waive nothing:\n  " + "\n  ".join(problems)
    declared = {line for line in (REPO / "WAIVERS.md").read_text().splitlines()
                if line.strip().startswith("WAIVED:")}
    assert len(waivers) == len(declared), (
        f"{len(declared)} WAIVED: lines, {len(waivers)} parsed — some line is being "
        f"dropped without a problem being reported")


# ── deferral: the run report must be bound to the working tree ──────────────

def test_issue_n_a_run_report_matching_head_but_not_the_tree_is_red(tmp_path):
    """Round 5 bound the report to `git rev-parse HEAD` and recorded the gap as open.

    HEAD does not change when you edit a file. So the window this leaves is exactly the
    dangerous one: run the suite, watch a requirement go red, edit the code, re-run the
    *gate* — which reads the working tree — and it grades the new tree against the old
    run. Nothing in the output says the tests never saw the change.
    """
    stale = {
        "schema_version": 1, "sha": head_sha(),
        "tree": "sha256:" + "0" * 64,
        "generated_at": "2026-08-11T00:00:00Z", "pytest_exitstatus": 0,
        "full_run": True, "narrowed_by": [], "outcomes": {},
    }
    root = write_repo(tmp_path / "stale", reqs=[_gate_req(gate=None)],
                      waivers=GOOD_WAIVER, report=stale, makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW})
    result = run_check(root)
    assert result.returncode == 1, (
        f"a run report describing a different working tree was accepted:\n{result.stdout}")
    assert "working tree" in result.stdout and "make test" in result.stdout, (
        f"the failure does not say what changed or how to fix it:\n{result.stdout}")


def test_issue_n_a_run_report_with_no_tree_binding_is_red(tmp_path):
    """An absent binding is not a claim that the tree is unchanged; it is no claim."""
    report = {
        "schema_version": 1, "sha": head_sha(),
        "generated_at": "2026-08-11T00:00:00Z", "pytest_exitstatus": 0,
        "full_run": True, "narrowed_by": [], "outcomes": {},
    }
    root = write_repo(tmp_path / "unbound", reqs=[_gate_req(gate=None)],
                      waivers=GOOD_WAIVER, report=report, makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW})
    result = run_check(root)
    assert result.returncode == 1 and "no 'tree'" in result.stdout, result.stdout


def test_issue_n_the_fingerprint_moves_when_a_tracked_file_changes(tmp_path):
    """The fingerprint has to actually depend on file content, not just on the path list.

    Without this, `tree_fingerprint` could hash `git status` alone and pass every test
    above while still failing to notice an edit to a file that was already dirty — which
    is the normal state of a working tree mid-change.
    """
    root = tmp_path / "repo"
    root.mkdir()

    def run(*args):
        return subprocess.run(["git", "-C", str(root), *args], check=True,
                              capture_output=True, text=True)

    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@example.com")
    run("config", "user.name", "t")
    (root / "a.py").write_text("x = 1\n")
    run("add", "-A")
    run("commit", "-qm", "first")

    clean = gates.tree_fingerprint(root)
    assert clean, "a clean checkout must still produce a fingerprint"
    assert gates.tree_fingerprint(root) == clean, "the fingerprint is not stable"

    (root / "a.py").write_text("x = 2\n")
    dirty = gates.tree_fingerprint(root)
    assert dirty != clean, "editing a tracked file did not move the fingerprint"

    (root / "a.py").write_text("x = 3\n")
    assert gates.tree_fingerprint(root) != dirty, (
        "a second edit to an already-dirty file did not move the fingerprint — the "
        "fingerprint is reading the path list, not the content")

    (root / "b.py").write_text("y = 1\n")
    assert gates.tree_fingerprint(root) not in {clean, dirty}, (
        "a new untracked file did not move the fingerprint")

    (root / "a.py").write_text("x = 1\n")
    (root / "b.py").unlink()
    assert gates.tree_fingerprint(root) == clean, (
        "restoring the tree did not restore the fingerprint")


# ── deferral: text_hash must pin every section the source cites ─────────────

TWO_SECTION_DOC = """\
# Fixture plan

## A1 First section

The first section's body, which one requirement cites.

## D7 Second section

The second section's body, which the same requirement also cites — and which the
round-5 implementation never hashed.

## Z9 Unrelated

Nothing cites this.
"""


def _pin(root, req_id):
    """The hash check.py recomputes for `req_id` on this tree."""
    result = run_check(root, extra=("--print-text-hashes",))
    assert result.returncode == 0, result.stdout + result.stderr
    for line in result.stdout.splitlines():
        if line.startswith(f"{req_id}:"):
            m = re.search(r"(sha256:[0-9a-f]{64})", line)
            return m.group(1) if m else None
    raise AssertionError(f"{req_id} not in --print-text-hashes output:\n{result.stdout}")


def _two_section_repo(tmp_path, name, doc=TWO_SECTION_DOC, pinned=None):
    req = {"id": "P0-TWO-SECTION", "phase": 1, "verify": "checklist",
           "source": "fixture-plan.md §A1/§D7", "gate": "lint",
           "text": "A requirement whose source cites two sections."}
    if pinned:
        req["text_hash"] = pinned
    return write_repo(tmp_path / name, reqs=[req], makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW},
                      files={"docs/plan/fixture-plan.md": doc})


def test_issue_n_text_hash_covers_every_section_the_source_cites(tmp_path):
    """`§A1/§D7` means both sections. Round 5 hashed §A1 and called it pinned.

    A requirement citing two sections is citing two sections *because both carry the
    obligation*: `P0-AUTHZ-TOPIC` is §A1 (every subscribe is authorised) plus §D7 (the
    topic vocabulary it is authorised against). Editing §D7 silently changed what the
    requirement means while its pin stayed green — and the pin exists precisely so that
    editing the text re-opens the tests that claim to prove it.
    """
    root = _two_section_repo(tmp_path, "pinned")
    pinned = _pin(root, "P0-TWO-SECTION")
    assert pinned, "no hash was recomputed for a two-section source"

    green = _two_section_repo(tmp_path, "green", pinned=pinned)
    assert run_check(green).returncode == 0, run_check(green).stdout

    edited = TWO_SECTION_DOC.replace(
        "The second section's body", "The second section's REWRITTEN body")
    red = _two_section_repo(tmp_path, "red", doc=edited, pinned=pinned)
    result = run_check(red)
    assert result.returncode == 1, (
        "editing the second cited section left the pin green — only §A1 is hashed:\n"
        + result.stdout)
    assert "text_hash stale" in result.stdout

    # An edit to a section the requirement does not cite must NOT re-open it, or the
    # pin becomes a whole-document hash and every plan edit re-opens every test.
    unrelated = TWO_SECTION_DOC.replace("Nothing cites this.", "Still nothing cites this.")
    quiet = _two_section_repo(tmp_path, "quiet", doc=unrelated, pinned=pinned)
    assert run_check(quiet).returncode == 0, run_check(quiet).stdout


def test_issue_n_a_single_section_pin_is_byte_compatible(tmp_path):
    """Single-citation hashes must not change, or all 74 live pins re-pin at once and
    the diff stops being reviewable — every changed hash would have to be checked by
    hand against a doc that did not change."""
    req = {"id": "P0-ONE-SECTION", "phase": 1, "verify": "checklist",
           "source": "fixture-plan.md §A1", "gate": "lint",
           "text": "A requirement whose source cites one section."}
    root = write_repo(tmp_path, reqs=[req], makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW},
                      files={"docs/plan/fixture-plan.md": TWO_SECTION_DOC})
    body = "\n".join([
        "## A1 First section",
        "",
        "The first section's body, which one requirement cites.",
    ])
    expected = "sha256:" + hashlib.sha256(body.encode()).hexdigest()
    assert _pin(root, "P0-ONE-SECTION") == expected, (
        "the single-section hash is no longer sha256 of the section body alone")


def test_issue_n_an_unresolvable_citation_is_named_not_swallowed(tmp_path):
    """A source citing two sections of which one cannot be resolved is *partially*
    pinned, and the warning has to say which part is unwatched."""
    req = {"id": "P0-HALF-PINNED", "phase": 1, "verify": "checklist",
           "source": "fixture-plan.md §A1 / §NOSUCH", "gate": "lint",
           "text": "A requirement citing one real section and one that is not there."}
    root = write_repo(tmp_path, reqs=[req], makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW},
                      files={"docs/plan/fixture-plan.md": TWO_SECTION_DOC})
    pinned = _pin(root, "P0-HALF-PINNED")
    req["text_hash"] = pinned
    root2 = write_repo(tmp_path / "pinned", reqs=[req], makefile=GATED_MAKEFILE,
                       workflows={"push-checks.yml": HONEST_WORKFLOW},
                       files={"docs/plan/fixture-plan.md": TWO_SECTION_DOC})
    result = run_check(root2)
    assert result.returncode == 0, result.stdout
    assert "NOSUCH" in result.stdout, (
        f"the unresolved citation was hashed over in silence:\n{result.stdout}")
    entry = matrix(root2)["requirements"]["P0-HALF-PINNED"]
    assert entry.get("text_hash_unresolved"), (
        f"matrix.json does not record which citations are unpinned: {json.dumps(entry)}")
