"""`python -m hub scan` — the OTHER presentation of one report.

`hub/__main__.py`'s docstring says it renders "the same ScanReport the UI stores — one
code path (scanner.core.scan), two presentations". That is a claim about the renderer as
much as about the scan, and nothing had ever compared what the two presentations put on a
screen.
"""
import ast
import json
import os
import pathlib
import re
import subprocess
import sys

import pytest

from hub.__main__ import render_text
from scanner import core, presentation
from scanner.modules.fallbacks import _MAX_SKIPPED_REPORTED

REPO = pathlib.Path(__file__).resolve().parent.parent
BACKSLASH = chr(92)
LINK_COUNT = _MAX_SKIPPED_REPORTED + 4


def _many_escaping_links(tmp_path, count=LINK_COUNT):
    """A scannable repo whose `src/` carries `count` links into a neighbouring tree."""
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n', encoding="utf-8")
    names = [f"vendored{i:02d}.ts" for i in range(count)]
    for name in names:
        target = neighbour / name
        target.write_text("export const x = 1;\n", encoding="utf-8")
        link = root / "src" / name
        os.symlink(os.path.relpath(target, link.parent), link)
    return root, [f"src/{name}" for name in names]


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r14_arch_a_the_text_renderer_names_every_refused_file(tmp_path):
    """R14-ARCH-A: the CLI dropped the tail of the refusal list on the floor.

    `core.symlinked-files`'s DETAIL prints ten paths and counts the rest — deliberately,
    because a report line is for reading (`_MAX_SKIPPED_REPORTED`). `refused_paths` is the
    complete announcement, and R12-A1 added it precisely so the fact would not be the
    prose. `CheckBody` renders all of them; `render_text` rendered the detail and stopped,
    so on a tree with fourteen escaping links the four in the tail appeared in NO line of
    the CLI's output at all.

    An operator reading the terminal was told "… and 4 more" and given no way to learn
    which four. The two presentations of one report disagreed about what the report said.
    """
    root, expected = _many_escaping_links(tmp_path)
    report = core.scan(root)
    check = next(c for c in report["checks"] if c["id"] == "core.symlinked-files")

    # The premise: the prose really does stop short, and the field really does not.
    assert len(check["refused_paths"]) == LINK_COUNT
    shown_in_prose = [p for p in expected if p in check["detail"]]
    assert len(shown_in_prose) == _MAX_SKIPPED_REPORTED
    assert f"and {LINK_COUNT - _MAX_SKIPPED_REPORTED} more" in check["detail"]

    text = render_text(report)

    missing = [p for p in expected if p not in text]
    assert missing == [], f"named nowhere in the CLI output: {missing}"
    # One path per line, so the output can be grepped and pasted — the same reason
    # `CheckBody` renders one `<li>` per path rather than a joined string.
    for path in expected:
        assert any(line.strip() == path for line in text.splitlines()), path


@pytest.mark.req("SCAN-S3-DETECTION-RULES")
def test_issue_r14_arch_a_a_check_with_no_refusals_renders_as_before(tmp_path):
    """The other side of the same line: a report with nothing refused is unchanged.

    Same property `CheckResult.as_dict` has (the key is omitted when the list is empty)
    and for the same reason — the artifacts, transcripts and demo records that quote this
    output do not move because a field was added for the trees that need it.
    """
    root = tmp_path / "repo"
    root.mkdir()
    (root / "Dockerfile").write_text(
        'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n', encoding="utf-8")

    text = render_text(core.scan(root))

    assert "did not read" not in text.lower()
    assert "core.symlinked-files" not in text


# ── R15-SEC-1: repo-controlled filenames reaching a terminal ─────────────────

ESC_NAME = "\x1b]0;pwned\x07\x1b[31mred\x1b[2Jcleared.ts"
BIDI_NAME = "src‮gnp.exe‬.ts"
ZERO_WIDTH_NAME = "inv​isible﻿.ts"


def _linked(root, neighbour, name):
    target = neighbour / "target.ts"
    target.write_text("export const x = 1;\n", encoding="utf-8")
    link = root / "src" / name
    os.symlink(os.path.relpath(target, link.parent), link)


def _terminal_hostile_tree(tmp_path, names):
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n', encoding="utf-8")
    for name in names:
        _linked(root, neighbour, name)
    return root


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r15_sec_1_a_committed_name_cannot_drive_the_terminal(tmp_path):
    """R15-SEC-1 (medium). A filename is repo-controlled text, and `render_text` handed it
    to a terminal unescaped — through the detail line AND through the refusal list.

    Demonstrated before the fix, on this tree:

        raw ESC in text output : True
        raw BEL in text output : True
        lines carrying it      : [15, 16]
        raw ESC in --json      : False

    What that buys an attacker who can land a symlink in a scanned repository: `\\x1b[2J`
    clears the screen the summary was just printed on, OSC 0 rewrites the window title,
    SGR repaints later output in a colour of its choosing, and OSC 52 writes the
    operator's clipboard. The report is read by a person deciding whether a deploy is
    safe, so a repository that can edit that report's appearance is editing the decision.

    NAMED, NOT STRIPPED. The escaped spelling is in the output because the text IS the
    finding's name — an operator who has to go and delete this file needs to know what it
    is called, and a stripped name is a file that does not exist.
    """
    root = _terminal_hostile_tree(tmp_path, [ESC_NAME])
    report = core.scan(root)

    text = render_text(report)

    assert "\x1b" not in text, "an escape sequence reached the terminal"
    assert "\x07" not in text, "a BEL reached the terminal"
    assert "\\x1b]0;pwned\\x07" in text, (
        "the file is named nowhere in a form the operator can act on")
    # …and the fact and the prose both, because the name arrives twice by two routes.
    named = [line for line in text.splitlines() if "cleared.ts" in line]
    assert len(named) >= 2, named

    # `--json` needs no DISPLAY escaping for this payload: `json.dumps` escapes
    # U+0000-001F by construction, and ESC is one of them. R17-SEC-1 is what that
    # sentence used to claim beyond its evidence — it said "escapes control characters",
    # and C0 is not the class. Everything above U+001F in `CONTROL_CLASS` went out raw
    # until `json_safe`; the pins for that are in the R17-SEC-1 section below.
    assert "\x1b" not in json.dumps(report)
    assert any("\x1b" in p for c in report["checks"]
               for p in (c.get("refused_paths") or [])), (
        "the REPORT still carries the true bytes — sanitizing the data would have been "
        "a scanner that lies about what it found")


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
@pytest.mark.parametrize("name,codepoint", [(BIDI_NAME, "\\u202e"),
                                            (ZERO_WIDTH_NAME, "\\u200b")])
def test_issue_r15_sec_1_the_appearance_class_is_escaped_too(tmp_path, name, codepoint):
    """The second family: code points that do not write lines but lie about them.

    A right-to-left override makes `exe.png` read as `gnp.exe` on the screen it is
    printed on, and a zero-width space makes two different filenames look identical. The
    class is `scanner.presentation.CONTROL_CLASS`, which is the set
    `scanner/declarations.py` refuses in a repo-supplied reason — one set, two policies,
    and this is the presentation one.
    """
    root = _terminal_hostile_tree(tmp_path, [name])

    text = render_text(core.scan(root))

    # The whole rendered block, against the class MINUS newline — the output is lines,
    # and its own line breaks are the renderer's, not the repository's.
    assert not presentation._TEXT_CONTROL_RE.search(text), (
        "a code point that reorders or hides text reached the output raw")
    assert codepoint in text, "…and it is named, so the operator can find the file"


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r15_sec_1_the_sanitizers_keep_what_the_server_composed(tmp_path):
    """The line between the two sanitizers, which is the whole of their difference.

    A `detail` is the scanner's own prose and legitimately multi-line; a path is one
    token on a line of its own, so a newline in a FILENAME would forge an entry in the
    refusal list. `safe_text` keeps `\\n`, `safe_path` does not.
    """
    assert presentation.safe_text("a\nb") == "a\nb"
    assert presentation.safe_path("a\nb") == "a\\nb"
    assert presentation.safe_text("a\x1bb") == "a\\x1bb"
    assert presentation.safe_text("正體中文 — ok") == "正體中文 — ok", (
        "ordinary non-ASCII is text, not a control character; this fleet is Taiwanese")


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_f16_1_the_escape_vocabulary_is_pythons_own_for_every_code_point():
    """One name, one spelling, wherever it is escaped (F16-1).

    The scanner composes prose about the same filenames this module lists —
    `_report_path` quotes a path that spans lines through `repr` — so a name could appear
    in one check body twice: `'src/two\\nlines.ts'` from the prose and
    `src/two\\x0alines.ts` from the refusal list. Only the newline class diverged, because
    everything else `repr` escapes it escapes the same way. That is why the answer is to
    take `repr`'s spelling verbatim rather than keep a second table that matches today.

    Asserted over the WHOLE class rather than a sample, and against `repr` itself rather
    than a list of expected strings — a list of expected strings IS the second table.
    This replaces the `< 0x100` boundary test the mutation gate asked for in R15: that
    branch is gone, because there is no branch left.

    R21-ARCH-2: except where `repr` HAS no escape. It escapes by printability, and the
    variation selectors this round added to the class are category Mn — "printable" —
    so `repr` returns the character itself, which would escape nothing. The property
    holds in the form "repr's spelling wherever repr has one", and the third assertion
    below is the one that makes the fallback safe rather than merely different: every
    escape, `repr`'s or the fallback's, DECODES BACK to the code point it names. A
    ten-character `\\U000e0041` mis-spelled as `\\ue0041` names another character and
    fails there.
    """
    import re as _re

    every = "".join(map(chr, range(0x110000)))
    fallbacks = []
    for char in _re.findall(f"[{presentation.CONTROL_CLASS}]", every):
        escaped = presentation.safe_path(char)
        if repr(char)[1:-1] == char:
            fallbacks.append(char)
            assert escaped == f"{BACKSLASH}u{ord(char):04x}", (char, escaped)
        else:
            assert escaped == repr(char)[1:-1], (char, escaped)
        assert not presentation._CONTROL_RE.search(escaped), (
            f"U+{ord(char):04X} escaped to something still in the class: {escaped!r}")
        assert ast.literal_eval(f"'{escaped}'") == char, (
            f"U+{ord(char):04X} is spelled {escaped!r}, which reads back as something else")

    assert fallbacks == [chr(cp) for cp in range(0xFE00, 0xFE10)], (
        "the set `repr` will not escape moved; the fallback's `\\uXXXX` width is only "
        "right while every one of them is BMP")

    # The ones the finding was about, spelled once and read twice.
    assert presentation.safe_path("two\nlines.ts") == "two\\nlines.ts"
    assert repr("two\nlines.ts")[1:-1] == "two\\nlines.ts"
    assert presentation.safe_path("\x1b\t\udc9b\u200b") == "\\x1b\\t\\udc9b\\u200b"


# ── R21-ARCH-2: the invisible NON-LETTERS the class did not name ─────────────
#
# The class covered the bidi family and the zero-width family and stopped there, and the
# Phase-1 exit statement claims it is complete. It was not: a handful of assigned,
# invisible, non-letter format and default-ignorable code points rendered as nothing at
# all five exits, so two names differing only by one of them displayed identically — the
# same threat U+200B is in the class for.
#
# The line is "invisible non-letter format/default-ignorable IN, everything else OUT", and
# the neighbours below are the other side of it: the Mongolian free variation selectors,
# a superscript digit, a presentation form, the object-replacement character and the
# unassigned code points beside the tag block are all left alone. Soft hyphen U+00AD and
# the Hangul fillers stay out too — that exclusion is argued in `declarations.py` and is
# not disturbed here.
_INVISIBLE_NON_LETTERS = [
    (0x180E, "MONGOLIAN VOWEL SEPARATOR", "\\u180e", 0x180D),
    (0x206A, "INHIBIT SYMMETRIC SWAPPING", "\\u206a", 0x2070),
    (0x206F, "NOMINAL DIGIT SHAPES", "\\u206f", 0x2070),
    (0xFE00, "VARIATION SELECTOR-1", "\\ufe00", 0xFE10),
    (0xFE0F, "VARIATION SELECTOR-16", "\\ufe0f", 0xFE10),
    (0xFFF9, "INTERLINEAR ANNOTATION ANCHOR", "\\ufff9", 0xFFFC),
    (0xFFFB, "INTERLINEAR ANNOTATION TERMINATOR", "\\ufffb", 0xFFFC),
    (0xE0001, "LANGUAGE TAG", "\\U000e0001", 0xE0002),
    (0xE0041, "TAG LATIN CAPITAL LETTER A", "\\U000e0041", 0xE0080),
    (0xE007F, "CANCEL TAG", "\\U000e007f", 0xE0080),
]


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
@pytest.mark.parametrize("codepoint,name,spelling,neighbour", _INVISIBLE_NON_LETTERS)
def test_issue_r21_arch_2_an_invisible_non_letter_is_named(
        codepoint, name, spelling, neighbour):
    """Both sanitizers, on each new member and on the neighbour that stays out.

    `a\\ufe0fb.ts` and `ab.ts` are two files and were one string on screen; a tag
    character can carry a whole hidden word through a filename. The escape is the same
    vocabulary as every other member — `repr`'s, except where `repr` has none (the
    variation selectors are category Mn, so `str.isprintable()` says True and `repr`
    hands the character back unchanged; the fallback is `repr`'s own `\\uXXXX`).
    """
    char = chr(codepoint)

    assert presentation.safe_path(f"a{char}b.ts") == f"a{spelling}b.ts"
    assert presentation.safe_text(f"a{char}b") == f"a{spelling}b"
    # …and it is no longer invisible: two names that differed by nothing readable differ.
    assert presentation.safe_path(f"a{char}b.ts") != presentation.safe_path("ab.ts")

    # The other side of the line, pinned so the boundary is a decision and not a guess.
    other = chr(neighbour)
    assert presentation.safe_path(f"a{other}b.ts") == f"a{other}b.ts", (
        f"U+{neighbour:04X} is outside the rule and must pass through")


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r21_arch_2_an_astral_member_is_a_surrogate_pair_in_json():
    """The JSON exits, where `\\uXXXX` names a code UNIT and not a code point.

    The tag characters are the first astral members of the class, and
    `f"{BACKSLASH}u{ord(char):04x}"` would have spelled U+E0041 `\\ue0041` — which a
    parser reads as U+E004 followed by the digit `1`. A different string, silently, in
    `--json`, the API body and every WS frame.
    """
    payload = {"p": "x\U000e0041y"}
    escaped = presentation.json_safe(json.dumps(payload, ensure_ascii=False))

    assert "\U000e0041" not in escaped, "the tag character went out raw"
    assert BACKSLASH + "udb40" + BACKSLASH + "udc41" in escaped
    assert json.loads(escaped) == payload, "the round trip lost the code point"


# ── R15-ARCH-1: one presentation model, two renderers ────────────────────────

def test_issue_r15_arch_1_the_text_renderer_reads_the_shared_model(tmp_path):
    """Both renderers are DRIVEN by `scanner.presentation`, not compared against it.

    Patching the declarations is how a test asserts there is one of them — the R10-A5
    precedent. A renderer with the field list written into its own body passes an
    equivalence test and fails this one.
    """
    root = _many_escaping_links(tmp_path, count=1)[0]
    report = core.scan(root)

    original = presentation.CHECK_FIELDS
    try:
        presentation.CHECK_FIELDS = (
            {"key": "detail", "label": "SENTINEL:", "kind": "prose"},)
        text = render_text(report)
    finally:
        presentation.CHECK_FIELDS = original

    assert "SENTINEL:" in text
    assert "Did not read:" not in text, "the renderer kept a field the model dropped"


def test_issue_r15_arch_1_the_fix_hint_renders_at_every_tier(tmp_path):
    """SUBSUMED LOW, decided as a spec decision: `fix_hint` is not tier-gated.

    `render_text` printed it for `blocker` and `warning` only; `CheckBody` printed it
    always. The direction is the UI's, because the gate was withholding information
    nobody had decided to withhold: every `pending_sandbox` check's hint is the WHY of a
    deferred job, and the CLI operator was the one person who could not read it. No `ok`
    check in this tree carries a hint at all, so the "noise on the happy path" a gate
    might have been for does not exist.
    """
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n', encoding="utf-8")
    report = core.scan(root)
    report["checks"].append({
        "id": "t.advice", "tier": "advice", "title": "An advisory finding",
        "detail": "", "fix_hint": "ADVICE HINT", "execution": "static"})
    report["checks"].append({
        "id": "t.sandbox", "tier": "pending_sandbox", "title": "A deferred job",
        "detail": "", "fix_hint": "SANDBOX WHY", "execution": "executing"})
    report["summary"]["advice"] = 1
    report["summary"]["pending_sandbox"] = 1

    text = render_text(report)

    assert "Fix: ADVICE HINT" in text
    assert "Fix: SANDBOX WHY" in text
    assert presentation.TIER_GATES == {}, (
        "a tier gate landed in the model; both renderers now honour it, and this test "
        "should be the one that says which tiers and why")


def test_issue_r15_arch_1_the_refusal_label_is_the_shared_one(tmp_path):
    """SUBSUMED LOW: the label was typed in each renderer. One spelling, both media."""
    root = _terminal_hostile_tree(tmp_path, ["plain.ts"])
    label = next(f["label"] for f in presentation.CHECK_FIELDS
                 if f["key"] == "refused_paths")

    text = render_text(core.scan(root))

    assert label == "Did not read:"
    assert f"{presentation.TEXT_INDENT}{label}" in text


def test_issue_r15_arch_1_a_multi_line_detail_keeps_its_indent(tmp_path):
    """SUBSUMED LOW, on the fixture that produced it: `core.secret-scan`'s fifteen
    `file:line` findings.

    The renderer indented the FIRST line of a detail and let every line after it fall
    back to column zero — so fourteen of fifteen findings sat at the left margin, in line
    with the section headings rather than under the check they belong to, and a reader
    scanning the left edge for structure found findings there instead.
    """
    root = tmp_path / "repo"
    (root / "app").mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n', encoding="utf-8")
    report = core.scan(root)
    detail = "\n".join(f"src/file{i:02d}.py:{i}: [heuristic] hardcoded value"
                       for i in range(15))
    report["checks"].append({
        "id": "t.multi", "tier": "blocker", "title": "Committed secrets detected",
        "detail": detail, "fix_hint": "one\ntwo", "execution": "static"})
    report["summary"]["blocker"] = 1

    lines = render_text(report).splitlines()
    findings = [line for line in lines if "[heuristic]" in line]

    assert len(findings) == 15
    assert all(line.startswith(presentation.TEXT_INDENT) for line in findings), (
        "continuation lines fell back to column zero")
    assert all(not line[len(presentation.TEXT_INDENT)].isspace() for line in findings)
    # …and the fix hint's own second paragraph too, which is the same value shape.
    assert f"{presentation.TEXT_INDENT}two" in lines


# ── R15-SEC-2: bytes that are not characters ─────────────────────────────────

CSI_BYTE_NAME = b"csi\x9bmark.ts"          # a bare 0x9b: 8-bit CSI, invalid UTF-8


def _undecodable_name_tree(tmp_path):
    """A repo whose committed symlink is named with a byte no UTF-8 decoder accepts.

    Built through `os.fsencode`, because the point is that a POSIX filename is BYTES and
    this one is not text. Python reads it back as U+DC9B — `surrogateescape`'s spelling
    for "byte 0x9b, undecodable" — and that is what the scan report carries.
    """
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    target = neighbour / "target.ts"
    target.write_text("export const x = 1;\n", encoding="utf-8")
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n', encoding="utf-8")
    link = os.path.join(os.fsencode(str(root / "src")), CSI_BYTE_NAME)
    os.symlink(os.path.relpath(os.fsencode(str(target)),
                               os.fsencode(str(root / "src"))), link)
    assert any("\udc9b" in name for name in os.listdir(root / "src"))
    return root


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
@pytest.mark.parametrize("errors", ["strict", "surrogateescape"])
@pytest.mark.parametrize("flag", [[], ["--json"]])
def test_issue_r15_sec_2_an_undecodable_filename_cannot_take_the_cli_down(
        tmp_path, errors, flag):
    """R15-SEC-2, end to end through the entry point an operator actually runs.

    `CONTROL_CLASS` covered every code point that IS a control character and none of the
    code points that are not characters at all. A filename is bytes; `os.listdir` decodes
    the undecodable ones with `surrogateescape` into U+DC80-DCFF, which no range in the
    class described. Measured before the fix, on this tree:

        strict  text  : UnicodeEncodeError: 'utf-8' codec can't encode character '\\udc9b'
        strict  --json: UnicodeEncodeError: … (the same, by a different route)
        surrogateescape text/--json: 2 lines carrying the raw 0x9b byte

    Both halves are the finding. The first is a repository stopping an operator from
    reading any report about it — the scan succeeds and the CLI dies printing it. The
    second is 0x9b arriving intact, and 0x9b IS the 8-bit CSI: the C1 control the
    `\\x80-\\x9f` range is escaped for, reaching the terminal by the one route that range
    cannot see.

    Run as a SUBPROCESS with `PYTHONIOENCODING` set, because the crash is in the encoder
    on the way to the device and an in-process assertion about a string cannot see it.
    """
    root = _undecodable_name_tree(tmp_path)
    env = {**os.environ, "PYTHONIOENCODING": f"utf-8:{errors}"}

    result = subprocess.run([sys.executable, "-m", "hub", "scan", str(root), *flag],
                            capture_output=True, cwd=str(REPO), env=env, timeout=180)

    assert result.returncode == 0, result.stderr.decode("utf-8", "replace")
    assert b"UnicodeEncodeError" not in result.stderr
    assert b"\x9b" not in result.stdout, "the byte reached the terminal as itself"
    assert b"\\udc9b" in result.stdout, (
        "the file is named nowhere in a form the operator can act on")


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r15_sec_2_the_json_body_is_still_what_the_scanner_found(tmp_path):
    """…and `--json`'s consumer receives the same report, not a sanitized one.

    `json_safe` (R15-SEC-2 shipped it as `escape_surrogates`; R17-SEC-1 widened it to the
    whole class) spells those code points the way `ensure_ascii=True` would have and
    touches nothing else, so the bytes on the wire are valid JSON and `json.loads` reads
    the lone surrogate back. A scanner that quietly repaired the name would be lying
    about what it found.
    """
    root = _undecodable_name_tree(tmp_path)

    result = subprocess.run([sys.executable, "-m", "hub", "scan", str(root), "--json"],
                            capture_output=True, cwd=str(REPO), timeout=180)
    report = json.loads(result.stdout.decode("utf-8"))

    refused = [p for c in report["checks"] for p in (c.get("refused_paths") or [])]
    assert any("\udc9b" in p for p in refused), refused
    assert os.fsencode(refused[0]).endswith(CSI_BYTE_NAME), (
        "the round trip does not name the file on disk")


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r17_sec_1_the_json_escaper_covers_the_whole_class():
    """`json_safe` in process, over every member of `CONTROL_CLASS`.

    R15-SEC-2 shipped this as `escape_surrogates` — the same function with one range
    instead of the class — and R17-SEC-1 is the rest of the class arriving raw and valid
    in `--json`: U+009B (the 8-bit CSI), U+0085, the bidi overrides and isolates, the
    zero-width family, the BOM. `json.dumps(ensure_ascii=False)` escapes U+0000-001F, the
    quote and the backslash, and nothing else.

    Asserted in process as well as end to end, and that is not belt-and-braces: `make
    mutation` reported all four mutants of the old function as `no tests`, because mutmut
    records coverage in ITS process and the end-to-end cases run a subprocess.
    """
    every = "".join(map(chr, range(0x110000)))
    members = set(re.findall(f"[{presentation.CONTROL_CLASS}]", every))

    for char in members:
        dumped = json.dumps({"p": f"x{char}y"}, ensure_ascii=False)
        escaped = presentation.json_safe(dumped)
        assert char not in escaped, f"U+{ord(char):04X} survived into the JSON text"
        # …and a parser gives the identical code point back. The scanner still reports
        # what it found; only the spelling on the wire changed.
        assert json.loads(escaped) == {"p": f"x{char}y"}, char

    # JSON's vocabulary, not `repr`'s: `\x9b` is not a JSON escape and a parser rejects
    # it, which is why display and serialization cannot share one escaper.
    assert presentation.json_safe(json.dumps("x\x9by")) == '"x' + BACKSLASH + 'u009by"'
    assert presentation.json_safe("plain") == "plain"

    # Everything outside the class is left exactly as it is — the reason
    # `ensure_ascii=False` was chosen in the first place.
    assert presentation.json_safe("正體中文 · ok") == "正體中文 · ok"


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
@pytest.mark.parametrize("codepoint,label", [("\u009b", "C1 CSI"), ("\u202e", "RLO"),
                                             ("\u2066", "bidi isolate"),
                                             ("\u200b", "zero width"), ("\ufeff", "BOM")])
def test_issue_r17_sec_1_a_hostile_name_is_escaped_in_json_end_to_end(
        tmp_path, codepoint, label):
    """The whole route: a committed symlink named with each class, through
    `python -m hub scan --json`.

    These names are VALID UTF-8 — unlike R15-SEC-2's bare byte — so nothing upstream
    stumbles on them and they arrived in the output as themselves. `--json` is piped into
    `jq`, `less` and CI logs at least as often as it is parsed, so U+009B reaching a
    terminal that honours 8-bit C1 is the round-15 finding by the exit nobody guarded.
    """
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    target = neighbour / "t.ts"
    target.write_text("export const x = 1;\n", encoding="utf-8")
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n', encoding="utf-8")
    link = root / "src" / f"na{codepoint}me.ts"
    os.symlink(os.path.relpath(target, link.parent), link)

    result = subprocess.run([sys.executable, "-m", "hub", "scan", str(root), "--json"],
                            capture_output=True, cwd=str(REPO), timeout=180)
    out = result.stdout.decode("utf-8")

    assert codepoint not in out, f"{label} reached the output raw"
    assert f"{BACKSLASH}u{ord(codepoint):04x}" in out, f"{label} is named nowhere"

    # The report a consumer parses still carries the true code point.
    report = json.loads(out)
    refused = [p for c in report["checks"] for p in (c.get("refused_paths") or [])]
    assert any(codepoint in p for p in refused), refused


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r17_sec_1_a_readable_path_stays_readable_in_json(tmp_path):
    """The over-correction guard, which this fleet has needed twice before.

    `ensure_ascii=False` exists so a Chinese path is legible in `--json`. An escaper that
    reached beyond the class would undo the only reason the flag is there.
    """
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    target = neighbour / "t.ts"
    target.write_text("export const x = 1;\n", encoding="utf-8")
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n', encoding="utf-8")
    link = root / "src" / "報表·結算.ts"
    os.symlink(os.path.relpath(target, link.parent), link)

    result = subprocess.run([sys.executable, "-m", "hub", "scan", str(root), "--json"],
                            capture_output=True, cwd=str(REPO), timeout=180)
    out = result.stdout.decode("utf-8")

    assert "報表·結算.ts" in out, "a legible path was escaped into hex"
    assert BACKSLASH + "u5831" not in out


# ── R16-SEC-1: the heading, which the boundary was not drawn around ──────────

SERVICE_DIR_NAME = "svc\x1b]0;PWNED\x07\x1b[31m\x1b[2Jx"


def _hostile_service_dir_tree(tmp_path):
    """A pnpm monorepo whose SERVICE DIRECTORY is named with terminal escapes.

    `node-ts.service-package`'s title interpolates `service_name()`, which is
    `service_dir.name` — repo-controlled text, in a check's TITLE rather than its body.
    """
    root = tmp_path / "repo"
    package = root / "packages" / SERVICE_DIR_NAME
    (package / "src").mkdir(parents=True)
    (root / "package.json").write_text('{"name": "m", "private": true}\n',
                                       encoding="utf-8")
    (root / "pnpm-workspace.yaml").write_text("packages:\n  - 'packages/*'\n",
                                              encoding="utf-8")
    (package / "package.json").write_text(
        '{"name": "@m/server", "main": "dist/index.js",\n'
        ' "dependencies": {"fastify": "^4.28.0"}}\n', encoding="utf-8")
    (package / "src" / "index.ts").write_text("import Fastify from 'fastify';\n",
                                              encoding="utf-8")
    return root


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r16_sec_1_a_check_title_cannot_drive_the_terminal(tmp_path):
    """R16-SEC-1 (medium). R15-SEC-1 sanitized the check BODY and printed the HEADING raw.

    The boundary had been drawn in the wrong place — around "the fields `_render_fields`
    renders" rather than around "repo-controlled text reaching a device" — so the first
    title to interpolate a repository's own string walked straight through it.
    `node-ts.service-package` is that title: it names `service_dir.name`. Measured before
    the fix, on this tree:

        raw ESC in output: True
        raw BEL in output: True
          line 56 : '  ✓ node-ts.service-package: Deployable service package: svc\\x1b]0;PWNED…'

    Same payload, same consequences as R15-SEC-1 — `\\x1b[2J` clears the screen the
    summary was printed on, OSC 0 retitles the window, OSC 52 writes the clipboard — by a
    route that commit's tests could not see, because they asserted about details and
    refusal lists.
    """
    root = _hostile_service_dir_tree(tmp_path)
    report = core.scan(root)

    title = next(c["title"] for c in report["checks"]
                 if c["id"] == "node-ts.service-package")
    assert "\x1b" in title, "the fixture stopped exercising the title path"

    text = render_text(report)

    assert not presentation._TEXT_CONTROL_RE.search(text), (
        "repo-controlled text reached the terminal raw, through the heading")
    assert "\\x1b]0;PWNED\\x07" in text, "…and the operator cannot see what it is called"


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r16_sec_1_the_renderer_is_safe_at_the_seam_not_per_field(tmp_path):
    """SAFE BY CONSTRUCTION, which is the architectural half of the finding.

    A per-field opt-in is a rule every future interpolation has to remember; this one was
    forgotten by the commit that wrote the rule. `render_text` now sanitizes its WHOLE
    output on the way out, so a new field, a new heading, a new summary line is safe
    because of where it is printed rather than because somebody remembered.

    Asserted by planting the payload in every string a check carries — id and tier
    included, which no scanner emits and which the seam covers anyway.
    """
    report = core.scan(_hostile_service_dir_tree(tmp_path))
    report["checks"].append({
        "id": "t.hostile\x1b[2J", "tier": "advice",
        "title": "t\x07itle", "detail": "de\x1btail", "fix_hint": "fi\x1bx",
        "execution": "static", "refused_paths": ["p\x1ba.ts"]})
    report["summary"]["advice"] = report["summary"].get("advice", 0) + 1
    report["modules"] = [*report["modules"], "mod\x1bule"]

    text = render_text(report)

    assert not presentation._TEXT_CONTROL_RE.search(text), text[:400]
    for named in ("t.hostile\\x1b[2J", "t\\x07itle", "de\\x1btail", "fi\\x1bx",
                  "p\\x1ba.ts", "mod\\x1bule"):
        assert named in text, named


def test_issue_r16_sec_1_check_ids_are_scanner_authored_slugs(tmp_path):
    """…and the other half of the id/tier question, answered rather than assumed.

    The seam covers them, so nothing rests on this — but a check id is a scanner-authored
    slug by construction (it keys supersession, the registry invariant and the demo
    records), and saying so mechanically is cheaper than the next reader wondering whether
    a repository can reach one.
    """
    import re as _re

    for root in (_hostile_service_dir_tree(tmp_path), tmp_path / "empty"):
        (tmp_path / "empty").mkdir(exist_ok=True)
        for check in core.scan(root)["checks"]:
            assert _re.fullmatch(r"[a-z0-9][a-z0-9.\-]*", check["id"]), check["id"]
            assert check["tier"] in core.TIERS


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_f16_1_one_filename_reads_the_same_in_both_halves_of_a_check(tmp_path):
    """F16-1, on the tree that produced it: a committed symlink named across two lines.

    `core.symlinked-files` names it twice in one body — in the prose, quoted through the
    scanner's `repr` because a name that occupies two lines would forge a report line
    (R7-3), and in the refusal list, escaped by this module. Before the escape vocabulary
    was Python's, the operator read `'src/two\\nlines.ts'` on one line and
    `src/two\\x0alines.ts` three lines below it, and had to work out that those are the
    same file.

    The outer quotes stay, and they are not a second spelling: they BOUND a name inside a
    sentence, and a list that gives each name its own line has nothing to bound.
    """
    neighbour = tmp_path / "neighbour"
    neighbour.mkdir()
    target = neighbour / "t.ts"
    target.write_text("export const x = 1;\n", encoding="utf-8")
    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    (root / "Dockerfile").write_text(
        'FROM python:3.12\nUSER app\nEXPOSE 8000\nCMD ["app"]\n', encoding="utf-8")
    link = root / "src" / "two\nlines.ts"
    os.symlink(os.path.relpath(target, link.parent), link)

    check = next(c for c in core.scan(root)["checks"]
                 if c["id"] == "core.symlinked-files")
    prose = next(line for line in check["detail"].splitlines() if "lines.ts" in line)
    listed = presentation.safe_path(check["refused_paths"][0])

    assert prose == f"'{listed}'", (prose, listed)
    assert "\\n" in listed and "\\x0a" not in listed


# ── QUALITY F-1: an escape vocabulary that was not injective ─────────────────

def test_issue_f16_1_quality_f1_the_path_encoding_is_injective():
    """One escaped string, one file — which R16-SEC-1's vocabulary change did not give.

    Taking `repr`'s spelling for the control class left `repr`'s other rule behind: the
    literal backslash is doubled. Without that, two different names collapse onto one
    string, and the operator reading a refusal list cannot tell which file to delete:

        safe_path("two" + chr(92) + "nlines.ts")   ->  two\\nlines.ts
        safe_path("two" + chr(10) + "lines.ts")    ->  two\\nlines.ts   (the same)

    The compound name is the other half, and it is the one that showed in a panel: the
    scanner's prose DOES double (it is `repr` of the whole string), so one filename read
    `'src/a\\\\b\\nc.ts'` in the detail and `src/a\\b\\nc.ts` in the list.
    """
    literal = "two" + BACKSLASH + "nlines.ts"
    newline = "two\nlines.ts"

    assert presentation.safe_path(literal) != presentation.safe_path(newline)
    assert presentation.safe_path(literal) == "two" + BACKSLASH * 2 + "nlines.ts"
    assert presentation.safe_path(newline) == "two" + BACKSLASH + "nlines.ts"

    # The compound name, against the prose spelling it has to agree with.
    compound = "src/a" + BACKSLASH + "b\nc.ts"
    assert presentation.safe_path(compound) == repr(compound)[1:-1]


def test_issue_f16_1_quality_f1_safe_text_stays_idempotent():
    """…and `safe_text` does NOT double, because it is applied twice by design.

    R16-SEC-1's seam runs it over the whole assembled output, after `_render_fields` has
    already run it per field. Doubling there would turn the `\x1b` the first pass wrote
    into `\\x1b` — every escape in the report growing a backslash per pass.

    So the two functions carry different properties on purpose: a path is a NAME (one
    string, one file) and prose is TEXT for a device (neutralized, however many times it
    crosses the boundary). The authoritative names are in `refused_paths`.
    """
    once = presentation.safe_text("a\x1bb" + BACKSLASH + "c")
    assert presentation.safe_text(once) == once
    assert once == "a" + BACKSLASH + "x1bb" + BACKSLASH + "c"


def test_issue_f16_1_quality_f1_the_whole_class_walk_still_holds():
    """The R16-F16-1 property, re-verified under the doubling: for every member of the
    class the escape is still `repr`'s, and no escape is itself still in the class.

    The doubling changes what happens to a character OUTSIDE the class (the backslash),
    so this is the assertion that says it did not disturb the vocabulary inside it.

    R21-ARCH-2: `repr` has no escape for the variation selectors (category Mn is
    "printable"), so the vocabulary is "repr's spelling wherever repr has one, repr's own
    `\\uXXXX` where it has none" — and the escape still round-trips to the code point it
    names, which is the property the doubling could break and does not.
    """
    every = "".join(map(chr, range(0x110000)))
    for char in re.findall(f"[{presentation.CONTROL_CLASS}]", every):
        escaped = presentation.safe_path(char)
        expected = repr(char)[1:-1]
        assert escaped == (expected if expected != char
                           else f"{BACKSLASH}u{ord(char):04x}"), (char, escaped)
        assert not presentation._CONTROL_RE.search(escaped), escaped
        assert ast.literal_eval(f"'{escaped}'") == char, escaped
