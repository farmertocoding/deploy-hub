"""The mutation gate's two derived lists, in one place.

WHY THIS EXISTS AT ALL. `spec-mutation-gate.md` §1: a hand-typed list of anything is
R4-12's defect in a new costume — `wizard/` landed and both the bandit list and the
log-scrubber list were missed, separately, because each was a list somebody had typed.
The mutation set itself is derived by mutmut from the code, which is the whole point of
using a tool rather than a curated table of mutations. But the gate has two lists of its
own, and both are the same hazard one level up:

  * WHICH MODULES ARE MUTATED — `[tool.mutmut] source_paths` in `pyproject.toml`. This
    one is a DELIBERATE list (the gate-bearing set), so it cannot be derived; what it
    can be is single. It lives once, in the config the tool reads, and
    `tests/test_mutation_gate.py` asserts it is still a superset of the three files the
    spec names (§3, §7.2), so a round cannot quietly narrow the set that judges it.

  * WHICH TESTS RUN PER MUTANT — spec §3 asks for "any test file that imports a mutated
    module — derive the file list with a small script rather than typing it". That is
    `test_files_touching()` below. mutmut then narrows FURTHER, per mutant, using the
    per-function coverage it records during its stats run; this list is the outer bound
    it narrows from, and being an honest superset of the tests that reach these modules
    is exactly what makes that narrowing safe.

  * WHAT THE VERDICT CACHE WATCHES — `sandbox_files()` below, added by F2. The first cut
    of the cache key was a THIRD hand-typed list (source_paths + the selected tests +
    conftest), and it was wrong in the way a hand-typed list is always wrong: it missed
    `wizard/service.py`, `wizard/views.py`, `vault/service.py` and `sample-node-site/` —
    modules that no mutant touches but that every killing chain runs THROUGH. See
    `scripts_dev/mutation_gate.py::_fingerprint` for what a miss costs.

`conformance/` and `scripts_dev/` have no `__init__.py` on purpose (see the Makefile's
$(PY_ROOTS) comment), so this module is not importable as a package. Its callers put
its directory on the path, the same way `tests/conftest.py` does for `conformance/`.
"""
import ast
import pathlib
import subprocess
import sys
import tomllib

REPO = pathlib.Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"

# The two files spec §3 names as the floor of the derived test selection. Asserted, not
# assumed: a derivation that silently found nothing would otherwise be a green gate that
# runs no tests at all, which is the failure mode this whole gate exists to catch.
REQUIRED_TEST_FILES = ("tests/test_scanner_declarations.py", "tests/test_wizard.py")

# Directories mutmut copies into `mutants/` without being told to (mutmut 3's
# `_load_config` appends these to whatever `also_copy` says), plus the config file it
# reads from inside the copy. Listed here because the cache key has to cover the WHOLE
# sandbox and mutmut's defaults are part of it — restated from mutmut's source, and the
# restatement is safe in the only direction that matters: if a future mutmut adds a
# default we do not know about, this list is too SMALL, which the sandbox-coverage test
# catches for everything derivable from the tree.
MUTMUT_IMPLICIT_COPIES = ("tests", "pyproject.toml", "setup.cfg")

# Not in the sandbox, and watched anyway. Closing the file-shaped half of the review's
# note on branch 1: `_fingerprint` already hashes the PINNED mutmut version, because
# mutmut's operator set is the gate's definition of "every way this code could be
# wrong". The same argument reaches one step further — a mutant's verdict is a property
# of the whole installed dependency set, and a `pytest`, `django` or `pyyaml` pin moving
# can flip a kill into a survivor with not one byte of this repository changed. The pin
# files are what this repository SAYS that set is, so a pin edit now discards the cached
# verdicts instead of silently inheriting the previous release's.
#
# DERIVED, ROUND-9 ITEM 2: this was `("requirements.txt", "requirements-dev.txt")`,
# typed out — the fourth hand-typed list in a module whose opening paragraph is about
# what the first three cost. Nothing asserted it against the tree, so a
# `requirements-prod.txt` landing next week would pin the versions that decide every
# verdict while the cache went on inheriting the previous release's answers, with no
# signal anywhere. That is R4-12's shape, and the answer is R4-12's answer: ask the tree.
#
# THE ENVIRONMENT-SHAPED HALF IS STILL OPEN and this does not pretend otherwise: a
# `pip install -U` behind an unchanged `>=` floor moves the installed versions without
# moving these files, and only hashing the resolved environment (`pip freeze`) would
# catch that. That is a cost-per-run decision of its own; what is closed here is the
# case where the repo's own diff shows the change and the gate ignored it.
#
# `constraints*.txt` matches nothing today and is in the set anyway: it is pip's other
# pin file and the name a future one lands under, and a pattern that matches nothing
# costs one glob. The patterns are restated in
# tests/test_mutation_gate.py::test_the_dependency_pins_are_the_repos_pin_files_not_a_typed_list,
# which is what stops a future round narrowing them back into a list.
PIN_FILE_PATTERNS = ("requirements*.txt", "constraints*.txt")


def dependency_pins(root=None):
    """The repo-root pip pin files, by pattern. Sorted, repo-relative, deduplicated."""
    root = pathlib.Path(root or REPO)
    return tuple(sorted({p.name for pattern in PIN_FILE_PATTERNS
                         for p in root.glob(pattern) if p.is_file()}))


DEPENDENCY_PINS = dependency_pins()

# Names never hashed: caches whose contents change on every run (so watching them would
# discard the cache every time) and vendored trees that are not inputs to any test.
NOT_AN_INPUT = {"__pycache__", "node_modules", ".git", ".pytest_cache", ".ruff_cache",
                "mutants"}


def mutated_paths(root=None):
    """The mutated file list, read from the ONE place it is configured."""
    root = pathlib.Path(root or REPO)
    config = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))
    return tuple(config["tool"]["mutmut"]["source_paths"])


def _first_party_modules(root):
    """`{dotted module name: path}` for every python module in the repo's packages.

    A package is a top-level directory with an `__init__.py` — the same predicate the
    Makefile's $(PY_ROOTS) uses, and for the same reason: it is the tree's own answer to
    "what is importable here", so a package that lands next week is in scope by
    existing rather than by being remembered.
    """
    modules = {}
    for package in sorted(p for p in root.iterdir()
                          if p.is_dir() and (p / "__init__.py").exists() and p.name != "tests"):
        for path in sorted(package.rglob("*.py")):
            parts = path.relative_to(root).with_suffix("").parts
            if parts[-1] == "__init__":
                parts = parts[:-1]
            modules[".".join(parts)] = path
    return modules


def _imported_names(path, package_parts):
    """Every module name `path` imports, absolute and relative forms both.

    Relative imports are resolved against the importing module's own package, because
    `scanner/core.py` spells its sibling `from . import declarations` — which is the
    exact spelling F1 (6cb759b) caught a hand-written guard missing.
    """
    names = set()
    tree = ast.parse(path.read_text("utf-8"), filename=str(path))
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = package_parts[:len(package_parts) - (node.level - 1)] if node.level > 1 \
                    else package_parts
                prefix = ".".join(base)
            else:
                prefix = node.module or ""
            if node.module and node.level:
                prefix = f"{prefix}.{node.module}" if prefix else node.module
            if prefix:
                names.add(prefix)
            for alias in node.names:
                names.add(f"{prefix}.{alias.name}" if prefix else alias.name)
    return names


def _closure(start_names, modules, module_packages):
    """Every first-party module reachable from `start_names` by imports, transitively.

    Transitive because a test that imports `wizard.service` is a test that exercises
    `wizard.materialize`, and the tests that reach a mutated module through one hop are
    most of the tests that kill its mutants.
    """
    seen, queue = set(), [n for n in start_names]
    while queue:
        name = queue.pop()
        # `from wizard.materialize import x` also yields `wizard.materialize.x`; walk
        # the dotted prefixes so an imported ATTRIBUTE still resolves to its module.
        for candidate in (name, name.rsplit(".", 1)[0] if "." in name else name):
            if candidate in modules and candidate not in seen:
                seen.add(candidate)
                queue.extend(_imported_names(modules[candidate], module_packages[candidate]))
    return seen


def test_files_touching(paths=None, root=None):
    """Test files whose import closure reaches any of `paths`. Sorted, repo-relative."""
    root = pathlib.Path(root or REPO)
    paths = tuple(paths if paths is not None else mutated_paths(root))
    modules = _first_party_modules(root)
    module_packages = {name: tuple(name.split(".")[:-1]) or (name,) for name in modules}
    targets = {name for name, path in modules.items()
               if str(path.relative_to(root)) in paths}
    if not targets:
        raise SystemExit(f"no first-party module matches the mutated paths {paths!r}")

    found = []
    for test in sorted((root / "tests").rglob("test_*.py")):
        names = _imported_names(test, ("tests",))
        if targets & _closure(names, modules, module_packages):
            found.append(str(test.relative_to(root)))
    return found


def py_roots(root=None):
    """The tree's Python packages, by the Makefile's own predicate.

    A top-level directory with an `__init__.py`, minus the test suite. Restating the
    predicate rather than shelling out to `make py-roots` keeps this importable from a
    test, and `tests/test_mutation_gate.py` asserts the two agree — R4-12 is what a
    second, drifting copy of a scan scope costs, and this gate is not allowed to grow
    one.
    """
    root = pathlib.Path(root or REPO)
    return sorted(p.name for p in root.iterdir()
                  if p.is_dir() and (p / "__init__.py").exists() and p.name != "tests")


def _git_ignored(root, relative_paths):
    """The subset of `relative_paths` git ignores. Empty on any doubt.

    WHY GIT AND NOT ANOTHER NAME LIST. Two files inside the sandbox are REWRITTEN by the
    gates that run before this one in `review-round`: `make test` writes
    `conformance/run-report.json` (the conftest plugin) and `make conformance` writes
    `conformance/matrix.json`. Watching them means the cache is discarded on every
    single round — measured: two consecutive `make mutation` runs with no edit between
    them both ran cold — which does not make the gate WRONG, it makes the warm path
    unreachable, and a gate that always costs three minutes is a gate people find a way
    around.

    "Generated artifact, not an input under review" is exactly what `.gitignore` already
    says about both of them, and it says it in one place that a human maintains for
    other reasons. Reading it is derivation; adding two more names to `NOT_AN_INPUT`
    would be the third hand-typed list in a module written about the cost of the first
    two. `conformance/gates.py` already shells out to git for `git_head` and
    `tree_fingerprint`, so this is not a new dependency for gate machinery.

    FAILING TOWARD MORE WORK, deliberately: any error, a missing git, a directory that
    is not a repository — all of them return the empty set, so nothing is dropped from
    the watch set and the gate runs cold. The dangerous direction is watching too
    little, and this cannot get there.
    """
    paths = [p for p in relative_paths if "\n" not in p]
    if not paths:
        return set()
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "check-ignore", "--stdin", "-z"],
            input="\0".join(paths), capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        return set()
    # 0 = some paths are ignored, 1 = none are. Anything else (128: not a repository)
    # is an answer this cannot trust.
    if result.returncode not in (0, 1) or not isinstance(result.stdout, str):
        return set()
    return {p for p in result.stdout.split("\0") if p}


def sandbox_files(root=None):
    """Every file that ends up inside the gate's `mutants/` sandbox. Sorted, relative.

    DERIVED FROM THE CONFIG, not from a list: mutmut builds the sandbox out of
    `source_paths` + `also_copy` + its own implicit copies, so that union IS the answer
    to "what can change a mutant's verdict without being a mutant". Anything a test can
    read is in here; anything not in here is not in the sandbox at all.

    This is deliberately wider than "the modules the killing chains traverse", which is
    the F2 finding's own wording, because that phrasing is a judgement call and this is
    not: enumerating which non-mutated modules a chain runs through is the same guessing
    game that produced the missed list in the first place. The union is mechanical.

    `dependency_pins(root)` joins it although those files are not copied into the
    sandbox: the tests inside it import the versions those files pin, so the pins are an
    input to every verdict even though nothing there opens them. Resolved against the
    ROOT being fingerprinted rather than through the `DEPENDENCY_PINS` constant, which
    answers for this repository only — a fixture tree's pins are its own.
    """
    root = pathlib.Path(root or REPO)
    config = tomllib.loads((root / "pyproject.toml").read_text("utf-8"))["tool"]["mutmut"]
    roots = [*config["source_paths"], *config.get("also_copy", ()),
             *MUTMUT_IMPLICIT_COPIES, *dependency_pins(root)]

    found = set()
    for name in roots:
        start = root / name
        if start.is_file():
            found.add(name)
            continue
        if not start.is_dir():
            continue
        for path in start.rglob("*"):
            rel = path.relative_to(root)
            if NOT_AN_INPUT & set(rel.parts) or not path.is_file():
                continue
            if path.suffix in (".pyc", ".pyo"):
                continue
            found.add(rel.as_posix())
    return sorted(found - _git_ignored(root, sorted(found)))


if __name__ == "__main__":
    if "--mutated" in sys.argv:
        print("\n".join(mutated_paths()))
    elif "--sandbox" in sys.argv:
        print("\n".join(sandbox_files()))
    else:
        print("\n".join(test_files_touching()))
