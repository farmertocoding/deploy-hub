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

This module is PARSING AND VALIDATION ONLY plus the confirm it raises. It changes no
tier and reads no source file: `fallbacks._check_secret_scan` decides what a declaration
does, and does it to one axis (the N6 rule — scope the axis, never the walk).

ROUND 7 (R7-1), and it is the reason the confirm now lives here rather than in
`scanner/core.py`: a declaration is a REQUEST, and the confirm is the only thing that
grants it. Its id, its prompt copy and the `_env_name` defense behind its slug scheme
are rules about a declaration, so they belong beside the rules that accepted it — D-010
made core the composer, not the author of every string in the report. `core.scan` calls
`confirm_questions` and extends; `fallbacks` calls `confirm_question_id` so the id the
gate opens for is derived once, in one place, and cannot drift from the id the operator
was actually asked about.
"""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

import yaml

from scanner.core import WizardQuestion

DECLARATION_FILE = "deployhub.yaml"

# ── adversarial round 1: THE REPORT IS PART OF THE ATTACK SURFACE ───────────────
#
# `reason` and `path` come from the scanned repo and are printed into the check detail
# — the header, every `[heuristic, declared: …]` label — and into the wizard prompt.
# Until this round they were printed verbatim, newlines included, so a repo author could
# write whole lines into the evidence a reviewer reads to decide whether a deploy is
# safe. Demonstrated: a reason of
#
#     drill scripts"\n\nAlso in test material (not blocking):\nsrc/app.py:1: [heuristic] …
#
# produced a fake section header and a fake finding in the report, at warning tier.
#
# The rule is refuse, never repair. Text that will be read as the justification for
# hiding findings is exactly what was written or it is rejected — a collapsed forgery is
# still a claim nobody wrote, and it would be printed as if somebody had.
# ROUND 2 WIDENED THIS CLASS, because round 1 defined it by what looks like a control
# character in ASCII and the forgery reopened one code point up. The class is defined by
# what a RENDERER treats as structure, not by what YAML admits:
#
#   * `str.splitlines` — which builds every line of this report — breaks on U+2028,
#     U+2029 and U+0085 as well as on C0. `[\x00-\x1f\x7f]` contained none of them;
#   * a browser rendering the `--json` output breaks on U+2028/U+2029 too: they are JS
#     LineTerminators, and the CLI dumps with `ensure_ascii=False`, so nothing between
#     this validator and the browser will escape them;
#   * PyYAML's reader refuses most of C1 as non-printable, which hid the gap — U+0085
#     is the one it admits, so C1 is refused HERE rather than left to a dependency's
#     idea of printable.
#
# The second family is not about lines but about appearance: bidi overrides (U+202A-E,
# U+200E/F) reverse rendered order and zero-width code points (U+200B-D, U+2060-4,
# U+FEFF) render as nothing, so a reason can read `drill scripts` on screen while the
# bytes say something else. A justification nobody can read accurately is not reviewable,
# which is the whole purpose of the field.
#
# Ordinary non-ASCII text is untouched and must stay that way: this fleet is Taiwanese
# and reasons will be written in Chinese. Refusing code points that lie about structure
# is not refusing a script.
#
# WHERE THE LINE IS DRAWN, and it is drawn deliberately short of "everything invisible":
# some code points render as blank yet are LETTERS or format characters belonging to a
# script — Hangul fillers U+115F, U+3164 and U+FFA0 (category Lo), soft hyphen U+00AD.
# They are NOT refused here. "Renders as nothing" is not "is a control character", and a
# rule built on the first phrasing ends up refusing scripts, which is round-6b's mistake
# in a new costume. What is refused is the set that rewrites LINES (the report is built
# line by line) or reorders them (bidi), because those forge the scanner's own output;
# a blank-looking letter in a reason is only a badly written reason.
_CONTROL_CHARS_RE = re.compile(
    "["
    "\\x00-\\x1f"        # C0
    "\\x7f"              # DEL
    "\\x80-\\x9f"        # C1, incl. U+0085 NEL - the one PyYAML lets through
    "\\u2028\\u2029"      # LINE / PARAGRAPH SEPARATOR
    "\\u200b-\\u200f"     # zero-width space/joiners + LRM/RLM
    "\\u202a-\\u202e"     # bidi embeddings and overrides
    "\\u2066-\\u2069"     # bidi ISOLATES - the Trojan-Source family (CVE-2021-42574)
    "\\u061c"            # ARABIC LETTER MARK
    "\\u2060-\\u2064"     # word joiner + invisible operators
    "\\ufeff"            # BOM / zero-width no-break space
    "]"
)
# A cap, because length is the other way to edit the report: the findings count sits at
# the END of the header line, and a wall of prose in front of it buries the number the
# reader came for.
MAX_REASON_CHARS = 200
# A config file bigger than this is not a config file. `load` used to read it unbounded,
# so a repo could hand the scanner a gigabyte of YAML to parse.
MAX_DECLARATION_BYTES = 256 * 1024
# How much repo-controlled text a REFUSAL may quote back, and it is quoted with `repr`
# so a control character shows up as an escape rather than acting on the terminal.
_QUOTE_LIMIT = 80

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

def guard_prune_dirs():
    """Directory names the manifest guard may skip — DERIVED, never a private copy.

    Adversarial round 1, and it is the N6 class one layer in: the first cut kept its own
    list here, which pruned `vendor`, `.hg` and `.svn` while `fallbacks._iter_files`
    does not. So `svc/vendor/package.json` was invisible to this guard, the declaration
    of `svc` was accepted, and `svc/**` was downgraded — a guard that skips a directory
    the check still READS is a guard with a hole in it.

    Deriving it from the walk's own skip set makes the safe direction structural: this
    may only skip what the secret scan already refuses to open. Imported lazily because
    `fallbacks` imports this module; a test asserts the subset property directly.
    """
    from scanner.modules import fallbacks

    return frozenset(fallbacks._SKIP_DIRS)

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


# ── the confirm: the operator's half of the bargain (R7-14) ────────────────────

CONFIRM_ID_PREFIX = "scanner.test_material."


def confirm_question_id(index, path):
    """The confirm id for the `index`-th (1-based) accepted declaration of `path`.

    The id carries an INDEX and a slug, never the raw path, for one specific reason:
    `wizard.materialize._env_name` turns any question id containing `.env.` into an
    environment variable name, and a declared path is text the scanned repo controls —
    `docker/.env.d` would otherwise turn a confirm into an env var. The slug is
    non-alphanumerics collapsed to `-`, so it can hold no dot at all; the index keeps
    two paths that slug alike apart, and the scan draft's `declared_test_material` list
    is in the same order, so an answer is always resolvable to its path.

    Round 7 made this a public function because three call sites now need the SAME id:
    the question the wizard asks, the `acceptance.questions` a blocker check publishes,
    and the manifest record `materialize` builds from the answer. Recomputed
    independently they would agree until the day they did not, and the day they did not
    the gate would open for a question nobody was asked.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-").lower()
    return f"{CONFIRM_ID_PREFIX}{index}.{slug}"


def confirm_questions(declared):
    """One confirm per accepted declaration, in declaration order.

    `default=None` is load-bearing and R7-11 is why it is now pinned by a test: an
    unanswered claim is not an accepted one, the whole acceptance gate rests on that,
    and a client that submits the defaults it was handed would pre-accept every
    declaration in the file if this ever became `True`.
    """
    return [
        WizardQuestion(
            id=confirm_question_id(index, declaration.path),
            kind="bool",
            default=None,
            prompt=(f"This repo declares `{declaration.path}` as test material — "
                    f'"{declaration.reason}". Accept that claim? Until you do, the '
                    f"heuristic secret findings under that path BLOCK the deploy like "
                    f"any other; accepting reports them without blocking. Published "
                    f"credential formats and .env files there block either way, and "
                    f"refusing is recorded in the manifest."),
        )
        for index, declaration in enumerate(declared.accepted, 1)
    ]


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
        size = path.stat().st_size
    except OSError as exc:
        return Declarations(problems=(f"{DECLARATION_FILE} could not be read ({exc}); "
                                      f"no declaration was applied",), present=True)
    if size > MAX_DECLARATION_BYTES:
        # Refused BEFORE the parser sees it: `yaml.safe_load` on repo-controlled input
        # of unbounded size is the scan's cheapest denial of service.
        return Declarations(
            problems=(f"{DECLARATION_FILE} is too large ({size} bytes; the limit is "
                      f"{MAX_DECLARATION_BYTES}) — a config file that size is not a "
                      f"config file; it was not parsed and no declaration was applied",),
            present=True)

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
        return None, (f"{where} ({_quote(raw_path)}) has no `reason` — a downgrade with "
                      f"no stated reason is not reviewable; ignored")

    # Checked on the RAW strings, before any stripping: a leading newline would be
    # stripped away and the forgery with it, which would be a validator that hides the
    # very thing it exists to catch. The refusal names the entry and quotes at most
    # `_QUOTE_LIMIT` characters through `repr`, so the attacker's text can never reach
    # the report as text — that is the point of the whole rule.
    for field_name, value in (("path", raw_path), ("reason", reason)):
        hit = _CONTROL_CHARS_RE.search(value)
        if hit:
            # NOTHING of the offending value is quoted, not even escaped: the value is
            # by definition text crafted to be read as something it is not, and an
            # escaped copy of a forged section header is still a forged section header
            # sitting in the report where a reader greps for one. The coordinates —
            # entry, field, offset, codepoint — are what a maintainer needs to fix it,
            # and they cannot be authored.
            return None, (
                f"{where} has a control character in its `{field_name}` "
                f"(U+{ord(hit.group()):04X} at offset {hit.start()} of "
                f"{len(value)} characters; the value is not quoted here on purpose) — "
                f"the report prints this text as evidence, and a line break, a tab or a "
                f"bidi override in it writes or reorders lines a reviewer would read as "
                f"the scanner's own findings; rejected rather than repaired")
        # The belt, and it is not redundant: `splitlines` recognizes more separators
        # than any character class somebody remembered to write down (\x0b, \x0c,
        # \x1c-\x1e among them), and it is the function that actually builds this
        # report's lines. If the class above ever drifts behind CPython, this still
        # catches the only thing that matters — a value that occupies two lines.
        if value and value.splitlines() != [value]:
            return None, (
                f"{where} has a `{field_name}` that spans more than one line as Python "
                f"reads it (the value is not quoted here on purpose) — the report is "
                f"built line by line, so a multi-line value writes lines of its own; "
                f"rejected rather than repaired")
    if len(reason) > MAX_REASON_CHARS:
        return None, (f"{where} ({_quote(raw_path)}) has a `reason` of {len(reason)} "
                      f"characters; the limit is {MAX_REASON_CHARS} — the findings "
                      f"count is printed after the reason, and a wall of text buries "
                      f"it; rejected")
    reason = reason.strip()

    candidate = raw_path.strip()
    normalized = candidate.rstrip("/")
    if candidate in _ROOTISH or normalized in _ROOTISH or not normalized:
        return None, (f"{where} declares the scan root ({_quote(raw_path)}) — a "
                      f"declaration that swallows the whole repo is indistinguishable "
                      f"from hiding; rejected")
    if _GLOB_CHARS & set(normalized):
        return None, (f"{where} ({_quote(raw_path)}) looks like a glob; a declaration "
                      f"names one directory, so the reviewer reads the same tree the "
                      f"scanner does; rejected")
    posix = PurePosixPath(normalized.replace(os.sep, "/"))
    if posix.is_absolute() or normalized.startswith("/") or ":" in posix.parts[0]:
        return None, (f"{where} ({_quote(raw_path)}) is an absolute path; declarations "
                      f"are relative to the scan root; rejected")
    if ".." in posix.parts:
        return None, (f"{where} ({_quote(raw_path)}) escapes the scan root with `..`; "
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


def _quote(text):
    """Repo-controlled text, safe to print in a REFUSAL.

    `repr` turns a newline into `\\n` and `\\x7f` into an escape, so a rejected string
    cannot forge a line in the very message that rejects it; the truncation stops a
    megabyte-long `path` from becoming the report.
    """
    if not isinstance(text, str):
        return repr(text)[:_QUOTE_LIMIT]
    if len(text) > _QUOTE_LIMIT:
        return repr(text[:_QUOTE_LIMIT]) + " (truncated)"
    return repr(text)


def _scanner_key_file_in(directory):
    """The first `SCANNER_KEY_FILES` name inside `directory` (recursively), or None."""
    prune = guard_prune_dirs()
    for current, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(d for d in dirnames if d not in prune)
        for name in sorted(filenames):
            if name in SCANNER_KEY_FILES:
                rel = Path(current, name).relative_to(directory)
                return str(PurePosixPath(*rel.parts))
    return None
