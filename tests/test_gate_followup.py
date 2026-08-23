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
import functools
import hashlib
import json
import os
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


def _gates_names(path):
    """Every local name that refers to conformance/gates.py in this module.

    `import gates`, `import gates as g`, `from gates import parse_waivers` — all three
    are delegation, and a check that only knows the literal `gates` calls the second one
    a re-implementation (round-6 F3 residual).
    """
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    modules, members = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(a.asname or a.name for a in node.names if a.name == "gates")
        elif isinstance(node, ast.ImportFrom) and node.module == "gates":
            members.update(a.asname or a.name for a in node.names)
    return modules, members


def _reaches_gates(node, modules, members):
    """True if this definition ever touches the `gates` module.

    Round-6 F3: this used to be `"gates." in source`, which a docstring or an
    attribution comment satisfied — so "unlike conformance/gates.py, mine is lenient"
    counted as delegation. Only a real reference counts now.
    """
    for child in ast.walk(node):
        if (isinstance(child, ast.Attribute) and isinstance(child.value, ast.Name)
                and child.value.id in modules):
            return True
        if isinstance(child, ast.Name) and child.id in members:
            return True
    return False


def _definitions(path):
    """{name: node} for every assignment and function def, at any nesting depth.

    Round-6 F3 again: walking only `tree.body` meant a copy tucked inside a class or a
    helper function was invisible. `ast.walk` sees all of them.
    """
    tree = ast.parse(pathlib.Path(path).read_text(encoding="utf-8"))
    out = {}

    def bind(target, node):
        # Round-6 F3 residual: plain `x = ...` was the only binding form recognised, so
        # an annotated assignment or a tuple unpack hid a copy in plain sight.
        if isinstance(target, ast.Name):
            out.setdefault(target.id, node)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                bind(element, node)

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.setdefault(node.name, node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                bind(target, node)
        elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
            bind(node.target, node)
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
    modules, members = _gates_names(path)
    return sorted(name for name, node in _definitions(path).items()
                  if name in GATES_OWNED and not _reaches_gates(node, modules, members))


def _consumers():
    """Every module that reads the gate machinery — not a hard-coded pair.

    Round-6 F3: scanning only check.py and test_gate_parity.py meant a third file could
    hold the next copy. Anything under conformance/ or tests/ that imports `gates` is a
    consumer and is held to the same rule.
    """
    # Round-6 F3 residual: `rglob("tests/*.py")` missed `tests/acceptance/`, and a flat
    # `conformance/*.py` would miss a future subdirectory. And a module holding a second
    # implementation is exactly the one that would *not* import gates, so the scan is no
    # longer limited to importers — every module under these two trees is held to the
    # rule, which is the honest scope for "nobody re-derives this".
    candidates = sorted((REPO / "conformance").rglob("*.py")) + sorted(
        (REPO / "tests").rglob("*.py"))
    return [p for p in candidates if p.name != "gates.py"]


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
    consumers = _consumers()
    assert set(consumers) >= {CHECK_PY, PARITY_PY}, (
        f"the two files N1 names are no longer detected as consumers: {consumers}")
    for path in consumers:
        rel = path.relative_to(REPO)
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

    # Round-6 F3, the three evasions the substring-and-top-level version accepted.
    disguised = tmp_path / "disguised.py"
    disguised.write_text(
        "import gates\n\n\n"
        "def parse_waivers(root):\n"
        '    """Unlike gates.parse_waivers, this one is forgiving."""\n'
        "    return {}, []\n\n\n"
        "class Helper:\n"
        "    def bare_make_target(self, command):\n"
        "        return command.split()[-1]\n\n\n"
        "def _outer():\n"
        "    def tree_fingerprint(root):\n"
        "        return ''\n"
        "    return tree_fingerprint\n",
        encoding="utf-8")
    assert _reimplemented(disguised) == [
        "bare_make_target", "parse_waivers", "tree_fingerprint"], (
        "a re-implementation escaped by mentioning `gates.` in a docstring, or by "
        "hiding inside a class or a function body: " + str(_reimplemented(disguised)))

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


# ── round-6 verifier findings ───────────────────────────────────────────────

@pytest.mark.parametrize("flag", ["-n", "--dry-run", "-i", "--ignore-errors",
                                  "-q", "--question", "-t", "--touch", "-o"])
def test_issue_f1_a_make_flag_that_skips_the_recipe_is_not_an_honest_invocation(
        tmp_path, flag):
    """`run: make --dry-run lint` reaches the gate and does not run it (round-6 F1).

    Round 5 wrote `(?:\\s+-[A-Za-z-]+)*` for "make's own flags" and stopped there, so
    every flag that suppresses or fakes the recipe — `-n` prints it and exits 0, `-i`
    ignores its errors, `-q` returns an exit status without running anything, `-t`
    touches the targets instead — read as a bare, honest `make <target>` call to both
    consumers. That is the same false green as `continue-on-error: true`, arriving
    through the exact syntax the parity test was built to bless.
    """
    assert gates.bare_make_target(f"make {flag} lint") is None, (
        f"`make {flag} lint` is treated as an honest gate invocation")
    assert flag in gates.rejected_make_flags(f"make {flag} lint")

    workflow = (
        "name: push-checks\non: [push, pull_request]\njobs:\n  gates:\n"
        "    runs-on: ubuntu-latest\n    steps:\n"
        f"      - name: lint gate\n        run: make {flag} lint\n"
        "      - name: unit tests\n        run: make test\n"
        "      - name: conformance gate\n        run: make conformance\n"
    )
    root = write_repo(tmp_path, reqs=[_gate_req()], makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": workflow})
    result = run_check(root)
    assert result.returncode == 1, (
        f"check.py resolved `gate: lint` on a `make {flag}` step:\n{result.stdout}")
    assert flag in result.stdout, (
        f"the failure does not name the flag that disqualified it:\n{result.stdout}")


def test_issue_f1_the_flags_ci_legitimately_needs_still_pass():
    """The allow-list has to leave CI's real invocations alone, or it is just a ban."""
    for flag in ("-s", "--silent", "--quiet", "--no-print-directory"):
        assert gates.bare_make_target(f"make {flag} lint") == "lint", flag
    assert gates.bare_make_target("make lint") == "lint"
    assert gates.bare_make_target("make -s --no-print-directory lint") == "lint"


def test_issue_f2_a_retired_requirement_that_keeps_its_pin_does_not_crash_the_gate(tmp_path):
    """`status: retired` + `text_hash:` is a legal registry state and used to be fatal.

    Round-6 F2: `resolved` was bound only on the non-retired path while the pinned block
    ran unconditionally, so the first such requirement raised `UnboundLocalError`, a
    later one raised `KeyError`, and in between the retired req's pin was compared
    against the *previous* requirement's sections. There are no retired reqs today,
    which is exactly why nothing caught it.
    """
    retired = {"id": "P0-RETIRED-PIN", "phase": 0, "verify": "checklist",
               "source": "build-process.md §4", "status": "retired",
               "retired_reason": "superseded by PROC-EXAMPLE-GATE",
               "text_hash": "sha256:" + "0" * 64,
               "text": "A retired requirement that kept its metadata."}
    for order in ([retired, _gate_req()], [_gate_req(), retired]):
        root = write_repo(tmp_path / f"o{order.index(retired)}", reqs=order,
                          makefile=GATED_MAKEFILE,
                          workflows={"push-checks.yml": HONEST_WORKFLOW})
        result = run_check(root)
        assert "Traceback" not in result.stderr, (
            f"the gate crashed on a retired requirement carrying a pin:\n{result.stderr}")
        assert result.returncode == 0, f"{result.stdout}{result.stderr}"
        assert status_of(root, "P0-RETIRED-PIN") == "retired"


def test_issue_f5_a_broken_step_only_disqualifies_its_own_job(tmp_path):
    """Steps were tracked by name alone, so same-named steps in different jobs collided.

    Round-6 F5. Fail-safe (an honest invocation was discarded, never the reverse), but a
    gate that reads uninvoked because an unrelated job has a step of the same name sends
    the author looking in the wrong place — and unnamed steps collide by construction,
    since every job's first step is `step #1`.
    """
    workflow = """\
name: push-checks
on: [push, pull_request]
jobs:
  broken:
    runs-on: ubuntu-latest
    steps:
      - name: build
        continue-on-error: true
        run: make lint
  honest:
    runs-on: ubuntu-latest
    steps:
      - name: build
        run: make lint
      - name: unit tests
        run: make test
      - name: conformance gate
        run: make conformance
"""
    root = write_repo(tmp_path, reqs=[_gate_req()], makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": workflow})
    invoked, _rejected = gates.ci_gate_invocations(root)
    assert "lint" in invoked, (
        "the honest `build` step in job 'honest' was suppressed by the broken `build` "
        f"step in job 'broken': invoked={invoked}")
    assert any("'honest'" in where for where in invoked["lint"]), invoked["lint"]

    # The neutered step is still a violation — this widens nothing.
    violations = gates.gate_step_violations(
        root / ".github/workflows/push-checks.yml", gates.review_round_prerequisites(root))
    assert any("broken" in v and "continue-on-error" in v for v in violations), violations


def test_issue_f6_the_exemption_may_not_cover_every_gate(tmp_path):
    """An exemption that can cover everything is not an exemption (round-6 F6).

    Declaring every `review-round` prerequisite PR-only was accepted with no diagnostic,
    at which point a direct push to the default branch runs no gate at all.
    """
    makefile = GATED_MAKEFILE.replace(
        ".PHONY:", "PR_ONLY_GATES := lint test conformance\n.PHONY:")
    root = write_repo(tmp_path, reqs=[_gate_req()], makefile=makefile,
                      workflows={"push-checks.yml": HONEST_WORKFLOW})
    problems = gates.pr_only_declaration_problems(root)
    assert any("run no gate at all" in p for p in problems), problems
    assert run_check(root).returncode == 1

    # One gate left unconditional is enough to keep the declaration honest.
    partial = GATED_MAKEFILE.replace(
        ".PHONY:", "PR_ONLY_GATES := lint test\n.PHONY:")
    ok = write_repo(tmp_path / "partial", reqs=[_gate_req()], makefile=partial,
                    workflows={"push-checks.yml": HONEST_WORKFLOW})
    assert gates.pr_only_declaration_problems(ok) == []


def test_issue_f6_an_exported_declaration_is_not_silently_empty():
    """`export PR_ONLY_GATES := sp` used to parse as an empty declaration, un-declaring
    an exemption its author believed they had written."""
    assert gates.pr_only_gates(text="export PR_ONLY_GATES := sp\n") == {"sp"}
    assert gates.pr_only_gates(text="export  PR_ONLY_GATES\t:= sp other\n") == {"sp", "other"}


def test_issue_f7_a_gate_only_a_human_can_trigger_is_not_run_by_ci(tmp_path):
    """An honest `make lint` in a `workflow_dispatch`-only file resolved the gate.

    Round-6 F7: trigger awareness arrived with N3 but was consulted only on the
    exemption path. A workflow nothing automatic ever fires does not guard the branch,
    however honest its steps.
    """
    manual = HONEST_WORKFLOW.replace("on: [push, pull_request]", "on: workflow_dispatch")
    root = write_repo(tmp_path, reqs=[_gate_req()], makefile=GATED_MAKEFILE,
                      workflows={"manual.yml": manual})
    invoked, _ = gates.ci_gate_invocations(root)
    assert "lint" not in invoked, f"a manual-only workflow resolved the gate: {invoked}"
    result = run_check(root)
    assert result.returncode == 1 and "does not run it" in result.stdout, result.stdout

    # `schedule` alone is the same story; `push` or `pull_request` is what counts.
    for trigger, resolves in (("schedule:\n  - cron: '0 0 * * *'", False),
                              ("[push]", True),
                              ("[pull_request]", True)):
        wf = HONEST_WORKFLOW.replace("on: [push, pull_request]", f"on: {trigger}")
        tree = write_repo(tmp_path / trigger[:6].strip("[:"), reqs=[_gate_req()],
                          makefile=GATED_MAKEFILE, workflows={"w.yml": wf})
        assert ("lint" in gates.ci_gate_invocations(tree)[0]) is resolves, trigger


def test_issue_f8_a_duplicate_waiver_line_is_reported(tmp_path):
    """Two lines for one fingerprint collapsed to whichever came last, so a superseded
    reason could sit in the file reading as current (round-6 F8)."""
    waivers = (GOOD_WAIVER
               + "WAIVED: PROC-EXAMPLE-GATE — a second, different reason (2026-08-12)\n")
    _, problems = gates.parse_waivers(text=waivers)
    assert any("duplicate waiver" in p and "WAIVERS.md:2" in p for p in problems), problems
    root = write_repo(tmp_path, reqs=[_gate_req(gate=None)], waivers=waivers,
                      makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW})
    assert run_check(root).returncode == 1


@pytest.mark.parametrize("fingerprint,needle", [
    ("PROC—EXAMPLE-GATE", "not spelled the way the registry spells"),   # em dash in id
    ("PROC–EXAMPLE-GATE", "not spelled the way the registry spells"),   # en dash
    ("proc-example-gate", "not spelled the way the registry spells"),   # lowercased
    ("PROC—EXAMPLE-TYPO", "not a requirement id"),                      # and not real
])
def test_issue_f4_a_near_miss_requirement_id_is_still_held_to_the_registry(
        tmp_path, fingerprint, needle):
    """`ID_RE` alone let the near-misses through silently (round-6 F4).

    An em dash inside the id is the very transcription slip the parser's own hint text
    anticipates for the *separator*; it produced a fingerprint that is not
    requirement-shaped, escaped the registry check, and waived nothing while reading to
    a human as a waiver in force.
    """
    waivers = f"WAIVED: {fingerprint} — a typo nobody would see (2026-08-11)\n"
    root = write_repo(tmp_path, reqs=[_gate_req(gate=None)], waivers=waivers,
                      makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW})
    result = run_check(root)
    assert result.returncode == 1, (
        f"a near-miss id waived nothing, in silence:\n{result.stdout}")
    assert fingerprint in result.stdout and needle in result.stdout, result.stdout

    # A genuinely non-requirement fingerprint is still none of the registry's business.
    ok = write_repo(
        tmp_path / "path-shaped", reqs=[_gate_req(gate=None)],
        waivers=(GOOD_WAIVER
                 + "WAIVED: conformance/demos/phase-1+unread — a tree (2026-08-11)\n"),
        makefile=GATED_MAKEFILE, workflows={"push-checks.yml": HONEST_WORKFLOW})
    assert run_check(ok).returncode == 0


@pytest.mark.parametrize("scope", ["workflow", "job", "step"])
@pytest.mark.parametrize("var", ["MAKEFLAGS", "GNUMAKEFLAGS"])
def test_issue_r7_make_flags_from_the_environment_neuter_a_gate(tmp_path, scope, var):
    """`env: MAKEFLAGS: -n` is the F1 false green through a channel argv never shows.

    Round-6 re-verification, finding N1: GNU make reads its flags from the environment
    as well as the command line, proven against the real tool — `MAKEFLAGS=-n make lint`
    on a failing recipe prints the recipe and exits 0; `MAKEFLAGS=i` runs it and swallows
    the failure. The F1 allow-list looks only at the command, so a workflow whose gate
    steps are all bare `make <target>` calls ran no gate at all and was green to both
    consumers.
    """
    env_block = f"env:\n  {var}: -n\n"
    workflow = (
        "name: push-checks\non: [push, pull_request]\n"
        + (env_block if scope == "workflow" else "")
        + "jobs:\n  gates:\n    runs-on: ubuntu-latest\n"
        + (("    " + env_block.replace("\n  ", "\n      ").rstrip() + "\n")
           if scope == "job" else "")
        + "    steps:\n      - name: lint gate\n"
        + (("        " + env_block.replace("\n  ", "\n          ").rstrip() + "\n")
           if scope == "step" else "")
        + "        run: make lint\n"
        "      - name: unit tests\n        run: make test\n"
        "      - name: conformance gate\n        run: make conformance\n"
    )
    root = write_repo(tmp_path, reqs=[_gate_req()], makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": workflow})
    wf = root / ".github/workflows/push-checks.yml"
    violations = gates.gate_step_violations(wf, gates.review_round_prerequisites(root))
    assert any(var in v for v in violations), (
        f"`{var}` at {scope} scope was not treated as neutering the gate: {violations}")

    result = run_check(root)
    assert result.returncode == 1, (
        f"check.py resolved `gate: lint` with {var} set at {scope} scope:\n{result.stdout}")
    assert var in result.stdout, result.stdout


def test_issue_r7_an_unrelated_env_var_on_a_gate_step_is_fine(tmp_path):
    """Only make's own flag variables are banned — the rule is not "no env on gates"."""
    workflow = HONEST_WORKFLOW.replace(
        "      - name: lint gate\n",
        "      - name: lint gate\n        env:\n          CI: 'true'\n")
    root = write_repo(tmp_path, reqs=[_gate_req()], makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": workflow})
    assert gates.gate_step_violations(
        root / ".github/workflows/push-checks.yml",
        gates.review_round_prerequisites(root)) == []
    assert run_check(root).returncode == 0


def _make_with_env(env_overrides, target="py-roots", args=()):
    """Run the repo's real Makefile with a hostile environment, out of tree."""
    env = dict(os.environ)
    env.pop("MAKEFLAGS", None)
    env.pop("GNUMAKEFLAGS", None)
    env.update(env_overrides)
    return subprocess.run(["make", "-f", str(REPO / "Makefile"), *args, target],
                          cwd=REPO, capture_output=True, text=True, env=env, timeout=120)


@functools.lru_cache(maxsize=1)
def _honest_py_roots_stdout():
    """Fingerprint of a real `py-roots` run, used to probe whether a hostile input is a no-op."""
    result = _make_with_env({}, args=())
    assert result.returncode == 0, (
        "honest `make py-roots` must run for the capability probe:\n"
        f"{result.stdout}{result.stderr}")
    assert "refusing to run" not in result.stderr
    assert result.stdout.strip(), (
        "honest py-roots printed nothing — the probe has no fingerprint")
    return result.stdout


def _py_roots_recipe_ran(result):
    """True iff this make actually executed `py-roots` (the hostile input was a no-op).

    Match the honest package list exactly. A dry-run prints the recipe (`echo catalog
    …`) and would still contain those names as a substring; equality is the difference
    between "the recipe ran" and "the recipe was printed".
    """
    return result.returncode == 0 and result.stdout == _honest_py_roots_stdout()


# GNUMAKEFLAGS landed in 3.82; `--eval` in 4.0. On GNU Make 3.81 (stock macOS
# `/usr/bin/make`) both are unknown and the recipe still runs. That is not a hole in
# the guard: the input does not suppress or fake recipes here. Probe by whether
# `py-roots` still prints the package list — do not hardcode `sys.platform`.
R8_MAYBE_UNIMPLEMENTED = [
    ({"GNUMAKEFLAGS": "-n"}, ()),
    ({"GNUMAKEFLAGS": "SHELL=/bin/true"}, ()),
    ({"MAKEFLAGS": "--eval=x:=1"}, ()),
]


R8_NEUTERINGS = [
    ({"MAKEFLAGS": "-n"}, ()),            # dry run: prints the recipe, exits 0
    ({"MAKEFLAGS": "n"}, ()),             # the short-flag spelling make itself writes
    ({"MAKEFLAGS": "ni"}, ()),            # combined with another
    ({"MAKEFLAGS": "i"}, ()),             # ignore-errors: runs, swallows the failure
    ({"MAKEFLAGS": "q"}, ()),             # question mode: runs nothing
    ({"MAKEFLAGS": "t"}, ()),             # touch instead of running
    ({"MAKEFLAGS": "SHELL=/bin/true"}, ()),        # every recipe through `true`
    ({"MAKEFLAGS": ".SHELLFLAGS=-c true"}, ()),
    ({"MAKEFILES": "/tmp/injected.mk"}, ()),       # inject a whole makefile
    ({}, ("-n",)),                        # and the same flags straight from argv
    ({}, ("--dry-run",)),
    ({}, ("-i",)),
    ({}, ("-q",)),
    ({}, ("-t",)),
]


@pytest.mark.parametrize("env_overrides,args", R8_NEUTERINGS)
def test_issue_r8_make_refuses_to_start_when_its_own_inputs_suppress_recipes(
        env_overrides, args):
    """The gates defend themselves, because parsing workflows can never be enough.

    Three verification passes each closed one channel and surfaced the next: argv flags
    (round-6 F1), `env:` at step/job/workflow scope (N1), and then `echo MAKEFLAGS=-n >>
    $GITHUB_ENV` from an earlier step — which appears in no `env:` block anywhere, so no
    amount of workflow parsing can see it. Enumerating make's inputs is a losing game.
    This stops playing it: whatever route the flag took, make refuses to start, and a
    gate that refuses to start is red rather than falsely green.

    Inputs this make does not implement (GNUMAKEFLAGS before 3.82, `--eval` before 4.0)
    live in R8_MAYBE_UNIMPLEMENTED and are probed, not assumed: a no-op that still
    executes py-roots is not a suppressor here.
    """
    result = _make_with_env(env_overrides, args=args)
    assert result.returncode != 0, (
        f"make ran with {env_overrides or list(args)} — the recipe is suppressed or "
        f"faked and the gate would report success:\n{result.stdout}{result.stderr}")
    assert "refusing to run" in result.stderr, (
        f"make failed, but not with the guard's message, so this is some other error:\n"
        f"{result.stderr}")


@pytest.mark.parametrize(
    "env_overrides,args",
    R8_MAYBE_UNIMPLEMENTED,
    ids=["GNUMAKEFLAGS=-n", "GNUMAKEFLAGS=SHELL=/bin/true", "MAKEFLAGS=--eval"],
)
def test_issue_r8_a_hostile_input_this_make_does_not_honor_still_runs_the_recipe(
        env_overrides, args):
    """Demanding refuse for a flag this make does not implement is a false-red.

    GNUMAKEFLAGS is 3.82+; `--eval` is 4.0+. GNU Make 3.81 — stock macOS
    `/usr/bin/make` — treats both as unknown: `GNUMAKEFLAGS=-n make py-roots` still
    prints the package list and exits 0; so does `MAKEFLAGS=--eval=x:=1`. The guard
    looks at `$(MAKEFLAGS)` after make has absorbed its inputs, so there is nothing
    to refuse — the input never became a recipe suppressor.

    Probe that, do not hardcode `sys.platform == "darwin"` and do not weaken the
    guard for flags 3.81 *does* honor (`MAKEFLAGS=-n`/`n`/`i`/`q`/`t`, `SHELL=`,
    `MAKEFILES=`, argv). If this make still executes `py-roots`, the case must not
    sit on the always-refuse list: asserting "refusing to run" here is a false-red,
    not a hole. If a future make starts honoring the flag, the package list will
    stop appearing, this branch will fail, and the case must join the refuse list.
    """
    result = _make_with_env(env_overrides, args=args)
    if _py_roots_recipe_ran(result):
        assert (env_overrides, args) not in R8_NEUTERINGS, (
            f"this make still executes py-roots under {env_overrides or list(args)} "
            "— the input is not a recipe suppressor here. Leaving it on the always-"
            "refuse list is a false-red, not a hole. Split it out of R8_NEUTERINGS "
            "and assert the recipe ran instead.")
        assert "refusing to run" not in result.stderr
        return
    assert result.returncode != 0, (
        f"make ran with {env_overrides or list(args)} without printing py-roots "
        "— this make honors the input, so the guard must refuse:\n"
        f"{result.stdout}{result.stderr}")
    assert "refusing to run" in result.stderr, (
        f"make failed, but not with the guard's message, so this is some other error:\n"
        f"{result.stderr}")


def test_lint_turns_off_the_pip_audit_tty_spinner():
    """pip-audit's default TTY spinner has killed `make lint` in this wrapper.

    Empirically: the spinner path hangs ~400s and exits 2; `pip-audit --progress-spinner
    off` is clean. The gate stays advisory (`|| true`); this only pins the flag that
    keeps the recipe from dying before that `|| true` can run.
    """
    recipe = gates.recipe(REPO, "lint")
    assert "pip-audit --progress-spinner off -r requirements.txt" in recipe, (
        "make lint must disable pip-audit's TTY spinner; the default has killed "
        "the recipe in this wrapper:\n" + recipe)


@pytest.mark.parametrize("env_overrides,args", [
    ({"MAKEFLAGS": "-s"}, ()),
    ({"MAKEFLAGS": "--no-print-directory"}, ()),
    ({"MAKEFLAGS": ""}, ()),
    ({}, ("-s",)),
    ({}, ()),
])
def test_issue_r8_the_guard_leaves_honest_invocations_alone(env_overrides, args):
    """A guard that refuses everything is not a guard, it is an outage."""
    result = _make_with_env(env_overrides, args=args)
    assert result.returncode == 0, (
        f"an honest invocation with {env_overrides or list(args)} was refused:\n"
        f"{result.stdout}{result.stderr}")
    assert "refusing to run" not in result.stderr


def test_issue_n4_a_make_without_shellflags_is_not_accused_of_overriding_it(tmp_path):
    """GNU make 3.81 — stock macOS `/usr/bin/make` — has no `.SHELLFLAGS` at all.

    On that make, `$(origin .SHELLFLAGS)` is the string `undefined`, and the guard read
    it as an override: every honest invocation on the platform was refused with the
    accusation `[undefined]` (found live during the 2026-08-11 round-6 merge, as 7 test
    failures in whatever spawns `make` from PATH). A variable that does not exist
    cannot carry an override. Simulated here on modern make: `undefine .SHELLFLAGS`
    before including the real Makefile puts the origin in exactly the state 3.81
    reports natively, so this test fails on the unfixed guard without needing a 2006
    make on the box.
    """
    # The guard is evaluated while the Makefile is being read, so the undefine is what
    # it sees. The restoration afterward is simulation plumbing only: real 3.81 needs
    # none — its `-c` is hardcoded — but on modern make an actually-undefined
    # .SHELLFLAGS invokes `sh` without `-c` and the recipe itself breaks, which would
    # test the wrong thing.
    shim = tmp_path / "make381.mk"
    shim.write_text(
        "undefine .SHELLFLAGS\n"
        "include " + str(REPO / "Makefile") + "\n"
        ".SHELLFLAGS := -c\n",
        encoding="utf-8")
    env = dict(os.environ)
    env.pop("MAKEFLAGS", None)
    env.pop("GNUMAKEFLAGS", None)
    result = subprocess.run(
        ["make", "-f", str(shim), "py-roots"],
        cwd=REPO, capture_output=True, text=True, env=env, timeout=120)
    assert result.returncode == 0, (
        f"a make whose .SHELLFLAGS does not exist was refused — the guard is again "
        f"accusing GNU make 3.81 of an override it cannot express:\n"
        f"{result.stdout}{result.stderr}")
    assert "refusing to run" not in result.stderr


def test_issue_n4_residual_a_real_shellflags_override_is_still_refused():
    """Demoting `undefined` to clean must not have taken `command line` with it."""
    result = _make_with_env({}, args=(".SHELLFLAGS=-c true",))
    assert result.returncode != 0 and "refusing to run" in result.stderr, (
        f"a command-line .SHELLFLAGS override ran — the N4 fix widened the hole it sat "
        f"next to:\n{result.stdout}{result.stderr}")


def test_issue_n4_residual_an_undefined_shell_is_also_clean_not_an_offense(tmp_path):
    """The same reasoning covers `SHELL`, symmetrically, should a make ever lack it."""
    # Same simulation plumbing as the .SHELLFLAGS test: the guard reads the undefined
    # origin at include time; the restoration only lets the recipe execute afterward.
    shim = tmp_path / "noshell.mk"
    shim.write_text(
        "undefine SHELL\n"
        "include " + str(REPO / "Makefile") + "\n"
        "SHELL := /bin/sh\n",
        encoding="utf-8")
    env = dict(os.environ)
    env.pop("MAKEFLAGS", None)
    env.pop("GNUMAKEFLAGS", None)
    result = subprocess.run(
        ["make", "-f", str(shim), "py-roots"],
        cwd=REPO, capture_output=True, text=True, env=env, timeout=120)
    assert result.returncode == 0, (
        f"an undefined SHELL was treated as an override:\n{result.stdout}{result.stderr}")


def test_issue_r8_the_guard_cannot_be_quietly_deleted():
    """It is one `ifneq` in a file nobody reads twice; say out loud that it must be there.

    Without this, the guard is exactly the kind of check that disappears in a cleanup
    diff and takes three verification passes to notice.
    """
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    assert "_MF_BAD" in text and "refusing to run" in text, (
        "the Makefile's self-defence guard is gone — make will again accept a "
        "recipe-suppressing flag from MAKEFLAGS, GNUMAKEFLAGS, MAKEFILES or argv")
    assert text.index("_MF_BAD") < text.index("review-round:"), (
        "the guard must be evaluated before any target is defined")


@pytest.mark.parametrize("var", gates.MAKE_ENV_VARS)
def test_issue_r8_both_halves_of_the_defence_cover_the_same_variables(var):
    """gates.py bans these in `env:`; the Makefile must actually refuse them.

    Asserted by running make, not by grepping the Makefile for the variable's name —
    a name in a comment satisfies a substring check while enforcing nothing, and two
    checks of one rule drifting apart is the N1 defect this branch exists to close.

    GNUMAKEFLAGS is the exception that is not a drift: a make that does not read
    that variable cannot put `-n` into `$(MAKEFLAGS)`, so the guard has nothing to
    refuse. Probe py-roots the same way as R8_MAYBE_UNIMPLEMENTED.
    """
    hostile = {"MAKEFILES": "/tmp/injected-by-a-test.mk"} if var == "MAKEFILES" \
        else {var: "-n"}
    result = _make_with_env(hostile)
    # GNUMAKEFLAGS is 3.82+: on a make that does not read it, `-n` never reaches
    # `$(MAKEFLAGS)` and the recipe still runs. That is the same no-op the split
    # R8_MAYBE_UNIMPLEMENTED cases cover, not a drift between gates.py and the
    # Makefile. A make that starts honoring GNUMAKEFLAGS will stop printing
    # py-roots and must refuse here.
    if var == "GNUMAKEFLAGS" and _py_roots_recipe_ran(result):
        assert "refusing to run" not in result.stderr
        return
    assert result.returncode != 0 and "refusing to run" in result.stderr, (
        f"conformance/gates.py bans `env: {var}` in a workflow, but the Makefile runs "
        f"happily with it set — the two halves of this defence have drifted, and only "
        f"the half that cannot see $GITHUB_ENV is still enforcing:\n"
        f"{result.stdout}{result.stderr}")


def test_issue_f3_residual_delegation_survives_an_import_alias(tmp_path):
    """`import gates as g` is delegation, and a copy can hide in shapes `ast.Assign`
    does not cover or in a module that imports nothing at all."""
    aliased = tmp_path / "aliased.py"
    aliased.write_text(
        "import gates as g\n"
        "from gates import parse_waivers as _pw\n\n\n"
        "def gate_step_violations(workflow):\n"
        "    return g.gate_step_violations(workflow, {'lint'})\n\n\n"
        "def parse_waivers(root):\n"
        "    return _pw(root)\n", encoding="utf-8")
    assert _reimplemented(aliased) == [], (
        f"a delegating wrapper using an import alias was called a copy: "
        f"{_reimplemented(aliased)}")

    hidden = tmp_path / "hidden.py"
    hidden.write_text(
        "MAKE_CALL_RE: object = None\n"
        "SHELL_JOINERS, _other = ('&&',), None\n", encoding="utf-8")
    assert _reimplemented(hidden) == ["MAKE_CALL_RE", "SHELL_JOINERS"], (
        f"an annotated assignment or a tuple unpack hid a copy: {_reimplemented(hidden)}")


def test_issue_f5_residual_two_steps_of_one_name_in_one_job_are_distinguishable(tmp_path):
    """Within a single job the same fix has to hold as across jobs."""
    workflow = """\
name: push-checks
on: [push, pull_request]
jobs:
  gates:
    runs-on: ubuntu-latest
    steps:
      - name: build
        continue-on-error: true
        run: make lint
      - name: build
        run: make lint
      - name: unit tests
        run: make test
      - name: conformance gate
        run: make conformance
"""
    root = write_repo(tmp_path, reqs=[_gate_req()], makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": workflow})
    invoked, _ = gates.ci_gate_invocations(root)
    assert "lint" in invoked, (
        f"the honest second `build` step was suppressed by its broken namesake in the "
        f"same job: {invoked}")


def test_issue_f6_residual_every_makefile_assignment_form_declares():
    """`override`, `?=` and `+=` were as silent as `export` was."""
    assert gates.pr_only_gates(text="override PR_ONLY_GATES := sp\n") == {"sp"}
    assert gates.pr_only_gates(text="PR_ONLY_GATES ?= sp\n") == {"sp"}
    assert gates.pr_only_gates(text="PR_ONLY_GATES := a\nPR_ONLY_GATES += b\n") == {"a", "b"}
    assert gates.pr_only_gates(text="export override PR_ONLY_GATES ::= sp\n") == {"sp"}


def test_issue_f7_residual_a_skipped_workflow_says_why(tmp_path):
    """"No workflow step invokes make lint" is not an answer when one plainly does."""
    manual = HONEST_WORKFLOW.replace("on: [push, pull_request]", "on: workflow_dispatch")
    root = write_repo(tmp_path, reqs=[_gate_req()], makefile=GATED_MAKEFILE,
                      workflows={"manual.yml": manual})
    result = run_check(root)
    assert result.returncode == 1
    assert "manual.yml" in result.stdout and "workflow_dispatch" in result.stdout, (
        f"the failure does not name the workflow that was skipped or its triggers:\n"
        f"{result.stdout}")


@pytest.mark.parametrize("fingerprint", [
    "PROC‑EXAMPLE‑GATE",   # non-breaking hyphen
    "PROC−EXAMPLE-GATE",        # minus sign
    "PROC-EXAMPLE-GATE.",            # trailing sentence punctuation
])
def test_issue_f4_residual_other_lookalike_characters_are_caught(tmp_path, fingerprint):
    """Em and en dash were the two the first fix knew about; a copy-paste has more."""
    root = write_repo(tmp_path, reqs=[_gate_req(gate=None)],
                      waivers=f"WAIVED: {fingerprint} — a typo (2026-08-11)\n",
                      makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW})
    result = run_check(root)
    assert result.returncode == 1 and "not spelled the way" in result.stdout, result.stdout


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


def test_issue_f9_a_doc_alias_matches_a_whole_word_not_a_prefix(tmp_path):
    """`addendum` must not resolve `addendum-2026-08-02` (round-6 F9).

    A prefix match sends a citation to the wrong frozen copy, and if that copy happens
    to contain the anchor the requirement is pinned to text it does not cite. No live
    source has this shape; the point is that the next one cannot.
    """
    req = {"id": "P0-ALIAS-PREFIX", "phase": 1, "verify": "checklist",
           "source": "fixture-plan.md §A1 / addendum-2999-01-01 §D7", "gate": "lint",
           "text": "A requirement citing a doc whose name starts with an alias."}
    root = write_repo(tmp_path, reqs=[req], makefile=GATED_MAKEFILE,
                      workflows={"push-checks.yml": HONEST_WORKFLOW},
                      files={"docs/plan/fixture-plan.md": TWO_SECTION_DOC,
                             "docs/plan/plan-addendum-2026-07-30.md": TWO_SECTION_DOC})
    result = run_check(root)
    assert result.returncode == 0, result.stdout
    entry = matrix(root)["requirements"]["P0-ALIAS-PREFIX"]
    assert entry["text_hash_sections"] == ["docs/plan/fixture-plan.md §A1"], (
        "the alias `addendum` prefix-matched `addendum-2999-01-01` and pinned a section "
        f"of the wrong document: {entry['text_hash_sections']}")
    assert entry.get("text_hash_unresolved") == ["addendum-2999-01-01 §D7"]


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
