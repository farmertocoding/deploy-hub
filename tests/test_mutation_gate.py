"""The mutation gate's own tests (spec-mutation-gate.md §7).

A gate is code, and this repo's rule for gate code is that it is guarded like any other
(SPEC-gate-integrity.md). Three things are asserted here, and the numbering follows the
spec's:

  7.1 THE GATE CATCHES A HOLLOW ASSERTION. Not a test — a demonstration, run by hand in
      a throwaway state and recorded in the commit message, because it costs a full
      mutation run and the honest form of it is "apply a named mutation with its fix
      absent and watch `make mutation` go red". What lives here instead is the assertion
      that the gate's verdict is computed from mutmut's results at all, and that a
      surviving mutant is a non-zero exit.

  7.2 SCOPE CANNOT NARROW SILENTLY. The `[tool.mutmut]` scope is a superset of the three
      gate-bearing modules, and the derived test selection is still the derivation.
      §6's anti-gaming rule — "a round that improves by narrowing the mutated set is an
      automatic critical finding" — is a sentence in a document until something fails.

  7.3 SELF-DEFENSE. `mutation` is `.PHONY` and reached through `review-round`, which is
      what puts it behind the Makefile's `MAKEFLAGS` preamble; no new work, because that
      preamble refuses `-n`/`-i`/`-q`/`-t` and `SHELL=` before any recipe is read.

This module deliberately imports NO mutated module, so it does not join the gate's own
test selection: the tests that judge the gate must not be tests the gate runs under
mutation, or a mutant of `declarations.py` could turn the scope check green.
"""
import pathlib
import subprocess
import sys
import tomllib

import gates
import pytest

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "scripts_dev"))

import mutation_scope  # noqa: E402 — the path insert above is its prerequisite

# The gate-bearing set, spelled here as the FLOOR the config may not fall below. This is
# the one place these three names appear outside the config itself, and that is the
# point: a superset assertion needs both copies, and the review that changes the scope
# has to change this file too (spec §3, §7.2).
GATE_BEARING = {
    "wizard/materialize.py",
    "wizard/questions.py",
    "scanner/declarations.py",
}


def _mutmut_config():
    config = tomllib.loads((REPO / "pyproject.toml").read_text("utf-8"))
    return config["tool"]["mutmut"]


def test_the_mutated_scope_covers_every_gate_bearing_module():
    """Spec §7.2. Removing a module from `source_paths` makes this red.

    `scanner/declarations.py` is in the set WHILE PARKED, deliberately: its tests keep
    running so the module cannot rot, and a parked security module whose tests pass
    under mutation is exactly that rot. R8-5 and R8-12 both lived there.
    """
    configured = set(_mutmut_config()["source_paths"])

    assert GATE_BEARING <= configured, GATE_BEARING - configured
    for path in configured:
        assert (REPO / path).is_file(), f"{path} is configured but does not exist"


def test_the_mutated_scope_is_declared_in_exactly_one_place():
    """The N6 two-copies rule applied to the gate's own scope. Neither the Makefile
    recipe nor the CI step may name a mutated file: a second list is a list that drifts,
    and the one that drifts is always the one nobody runs."""
    recipe = gates.recipe(REPO, "mutation")
    workflow = (REPO / ".github/workflows/push-checks.yml").read_text("utf-8")

    for path in _mutmut_config()["source_paths"]:
        assert path not in recipe, f"the Makefile recipe names {path}"
        assert path not in workflow, f"the CI workflow names {path}"


def test_the_per_mutant_test_selection_is_the_derivation_not_a_typed_list():
    """Spec §3: "derive the file list with a small script rather than typing it".

    The list has to be static — mutmut reads it out of `pyproject.toml` — so what makes
    it derived is that it is asserted equal to the derivation. Add a test file that
    reaches a mutated module and this goes red until the config catches up, which is the
    property a hand-typed list does not have: R4-12 is what a hand-typed list costs.
    """
    derived = mutation_scope.test_files_touching()
    configured = _mutmut_config()["pytest_add_cli_args_test_selection"]

    assert sorted(configured) == sorted(derived), (
        f"configured but not derived: {sorted(set(configured) - set(derived))}; "
        f"derived but not configured: {sorted(set(derived) - set(configured))}")


def test_the_derivation_finds_at_least_the_two_named_test_files():
    """Spec §3's floor, asserted so a derivation that silently found nothing cannot
    present itself as a green gate that runs no tests."""
    derived = set(mutation_scope.test_files_touching())

    assert set(mutation_scope.REQUIRED_TEST_FILES) <= derived, derived


def test_the_sandbox_copy_covers_every_python_package_in_the_tree():
    """mutmut 3 runs the tests inside a `mutants/` COPY, so `also_copy` is what makes the
    selected tests importable there. It is not a scope list, but it fails the same way a
    scope list does — a package that lands next week and is not copied makes the gate
    error out — so it is checked against the same derivation the Makefile's $(PY_ROOTS)
    uses rather than against a second hand-typed list."""
    py_roots = {p.name for p in REPO.iterdir()
                if p.is_dir() and (p / "__init__.py").exists() and p.name != "tests"}
    also_copy = set(_mutmut_config()["also_copy"])

    assert py_roots <= also_copy, py_roots - also_copy


def test_the_sandbox_copy_includes_scripts_dev_exhaust_conftest_loads():
    """conftest execs scripts_dev/exhaust.py from disk (not a PY_ROOT). If also_copy
    omits scripts_dev, a cold mutants/ rebuild fails stats collection and every
    mutant stays not-checked.

    What would make this fail: listing only packages-with-__init__ so exhaust.py
    is absent from the sandbox after a cache discard.
    """
    also_copy = set(_mutmut_config()["also_copy"])
    conftest = (REPO / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert "scripts_dev" in conftest and "exhaust.py" in conftest
    assert "scripts_dev" in also_copy
    phase4 = (REPO / "tests" / "acceptance" / "test_phase_4.py").read_text(encoding="utf-8")
    assert "frontend" in phase4 and "Home.jsx" in phase4
    assert "frontend/src" in also_copy
    assert "frontend/tests" in also_copy
    assert "WAIVERS.md" in also_copy
    assert "docker-compose.yml" in also_copy
    assert "Makefile" in also_copy


def test_the_mutation_gate_is_phony_and_is_reached_through_review_round():
    """Spec §7.3. Being `.PHONY` and being a `review-round` prerequisite is what puts
    this gate behind the Makefile's self-defense preamble — the preamble refuses
    `-n`/`-i`/`-q`/`-t`, `MAKEFILES=` and a `SHELL` override while the makefile is being
    READ, so it protects every target including this one, and `-o`/`-W` cannot skip a
    phony target."""
    assert "mutation" in gates.phony_targets(REPO)
    assert "mutation" in gates.review_round_prerequisites(REPO)
    assert "mutation" not in gates.pr_only_gates(REPO), (
        "the mutation gate runs on a push; it may not claim the PR-only exemption")


def test_the_mutation_gate_runs_after_the_test_suite_and_before_conformance():
    """Spec §4's ordering, which is a correctness property rather than taste: a red suite
    makes every mutant "survive" meaninglessly, so mutmut needs a green baseline in front
    of it. Asserted on the recipe's prerequisite ORDER, which is the order make runs them
    in for a serial build."""
    line = [ln for ln in gates.makefile_text(REPO).splitlines()
            if ln.startswith("review-round:")][0]
    order = line.split(":", 1)[1].split()

    assert order.index("test") < order.index("mutation") < order.index("conformance")


def test_ci_runs_the_identical_bare_target():
    """R4-8 parity, spec §4. The workflow step is one bare `make mutation` — no scope, no
    flags, no `continue-on-error`, no `if:` — so the copy that guards the branch is the
    copy a round exercises. `gates.gate_step_violations` is the shared rule; this asserts
    it against the mutation target specifically so a failure names this gate."""
    workflow = REPO / ".github/workflows/push-checks.yml"
    invoked, rejected = gates.ci_gate_invocations(REPO)

    assert "mutation" in invoked, rejected
    assert "mutation" not in rejected, rejected["mutation"]
    assert gates.gate_step_violations(workflow, {"mutation"},
                                      pr_only=gates.pr_only_gates(REPO)) == []


def test_a_surviving_mutant_is_a_non_zero_exit(tmp_path, monkeypatch):
    """Spec §7.1's mechanical half: the gate's VERDICT, tested without a mutation run.

    `mutmut run` exits 0 whether or not anything survived, so the whole gate rests on
    `scripts_dev/mutation_gate.py` reading the per-mutant results and deciding. That
    decision is what is asserted here, over a faked result set — including that "no
    tests" fails, because a mutant nobody ran is not a mutant that passed, and a gate
    that scores it green stops covering a module the day its tests stop importing it.

    The full demonstration — a real named mutation applied to `wizard/materialize.py`
    with its fix absent, and `make mutation` going red on that mutant by name — is in
    this change's commit message, where a failing-first record belongs.
    """
    import mutation_gate

    def fake_results(results):
        return lambda: {name: (status, "wizard/materialize.py")
                        for name, status in results.items()}

    # A realistic CompletedProcess, because `mutation_gate.subprocess` IS the stdlib
    # module — patching its `run` also patches the `git check-ignore` call inside
    # `mutation_scope._git_ignored`, and a fake with no `stdout` would exercise that
    # function's error path by accident rather than on purpose.
    monkeypatch.setattr(mutation_gate.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="",
                                                                     stderr=""))
    # Pointed at a directory that does not exist, so this test cannot delete the real
    # `mutants/` cache out from under a run — which it did, once, and the symptom was a
    # different test failing three minutes later.
    monkeypatch.setattr(mutation_gate, "MUTANTS", tmp_path / "mutants")
    monkeypatch.setattr(mutation_gate, "FINGERPRINT", tmp_path / "mutants/.fingerprint")
    monkeypatch.setattr(mutation_gate, "_waived_mutants", lambda: (set(), []))

    monkeypatch.setattr(mutation_gate, "_results", fake_results({"m1": "killed"}))
    assert mutation_gate.main([]) == 0

    for bad in ("survived", "no tests", "suspicious", "segfault"):
        monkeypatch.setattr(mutation_gate, "_results",
                            fake_results({"m1": "killed", "m2": bad}))
        assert mutation_gate.main([]) == 1, bad

    # A timeout is the per-mutant clock doing its job, not a mutant the tests missed.
    monkeypatch.setattr(mutation_gate, "_results",
                        fake_results({"m1": "killed", "m2": "timeout"}))
    assert mutation_gate.main([]) == 0

    # And an empty result set is never green: it is what a run that never started looks
    # like, and it would otherwise be the cheapest way to switch this gate off.
    monkeypatch.setattr(mutation_gate, "_results", lambda: {})
    assert mutation_gate.main([]) == 1


@pytest.mark.req("PROC-SENSITIVE-HUMAN-MERGE")
def test_the_gate_files_are_on_the_human_merge_list():
    """build-process.md §4: the gate scripts are always human-merged. A mutation gate the
    loop could edit inside a round it is being judged by is not a gate (spec §6)."""
    paths = (REPO / "conformance/paths.yaml").read_text("utf-8")

    for path in ("scripts_dev/mutation_gate.py", "scripts_dev/mutation_scope.py"):
        assert path in paths, f"{path} is not on the sensitive-path list"


def test_a_waiver_only_silences_a_mutant_that_is_actually_surviving(tmp_path,
                                                                    monkeypatch):
    """Spec §4's escape hatch, and the two ways it must not become a baseline file.

    A `WAIVERS.md` line silences one mutant by id — that is the hatch. What keeps it a
    hatch is that a waiver whose mutant is KILLED, or which names a mutant that no longer
    exists, fails the gate: a spent waiver is a judgement nobody re-made, sitting in the
    file reading as current, which is the same rot `_read_entry` refuses in a stale
    declaration and the same rot round 6 found in a duplicated waiver line.
    """
    import mutation_gate

    # A realistic CompletedProcess, because `mutation_gate.subprocess` IS the stdlib
    # module — patching its `run` also patches the `git check-ignore` call inside
    # `mutation_scope._git_ignored`, and a fake with no `stdout` would exercise that
    # function's error path by accident rather than on purpose.
    monkeypatch.setattr(mutation_gate.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="",
                                                                     stderr=""))
    monkeypatch.setattr(mutation_gate, "MUTANTS", tmp_path / "mutants")
    monkeypatch.setattr(mutation_gate, "FINGERPRINT", tmp_path / "mutants/.fingerprint")
    monkeypatch.setattr(mutation_gate, "_waived_mutants",
                        lambda: ({"pkg.f__mutmut_1"}, []))

    def results(mapping):
        monkeypatch.setattr(mutation_gate, "_results",
                            lambda: {k: (v, "pkg/f.py") for k, v in mapping.items()})

    results({"pkg.f__mutmut_1": "survived"})
    assert mutation_gate.main([]) == 0

    results({"pkg.f__mutmut_1": "killed"})
    assert mutation_gate.main([]) == 1, "a spent waiver passed"

    results({"pkg.f__mutmut_2": "killed"})
    assert mutation_gate.main([]) == 1, "a waiver for a vanished mutant passed"


def test_every_mutation_waiver_names_a_mutant_id_the_gate_would_print():
    """The live `WAIVERS.md` lines, checked against the fingerprint the gate prints
    (`mutation+<file>+<mutant id>`) and against the configured scope. A waiver whose
    file is not in the mutated set silences nothing and reads as though it did."""
    waivers, problems = gates.parse_waivers(REPO)
    assert problems == [], problems

    scope = set(_mutmut_config()["source_paths"])
    mutation_waivers = [f for f in waivers if f.startswith("mutation+")]
    assert mutation_waivers, "the mutation gate's waivers vanished from WAIVERS.md"
    for fingerprint in mutation_waivers:
        _, path, mutant_id = fingerprint.split("+", 2)
        assert path in scope, f"{fingerprint} waives a file outside the mutated scope"
        module = path[:-len(".py")].replace("/", ".")
        assert mutant_id.startswith(f"{module}.x"), fingerprint
        assert "__mutmut_" in mutant_id, fingerprint


# ── F2: what the verdict cache watches ────────────────────────────────────────
#
# The review of the gate PR found the cache key was a THIRD hand-typed list — mutated
# sources, the selected test files, conftest — and that it missed every module a killing
# chain runs THROUGH without being mutated itself. Demonstrated with a comment appended
# to `wizard/service.py`: the run went warm from the cache while mutmut re-synced that
# same edit into `mutants/`, so the verdicts reported had been computed against a tree
# that no longer existed. The tests below are the fix's teeth.


def test_the_cache_watches_every_file_the_sandbox_can_read():
    """`sandbox_files()` is derived from mutmut's own sandbox construction — the union of
    `source_paths`, `also_copy` and mutmut's implicit copies — so "can this change a
    verdict?" and "is this in the sandbox?" are the same question.

    The four names F2 cited are asserted individually as well as through the derivation.
    A derivation that is right today and a finding that names four files are two
    different claims, and the second is the one that goes red if somebody narrows the
    first.
    """
    watched = set(mutation_scope.sandbox_files(REPO))

    for named in ("wizard/service.py", "wizard/views.py", "vault/service.py",
                  "sample-node-site/package.json"):
        assert named in watched, f"F2's own example {named} is outside the cache key"

    # Every Python file in every package, by the tree's own definition of a package.
    for root in mutation_scope.py_roots(REPO):
        for path in sorted((REPO / root).rglob("*.py")):
            rel = path.relative_to(REPO).as_posix()
            if "__pycache__" in rel:
                continue
            assert rel in watched, rel

    # The fixture repo the phase-1 acceptance tier scans off disk, which is not Python at
    # all — the reason the watch set is "files in the sandbox" rather than "modules".
    for path in sorted((REPO / "sample-node-site").rglob("*")):
        if path.name == ".DS_Store":
            continue
        if path.is_file():
            assert path.relative_to(REPO).as_posix() in watched, path

    # …and the things the first cut did get right, so the fix cannot lose them.
    for selected in _mutmut_config()["pytest_add_cli_args_test_selection"]:
        assert selected in watched, selected
    assert "tests/conftest.py" in watched
    assert "pyproject.toml" in watched

    # The dependency pins, which are NOT copied into the sandbox and are watched anyway:
    # a mutant's verdict is a property of the installed dependency set, and these two
    # files are what this repository says that set is.
    for pins in mutation_scope.DEPENDENCY_PINS:
        assert pins in watched, pins


def test_the_cache_never_watches_a_file_that_a_gate_rewrites():
    """The other direction, and it is not cosmetic: a watch set containing anything the
    run itself rewrites makes the fingerprint differ from itself, every round pays for a
    cold run, and a gate that always costs three minutes is a gate people find a way
    around.

    Two of these are inside the sandbox and were watched by the first cut of the F2 fix:
    `make test` writes `conformance/run-report.json` and `make conformance` writes
    `conformance/matrix.json`, and both run before `make mutation` in the `review-round`
    chain — so two consecutive runs with no edit between them both went cold. They are
    excluded through `.gitignore`, which is where the tree already says "generated
    artifact", rather than through two more typed names.
    """
    watched = mutation_scope.sandbox_files(REPO)

    for rel in watched:
        assert not (mutation_scope.NOT_AN_INPUT & set(rel.split("/"))), rel
        assert not rel.endswith((".pyc", ".pyo")), rel
    for generated in ("conformance/matrix.json", "conformance/run-report.json"):
        assert generated not in watched, generated

    assert mutation_scope.sandbox_files(REPO) == watched, "the watch set is not stable"


def test_running_the_gates_before_it_does_not_move_the_cache_key():
    """The property those exclusions exist for, asserted end to end rather than by
    name: run the two gates that precede `mutation` in `review-round` and the cache key
    must not have moved. This is what makes the warm path reachable in a real round —
    if it goes red, `make mutation` is a cold run every time and the reason will not be
    obvious from the timing alone.
    """
    import mutation_gate

    before = mutation_gate._fingerprint(REPO)
    subprocess.run([sys.executable, "-m", "pytest", "-q", "tests/test_smoke.py"],
                   cwd=REPO, capture_output=True, timeout=300)
    subprocess.run([sys.executable, "conformance/check.py", "--phase", "1"],
                   cwd=REPO, capture_output=True, timeout=300)

    assert mutation_gate._fingerprint(REPO) == before


def _fixture_repo(root):
    """A miniature tree with mutmut's config in it, shaped like this repo's sandbox."""
    (root / "pkg").mkdir(parents=True)
    (root / "pkg/__init__.py").write_text("", encoding="utf-8")
    (root / "pkg/mutated.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    # The F2 module: never mutated, but a killing chain runs through it.
    (root / "pkg/helper.py").write_text("def used_by_f():\n    return 2\n",
                                        encoding="utf-8")
    (root / "fixture-repo").mkdir()
    (root / "fixture-repo/package.json").write_text("{}\n", encoding="utf-8")
    (root / "tests").mkdir()
    (root / "tests/conftest.py").write_text("", encoding="utf-8")
    (root / "tests/test_pkg.py").write_text("def test_f():\n    assert True\n",
                                            encoding="utf-8")
    (root / "docs").mkdir()
    (root / "docs/notes.md").write_text("not an input to anything\n", encoding="utf-8")
    # No `.git` here on purpose: `_git_ignored` must fail toward watching everything, so
    # the fixture tests below exercise the degraded path as well as the happy one.
    (root / "pyproject.toml").write_text(
        '[tool.mutmut]\n'
        'source_paths = ["pkg/mutated.py"]\n'
        'pytest_add_cli_args_test_selection = ["tests/test_pkg.py"]\n'
        'also_copy = ["pkg", "fixture-repo"]\n',
        encoding="utf-8")
    return root


def test_editing_a_module_no_mutant_touches_discards_the_cache(tmp_path):
    """F2's regression test, stated at the cache key.

    `pkg/helper.py` is in the sandbox and is mutated by nothing — the shape of
    `wizard/service.py`, whose `downgraded_answers` and `scrub_downgraded_answers` are
    imported by `preflight` and `materialize` and are on the path of every mutant those
    two functions produce. Under the old key, appending a comment to it left the
    fingerprint unchanged, the run went warm, and mutmut copied the edit into the sandbox
    anyway: cached verdicts describing one tree, reported over another.
    """
    import mutation_gate

    root = _fixture_repo(tmp_path / "repo")
    before = mutation_gate._fingerprint(root)

    (root / "pkg/helper.py").write_text(
        "def used_by_f():\n    return 2\n# a comment, and nothing more\n",
        encoding="utf-8")

    assert mutation_gate._fingerprint(root) != before, (
        "a change to a non-mutated module in the sandbox left the cache key unmoved")


def test_editing_a_non_python_fixture_the_scan_reads_discards_the_cache(tmp_path):
    """The same finding's second half, and the reason the watch set is files rather than
    modules: `sample-node-site/` is a fixture REPO the phase-1 acceptance tier scans off
    disk, so its `package.json` decides what that scan reports and therefore which
    mutants it kills. No import graph would ever find it."""
    import mutation_gate

    root = _fixture_repo(tmp_path / "repo")
    before = mutation_gate._fingerprint(root)

    (root / "fixture-repo/package.json").write_text('{"name": "changed"}\n',
                                                    encoding="utf-8")

    assert mutation_gate._fingerprint(root) != before


def test_a_file_outside_the_sandbox_does_not_discard_the_cache(tmp_path):
    """Over-invalidation is the other failure, and it has to be excluded deliberately: a
    key that moves for every edit anywhere makes the warm path unreachable. `docs/` is
    not copied into `mutants/`, so nothing inside it can be read by a test there."""
    import mutation_gate

    root = _fixture_repo(tmp_path / "repo")
    before = mutation_gate._fingerprint(root)

    (root / "docs/notes.md").write_text("still not an input\n", encoding="utf-8")

    assert mutation_gate._fingerprint(root) == before


def test_the_gates_package_derivation_is_the_makefiles():
    """`mutation_scope.py_roots()` restates the Makefile's $(PY_ROOTS) predicate so a
    test can import it, and R4-12 is precisely what a second copy of a scan scope costs.
    So the two are asserted equal, the same way
    test_issue_r4_12_scan_scope_is_derived_from_the_package_roots asserts it for bandit
    and the log scrubber."""
    import shutil as _shutil

    make = _shutil.which("make")
    assert make, "make is not installed — the Makefile gates cannot run at all"
    result = subprocess.run([make, "-s", "py-roots"], cwd=REPO, capture_output=True,
                            text=True, timeout=60)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stdout.split() == mutation_scope.py_roots(REPO)
    assert {"wizard", "scanner", "vault"} <= set(mutation_scope.py_roots(REPO))


def test_the_ignore_lookup_fails_toward_watching_too_much(tmp_path):
    """`_git_ignored` drops files from the cache key, so every way it can fail has to
    fail by dropping NOTHING. A directory that is not a git repository is the case a
    test fixture hits every time, and it is the same shape as git being absent."""
    root = _fixture_repo(tmp_path / "repo")

    assert mutation_scope._git_ignored(root, ["pkg/helper.py", "docs/notes.md"]) == set()
    assert "pkg/helper.py" in mutation_scope.sandbox_files(root)


def test_a_dependency_pin_edit_discards_the_cache(tmp_path):
    """`_fingerprint` already hashes the pinned mutmut version, because mutmut's
    operator set defines what the gate asserts. The same argument reaches the rest of
    the dependency set: `pytest`, `django` and `pyyaml` all sit between a mutant and its
    verdict, and a pin moving can turn a kill into a survivor with not one byte of this
    repository's own code changed.

    Stated at the cache key over a fixture tree, like the other F2 tests. What it does
    NOT claim is stated in `mutation_scope.DEPENDENCY_PINS`: a `pip install -U` behind
    an unchanged `>=` floor moves the installed versions without moving these files, and
    only hashing the resolved environment would catch that.
    """
    import mutation_gate

    root = _fixture_repo(tmp_path / "repo")
    (root / "requirements.txt").write_text("pyyaml>=6\n", encoding="utf-8")
    (root / "requirements-dev.txt").write_text("-r requirements.txt\npytest==8.4.2\n",
                                               encoding="utf-8")
    before = mutation_gate._fingerprint(root)

    (root / "requirements-dev.txt").write_text("-r requirements.txt\npytest==8.4.1\n",
                                               encoding="utf-8")

    assert mutation_gate._fingerprint(root) != before


def test_a_new_dependency_pin_file_is_watched_without_being_remembered(tmp_path):
    """Round-9 queue item 2. The pin list was the fourth hand-typed list in a module
    written about the cost of the first three.

    `DEPENDENCY_PINS` was `("requirements.txt", "requirements-dev.txt")`, typed out, with
    nothing asserting it against the tree. That is R4-12's shape exactly: the day a
    `requirements-prod.txt` or a second constraints file lands, it pins the versions that
    decide every mutant's verdict and the cache inherits the previous release's answers
    with no signal anywhere — the same silence that cost `wizard/` its place in the
    bandit and log-scrubber scopes, separately.

    Derived instead, and stated at the cache key over a fixture tree like the other F2
    tests: a pin file that exists is watched because it exists, not because somebody
    remembered it.
    """
    import mutation_gate

    root = _fixture_repo(tmp_path / "repo")
    (root / "requirements.txt").write_text("pyyaml>=6\n", encoding="utf-8")
    (root / "requirements-prod.txt").write_text("gunicorn==23.0.0\n", encoding="utf-8")
    before = mutation_gate._fingerprint(root)

    (root / "requirements-prod.txt").write_text("gunicorn==22.0.0\n", encoding="utf-8")

    assert mutation_gate._fingerprint(root) != before
    assert "requirements-prod.txt" in mutation_scope.sandbox_files(root)


def test_the_dependency_pins_are_the_repos_pin_files_not_a_typed_list():
    """The assertion that pins the derivation, in the direction that matters.

    The test above proves a new pin file is picked up in a fixture tree; this one proves
    the constant this repository actually runs with is the tree's own answer. Both
    patterns are restated here on purpose — narrowing the derivation to match a typed
    list again has to change this file too, which is the same bargain
    `GATE_BEARING` and `py_roots` strike above.

    `constraints*.txt` is in the pattern set and matches nothing today. That is
    deliberate: it is pip's other pin file, it is the name a future one would land under,
    and a pattern that matches nothing costs a glob.
    """
    expected = sorted({p.name for p in REPO.glob("requirements*.txt")}
                      | {p.name for p in REPO.glob("constraints*.txt")})

    assert list(mutation_scope.DEPENDENCY_PINS) == expected
    assert mutation_scope.DEPENDENCY_PINS == mutation_scope.dependency_pins(REPO)
    # The two the F2 commit named, asserted individually as well as through the
    # derivation — a derivation that is right today and a finding that names two files
    # are two different claims.
    assert {"requirements.txt", "requirements-dev.txt"} <= set(expected)


# ── R9-B: the verdict was a denylist, so an unknown status scored green ────────

@pytest.fixture
def gate(tmp_path, monkeypatch):
    """`mutation_gate.main` with the run, the cache and the waivers stubbed out.

    Same stubs as the two verdict tests above, hoisted so the R9-B cases can drive the
    verdict directly: a realistic `CompletedProcess` (`mutation_gate.subprocess` IS the
    stdlib module, and `mutation_scope._git_ignored` calls `run` too), a `mutants/`
    pointed at a directory that does not exist so no test can delete the real cache, and
    no waivers unless a case sets some.
    """
    import mutation_gate

    monkeypatch.setattr(mutation_gate.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(a, 0, stdout="",
                                                                    stderr=""))
    monkeypatch.setattr(mutation_gate, "MUTANTS", tmp_path / "mutants")
    monkeypatch.setattr(mutation_gate, "FINGERPRINT", tmp_path / "mutants/.fingerprint")
    monkeypatch.setattr(mutation_gate, "_waived_mutants", lambda: (set(), []))

    def results(mapping):
        monkeypatch.setattr(
            mutation_gate, "_results",
            lambda: {k: (v, "wizard/materialize.py") for k, v in mapping.items()})

    mutation_gate.results = results
    return mutation_gate


@pytest.mark.parametrize("status", [
    # mutmut 3.7.0's own `status_by_exit_code` table, minus the two that pass. The three
    # in the middle are the finding: none of them was in the old FAILING tuple, so each
    # scored green.
    "survived", "no tests", "suspicious", "segfault",
    "not checked", "check was interrupted by user", "skipped",
    "caught by type check",
    # …and one that is in no table at all. THIS is the property the fix is about: the
    # gate must fail on a status it has never heard of, because the alternative is a
    # mutmut upgrade adding a name and this gate scoring it green in silence.
    "invented by a future mutmut",
])
def test_issue_r9_b_every_status_that_is_not_killed_or_timeout_fails(gate, status):
    """R9-B. `FAILING = ("survived", "no tests", "suspicious", "segfault")` was a
    DENYLIST: a mutant whose status was not one of those four passed, and mutmut 3.7.0
    has four more — `not checked`, `check was interrupted by user`, `skipped` and
    `caught by type check` — every one of which means the tests did not demonstrate
    anything about that mutant.

    A denylist of statuses is the same defect as a hand-typed scope list (R4-12) one
    layer down: it is right until the tool it mirrors changes, and it fails open.
    """
    gate.results({"m1": "killed", "m2": status})
    assert gate.main([]) == 1, status


def test_issue_r9_b_only_killed_and_timeout_pass(gate):
    """The other side of the allowlist, so the fix cannot be "fail on everything".

    `timeout` stays green for the reason the module docstring has always given: the
    per-mutant clock in `[tool.mutmut]` exists so a mutant that makes the code loop
    forever does not hang the gate, and being killed by that clock is the clock working.
    """
    gate.results({"m1": "killed", "m2": "timeout"})
    assert gate.main([]) == 0


def test_issue_r9_b_a_filtered_run_cannot_report_green(gate, capsys):
    """The reviewer's demonstration, as a unit. Verbatim:

        $ python scripts_dev/mutation_gate.py <the 8 waived mutant ids>
        mutation gate: 710 mutants — not checked=702, survived=8, waived=8
        mutation gate: no surviving mutants
        $ echo $?
        0

    `main` passed its argv straight to `mutmut run`, so naming a handful of mutants ran
    only those and left every other mutant `not checked` — a status the old denylist did
    not fail on. Exit 0, on a run that tested 8 of 710 mutants and eight of them were the
    waived ones.

    Two independent things now stop it, because either alone would leave the other
    half open: the gate refuses argv at all (there is no supported way to scope this
    run — that rule is already in the Makefile recipe's comment, it just was not
    enforced anywhere), and `not checked` fails on its own account, which covers a
    partial run that arrives by any other route.
    """
    gate.results({"m1": "killed"})   # a result set that would otherwise score green
    assert gate.main(["wizard.materialize.x__apply_answers__mutmut_17"]) == 2
    assert "refus" in capsys.readouterr().err.lower()


def test_issue_r9_b_a_waiver_excuses_a_survivor_and_nothing_else(gate, monkeypatch):
    """The hole the demonstration went through, closed at the waiver end too.

    A waiver's claim is "this mutant SURVIVES and is provably equivalent" — that is what
    every line in WAIVERS.md says and what the gate's docstring describes. So a waiver
    excuses exactly `survived`. With the allowlist alone, a waived mutant that came back
    `not checked` would have been skipped by `name not in waived` and never reached the
    failure list: the eight ids in the demonstration are waived ones, which is not a
    coincidence.
    """
    monkeypatch.setattr(gate, "_waived_mutants", lambda: ({"m2"}, []))

    gate.results({"m1": "killed", "m2": "survived"})
    assert gate.main([]) == 0

    gate.results({"m1": "killed", "m2": "not checked"})
    assert gate.main([]) == 1, "a waiver excused a mutant that was never tested"

    gate.results({"m1": "killed", "m2": "killed"})
    assert gate.main([]) == 1, "a spent waiver passed"


def test_issue_r9_b_the_passing_set_is_the_whole_verdict(gate):
    """There is no second list. Spelled as an assertion because the fix's entire content
    is that the gate's judgement is stated once, positively, and read from `PASSING`."""
    assert gate.PASSING == ("killed", "timeout")
    assert not hasattr(gate, "FAILING"), \
        "the denylist is back; two lists of statuses is the R9-B defect"
