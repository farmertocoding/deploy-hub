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
import sys

import gates
import yaml

REPO = pathlib.Path(__file__).resolve().parent.parent
WORKFLOW_DIR = REPO / ".github/workflows"
WORKFLOWS = gates.workflow_paths(REPO)

# Tool invocations the Makefile owns (SPEC-gate-integrity.md §2.2). A workflow may name
# a make target; it may never name one of these.
OWNED_TOOLS = ("ruff ", "bandit ", "pip-audit ", "pytest ", "conformance/check.py")

# The §2.3 acceptance grep, run as a test instead of by hand. Deliberately broader than
# OWNED_TOOLS: it also catches a tool name hiding in a step `name:`, an `env:` value or
# a `with:` argument, none of which are `run:` strings.
ACCEPTANCE_RE = re.compile(r"(ruff|bandit|pip-audit|pytest|check\.py)")

# N1: the Makefile/workflow parsing this file used to carry — MAKE_CALL_RE, the bare-make
# matcher, the shell-joiner list, the `review-round` reader, `gate_step_violations` — now
# lives in conformance/gates.py, which conformance/check.py imports too. Round 5 left the
# two files holding separate implementations of "does CI invoke this gate", at different
# strictnesses, and they had already disagreed: a step with `continue-on-error: true` was
# neutered here and a working gate there. One rule, two declarations, is R4-8's own defect.
SHELL_JOINERS = gates.SHELL_JOINERS

# Every gate the Makefile owns must be reachable from CI (SPEC-gate-integrity.md §2.2),
# and the Makefile — not this file — says which those are.
REQUIRED_TARGETS = gates.review_round_prerequisites(REPO)
PR_ONLY = gates.pr_only_gates(REPO)


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
    """A workflow line may carry a gate tool name only as a comment or a bare make call."""
    text = line.strip()
    if text.startswith("#"):
        return True
    return gates.bare_make_target(_command(line)) is not None


def gate_step_violations(workflow, pr_only=None):
    """Ways a workflow step could invoke a required gate without obeying it (round-5 F2).

    Thin wrapper over `gates.gate_step_violations` so this file's tests keep reading the
    way they did; the rule itself is stated once, in conformance/gates.py, and check.py
    reads the same one (N1).
    """
    return gates.gate_step_violations(
        workflow, REQUIRED_TARGETS, PR_ONLY if pr_only is None else pr_only)


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
    for job_name, _job, step_name, step in gates.steps(workflow):
        yield job_name, step_name, step["run"]


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
    phony = gates.phony_targets(REPO)
    missing_targets = sorted(REQUIRED_TARGETS - phony)
    assert not missing_targets, (
        f"Makefile: .PHONY does not declare required gate target(s) {missing_targets} — "
        f"declared: {sorted(phony)}"
    )

    invoked = {}
    for workflow in WORKFLOWS:
        for job, step, run in _steps(workflow):
            for line in run.splitlines():
                for target in gates.MAKE_CALL_RE.findall(line):
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
        recipe = gates.recipe(REPO, target)
        assert recipe, f"Makefile: target '{target}' has no recipe"
        assert "$(PY_ROOTS)" in recipe, (
            f"Makefile: target '{target}' does not use $(PY_ROOTS); a hand-typed root "
            f"list is the defect R4-12 records. Recipe:\n{recipe}"
        )


# ── F1: a gate may not be claimed for a requirement it does not enforce ──────

def _registry():
    return yaml.safe_load((REPO / "conformance/requirements.yaml").read_text(encoding="utf-8"))


def _req(req_id):
    for entry in _registry()["requirements"]:
        if entry["id"] == req_id:
            return entry
    raise AssertionError(f"{req_id} is not in conformance/requirements.yaml")


def _waived_fingerprints():
    """`WAIVED: <fingerprint> — reason (YYYY-MM-DD)` lines, as check.py parses them.

    D-010 follow-up item 2: "as check.py parses them" used to be a claim rather than a
    fact — this file's regex was end-anchored and check.py's was not, so the two
    disagreed about SCAN-M4-EXPOSURE-AUTH, whose real tail was prose. One parser now,
    and a line that fails it is a reported problem instead of a silent absence.
    """
    waivers, problems = gates.parse_waivers(REPO)
    assert not problems, "WAIVERS.md has unparseable lines:\n  " + "\n  ".join(problems)
    return waivers


def test_issue_f1_secrets_in_exhaust_is_not_gated_by_log_scrub():
    """`make log-scrub` is a source scan; SEC-69-NO-SECRETS-IN-EXHAUST is exhaust.

    Round-5 finding F1: naming `gate: log-scrub` reported the requirement
    `verified` on a source grep for `SECRET_KEY\\s*=`. Phase 4 Task 8 converted
    the req to `verify: test` over captured pytest stdout/stderr/log and Celery
    kwargs. log-scrub stays as the source-scan it is; it is still not this
    requirement's gate.
    """
    req = _req("SEC-69-NO-SECRETS-IN-EXHAUST")
    assert req["verify"] == "test", (
        f"SEC-69-NO-SECRETS-IN-EXHAUST must be verify: test, got {req['verify']!r}"
    )
    assert "gate" not in req, (
        f"SEC-69-NO-SECRETS-IN-EXHAUST names gate: {req['gate']!r} — `make log-scrub` "
        "greps source files for an assignment literal, which is a different property. "
        "The exhaust gate is verify: test (captured output + Celery kwargs)."
    )

    waivers = _waived_fingerprints()
    assert "SEC-69-NO-SECRETS-IN-EXHAUST" not in waivers, (
        "SEC-69-NO-SECRETS-IN-EXHAUST is verified by test; the waiver must stay retired. "
        f"Waived today: {sorted(waivers)}"
    )

    # The source scan itself is useful and stays; it is simply not this req's gate.
    assert "log-scrub" in gates.phony_targets(REPO), (
        "make log-scrub was deleted along with the claim — it is a real source-scan gate "
        "and review-round runs it; only the requirement mapping was wrong"
    )


def test_issue_f9_phase_1_demo_artifacts_are_checked_or_recorded_as_unchecked():
    """Nothing reads conformance/demos/phase-1/ — say so out loud until something does.

    Round-5 F9. check.py only opens the paths a `demo:` key names (plus the
    `conformance/demos/phase-N.md` fallback), and the only `verify: demo` requirement is
    P0-WS-DEMO at phase 0. So the four phase-1 scan records are checked by nothing, which
    is why R4-10 did not surface when SPEC-gate-integrity.md §3.4 predicted the demo
    content check would surface it. This test retires itself: add a phase-1 demo
    requirement and it goes green on the first branch of the assertion instead.
    """
    tree = REPO / "conformance/demos/phase-1"
    if not tree.is_dir():
        return  # nothing to account for

    registry = _registry()["requirements"]
    watched = any(
        entry.get("verify") == "demo"
        and any("demos/phase-1" in str(path)
                for path in ([entry["demo"]] if isinstance(entry.get("demo"), str)
                             else entry.get("demo") or []))
        for entry in registry
    )
    if watched:
        return

    fingerprint = "conformance/demos/phase-1+unchecked-by-any-requirement"
    waivers = _waived_fingerprints()
    assert fingerprint in waivers, (
        f"{len(list(tree.iterdir()))} artifact(s) live under {tree.relative_to(REPO)} and no "
        f"requirement points at them: no registry entry is `verify: demo` at phase 1, so "
        f"check.py never opens that tree. Either add such a requirement or record the gap "
        f"as `WAIVED: {fingerprint} — ... (YYYY-MM-DD)`. Waived today: {sorted(waivers)}"
    )


# ── F2: invoking a gate is not the same as letting it decide the build ───────

NEUTERED_WORKFLOW = """\
name: neutered
on: [push]
jobs:
  lint-and-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: lint gate
        run: make lint && pytest -q --no-header || true
      - name: conformance gate
        continue-on-error: true
        run: make conformance
      - name: unit tests
        if: github.ref == 'refs/heads/main'
        run: make test
      - name: log scrub
        run: make log-scrub --keep-going
      - name: frontend contract tests
        run: |
          cd frontend
          make test-frontend
"""

HONEST_WORKFLOW = """\
name: honest
on: [push]
jobs:
  lint-and-unit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - run: pip install -r requirements-dev.txt
      - name: lint gate
        run: make lint
      - name: conformance gate
        run: make conformance
      - name: frontend deps
        run: cd frontend && npm ci
"""


def test_issue_f2_a_gate_step_cannot_be_neutered(tmp_path):
    """A step may *invoke* a gate; it may not chain, swallow or skip it.

    Round-5 finding F2, reproduced by the reviewer against the round-4 tests: adding
    `run: make lint && pytest -q --no-header || true` plus `continue-on-error: true` on
    the conformance step left all three parity tests green. `_is_allowed()` exempted any
    line beginning with `make `, and nothing looked at `continue-on-error:` or `if:`.

    So a gate step's `run:` must be exactly one `make <target>` command — no `&&`, `||`,
    `;`, `|`, no trailing arguments — and neither the step nor its job may carry
    `continue-on-error: true` or an `if:` expression. CI that reaches the gate and then
    ignores its verdict is CI that has no gate.
    """
    # The hole itself: the old allow-list said this line was fine because it starts with
    # `make `, so the `pytest ` in it never reached the re-declaration check.
    neutered_line = "        run: make lint && pytest -q --no-header || true"
    assert not _is_allowed(neutered_line), (
        f"a workflow line that chains a foreign tool onto a make call is treated as an "
        f"allowed make invocation: {neutered_line.strip()!r}. Only a bare `make <target>` "
        f"may carry a gate."
    )

    workflow = tmp_path / "neutered.yml"
    workflow.write_text(NEUTERED_WORKFLOW, encoding="utf-8")
    problems = gate_step_violations(workflow)
    blob = "\n".join(problems)

    expected = [
        ("lint gate", "&&"),               # chained with another command
        ("conformance gate", "continue-on-error"),  # verdict swallowed
        ("unit tests", "if"),              # gate made conditional
        ("log scrub", "--keep-going"),     # trailing argument changes what runs
        ("frontend contract tests", "cd frontend"),  # multi-command run block
    ]
    for step, token in expected:
        matching = [p for p in problems if step in p]
        assert matching, f"no violation reported for step {step!r}:\n{blob}"
        assert any(token in p for p in matching), (
            f"the violation for step {step!r} does not name the offending token "
            f"{token!r}:\n" + "\n".join(matching))
        assert any("neutered.yml" in p and "lint-and-unit" in p for p in matching), (
            f"the violation for step {step!r} must name the workflow and the job:\n"
            + "\n".join(matching))

    # The same two escapes one level up: a job may not be conditional or allowed to fail
    # either, or every gate step inside it is decorative.
    job_level = tmp_path / "job-level.yml"
    job_level.write_text("""\
name: job-level
on: [push]
jobs:
  soft-gates:
    runs-on: ubuntu-latest
    continue-on-error: true
    steps:
      - name: lint gate
        run: make lint
  conditional-gates:
    runs-on: ubuntu-latest
    if: github.event_name == 'pull_request'
    steps:
      - name: conformance gate
        run: make conformance
""", encoding="utf-8")
    job_problems = gate_step_violations(job_level)
    assert any("soft-gates" in p and "continue-on-error" in p for p in job_problems), (
        "a job-level `continue-on-error: true` swallowed its gate steps:\n"
        + "\n".join(job_problems))
    assert any("conditional-gates" in p and "if" in p for p in job_problems), (
        "a job-level `if:` made its gate steps conditional:\n" + "\n".join(job_problems))

    honest = tmp_path / "honest.yml"
    honest.write_text(HONEST_WORKFLOW, encoding="utf-8")
    assert gate_step_violations(honest) == [], (
        "a workflow whose gate steps are bare `make <target>` calls was rejected; "
        "non-gate steps (`cd frontend && npm ci`) are none of this check's business:\n"
        + "\n".join(gate_step_violations(honest)))


def test_issue_f2_the_real_workflows_run_their_gates_unconditionally():
    """The same check, against the tree it exists to protect."""
    problems = []
    for workflow in WORKFLOWS:
        problems.extend(gate_step_violations(workflow))
    assert not problems, (
        "workflow steps invoke a required gate but do not let it decide the build "
        "(round-5 F2):\n  " + "\n  ".join(problems))


# ── F8: `review-round` is the single declaration of what the gates are ──────

def test_issue_f8_the_required_gate_set_is_read_from_review_round():
    """A hand-typed list of gates is the R4-12 defect class; don't declare it a third time.

    Round-5 finding F8. The gates were declared in the Makefile (`review-round`'s
    prerequisites), in the workflows, and a third time as `REQUIRED_TARGETS` here — so
    adding a gate to `review-round` and to CI still left this test asserting the old set,
    and dropping one from `review-round` left it asserting a gate nobody runs. The
    required set is now parsed out of `review-round`, which makes that one line the
    single place the gate list is stated.
    """
    synthetic = (
        ".PHONY: lint new-gate test review-round\n"
        "review-round: lint new-gate test\n"
        "\t@echo mechanical gates green\n"
    )
    assert gates.review_round_prerequisites(text=synthetic) == {"lint", "new-gate", "test"}, (
        "a gate added to review-round must show up in the required set without anyone "
        "editing this test")

    # Line continuations are how the list will grow; they must not silently truncate it.
    wrapped = (
        "review-round: lint log-scrub test \\\n"
        "\ttest-frontend check-generated conformance\n"
        "\t@echo ok\n"
    )
    assert gates.review_round_prerequisites(text=wrapped) == {
        "lint", "log-scrub", "test", "test-frontend", "check-generated", "conformance",
    }, "a wrapped prerequisite list was truncated"

    live = gates.review_round_prerequisites(REPO)
    assert live == REQUIRED_TARGETS, (
        f"REQUIRED_TARGETS ({sorted(REQUIRED_TARGETS)}) is not the set review-round "
        f"declares ({sorted(live)}) — it is a fourth hand-typed copy")
    assert live, "Makefile: review-round declares no prerequisites; there are no gates left"


# ── F10: log-scrub needs a documented way out that is not "reword the product" ──

def _run_log_scrub(root):
    make = shutil.which("make")
    assert make, "make is not installed — the Makefile gates cannot run at all"
    return subprocess.run(
        [make, "-C", str(root), "-s", "log-scrub"],
        capture_output=True, text=True, timeout=60,
    )


def _scrub_tree(tmp_path, name, files):
    root = tmp_path / name
    root.mkdir(parents=True)
    shutil.copy(REPO / "Makefile", root / "Makefile")
    for rel, content in files.items():
        target = root / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
    return root


def test_issue_f10_log_scrub_has_a_documented_exemption_marker(tmp_path):
    """A source scan with no escape hatch gets paid for in product copy (round-5 F10).

    `log-scrub` greps every Python package root for `SECRET_KEY\\s*=` with one exemption,
    the substring `settings`. It has already cost once: widening the scope to $(PY_ROOTS)
    hit a `fix_hint` string in the scanner that quoted the assignment form as remediation
    advice, and the remedy was to reword the advice. The next docstring, error message or
    scanner rule that has to name the pattern faces the same choice — degrade what the
    user reads, or move the file out of scope. Give it a marker instead: an explicit,
    greppable, reviewable `# log-scrub: allow` on the line.
    """
    hit = _scrub_tree(tmp_path, "hit", {
        "pkg/__init__.py": "",
        "pkg/leak.py": 'SECRET_KEY = "django-insecure-hardcoded"\n',
    })
    res = _run_log_scrub(hit)
    assert res.returncode != 0, (
        f"log-scrub stopped catching a plain assignment — the gate itself is broken:\n"
        f"{res.stdout}{res.stderr}")

    allowed = _scrub_tree(tmp_path, "allowed", {
        "pkg/__init__.py": "",
        "pkg/advice.py": (
            "FIX_HINT = "
            '"Replace the literal with SECRET_KEY = os.environ[\'DJANGO_SECRET_KEY\']"'
            "  # log-scrub: allow — remediation copy, not a secret\n"
        ),
    })
    res2 = _run_log_scrub(allowed)
    assert res2.returncode == 0, (
        f"a line carrying the documented `# log-scrub: allow` marker still failed the "
        f"gate, so the only remedy left is degrading the string:\n{res2.stdout}{res2.stderr}")

    # The marker is line-scoped, and must stay that way: the grep is line-based, so a
    # marker anywhere else exempts nothing. Pinned so nobody "fixes" it into a
    # file-level or block-level exemption, which is how an escape hatch becomes a hole.
    elsewhere = _scrub_tree(tmp_path, "elsewhere", {
        "pkg/__init__.py": "",
        "pkg/advice.py": (
            "# log-scrub: allow — this file quotes the pattern deliberately\n"
            'SECRET_KEY = "django-insecure-hardcoded"\n'
        ),
    })
    res_elsewhere = _run_log_scrub(elsewhere)
    assert res_elsewhere.returncode != 0, (
        f"a marker on another line exempted the whole file — the exemption must sit on "
        f"the line it excuses:\n{res_elsewhere.stdout}")

    # The pre-existing exemption keeps working, and the marker did not widen it.
    settings = _scrub_tree(tmp_path, "settings", {
        "pkg/__init__.py": "",
        "pkg/settings/base.py": "SECRET_KEY = env('DJANGO_SECRET_KEY')\n",
    })
    assert _run_log_scrub(settings).returncode == 0

    both = _scrub_tree(tmp_path, "both", {
        "pkg/__init__.py": "",
        "pkg/advice.py": 'HINT = "SECRET_KEY = ..."  # log-scrub: allow\n',
        "pkg/leak.py": 'SECRET_KEY = "django-insecure-hardcoded"\n',
    })
    res3 = _run_log_scrub(both)
    assert res3.returncode != 0, (
        f"one exempted line silenced an unexempted one in the same tree:\n{res3.stdout}")


def test_issue_f10_the_log_scrub_exemptions_and_scope_are_documented_in_the_makefile():
    """An undocumented escape hatch is just a hole. Say where the gate does not look."""
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    comment = text.split("log-scrub:\n")[0].split("\n\n")[-1]
    for phrase in ("log-scrub: allow", "settings", "conformance/", "scripts_dev/", "tests/"):
        assert phrase in comment, (
            f"the Makefile comment above `log-scrub:` does not mention {phrase!r} — both "
            f"exemptions and everything outside $(PY_ROOTS) have to be written down where "
            f"the gate is. Comment block:\n{comment}")


def test_issue_r7_9_the_declaration_module_is_a_sensitive_path():
    """R7-9. `scanner/modules/**` is on the human-merge list because code there can
    weaken `core.secret-scan`. `scanner/declarations.py` holds the same authority and
    matched no glob on it: it decides which findings are eligible for the downgrade,
    and it derives the confirm id the acceptance gate opens for — change either and the
    gate opens for a question nobody was asked. Round 7 moved that id derivation into
    this module (R7-14), so the omission got worse in the same round that found it.

    Matched the way the guard matches, not by eye: a glob list is exactly the place a
    path is "obviously covered" by a pattern that does not cover it."""
    paths = yaml.safe_load(
        (REPO / "conformance" / "paths.yaml").read_text(encoding="utf-8"))
    patterns = paths["sensitive"]
    target = pathlib.PurePosixPath("scanner/declarations.py")
    assert any(target.full_match(p) if hasattr(target, "full_match")
               else target.match(p) for p in patterns), (
        f"scanner/declarations.py is matched by no sensitive-path glob in {patterns}")


# ── R15-ARCH-1: the presentation mirror, and the gate that keeps it current ───

def test_issue_r15_arch_1_the_generated_presentation_mirror_is_current():
    """`frontend/src/api/presentation.js` IS what the generator writes today.

    The presentation model is declared once, in `scanner/presentation.py`, because that
    is where `CheckResult` lives and where the CLI renderer reads it. The browser's copy
    is generated into `frontend/src/api/`, which `make check-generated` already rewrites
    and diffs — the mechanism the zod mirror has used since §4.5, so a stale copy is red
    in CI with no new gate and no new rule to remember. This is the same check, in the
    suite, so a stale mirror fails where a person is already looking.

    THROUGH A SUBPROCESS, not an import, and the reason is a real one rather than style:
    a test that imports the generator imports `scanner.presentation` with it, which puts
    this file in the mutation gate's DERIVED test selection — and then the mutation
    sandbox, which copies the Python packages and not `frontend/` or `scripts_dev/`,
    fails on a test that has nothing to do with any mutant. Found by running the gate:
    every mutant came back `not checked` because the selected tests could not import
    `generate_presentation`.
    """
    committed = (REPO / "frontend" / "src" / "api" / "presentation.js").read_text("utf-8")
    probe = ("import sys; sys.path.insert(0, 'scripts_dev'); "
             "import generate_presentation; "
             "sys.stdout.write(generate_presentation.render())")

    result = subprocess.run([sys.executable, "-c", probe], cwd=str(REPO),
                            capture_output=True, text=True, timeout=120)

    assert result.returncode == 0, result.stderr
    assert committed == result.stdout, (
        "the generated presentation mirror is stale — run `make generate-client`")


def test_issue_r15_arch_1_the_presentation_generator_refuses_arguments():
    """The `mutation_gate.py` / `sim_fixture_payloads.py` precedent: a generator that
    writes one whole file takes none, and an argument it silently ignored would be
    somebody believing they had scoped it. Exit 2 — declining to run, not a verdict."""
    result = subprocess.run(
        [sys.executable, "scripts_dev/generate_presentation.py", "--only-labels"],
        cwd=str(REPO), capture_output=True, text=True, timeout=120)

    assert result.returncode == 2, result.stdout
    assert "takes none" in result.stderr


def test_issue_r15_arch_1_the_makefile_generates_the_mirror_with_the_client():
    """…and the generation is wired to the target whose staleness gate covers that
    directory. A generator nothing runs is a mirror that is stale from the next edit."""
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("generate-client:")[1].split("\ncheck-generated:")[0]

    assert "scripts_dev/generate_presentation.py" in recipe
    assert "git diff --exit-code frontend/src/api/" in makefile
