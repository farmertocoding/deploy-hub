"""`python -m hub scan` — the OTHER presentation of one report.

`hub/__main__.py`'s docstring says it renders "the same ScanReport the UI stores — one
code path (scanner.core.scan), two presentations". That is a claim about the renderer as
much as about the scan, and nothing had ever compared what the two presentations put on a
screen.
"""
import os

import pytest

from hub.__main__ import render_text
from scanner import core
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
