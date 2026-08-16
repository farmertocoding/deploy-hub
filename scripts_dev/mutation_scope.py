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

`conformance/` and `scripts_dev/` have no `__init__.py` on purpose (see the Makefile's
$(PY_ROOTS) comment), so this module is not importable as a package. Its callers put
its directory on the path, the same way `tests/conftest.py` does for `conformance/`.
"""
import ast
import pathlib
import sys
import tomllib

REPO = pathlib.Path(__file__).resolve().parent.parent
TESTS = REPO / "tests"

# The two files spec §3 names as the floor of the derived test selection. Asserted, not
# assumed: a derivation that silently found nothing would otherwise be a green gate that
# runs no tests at all, which is the failure mode this whole gate exists to catch.
REQUIRED_TEST_FILES = ("tests/test_scanner_declarations.py", "tests/test_wizard.py")


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


if __name__ == "__main__":
    if "--mutated" in sys.argv:
        print("\n".join(mutated_paths()))
    else:
        print("\n".join(test_files_touching()))
