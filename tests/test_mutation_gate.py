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

    monkeypatch.setattr(mutation_gate.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(a, 0))
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

    monkeypatch.setattr(mutation_gate.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(a, 0))
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
