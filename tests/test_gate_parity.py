"""R4-8 / R4-12: CI must *invoke* the gates, never re-declare them.

The defect these tests exist to prevent (round-4 finding, SPEC-gate-integrity.md §1):
the same gate was declared twice — once in the `Makefile`, once in a workflow — and the
review rounds only ever ran the `Makefile` copy. So the copy that actually guards `main`
drifted for three separate gates (conformance phase, bandit roots, log-scrubber roots)
and nobody noticed, because nobody ran it.

The fix is to delete the second declaration, and these tests are what keep it deleted:

  * the first test asserts no workflow line names a tool the `Makefile` owns;
  * the second asserts every gate target the `Makefile` owns is actually called from CI
    — the half that catches a gate being *dropped* rather than mis-scoped;
  * the third asserts the one remaining scope list (the Python package roots, shared by
    bandit and the log scrubber) is derived from the tree rather than hand-typed, which
    is the mechanism that let `wizard/` and `scanner/` go unscanned.
"""
import pathlib
import re
import shutil
import subprocess

import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO / ".github/workflows"
WORKFLOWS = sorted(WORKFLOW_DIR.glob("*.yml")) + sorted(WORKFLOW_DIR.glob("*.yaml"))

# Tool invocations the Makefile owns (SPEC-gate-integrity.md §2.2). A workflow may name
# a make target; it may never name one of these.
OWNED_TOOLS = ("ruff ", "bandit ", "pip-audit ", "pytest ", "conformance/check.py")

# The §2.3 acceptance grep, run as a test instead of by hand. Deliberately broader than
# OWNED_TOOLS: it also catches a tool name hiding in a step `name:`, an `env:` value or
# a `with:` argument, none of which are `run:` strings.
ACCEPTANCE_RE = re.compile(r"(ruff|bandit|pip-audit|pytest|check\.py)")

# Every gate the Makefile owns must be reachable from CI (SPEC-gate-integrity.md §2.2).
REQUIRED_TARGETS = {
    "lint", "test", "test-frontend", "conformance", "check-generated", "log-scrub",
}

MAKE_CALL_RE = re.compile(r"\bmake\s+(?:-[A-Za-z-]+\s+)*([A-Za-z0-9_.-]+)")


def _command(line):
    """The shell-command part of a workflow line, for lines that carry one.

    `      - run: make lint`  -> `make lint`
    `        run: make test`  -> `make test`
    `          make log-scrub` (inside a `run: |` block) -> `make log-scrub`
    """
    text = line.strip()
    if text.startswith("- "):
        text = text[2:].strip()
    match = re.match(r"^run:\s*(.*)$", text)
    if match:
        text = match.group(1).strip()
    return text


def _is_allowed(line):
    """A workflow line may carry a gate tool name only as a comment or a make call."""
    text = line.strip()
    if text.startswith("#"):
        return True
    return _command(line).startswith("make ")


def _annotate(text):
    """Yield (lineno, line, job, step) for every line of a workflow file.

    Indentation bookkeeping, not a YAML parser — the point is to be able to name the job
    and step in a failure message for lines `yaml.safe_load` throws away (step names,
    comments, `with:` values). Jobs are the two-space keys under `jobs:`; a step begins
    at the `- name:`/`- uses:`/`- run:` that opens the list item.
    """
    job, step, in_jobs = "<top level>", "<no step>", False
    for lineno, line in enumerate(text.splitlines(), 1):
        if line.rstrip() == "jobs:":
            in_jobs = True
        job_match = re.match(r"^  ([A-Za-z0-9_.-]+):\s*$", line)
        if in_jobs and job_match:
            job, step = job_match.group(1), "<no step>"
        step_match = re.match(r"^\s*-\s+(?:name|uses|run):\s*(.*)$", line)
        if step_match:
            step = step_match.group(1).strip() or "<unnamed step>"
        yield lineno, line, job, step


def _steps(workflow):
    """Yield (job_name, step_name, run_string) for every step with a `run:`."""
    document = yaml.safe_load(workflow.read_text(encoding="utf-8")) or {}
    for job_name, job in (document.get("jobs") or {}).items():
        for index, step in enumerate(job.get("steps") or [], 1):
            run = step.get("run")
            if not run:
                continue
            name = step.get("name") or step.get("uses") or f"step #{index}"
            yield job_name, name, run


def _phony_targets():
    """The `.PHONY:` target list from the Makefile (continuations included)."""
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    targets = set()
    for match in re.finditer(r"^\.PHONY:((?:[^\n]*\\\n)*[^\n]*)", text, re.M):
        targets.update(match.group(1).replace("\\", " ").split())
    return targets


def _recipe(target):
    """The recipe lines of one Makefile target, as a single string."""
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(target)}:[^\n]*\n((?:\t[^\n]*\n)+)", text, re.M)
    return match.group(1) if match else ""


def _package_roots():
    """Top-level importable packages, excluding the test suite itself.

    SPEC-gate-integrity.md §2.1 asks for this to live in `tests/roots.py::python_roots()`.
    That module does not exist on this tree (see the report accompanying this change), so
    the derivation is stated here and asserted against the Makefile's copy below. Move it
    to `tests/roots.py` when that module lands and import it from here.
    """
    return sorted(
        path.name for path in REPO.iterdir()
        if path.is_dir() and (path / "__init__.py").exists() and path.name != "tests"
    )


def test_issue_r4_8_ci_does_not_redeclare_gate_invocations():
    """No workflow may name a tool the Makefile owns — only the target that owns it."""
    redeclared = []
    for workflow in WORKFLOWS:
        for job, step, run in _steps(workflow):
            for line in run.splitlines():
                if _is_allowed(line):
                    continue
                for tool in OWNED_TOOLS:
                    if tool in line:
                        redeclared.append(
                            f"{workflow.name}: job '{job}': step '{step}': run: line "
                            f"{line.strip()!r} declares '{tool.strip()}' — the Makefile "
                            f"owns that tool; call its target instead"
                        )
    assert not redeclared, (
        "workflow steps re-declare gate invocations the Makefile owns "
        "(SPEC-gate-integrity.md §2.1):\n  " + "\n  ".join(redeclared)
    )

    # §2.3 acceptance, asserted rather than eyeballed: after the fix, the only lines in
    # any workflow matching the gate-tool grep are make invocations and comments.
    stragglers = []
    for workflow in WORKFLOWS:
        for lineno, line, job, step in _annotate(workflow.read_text(encoding="utf-8")):
            if _is_allowed(line):
                continue
            match = ACCEPTANCE_RE.search(line)
            if match:
                stragglers.append(
                    f"{workflow.name}:{lineno}: job '{job}': step '{step}': "
                    f"names '{match.group(1)}' outside a make invocation or comment "
                    f"({line.strip()!r})"
                )
    assert not stragglers, (
        "gate tool names still appear in workflow files outside a make invocation or a "
        "comment (SPEC-gate-integrity.md §2.3 acceptance):\n  " + "\n  ".join(stragglers)
    )


def test_issue_r4_8_every_makefile_gate_target_is_reachable_from_ci():
    """The other half: a gate the Makefile owns but CI never calls is a dropped gate."""
    phony = _phony_targets()
    missing_targets = sorted(REQUIRED_TARGETS - phony)
    assert not missing_targets, (
        f"Makefile: .PHONY does not declare required gate target(s) {missing_targets} — "
        f"declared: {sorted(phony)}"
    )

    invoked = {}
    for workflow in WORKFLOWS:
        for job, step, run in _steps(workflow):
            for line in run.splitlines():
                for target in MAKE_CALL_RE.findall(line):
                    invoked.setdefault(target, f"{workflow.name}: job '{job}': step '{step}'")
    missing_from_ci = sorted(REQUIRED_TARGETS - set(invoked))
    assert not missing_from_ci, (
        f"gate target(s) {missing_from_ci} are declared in the Makefile but never invoked "
        f"by any workflow in {WORKFLOW_DIR.relative_to(REPO)} — a gate CI does not run is "
        f"not a gate. Invoked today: "
        + ", ".join(f"{t} ({where})" for t, where in sorted(invoked.items()))
    )


def test_issue_r4_12_scan_scope_is_derived_from_the_package_roots():
    """bandit and the log scrubber must share one *derived* root list, not two typed ones.

    Hand-typed root lists are the mechanism of the R4-12 defect: `wizard/` landed and the
    bandit list in CI and the log-scrubber list in CI were each missed, separately.
    """
    expected = _package_roots()
    assert "wizard" in expected and "scanner" in expected, (
        f"derivation is broken: {expected} should contain the packages the round-4 "
        f"finding named as unscanned (wizard, scanner)"
    )

    make = shutil.which("make")
    assert make, "make is not installed — the Makefile gates cannot run at all"
    result = subprocess.run(
        [make, "-s", "py-roots"], cwd=REPO, capture_output=True, text=True, timeout=60,
    )
    assert result.returncode == 0, (
        f"Makefile: `make py-roots` failed ({result.returncode}); the scan scope must be "
        f"printable so it can be checked:\n{result.stdout}{result.stderr}"
    )
    assert result.stdout.split() == expected, (
        f"Makefile: PY_ROOTS is {result.stdout.split()} but the tree's Python packages "
        f"are {expected} — the scan scope has drifted from the code it must scan"
    )

    for target in ("lint", "log-scrub"):
        recipe = _recipe(target)
        assert recipe, f"Makefile: target '{target}' has no recipe"
        assert "$(PY_ROOTS)" in recipe, (
            f"Makefile: target '{target}' does not use $(PY_ROOTS); a hand-typed root "
            f"list is the defect R4-12 records. Recipe:\n{recipe}"
        )
