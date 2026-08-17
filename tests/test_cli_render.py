"""`python -m hub scan` — the OTHER presentation of one report.

`hub/__main__.py`'s docstring says it renders "the same ScanReport the UI stores — one
code path (scanner.core.scan), two presentations". That is a claim about the renderer as
much as about the scan, and nothing had ever compared what the two presentations put on a
screen.
"""
import json
import os

import pytest

from hub.__main__ import render_text
from scanner import core, presentation
from scanner.modules.fallbacks import _MAX_SKIPPED_REPORTED

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

    # `--json` is untouched on purpose: `json.dumps` escapes control characters by
    # construction and its consumer is a parser, not a screen.
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
    assert presentation.safe_path("a\nb") == "a\\x0ab"
    assert presentation.safe_text("a\x1bb") == "a\\x1bb"
    assert presentation.safe_text("正體中文 — ok") == "正體中文 — ok", (
        "ordinary non-ASCII is text, not a control character; this fleet is Taiwanese")


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


@pytest.mark.req("SEC-69-NO-SECRETS-IN-EXHAUST")
def test_issue_r15_sec_1_the_escape_form_switches_at_the_byte_boundary():
    """`\\xNN` below U+0100 and `\\uNNNN` at or above it — the boundary, exactly.

    Found by `make mutation`: `code < 0x100` mutated to `<= 0x100` and to `< 257` both
    survived, because no code point in today's class sits at U+0100 and nothing called
    `_escaped` with one. The mutants are equivalent only for the class AS IT IS WRITTEN —
    widen it by one range and `\\x100` starts appearing, which is a three-hex-digit `\\x`
    escape: not a form Python, C or any reader parses back to one character.

    So it is killed rather than waived. The property is about the ESCAPE FORM, which is
    the operator's ability to retype the name of a file they have to go and delete, and
    it holds for every code point rather than for the ones the class happens to contain.
    """
    import re

    def escaped(char):
        return presentation._escaped(re.match(".", char, re.DOTALL))

    assert escaped("\x00") == "\\x00"
    assert escaped("\x1b") == "\\x1b"
    assert escaped("\x9f") == "\\x9f"          # the last two-digit code point
    assert escaped("\xff") == "\\xff"
    assert escaped("Ā") == "\\u0100"      # the first that is not
    assert escaped("​") == "\\u200b"
    assert escaped("﻿") == "\\ufeff"
