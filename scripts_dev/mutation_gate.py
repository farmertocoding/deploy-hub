"""`make mutation` — run mutmut over the configured scope and fail on any survivor.

WHY A SCRIPT AND NOT A ONE-LINE RECIPE. `mutmut run` exits 0 whether or not mutants
survived: it reports, it does not judge. A Makefile target that shells out to it and
stops there is a gate CI reaches and does not enforce — the same false green the
Makefile's own self-defense preamble was written against. So the verdict is computed
here, from mutmut's own per-mutant result file, and this process's exit status IS the
gate's.

WHAT COUNTS AS A PASS — and it is an ALLOWLIST, which is the whole of R9-B (spec §4's
zero-survivor policy, read for its intent rather than its one word):

  * `killed`   — a test saw the mutation. The only outcome that demonstrates anything.
  * `timeout`  — the mutant makes the code loop forever and the per-mutant clock in
                 `[tool.mutmut]` killed it, which is that clock working. Printed in the
                 summary so a rising count stays visible.

EVERYTHING ELSE FAILS, including a status this file has never heard of. That sentence
used to read the other way round — a `FAILING` tuple of `survived`, `no tests`,
`suspicious`, `segfault`, and anything outside it passed — and mutmut 3.7.0's own
`status_by_exit_code` table carries four more names than that tuple knew about:
`not checked`, `check was interrupted by user`, `skipped`, `caught by type check`. Every
one of them means the tests demonstrated nothing about that mutant, and every one of
them scored green.

A denylist of statuses is R4-12's hand-typed list one layer down: correct until the tool
it mirrors changes, and wrong in the direction that reports a gate as passing. The
allowlist is wrong in the other direction — a future mutmut status that IS a kill would
fail this gate until someone adds it, loudly, in a diff.

NO FILTERED RUNS. `main` refuses argv outright. `mutmut run` takes mutant-name arguments
and tests only those, leaving every other mutant `not checked`, and with the old denylist
that was a one-command green:

    $ python scripts_dev/mutation_gate.py <the eight waived mutant ids>
    mutation gate: 710 mutants — not checked=702, survived=8, waived=8
    mutation gate: no surviving mutants        # exit 0

The Makefile recipe already says the gate takes "NO SCOPE AND NO FLAGS", for the reason
that a scope spelled at the call site is the second copy that drifts; that was a comment
and is now the behaviour. The `not checked` failure above is the independent half: a
partial run that arrives by some other route — an interrupted run, a crash mid-sweep —
cannot report green either.

OUTPUT (spec §5): every failing mutant is one line — id, file, and the exact
`mutmut show <id>` command that prints its diff — so a survivor entering a round becomes
a finding with `fingerprint = mutation + <file> + <mutant id>` without anybody having to
reconstruct what it was.

WAIVERS (spec §4's escape hatch, and it is the ONLY one — there is no baseline file and
no allowlist this gate consults silently). A mutant that is provably equivalent — a
different spelling of the same behaviour, so no test anywhere can distinguish it — is
recorded in `WAIVERS.md` under the fingerprint above, one line per mutant, justified
individually, in the same file and the same format as every other waiver in this repo.
Two things keep that from becoming a baseline by another name:

  * a waiver whose mutant is NOT surviving fails the gate. A waiver that has been fixed,
    or whose mutant no longer exists after a refactor, is dead text claiming a judgement
    nobody re-made — the same rot `_read_entry` refuses in a stale declaration;
  * they are in WAIVERS.md, which the round reads. A waiver nobody sees is a baseline.

mutmut's own `# pragma: no mutate` was NOT used for these. It sits on the production
line and suppresses every mutation on that line, including the ones that ARE killed
today and the ones a future edit would add — a marker that silently widens is how a
scope narrows without a diff.
"""
import hashlib
import os
import pathlib
import shutil
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parent.parent
MUTANTS = REPO / "mutants"
FINGERPRINT = MUTANTS / ".gate-fingerprint"

# The gate's entire verdict, stated once and positively. Anything not in here fails —
# see the module docstring for why this direction and not the other.
PASSING = ("killed", "timeout")

# The one status a WAIVER may excuse. A waiver's claim is "this mutant survives and is
# provably equivalent"; it is not a claim about a mutant that was never tested. Without
# this the allowlist still had the demonstration's hole in it — the eight ids named on
# that command line were the waived ones, and `name not in waived` would have skipped
# them whatever `not checked` meant.
WAIVABLE = ("survived",)


def _fingerprint(root=None):
    """A digest of everything that can change a mutant's verdict but is not a mutant.

    THE CACHE IS THE ONE PLACE THIS GATE COULD LIE, and it is worth spelling out because
    the failure is silent and points the wrong way. mutmut caches a verdict per mutant
    and re-tests only when the mutated FUNCTION's hash changes — its own comment is
    "rerun mutant if it's explicitly mentioned, but otherwise let the result stand". A
    test edit is invisible to that rule, so writing the test that kills a survivor leaves
    the survivor cached as surviving (the gate stays red at a fixed fix), and DELETING
    the test that killed a mutant leaves it cached as killed (the gate goes green at a
    real regression). The second one is the dangerous direction.

    So the cache is keyed here on the things mutmut does not watch, and F2 is what the
    FIRST cut of that sentence cost. It read "the mutated sources, every test file in the
    configured selection, the shared conftest" — a third hand-typed list, and wrong in
    exactly the way R4-12 says a hand-typed list is wrong. It omitted every module that
    no mutant touches but that a killing chain runs THROUGH: `wizard/service.py`
    (`preflight` imports `downgraded_answers` from it, `materialize` imports
    `scrub_downgraded_answers`), `wizard/views.py`, `vault/service.py`, and the
    `sample-node-site/` fixture repo the phase-1 acceptance tier scans off disk. Appending
    a comment to `wizard/service.py` ran warm from the cache while mutmut re-synced the
    edit into `mutants/` in the same run, so the verdicts being reported had been computed
    against a tree that no longer existed. A behavioural edit there does the same thing
    silently, and in the direction that matters: a chain that stops killing a mutant keeps
    reporting it killed.

    So the watch set is DERIVED now, from mutmut's own sandbox construction:
    `mutation_scope.sandbox_files()` is the union of `source_paths`, `also_copy` and
    mutmut's implicit copies — that is, every file that can be read from inside
    `mutants/` at all. Anything outside it cannot influence a verdict, because it is not
    in the sandbox. Plus the `[tool.mutmut]` block itself and the pinned mutmut version,
    which are inputs to the run rather than files in the tree.

    Any of them moves and `mutants/` is rebuilt from scratch. A round that changes
    nothing re-runs warm; a round that touches any of the code or the tests pays for a
    cold run, which is exactly when a stale verdict would have mattered. Caches whose
    contents change per run (`__pycache__`, `.pytest_cache`) are excluded by
    `mutation_scope.NOT_AN_INPUT`, or the gate would discard its own cache every time.
    """
    import tomllib

    # `root` is a parameter so the digest can be computed over a fixture tree in a test —
    # a cache key nothing exercises is the same shape of defect as F2 itself.
    root = pathlib.Path(root or REPO)
    sys.path.insert(0, str(REPO / "scripts_dev"))
    import mutation_scope

    config = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["tool"]["mutmut"]
    digest = hashlib.sha256()
    digest.update(repr(sorted(config.items())).encode("utf-8"))
    try:
        import mutmut

        digest.update(getattr(mutmut, "__version__", "unknown").encode("utf-8"))
    except ImportError:                                          # pragma: no cover
        digest.update(b"mutmut-not-importable")
    for name in mutation_scope.sandbox_files(root):
        path = root / name
        digest.update(name.encode("utf-8"))
        digest.update(path.read_bytes() if path.exists() else b"<missing>")
    return digest.hexdigest()


def _results():
    """`{mutant id: status}` read from mutmut's own per-file meta files.

    Read through mutmut's API rather than by parsing `mutmut results` output, so the
    verdict cannot drift from what the tool recorded.
    """
    from mutmut.__main__ import status_by_exit_code, walk_mutatable_files
    from mutmut.mutation.data import SourceFileMutationData

    results = {}
    for path in walk_mutatable_files():
        data = SourceFileMutationData(path=path)
        data.load()
        for mutant_name, exit_code in data.exit_code_by_key.items():
            results[mutant_name] = (status_by_exit_code[exit_code], str(path))
    return results


def _waived_mutants():
    """`({mutant id}, [problems])` from WAIVERS.md.

    Parsed with `conformance/gates.py`'s reader rather than a second regex here: two
    parsers for one file is the D-010 defect that made a transcribed waiver silently
    waive nothing, and this gate would inherit it wholesale.
    """
    sys.path.insert(0, str(REPO / "conformance"))
    import gates

    waivers, problems = gates.parse_waivers(REPO)
    waived = set()
    for fingerprint in waivers:
        prefix, _, mutant = fingerprint.partition("+")
        if prefix != "mutation":
            continue
        _file, _, mutant_id = mutant.rpartition("+")
        waived.add(mutant_id)
    return waived, problems


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv:
        # R9-B. `mutmut run <mutant name> …` tests only the named mutants and leaves the
        # rest `not checked`, which the old denylist scored green — eight arguments and
        # this gate reported a clean sweep of 710 mutants it had not run. There is no
        # supported way to scope this gate (the recipe's own comment says so), so there
        # is nothing to pass through, and a refusal is the only reading of an argument
        # that cannot be wrong. Exit 2, distinct from the 1 a real survivor earns: this
        # is the gate declining to run, not a verdict.
        print(f"mutation gate: refusing to run with arguments {argv} — `mutmut run` "
              f"takes mutant names and tests ONLY those, leaving every other mutant "
              f"unchecked, which is a partial run wearing a full run's exit status. "
              f"Scope, test selection and per-mutant timeout live in [tool.mutmut] in "
              f"pyproject.toml, once. Run `make mutation` with no arguments.",
              file=sys.stderr)
        return 2
    env = dict(os.environ)
    # The conformance plugin in tests/conftest.py writes a run report next to the tests
    # it ran. Inside the `mutants/` copy that is a report of a mutated run, and nothing
    # should ever read it as the round's evidence — the same rule a nested pytest
    # invocation already follows.
    env["CONFORMANCE_RUN_REPORT"] = "off"

    fingerprint = _fingerprint()
    if MUTANTS.exists() and (not FINGERPRINT.exists()
                             or FINGERPRINT.read_text("utf-8").strip() != fingerprint):
        print("mutation gate: sources, tests or config moved since the cached run — "
              "discarding mutants/ and re-testing every mutant")
        shutil.rmtree(MUTANTS)

    run = subprocess.run([sys.executable, "-m", "mutmut", "run", *argv],
                         cwd=REPO, env=env)
    if MUTANTS.is_dir():
        FINGERPRINT.write_text(fingerprint + "\n", encoding="utf-8")

    os.chdir(REPO)   # mutmut resolves `mutants/` and `pyproject.toml` from the cwd
    results = _results()
    if not results:
        print("mutation gate: mutmut recorded no mutants at all — the scope is empty or "
              "the run did not start; refusing to report a green gate", file=sys.stderr)
        return 1

    waived, waiver_problems = _waived_mutants()

    counts = {}
    for status, _ in results.values():
        counts[status] = counts.get(status, 0) + 1
    summary = ", ".join(f"{status}={counts[status]}" for status in sorted(counts))
    print(f"mutation gate: {len(results)} mutants — {summary}"
          + (f", waived={len(waived)}" if waived else ""))

    failures = sorted((name, status, path)
                      for name, (status, path) in results.items()
                      if status not in PASSING
                      and not (name in waived and status in WAIVABLE))

    # A waiver for a mutant that is not surviving is a judgement nobody re-made.
    for name in sorted(waived):
        if name not in results:
            waiver_problems.append(
                f"WAIVERS.md waives {name}, which is not a mutant of the configured "
                f"scope any more — the waiver outlived the code it excused")
        elif results[name][0] in PASSING:
            waiver_problems.append(
                f"WAIVERS.md waives {name}, which is now '{results[name][0]}' — the "
                f"waiver is spent; delete the line")

    if waiver_problems:
        print("")
        for problem in waiver_problems:
            print(f"  waiver: {problem}")
        print("\nmutation gate FAILED: the waiver list does not match the run.")
        return 1

    if failures:
        print("")
        for name, status, path in failures:
            print(f"  {status}: {name}  [{path}]  ->  mutmut show {name}")
        print(f"\nmutation gate FAILED: {len(failures)} mutant(s) the tests do not "
              f"catch. Each one is a finding: fix it with a failing-first test, or — if "
              f"it is provably equivalent — record it in WAIVERS.md by mutant id.")
        return 1

    if run.returncode != 0:
        print(f"mutation gate: every mutant killed or timed out, but `mutmut run` "
              f"exited {run.returncode}", file=sys.stderr)
        return run.returncode
    # Not "no surviving mutants" any more, and the wording is part of the fix: that
    # sentence is what the filtered run printed over 702 mutants it never tested. What
    # the gate can now claim is what it checked.
    print("mutation gate: every mutant was killed or timed out")
    return 0


if __name__ == "__main__":
    sys.exit(main())
