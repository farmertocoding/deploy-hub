"""`deployhub.yaml` — what the scanned repo declares about itself.

PARKED 2026-08-16, per Joseph's round-6 cap decision
(`claude/decision-2026-08-16-round-6-cap.md`, Option A). This module is NOT WIRED INTO
ANY LIVE PATH in Phase 1: `scanner.core.scan` does not load it, the fallback suite does
not consult it, the wizard raises no confirm from it, and nothing downgrades anything.
Phase 1 ships with no declared-test-material mechanism at all; a repo that carries the
file is told so by the `core.declaration-file` presence notice and nothing else reads it.

It stays on master rather than being deleted, and the distinction is the whole of the
decision: the mechanism RETURNS as its own phase, with a threat model written FIRST, and
the six attack axes documented below — forged report lines, unicode line separators,
in-line label forgery, the settings-package guard, the parser's own resource limits, and
the content-keyed confirm id — are that threat model's FLOOR, not its ceiling. They were
found by three adversarial rounds against a real scanner; re-deriving them from scratch
would be the expensive way to learn the same six things. `tests/test_scanner_declarations.py`
keeps exercising the pure functions here so the parked code cannot rot, and
`conformance/paths.yaml` keeps listing this file: a parked authority file is still an
authority file, and the human-merge guard costs nothing while it sleeps.

Everything below describes the mechanism AS IT WAS WIRED, and is preserved as the record
of why each rule exists. Read it as a design document for the phase that re-introduces
this, not as a description of what Phase 1 does.

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
import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

import yaml

from scanner import presentation
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
#
# R15-SEC-1 moved the SET to `scanner/presentation.py`, and left this comment where it
# was written. The same class that refuses repo-controlled text here is the class a
# presentation layer must escape before handing repo-controlled text to a terminal — one
# set, two policies — and the ranges above are the documentation for both. What lives
# there is the data; what lives here is this rule and the reasons for it.
_CONTROL_CHARS_RE = re.compile(f"[{presentation.CONTROL_CLASS}]")
# ── ROUND 7 (R7-3): the forgery class, a third way in ──────────────────────────
#
# Rounds 1 and 2 closed the structure BETWEEN lines — a `reason` that writes lines of
# its own. This is the structure WITHIN one line. The evidence label packs four fields
# into one string with `[`, `]`, `"`, `—` and `:` as delimiters, and a reason of
#
#     fake creds"] hardcoded prod_master_key value — "see docs
#
# renders a line a reader takes for TWO findings:
#
#     drill/seed.py:1: [heuristic, declared: drill — "fake creds"] hardcoded
#     prod_master_key value — "see docs"] hardcoded admin_password value
#
# WHAT IS REFUSED IS THE ENCLOSURE CLOSERS, not "the label's delimiters", and the
# distinction is the whole design. The reason is rendered inside `"…"`, itself inside
# `[…]`. A character can only forge structure if it can END one of those enclosures:
# `"` closes the quoted region, `]` closes the bracket. The em dash, the colon and the
# comma are delimiters too and none of them can end anything — which is why a reason may
# still contain them, and it must: `red-team drill — deliberate fake credentials` is
# exactly how a person writes this field, and refusing it would be the noise-for-safety
# trade round-6b already lost. A lone `[` closes nothing either, so `[see docs]` is
# refused only for its `]`.
#
# BOTH FIELDS, because `path` is repo-controlled text as surely as `reason` is: a real
# directory may be named `drill" — "covers everything` on every filesystem this runs on,
# and it is rendered into the same label ahead of the reason. Fixing one field and not
# the other is this codebase's recurring defect written small. (The `]` half of the path
# attack was already closed by accident — `]` is a glob character — and accident is not
# a defense you can cite.)
#
# WHY THIS IS NOT THE ENUMERATION THAT FAILED TWICE, which is the objection to answer:
# it is not a list of characters that looked dangerous, it is the closer set of the
# enclosures the label actually uses, and
# `test_issue_r7_3_the_labels_structural_characters_are_frozen` freezes the label's
# punctuation against this constant. Add a delimiter to `Declaration.label()` and that
# test goes red, putting the author in front of the one question that matters: can a
# repo-controlled field close the new enclosure? The refusal set cannot silently fall
# behind the format, because the format cannot change quietly.
#
# REFUSAL, NOT ESCAPING, on the round-1 ground: escaping would let the text through in a
# repaired form, and `repr`-style escaping does not even close this — `repr` escapes the
# quote it chose as its own delimiter and never escapes `]`, so a `]` would still reach
# the label. A reason needs neither character.
LABEL_ENCLOSURE_CLOSERS = ('"', "]")

# A cap, because length is the other way to edit the report: the findings count sits at
# the END of the header line, and a wall of prose in front of it buries the number the
# reader came for.
MAX_REASON_CHARS = 200
# ROUND 7 (R7-10): and COUNT is the third way. ~3000 entries fit under the byte cap
# below, which buys 3000 header lines and — the worse half — 3000 wizard confirms, each
# of which must be answered `True` for anything to be accepted. A question list nobody
# reads to the end is a question list answered without reading, which is the one thing
# the acceptance gate cannot survive.
#
# The cap is on ENTRIES READ rather than on entries accepted, and that is deliberate:
# 3000 REFUSED entries build the identical wall out of problem lines, so a cap on the
# accepted list alone would close one door and leave the other open — this codebase's
# recurring defect again. Entries past the cap are not read at all, so nothing under
# them is downgraded; the overflow fails toward blocking, which is the safe direction.
MAX_DECLARATIONS = 50
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
#   settings.py              django's settings discovery — the LITERAL name only, which
#                            is why `_settings_package_file_in` exists beside this set
#                            (R7-4): a name set cannot express "any *.py in a directory
#                            called settings", and that is the layout the whole fleet has
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
    # R7-15: `_by_path` used to sit here — declared, written by nothing, read by
    # nothing, and it survived three adversarial rounds looking like a lookup somebody
    # relied on. A test freezes this field list now, because the cost of a dead field on
    # a security record is that the next reader assumes it is load-bearing.

    def covering(self, rel):
        """The first accepted declaration covering `rel`, or None."""
        for declaration in self.accepted:
            if declaration.covers(rel):
                return declaration
        return None


NONE = Declarations()


# ── the confirm: the operator's half of the bargain (R7-14) ────────────────────

CONFIRM_ID_PREFIX = "scanner.test_material."

# ROUND 7, SECOND VETO — an acceptance is of a CLAIM, not of a slot.
#
# The first remedy keyed this id on `(index, slug(path))`, and a stored answer is never
# invalidated by a re-scan, so the operator's `True` was locked to a POSITION. Two
# attacks came out of that, both demonstrated end to end against a real database:
#
#   * REASON SWAP. Accept `frontend/scripts/drill` for "deliberate fake credentials";
#     the repo then rewrites the reason to "ACTUALLY covers prod secrets now", same
#     path, same index, and re-scans. Same id, stale `True` still matches, preflight
#     clears, and the manifest freezes the NEW reason as accepted. `_read_entry` refuses
#     an entry with no reason on the stated ground that "a downgrade with no stated
#     reason is not reviewable" — a reason that is mutable underneath a granted
#     acceptance is worth less than no reason at all, because it comes with a signature
#     on it.
#   * INDEX ROUND-TRIP. Prepend a declaration and drill moves to index 2, which
#     correctly re-blocks; remove it again and drill returns to index 1, where the
#     orphaned `True` was still sitting, and clears with no re-confirmation.
#
# So the id is keyed on the declaration's CONTENT and on nothing else. Any edit to the
# path or the reason yields an id nobody has answered, `missing_required` fires, and the
# fail-closed machinery that is already proven re-blocks.
#
# THE INDEX IS GONE FROM THE ID, and that is what closes the second attack rather than
# merely surviving it. An index is a SLOT, and a slot is something an answer can be left
# lying in: while position was part of the key, the round trip ended on the id it started
# on and the orphan re-applied, so the only thing that could have stopped it was the
# hygiene sweep in `wizard.service` running at the right moment — and a sweep that has to
# run between two events to prevent a downgrade IS the security boundary, which the
# ordering below says it must never be. With content-only keys there is no old slot to
# come back to: moving a declaration does not change the question, because moving it does
# not change what is being asked, and the acceptance the operator gave still answers it.
# What changes the question is changing the claim.
#
# The index was only ever there to keep two paths that slug alike apart, and the digest
# does that far better — it is taken over the FULL path, not the lossy slug. Two entries
# with an identical path AND an identical reason now collapse to one id, which is right:
# that is one claim written twice, and asking the operator the same question twice is how
# you teach them to click through it.
#
# SIXTEEN HEX CHARACTERS (64 bits), and the length is not a birthday-bound argument.
# The attacker here CONTROLS BOTH INPUTS and is aiming at one specific stored id, so
# the work is a second preimage — 2^n, not 2^(n/2). At 32 bits that is ~4e9 hashes, a
# few minutes on a laptop, and the attacker can pad a plausible-sounding reason freely
# while grinding; 64 bits puts it out of reach of anyone who would bother. The full
# digest is not used because this id is READ BY THE OPERATOR in the wizard and in the
# refusal, and it must fit `WizardAnswer.question_id`, a CharField(max_length=128).
_CONFIRM_DIGEST_CHARS = 16
# Budget for the rest of the id: prefix (22) + slug + "--" + digest (16) = 40 + slug.
# The path is repo-controlled, so the slug is the only unbounded part and it is capped
# here, well inside `WizardAnswer.question_id`'s CharField(max_length=128). Truncating it
# is safe ONLY because the digest is taken over the full path and reason: two paths that
# truncate alike still get different ids, which is asserted by a test.
_MAX_SLUG_CHARS = 72


def confirm_question_id(path, reason):
    """The confirm id for the accepted declaration `(path, reason)`.

    The id carries a SLUG, never the raw path, for one specific reason:
    `wizard.materialize._env_name` turns any question id containing `.env.` into an
    environment variable name, and a declared path is text the scanned repo controls —
    `docker/.env.d` would otherwise turn a confirm into an env var. The slug is
    non-alphanumerics collapsed to `-`, so it can hold no dot at all.

    THE DIGEST IS JOINED WITH `--`, NOT WITH A DOT, and that is the whole of why this
    function did not reopen the hole it exists to close. A repo with a real directory
    called `env` slugs to `env`; appending the digest as a new dot segment would produce
    `scanner.test_material.env.<digest>`, which contains `.env.`, and `_env_name` would
    have turned the digest into an environment variable name. `--` cannot occur inside a
    slug — runs of non-alphanumerics collapse to a single `-` — so it is an unambiguous
    separator that leaves the id's dot structure exactly as it was.

    Round 7 made this a public function because three call sites need the SAME id: the
    question the wizard asks, the `acceptance.questions` a blocker check publishes, and
    the manifest record `materialize` builds from the answer. Recomputed independently
    they would agree until the day they did not, and the day they did not the gate would
    open for a question nobody was asked.

    `path` and `reason` are the NORMALIZED values `_read_entry` produced — posix, no
    trailing slash, reason stripped — so the id is stable across the cosmetic
    differences a YAML file can carry, and moves for the ones a reviewer would notice.
    A re-scan that finds the same claim asks the same question and keeps its answer;
    that is not laxity, it is the property that stops every re-scan re-asking an
    identical question until the operator answers it without reading it.
    """
    slug = re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-").lower()[:_MAX_SLUG_CHARS]
    digest = hashlib.sha256(
        f"{path}\n{reason}".encode("utf-8")
    ).hexdigest()[:_CONFIRM_DIGEST_CHARS]
    return f"{CONFIRM_ID_PREFIX}{slug}--{digest}"


def confirm_questions(declared):
    """One confirm per accepted declaration, in declaration order.

    `default=None` is load-bearing and R7-11 is why it is now pinned by a test: an
    unanswered claim is not an accepted one, the whole acceptance gate rests on that,
    and a client that submits the defaults it was handed would pre-accept every
    declaration in the file if this ever became `True`.

    De-duplicated by id, which since the id became content-keyed means de-duplicated by
    CLAIM: a file that declares the same path with the same reason twice is one claim
    written twice, and the wizard asks about it once. Two entries for the same path with
    DIFFERENT reasons stay two questions — they are two claims, and only the first of
    them will ever be credited with a finding (`Declarations.covering` takes the first
    match), so the second is asked about and recorded but gates nothing.
    """
    questions, seen = [], set()
    for declaration in declared.accepted:
        qid = confirm_question_id(declaration.path, declaration.reason)
        if qid in seen:
            continue
        seen.add(qid)
        questions.append(WizardQuestion(
            id=qid,
            kind="bool",
            default=None,
            prompt=(f"This repo declares `{declaration.path}` as test material — "
                    f'"{declaration.reason}". Accept that claim? Until you do, the '
                    f"heuristic secret findings under that path BLOCK the deploy like "
                    f"any other; accepting reports them without blocking. Published "
                    f"credential formats and .env files there block either way; "
                    f"refusing is recorded in the manifest, and editing the path or the "
                    f"reason brings this question back."),
        ))
    return questions


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
    except RecursionError:
        # R7-5, and the finding is that this function's own docstring — "never raises for
        # anything the scanned repo controls" — was a promise nothing kept.
        # A BYTE CAP IS NOT A DEPTH CAP: `yaml.safe_load` descends once per opening
        # bracket, so 100k `[` characters — 100 KB, comfortably inside the 256 KB limit
        # that is supposed to bound this input — exhausted the interpreter's stack and
        # threw a `RecursionError` out of `load`, out of `scan`, and onto the operator's
        # terminal as a traceback. `yaml.YAMLError` never sees it: nothing about the
        # document is invalid, the parser simply cannot reach the bottom of it.
        #
        # Caught by name rather than by widening to `Exception`, because a promise that
        # nothing the scanned repo controls can raise must not become a promise that no
        # BUG in this module can surface either. The recursion is bounded by CPython and
        # is a property of the input; a KeyError here would be a property of this code.
        return Declarations(
            problems=(f"{DECLARATION_FILE} is nested too deeply to parse (the parser ran "
                      f"out of stack; the {MAX_DECLARATION_BYTES}-byte limit bounds the "
                      f"file's SIZE, not its depth); no declaration was applied",),
            present=True)

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
    if len(entries) > MAX_DECLARATIONS:
        # R7-10. One problem line naming the count, and then the tail is not read at
        # all — see `MAX_DECLARATIONS` for why the cap counts entries rather than
        # acceptances. The overflow is not downgraded, so a repo cannot buy silence by
        # padding the list.
        problems.append(
            f"{DECLARATION_FILE}: `scanner.test_material` has {len(entries)} entries; "
            f"the limit is {MAX_DECLARATIONS} — a list that long is a wall of header "
            f"lines and confirms nobody reads to the end; only the first "
            f"{MAX_DECLARATIONS} were read, and nothing under the rest is downgraded")
        entries = entries[:MAX_DECLARATIONS]
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
        # R7-3: the same rule one dimension in — a value that can close the enclosure it
        # is printed inside forges a SECOND FINDING on a line of the scanner's own. The
        # offending character is named by code point and offset and the value is not
        # quoted, for the reason the block above gives: an escaped copy of a forged
        # finding is still a forged finding sitting where a reader greps for one.
        # The refusal deliberately does not SPELL the label's template either: a message
        # carrying `[heuristic, declared: …` is one more line in the report that greps
        # like a finding.
        for closer in LABEL_ENCLOSURE_CLOSERS:
            at = value.find(closer)
            if at >= 0:
                return None, (
                    f"{where} has a `{field_name}` containing {closer!r} "
                    f"(U+{ord(closer):04X} at offset {at} of {len(value)} characters; "
                    f"the value is not quoted here on purpose) — the evidence label "
                    f"prints this field inside a quoted region inside a bracketed "
                    f"marker, and either character closes one of those early, so the "
                    f"rest of the field is read as a second finding the scanner never "
                    f"made; rejected rather than repaired")
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
    settings_file = _settings_package_file_in(target)
    if settings_file:
        return None, (f"{where}: `{path}` holds `{settings_file}`, which django reads as "
                      f"a settings module — a declaration around a project's own "
                      f"settings hides production configuration from the check that "
                      f"reads it; rejected")
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


def _settings_package_file_in(directory):
    """The first file under `directory` that django reads as a settings module, or None.

    R7-4, and the finding is a DRIFT finding: `SCANNER_KEY_FILES` recognized the literal
    name `settings.py`, and not one repo in the fleet has one. They all carry a settings
    PACKAGE — `config/settings/base.py`, `prod.py` — which `django._settings_files`
    discovers by the PARENT DIRECTORY's name. So `backend/config` was an accepted
    declaration and a heuristic secret beside `base.py` was downgraded by a file the
    scanned repo writes. A guard whose authority does not match the discovery rule it
    guards is not guarding it.

    DERIVED FROM DJANGO'S OWN PREDICATE rather than restated here, which is the N6/N7
    lesson applied to the thing that just demonstrated it: two copies of a rule drift,
    and this finding IS that drift. `django.is_settings_module` is the single rule; this
    walks a declared tree asking it. Imported lazily because `scanner.modules.django`
    imports `fallbacks`, which imports this module — the same shape, and the same
    reason, as `guard_prune_dirs`.

    The `.py` requirement is django's, not an addition here, and it is what keeps this
    from becoming round-6b's classify-by-name mistake in a new costume: a drill tree with
    a `settings/keymap.json` in it is not a settings package, and django would read
    nothing there. A bare `settings/__init__.py` is likewise not one — django excludes
    it, so this does too, because it is the same line of code.
    """
    from scanner.modules.django import is_settings_module

    prune = guard_prune_dirs()
    for current, dirnames, filenames in os.walk(directory):
        dirnames[:] = sorted(d for d in dirnames if d not in prune)
        for name in sorted(filenames):
            candidate = Path(current, name)
            if is_settings_module(candidate):
                rel = candidate.relative_to(directory)
                return str(PurePosixPath(*rel.parts))
    return None
