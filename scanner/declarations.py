"""`deployhub.yaml` — what the scanned repo declares about itself.

Follow-up 2 of the D-011r noise work, ruled by Joseph 2026-08-11 and specified in
`docs/spec-declared-test-material.md`. The measurement behind it: 20 of
SATURDAYS_site's 26 blocking heuristic lines are `frontend/scripts/drill/**` — red-team
and QA scripts holding deliberate `admin_password` literals. Test material by intent and
by content, but not by path, so `core.secret-scan` has no honest way to know.

THE ALTERNATIVES WERE CONSIDERED AND NOT CHOSEN, and the shape of this module is what
that ruling costs:

  * the scanner guessing from directory names (`drill/`, `qa/`) — round-6b's
    `spec`/`fixtures`/`e2e` mistake, where a production directory called `e2e` had a
    real credential downgraded by its name alone. Nothing here classifies a directory
    by its name;
  * a Hub-side operator waiver — invisible in the repo, so the next reader of the code
    has no way to know a downgrade exists;
  * keeping it a blocker — which is what trains blocker-bypass, the mechanism D-011r
    named as grounds to reconsider the heuristic tier.

So the claim lives in the scanned repo, in a file that shows up in that repo's diffs and
its review, the report always prints the claim, and the wizard makes accepting it the
operator's logged act.

This module is PARSING AND VALIDATION ONLY. It changes no tier and reads no source
file: `fallbacks._check_secret_scan` decides what a declaration does, and does it to one
axis (the N6 rule — scope the axis, never the walk).
"""
import os
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

DECLARATION_FILE = "deployhub.yaml"

# Files whose presence means "the scanner keys on this directory" — a declaration
# wrapped around one is refused. Each name is here because something reads it:
#
#   package.json, pyproject.toml, requirements.txt, manage.py, Dockerfile, go.mod,
#   Gemfile, composer.json   `fallbacks._SERVER_MANIFESTS` (StaticModule's "is there a
#                            server here" test), and `core.lockfile` reads the first
#                            three wherever they nest
#   manage.py                django's `project_root()` rglob
#   pnpm-workspace.yaml      node_ts detection
#   settings.py              django's settings discovery
#   deployhub.yaml           a declaration file inside a declared tree is a nested
#                            claim nobody reviewed at the root
#
# A test freezes this set and asserts it covers `_SERVER_MANIFESTS`, so a manifest added
# to the module list cannot quietly stop being refusable here.
SCANNER_KEY_FILES = frozenset({
    "package.json", "pyproject.toml", "requirements.txt", "manage.py",
    "Dockerfile", "go.mod", "Gemfile", "composer.json",
    "pnpm-workspace.yaml", "settings.py", DECLARATION_FILE,
})

# Pruned when looking for those files inside a declared tree: a vendored `node_modules`
# under a drill directory holds thousands of `package.json` files and none of them is
# the project's manifest. Same names the walk prunes, kept local so this module imports
# nothing from `modules/`.
_PRUNE_DIRS = {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__",
               "dist", "build", ".next", ".nuxt", ".cache", "vendor", ".tox"}

_GLOB_CHARS = set("*?[]{}")
_ROOTISH = {"", ".", "./", "/", "./."}


@dataclass(frozen=True)
class Declaration:
    """One accepted `{path, reason}` entry."""

    path: str        # normalized, relative, posix, no trailing slash
    reason: str      # the repo's own words, copied verbatim into the report

    @property
    def parts(self):
        return PurePosixPath(self.path).parts

    def covers(self, rel):
        """True when `rel` (a path relative to the scan root) is inside this tree.

        Compared on PATH SEGMENTS, never as a string prefix: `frontend/scripts/drill`
        must not cover `frontend/scripts/drillbits`.
        """
        rel_parts = PurePosixPath(str(rel).replace(os.sep, "/")).parts
        return rel_parts[:len(self.parts)] == self.parts

    def label(self):
        return f'declared: {self.path} — "{self.reason}"'


@dataclass(frozen=True)
class Declarations:
    """Accepted declarations plus every problem the file produced.

    A problem is a sentence for the report, not an exception: a config file the scanner
    cannot read must never take the scan down with it, and must never be read
    optimistically either. Problems raise the check to `warning` and downgrade nothing.
    """

    accepted: tuple = ()
    problems: tuple = ()
    present: bool = False
    _by_path: dict = field(default_factory=dict, compare=False, repr=False)

    def covering(self, rel):
        """The first accepted declaration covering `rel`, or None."""
        for declaration in self.accepted:
            if declaration.covers(rel):
                return declaration
        return None


NONE = Declarations()


def load(root):
    """Read `<root>/deployhub.yaml` and return a `Declarations`.

    Never raises for anything the scanned repo controls — a malformed file, a wrong
    type, an unreadable byte sequence and a stale path are all findings.
    """
    root = Path(root)
    path = root / DECLARATION_FILE
    if not path.is_file():
        return NONE

    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        return Declarations(problems=(f"{DECLARATION_FILE} could not be read ({exc}); "
                                      f"no declaration was applied",), present=True)
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as exc:
        first = str(exc).splitlines()[0] if str(exc) else exc.__class__.__name__
        return Declarations(
            problems=(f"{DECLARATION_FILE} is not valid YAML ({first}); no declaration "
                      f"was applied",), present=True)

    if data is None:
        return Declarations(present=True)
    if not isinstance(data, dict):
        return Declarations(
            problems=(f"{DECLARATION_FILE} must be a mapping at the top level; no "
                      f"declaration was applied",), present=True)

    scanner_section = data.get("scanner")
    if scanner_section is None:
        return Declarations(present=True)
    if not isinstance(scanner_section, dict):
        return Declarations(
            problems=(f"{DECLARATION_FILE}: `scanner` must be a mapping; no declaration "
                      f"was applied",), present=True)

    entries = scanner_section.get("test_material")
    if entries is None:
        return Declarations(present=True)
    if not isinstance(entries, list):
        return Declarations(
            problems=(f"{DECLARATION_FILE}: `scanner.test_material` must be a list of "
                      f"path/reason entries; no declaration was applied",), present=True)

    accepted, problems = [], []
    for index, entry in enumerate(entries, 1):
        declaration, problem = _read_entry(root, index, entry)
        if problem:
            problems.append(problem)
        if declaration:
            accepted.append(declaration)
    return Declarations(accepted=tuple(accepted), problems=tuple(problems), present=True)


def _read_entry(root, index, entry):
    """(Declaration|None, problem|None) for one list entry. Whole-file structure is
    fatal to the whole file; a bad ENTRY costs only itself, so one typo does not
    silently drop a sibling declaration the reviewer approved."""
    where = f"{DECLARATION_FILE}: `scanner.test_material` entry {index}"
    if not isinstance(entry, dict):
        return None, f"{where} must be a mapping with `path` and `reason`; ignored"

    raw_path = entry.get("path")
    reason = entry.get("reason")
    if not isinstance(raw_path, str):
        return None, f"{where} has no string `path`; ignored"
    if not isinstance(reason, str) or not reason.strip():
        return None, (f"{where} ({raw_path!r}) has no `reason` — a downgrade with no "
                      f"stated reason is not reviewable; ignored")
    reason = reason.strip()

    candidate = raw_path.strip()
    normalized = candidate.rstrip("/")
    if candidate in _ROOTISH or normalized in _ROOTISH or not normalized:
        return None, (f"{where} declares the scan root ({raw_path!r}) — a declaration "
                      f"that swallows the whole repo is indistinguishable from hiding; "
                      f"rejected")
    if _GLOB_CHARS & set(normalized):
        return None, (f"{where} ({raw_path!r}) looks like a glob; a declaration names "
                      f"one directory, so the reviewer reads the same tree the scanner "
                      f"does; rejected")
    posix = PurePosixPath(normalized.replace(os.sep, "/"))
    if posix.is_absolute() or normalized.startswith("/") or ":" in posix.parts[0]:
        return None, (f"{where} ({raw_path!r}) is an absolute path; declarations are "
                      f"relative to the scan root; rejected")
    if ".." in posix.parts:
        return None, (f"{where} ({raw_path!r}) escapes the scan root with `..`; "
                      f"rejected")

    path = str(posix)
    target = root / posix
    if not target.is_dir():
        return None, (f"{where}: `{path}` does not exist in the scanned tree — a "
                      f"declaration that outlives its directory is a live claim nobody "
                      f"re-read; rejected as stale")

    found = _scanner_key_file_in(target)
    if found:
        return None, (f"{where}: `{path}` holds `{found}`, which the scanner keys on — "
                      f"a declaration around a project's own manifest hides production "
                      f"code from the check that reads it; rejected")
    return Declaration(path=path, reason=reason), None


def _scanner_key_file_in(directory):
    """The first `SCANNER_KEY_FILES` name inside `directory` (recursively), or None."""
    for current, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(d for d in dirnames if d not in _PRUNE_DIRS)
        for name in sorted(filenames):
            if name in SCANNER_KEY_FILES:
                rel = Path(current, name).relative_to(directory)
                return str(PurePosixPath(*rel.parts))
    return None
