"""How a `CheckResult` is presented — declared once, for every medium that renders one.

R15-ARCH-1. `hub/__main__.py::render_text` and `frontend/src/Readiness.jsx::CheckBody`
are two renderers of one object, and they were maintained by hand against each other.
Four filings in three rounds came out of the gap between them: the refusal list rendered
in one and not the other (R12-ARCH-1), then rendered in one and truncated in the other
(R14-ARCH-A), the fix hint gated to two tiers on one side and no tiers on the other, and
the refusal label typed separately in each. Every one of them is the same defect — a
presentation decision made twice — and the answer to a fact spelled twice is one spelling.

WHAT THIS MODULE DECLARES, and it is deliberately the MODEL rather than the pixels:

  * `CHECK_FIELDS` — which fields of a check are rendered, in what order, under what
    label, and what kind of value each is (prose that may contain the server's own
    newlines, or a list of repo-controlled paths);
  * `TIER_GATES` — which of those fields are hidden at which tiers. It is empty, and that
    emptiness is a decision this module records rather than an absence (see below);
  * `TEXT_INDENT` — the continuation indent the text medium owes a multi-line value;
  * the control-character class and the two sanitizers over it, because repo-controlled
    text reaching a terminal is a security boundary and not a formatting question.

HOW a paragraph wraps, what colour a label is, whether a list is `<li>` or an indented
line — those stay with each renderer. The line is: if the two media could DISAGREE ABOUT
WHAT THE REPORT SAYS, it belongs here; if they merely look different, it does not.

── THE BOUNDARY RULE (R16-SEC-1), stated so it is inherited rather than remembered ──

EVERY STRING A REPORT CARRIES IS UNTRUSTED, and the boundary is "repo-controlled text
reaching a device", not "the fields somebody listed". R15-SEC-1 drew it around the check
BODY, and the next title to interpolate a repository's own string walked through it — a
monorepo service directory named `svc\x1b]0;PWNED\x07\x1b[2Jx` cleared the operator's
screen from a HEADING line, in a field no sanitizer had been pointed at.

So the text renderer sanitizes at its SEAM: `render_text` returns
`safe_text("\n".join(lines))`, and a new field, heading or summary line is safe because
of where it is printed. The per-field calls stay, and the one thing they buy is the one
thing the seam cannot: `safe_text` keeps `\n` because the renderer's own line breaks are
structure, so a path carrying a newline has to be escaped BEFORE it becomes a line of a
list. Prose and paths are different policies; everything else is a backstop.

WHERE THE AUTHORITY REACHES (R18-ARCH-1 / R19-ARCH-1 / dom-bidi-display), so the list is a
fact rather than a memory. Five exits carry text to something that acts on it, and all five
enforce `CONTROL_CLASS` from here:

  * CLI TEXT — `hub/__main__.py::render_text`, escaped for DISPLAY at its seam;
  * CLI JSON — `--json`, through `json_safe`, escaped for a PARSER;
  * API JSON — `hub/renderers.py::ContainedJSONRenderer`, registered once in
    `DEFAULT_RENDERER_CLASSES`, through `json_safe`. A JSON API's consumers are terminals
    at least as often as they are parsers, and it had no treatment at all until R18-SEC-1:
    U+009B and the bidi overrides went out in the response bytes. R19-SEC-1 then found
    that a lone surrogate 500'd it — the escape has to happen on the STRING, before the
    encode, which is why that renderer replicates DRF's body instead of calling it;
  * WS JSON — `realtime/consumers.py::_ws_json`, through `json_safe`. A socket frame is
    read by a DevTools inspector and a proxy log; it was safe only by `json.dumps`'
    `ensure_ascii=True` default until R19-ARCH-1 made the class a rule there too;
  * DOM DISPLAY — `frontend/src/safe-display.js::safePath`/`safeText`, run at render time
    in `CheckBody` and on the check title. React escapes MARKUP, so a C0/C1 control is
    inert in a text node — but the API's escaping is data-preserving, so `JSON.parse`
    recovers a bidi override (U+202E, the isolates) or a zero-width code point and the
    browser REORDERS or HIDES the display of a repo-controlled filename. That is the
    fifth exit, closed on the `dom-bidi-display` branch (round 20). It makes the class
    VISIBLE in the same spelling as the other exits — isolation (`unicode-bidi: isolate`)
    was rejected because it does not neutralise an explicit RLO/isolate INSIDE the string
    (CVE-2021-42574) — and its class comes from `CONTROL_CLASS`/`TEXT_CONTROL_CLASS`,
    generated into `frontend/src/api/presentation.js`, so it is not a second hand-written
    copy of the range list.

A sixth exit is a sixth entry here, and the rule above says where its escaping goes.

ALL FIVE EXITS ARE NOW COVERED. Ordinary CJK and RTL-SCRIPT letters are untouched at every
one — the class is the format/control set, not scripts, so an Arabic or Chinese filename
renders as its letters. The one thing this authority still does not do is anything about
markup or scripting, which is not its job: React handles HTML escaping, and the scanner
executes nothing.

WHAT THE CLASS CONTAINS is stated at the constant below, and R21-ARCH-2 is why that
sentence is worth reading twice: "all five exits are covered" says nothing about WHICH
code points, and the class had the bidi and zero-width families and stopped there while
a second set of invisible non-letters — the Mongolian vowel separator, the deprecated
format controls, the interlinear annotation marks, the variation selectors and the tag
characters — rendered as nothing at all five of them. Coverage is two claims, and this
module makes both: every exit, and every code point that lies about what is on the screen.

AND THAT ROUND LEFT ONE, disclosed rather than closed, which is what this paragraph is
for: it added the variation selectors U+FE00-FE0F and not the variation selectors
SUPPLEMENT U+E0100-E01EF, because its spec named exactly the ranges it named. Those are
the same characters — same series, same category Mn, same default-ignorable property,
240 instead of 16 — so the class had sixteen of one family and none of the other while
claiming to be the set of code points that render as nothing. The supplement is in the
class now, and the deliberate exclusions are unchanged and still argued in
`declarations.py`: soft hyphen U+00AD, the Hangul fillers U+115F / U+3164 / U+FFA0, and
the Mongolian free variation selectors U+180B-180D and U+180F. A blank-looking LETTER,
or a code point that belongs to a script's own spelling, is not a forgery.

WHY HERE. `scanner` owns `CheckResult`, and both consumers already depend on this package
— `hub/__main__` imports `scanner.core.scan`, the frontend's copy is generated from this
file. It imports nothing but `re` and `json` — stdlib both, so the CLI stays Django-free
(that module's own docstring promises it), and nothing in the live scan path imports it:
a report is data, and a medium is a medium.

THE FRONTEND DOES NOT RETYPE THIS. `scripts_dev/generate_presentation.py` writes
`frontend/src/api/presentation.js` from the declarations below, `make generate-client`
runs it, and `make check-generated` fails on a stale copy — the same mechanism, the same
gate and the same directory as the zod mirror. A hand-typed second copy is the disease
this module is the treatment for.
"""
import json
import re

# The one character both escape vocabularies are built out of, named because a literal
# backslash inside a doubled-backslash expression is unreadable and the next edit to
# these functions will be made by somebody counting them.
BACKSLASH = chr(92)

# ── the declared model ────────────────────────────────────────────────────────
#
# `title` is not here: both media render it as the check's own heading (a `<summary>`, a
# line beginning with the tier's icon), which is a container decision rather than a field
# in a body. `id`, `tier` and `execution` likewise.
CHECK_FIELDS = (
    {"key": "detail", "label": "", "kind": "prose"},
    {"key": "refused_paths", "label": "Did not read:", "kind": "paths"},
    {"key": "fix_hint", "label": "Fix:", "kind": "prose"},
)

# Fields hidden at some tiers. EMPTY, and R15-ARCH-1 decided it rather than found it:
# `render_text` used to print `fix_hint` only for `blocker` and `warning` while
# `CheckBody` printed it at every tier, so the CLI and the panel disagreed about what a
# check says. Both now render it everywhere, and the direction is the UI's because the
# gate was costing information nobody had decided to withhold:
#
#   * no `ok` check in this tree carries a `fix_hint` at all (measured: ten of ten on the
#     clean fixture), so the "noise on the happy path" the gate might have been for does
#     not exist;
#   * every `pending_sandbox` check carries one, and it is the WHY of a deferred job
#     ("lifecycle scripts are the §6.8 supply-chain surface", "builds execute project
#     code") — the CLI operator was the one person who could not read it;
#   * `advice` hints are remediation for findings the report chose not to block on, which
#     is exactly where a hint is the whole value.
#
# A future gate goes here, in one place, and applies to both media at once.
TIER_GATES = {}

# What the text medium owes a value containing the server's own newlines: every line
# after the first is indented to the first one's column, so a multi-line detail reads as
# one block under its check instead of falling back to column zero and looking like a new
# check. The DOM's equivalent is `white-space: pre-line` inside the check's own box, which
# is why this is a text-medium constant and not a shared one.
TEXT_INDENT = " " * 6

# ── the control-character class (R15-SEC-1) ───────────────────────────────────
#
# ONE SPELLING, and this is its home. `scanner/declarations.py` compiled this class to
# REFUSE repo-controlled text outright; the same class is what a presentation layer has to
# escape before handing repo-controlled text to a terminal. Same set, two policies, and
# the set is the thing that must not be written twice — the ranges and the reasoning for
# each of them are in `declarations.py` beside the refusal that first needed them
# (bidi overrides reorder rendered text, zero-width code points render as nothing, C0/C1
# rewrite lines), and that comment is the documentation for this constant too.
#
# `_TEXT` is the same class minus U+000A. A newline in a PATH forges a line of the
# report; a newline in a `detail` is the server's own paragraph break, which the text
# renderer indents and the DOM honours. That is the entire difference between the two
# sanitizers below.
_C0 = "\\x00-\\x1f"
_C0_EXCEPT_NEWLINE = "\\x00-\\x09\\x0b-\\x1f"
_BEYOND_C0 = (
    "\\x7f"              # DEL
    "\\x80-\\x9f"        # C1, incl. U+0085 NEL
    "\\u2028\\u2029"     # LINE / PARAGRAPH SEPARATOR
    "\\u200b-\\u200f"    # zero-width space/joiners + LRM/RLM
    "\\u202a-\\u202e"    # bidi embeddings and overrides
    "\\u2066-\\u2069"    # bidi ISOLATES — the Trojan-Source family (CVE-2021-42574)
    "\\u061c"            # ARABIC LETTER MARK
    "\\u2060-\\u2064"    # word joiner + invisible operators
    "\\ufeff"            # BOM / zero-width no-break space
    # R21-ARCH-2: the rest of the INVISIBLE NON-LETTERS, which the list above missed
    # while claiming completeness. Every one of these renders as nothing, so two names
    # differing only by one of them are one string on the screen — the exact defect
    # U+200B is in this class for, arriving under other numbers.
    "\\u180e"            # MONGOLIAN VOWEL SEPARATOR (Cf since Unicode 6.3)
    "\\u206a-\\u206f"    # deprecated format controls (shaping / digit shapes)
    "\\ufe00-\\ufe0f"    # VARIATION SELECTOR-1..16 (…-17..256 are astral, below)
    "\\ufff9-\\ufffb"    # interlinear annotation anchor / separator / terminator
)

# …and the TAG characters, the same rule one plane up: U+E0020-E007F mirror ASCII
# invisibly, so a filename can carry a whole second word nobody can see, and U+E0001
# LANGUAGE TAG is the deprecated introducer for them.
#
# Written with `chr` rather than as `\U000e0001` ESCAPE TEXT because this string is also
# the JavaScript class: `\U` is not a JS RegExp escape at all, while a literal character
# is one code point in both engines — Python's `re` natively, and the browser under the
# `u` flag R21-SEC-1 put on those regexes. `generate_presentation.py` carries it across as
# a `json.dumps` surrogate-pair escape, which is the same code point again.
#
# WHERE THE LINE IS (and it is the same line `declarations.py` drew): invisible non-letter
# format / default-ignorable IN, everything else OUT. Soft hyphen U+00AD and the Hangul
# fillers U+115F / U+3164 / U+FFA0 stay out — that exclusion is argued there and is not
# disturbed here — and so do the neighbours of every range above and below: the Mongolian
# free variation selectors U+180B-180D and U+180F, U+2070, U+FE10, U+FFFC, and the
# unassigned code points beside the tag block and either side of the supplement (U+E00FF,
# U+E01F0). `tests/test_cli_render.py` pins one neighbour per range as pass-through.
_TAG_CHARS = chr(0xE0001) + chr(0xE0020) + "-" + chr(0xE007F)

# …and the VARIATION SELECTORS SUPPLEMENT, which is the other astral family and the one
# R21-ARCH-2 disclosed and did not close. U+FE00-FE0F is in the class above because a
# variation selector is invisible: `a️b.ts` and `ab.ts` are two files and one string
# on a screen. U+E0100-E01EF ARE THOSE CHARACTERS — VARIATION SELECTOR-17 through -256,
# the same series continued one plane up, the same category Mn, the same
# Default_Ignorable_Code_Point — and 240 of them, so a name can carry more hidden state
# up here than down there. They were outside the class for one reason: the round that
# added U+FE00-FE0F was scoped to exactly the ranges it named.
#
# Literal characters rather than `\U000e0100` escape text, for the reason stated above
# the tag characters: this string is the JavaScript class too, and `\U` is not a JS
# RegExp escape.
#
# They are also the first members that are BOTH repr-declining (Mn is "printable") and
# astral, which is why `_escaped` stopped hand-writing a `\uXXXX` fallback and takes
# `ascii`'s spelling instead — a width is a fact about a plane, and this range is where
# the hand-written one became wrong. See that function's docstring.
_VARIATION_SELECTORS_SUPPLEMENT = chr(0xE0100) + "-" + chr(0xE01EF)

# R15-SEC-2: and the code points that are not characters at all.
#
# A POSIX filename is BYTES. `os.listdir` decodes them with `surrogateescape`, so any byte
# that is not valid UTF-8 comes back as a lone surrogate in U+DC80-DCFF — 0x9b becomes
# U+DC9B — and none of the ranges above describe them, because none of them describe a
# character: they describe a byte that could not be decoded. The scanner carries them
# faithfully, which is right. A terminal is where they have to stop.
#
# What they cost, end to end, through `python -m hub scan` over a repository carrying a
# symlink named `csi\x9bmark.ts`:
#
#   * with a STRICT stdout (the default when the locale says UTF-8):
#     `UnicodeEncodeError: 'utf-8' codec can't encode character '\udc9b'` — the scan
#     completes and the CLI dies printing it. A repository that can add one file can stop
#     the operator reading any report about itself, in text mode AND in `--json`;
#   * with `PYTHONIOENCODING=utf-8:surrogateescape`: the byte goes back out as itself, and
#     0x9b IS the 8-bit CSI — the C1 control the `\x80-\x9f` range above exists to escape,
#     arriving by the one route that range cannot see.
#
# The same class, one range wider. `_escaped` prints U+DC9B as `\udc9b`, which is the
# decoded spelling and maps back to the byte by subtracting 0xDC00 — so the operator can
# still name the file, which is the whole rule: refusal, not repair.
_SURROGATE_ESCAPES = "\\udc80-\\udcff"
CONTROL_CLASS = (_C0 + _BEYOND_C0 + _TAG_CHARS + _VARIATION_SELECTORS_SUPPLEMENT
                 + _SURROGATE_ESCAPES)
TEXT_CONTROL_CLASS = (_C0_EXCEPT_NEWLINE + _BEYOND_C0 + _TAG_CHARS
                      + _VARIATION_SELECTORS_SUPPLEMENT + _SURROGATE_ESCAPES)

_CONTROL_RE = re.compile(f"[{CONTROL_CLASS}]")
_TEXT_CONTROL_RE = re.compile(f"[{TEXT_CONTROL_CLASS}]")


def _escaped(match):
    """One offending code point, as the escape a person can read and retype.

    REFUSAL, NOT REPAIR, and the distinction matters here because the text IS the
    finding's name: a path called `\\x1b[2J.ts` is a real file with a real name, and an
    operator who has to go and delete it needs to be told what it is called. Stripping
    the byte would name a file that does not exist; passing it through would let the
    repository paint the terminal. So it is NAMED and never acted on — the same choice
    `declarations` made when it quoted a refused value's coordinates instead of the value,
    one step less severe because a check detail is not a section header.

    F16-1: and the spelling is PYTHON'S OWN, which is what makes it one spelling rather
    than a second one. The scanner composes prose about the same names — `_report_path`
    quotes a path that spans lines through `repr`, `_quote_pattern` does the same for a
    refused workspace pattern — so a filename could arrive in a check body twice, spelled
    `'src/two\nlines.ts'` by the scanner's prose and `src/two\x0alines.ts` by this
    module's list. One name, two escapes, in one panel.

    `repr` of a single character is exactly the escape a Python reader already knows, and
    for almost every code point in the class above it is an escape rather than the
    character itself — so taking it verbatim makes the two agree BY CONSTRUCTION rather
    than by two tables that match today. The outer quotes stay the scanner's business:
    they bound a name inside a sentence (R7-3), and a list that gives each name its own
    line or `<li>` has nothing to bound.

    ALMOST EVERY, and R21-ARCH-2 is the exception. `repr` escapes by PRINTABILITY, and
    `str.isprintable()` is a CATEGORY question rather than a visibility one: the variation
    selectors U+FE00-FE0F are category Mn, a mark, so they are "printable" and `repr`
    hands the character straight back. An escape that returns the character escapes
    nothing — the class member would go out to the terminal it was added to stop. R21
    handled that with an `if`: `repr`'s spelling, or a hand-written `\\uXXXX` when `repr`
    declined.

    THE FALLBACK IS GONE, and `ascii` is why (vss-supplement). That hand-written spelling
    was right only while every code point `repr` declines is BMP, and this branch adds the
    variation selectors SUPPLEMENT U+E0100-E01EF — the same characters as U+FE00-FE0F one
    plane up, the residual R21-ARCH-2 disclosed — which are category Mn AND astral. `repr`
    declines them, and `\\ue0100` names U+E010 followed by the digit `0`: a different
    file, silently, in the refusal list. The same code-unit-for-code-point confusion
    `_json_escaped` was fixed for, in the display vocabulary instead of JSON's.

    `ascii(char)` is `repr(char)` with every non-ASCII code point escaped as well — the
    SAME builtin vocabulary, one rule wider, and the width is Python's business rather
    than this module's: `\\xNN` below U+0100, `\\uXXXX` through U+FFFF, `\\UXXXXXXXX`
    above it. Over this class the two builtins are not merely compatible but identical
    wherever `repr` escapes at all (the class walk in `tests/test_cli_render.py` asserts
    that member by member, all 579 of them), so F16-1's agreement with the scanner's prose
    is unchanged and the 256 `repr` declines now get a spelling instead of a branch.

    A branch here was also the wrong shape for the problem: it made the code point's PLANE
    a fact this function had to know, which is exactly the fact that was wrong when the
    supplement arrived. `\\U000e0100` is byte-identical to what the DOM exit's
    `escapeMatch` computes, which `frontend/tests/safe-display.test.ts` pins from the other
    side, and every escape decodes back to the code point it names — the class walk does
    that too, so a mis-spelling cannot arrive silently.
    """
    return ascii(match.group())[1:-1]


def safe_path(value):
    r"""A repo-controlled PATH, safe to print on a line of its own, and INJECTIVE.

    Every control code point is escaped, newline included: the refusal list is one path
    per line, so a newline in a filename would forge an entry.

    QUALITY F-1: and the literal backslash is doubled FIRST, which is the rest of `repr`'s
    rule and the half adopting its vocabulary left behind. Without it the encoding is not
    injective — two different files produce one string:

        safe_path("two\\nlines.ts")   # a name containing backslash, n
        safe_path("two\nlines.ts")    # a name containing a newline
        # both -> two\nlines.ts

    An operator reading the refusal list cannot tell which file to go and delete, and the
    prose beside it (through the scanner's `repr`, which DOES double) said something
    different again: `'src/a\\b\nc.ts'` against `src/a\b\nc.ts` for one compound name.
    Doubling closes both halves — the encoding round-trips, and the two spellings agree.

    ORDER MATTERS: double, then escape. The other way round would double the backslashes
    this function has just written.
    """
    return _CONTROL_RE.sub(_escaped, value.replace(BACKSLASH, BACKSLASH * 2))


def safe_text(value):
    r"""Repo-controlled PROSE, safe to print, keeping the server's own line breaks.

    `detail` and `fix_hint` are composed by the scanner and legitimately multi-line —
    `core.secret-scan` sends fifteen `file:line` findings and two paragraphs of hint — but
    the file names inside them come from the repository, which is how R15-SEC-1's escape
    sequence arrived: a committed symlink named `\x1b]0;…\x07` reached the terminal raw,
    through the detail line and through the refusal list both.

    NOT INJECTIVE, AND DELIBERATELY NOT (QUALITY F-1). `safe_path` doubles literal
    backslashes so that one string names one file; this function must not, because it is
    applied TWICE BY DESIGN — once per prose field and once over the whole assembled
    output at `render_text`'s seam (R16-SEC-1) — and doubling is not idempotent: the
    second pass would turn the `\x1b` the first pass wrote into `\\x1b`.

    The two functions want different properties, and the difference is what each value IS.
    A path is a NAME: one string, one file, or the operator cannot act on it. Prose is
    TEXT for a device: it has to be neutralized, however many times it passes the
    boundary. The authoritative names are in `refused_paths`, spelled by `safe_path`.
    """
    return _TEXT_CONTROL_RE.sub(_escaped, value)


def _json_escaped(match):
    """One code point, as JSON's only escape for it: `\\uXXXX`, four hex digits.

    NOT `_escaped`'s spelling, and the difference is not cosmetic: `repr` writes U+009B as
    `\\x9b`, and `\\x` is not a JSON escape at all — a parser rejects it. Display and
    serialization are two media with two vocabularies, over ONE class.

    AND `\\uXXXX` NAMES A CODE UNIT, NOT A CODE POINT (R21-ARCH-2). The tag characters
    U+E0001/U+E0020-E007F are the first members of the class above U+FFFF, and the
    hand-written `f"{BACKSLASH}u{ord(char):04x}"` that used to stand here spelled U+E0041
    `\\ue0041` — which a parser reads as U+E004 followed by the digit `1`. A different
    string, silently, in `--json`, in the API body and in every WS frame.

    So the spelling is JSON'S OWN, taken verbatim, exactly the way `_escaped` takes
    `repr`'s: `json.dumps` of one character with `ensure_ascii=True` (the default) IS the
    escape this function wants — the surrogate pair for an astral member, `\\uXXXX` for
    every other one, and the same lone surrogate R15-SEC-2 needs it to pass through. The
    docstring below already said "`\\uXXXX` is what `ensure_ascii=True` would have
    written"; this makes that a fact rather than a second implementation of it. The outer
    quotes `dumps` adds are the caller's business, and stripped for the same reason
    `_escaped` strips `repr`'s.
    """
    return json.dumps(match.group())[1:-1]


def json_safe(value):
    r"""A `json.dumps(..., ensure_ascii=False)` result, with every class member escaped.

    R17-SEC-1. `ensure_ascii=False` is the CLI's choice so a Chinese path stays readable
    in `--json`, and what it escapes is U+0000-001F, the quote and the backslash — and
    nothing else. So every OTHER member of `CONTROL_CLASS` went out raw and valid:
    U+009B (the 8-bit CSI), U+0085, the bidi overrides and isolates, the zero-width
    family, the BOM. `--json` is piped into terminals (`| jq`, `| less`, a CI log), and
    the round-15 claim that it was "safe by construction" was a claim about C0 only.

    R15-SEC-2's `escape_surrogates` was this function with one range instead of the class,
    and it is replaced rather than extended: a second range list is exactly the thing
    `CONTROL_CLASS` exists to prevent. What was true of the surrogates is true of all of
    them — `\uXXXX` is what `ensure_ascii=True` would have written, `json.loads` returns
    the identical code point, and everything outside the class (CJK included) stays
    literal. The scanner still reports the true bytes; only their spelling on the wire
    changes.

    THE CLASS MINUS NEWLINE, for `safe_text`'s reason one layer over: the line breaks in
    this string are `indent=2`'s, not the repository's. `json.dumps` has already escaped
    every U+000A that is INSIDE a string as `\n`, so a raw newline here can only be the
    pretty-printer's own — and escaping those writes `\u000a` where the document's
    structure was, which is not valid JSON at all. Caught by the end-to-end test doing
    what a consumer does: `json.loads` on the output.
    """
    return _TEXT_CONTROL_RE.sub(_json_escaped, value)


def text_block(value, indent=TEXT_INDENT):
    """`value` sanitized for a terminal and indented onto its continuation lines."""
    return safe_text(value).replace("\n", "\n" + indent)
