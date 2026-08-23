"""Server↔client ACTION_TIERS bijection (UX-F5, phase-exit I4).

core/actions.py is the source. frontend/src/api/action_tiers.js is the
generated mirror. Full-text UX-F5-ACTION-TIERS is marked on the hardware
tests, not this bijection file.
"""
import ast
import json
import pathlib
import re

REPO = pathlib.Path(__file__).resolve().parent.parent
JS = REPO / "frontend" / "src" / "api" / "action_tiers.js"


def _js_table():
    text = JS.read_text(encoding="utf-8")
    match = re.search(r"export const ACTION_TIERS = (\[.*?\]);", text, re.S)
    assert match, "generated action_tiers.js must export ACTION_TIERS as JSON"
    return json.loads(match.group(1))


def test_client_and_server_tier_tables_are_one_source():
    """What would make this fail: a hand-edited JS table that drifted from
    core/actions.py, or a generate step that stopped writing the mirror.
    """
    from core.actions import ACTION_TIERS

    assert _js_table() == [dict(row) for row in ACTION_TIERS]


def test_t3_rollback_never_grows_a_step_up():
    """site.rollback stays T3. A step-up on the recovery action is the defect.

    What would make this fail: moving rollback to T1/T2, or adding a confirm
    / step-up field the client would honour.
    """
    from core.actions import ACTION_TIERS

    row = next(r for r in ACTION_TIERS if r["id"] == "site.rollback")
    assert row["tier"] == "T3"
    assert "step_up" not in row and "stepUp" not in row
    client = (REPO / "frontend" / "src" / "actions.js").read_text(encoding="utf-8")
    assert (
        'if (row.tier === "T3") return { confirm: false, undo: true, stepUp: "none" }'
        in client
    )


def test_action_tiers_module_carries_no_full_text_req_marker():
    """SCAN-M4: this file must not claim UX-F5-ACTION-TIERS."""
    import check

    markers = check.collect_markers(REPO)
    nodeids = markers.get("UX-F5-ACTION-TIERS") or []
    mine = [n for n in nodeids if "test_action_tiers" in n]
    assert mine == []
    assert ast.parse(pathlib.Path(__file__).read_text(encoding="utf-8"))


def test_generate_client_writes_the_actions_mirror():
    """A generator nothing runs is a stale table. generate-client must write it."""
    makefile = (REPO / "Makefile").read_text(encoding="utf-8")
    recipe = makefile.split("generate-client:")[1].split("\ncheck-generated:")[0]
    assert "scripts_dev/generate_actions.py" in recipe


def test_actions_generator_refuses_arguments():
    """Same contract as generate_presentation: a whole-file writer takes none."""
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, "scripts_dev/generate_actions.py", "--only-labels"],
        cwd=str(REPO),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 2, result.stdout
    assert "takes none" in result.stderr
