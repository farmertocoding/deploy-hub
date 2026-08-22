"""Nightly must exercise a drill body, not only the drill tests (D-042)."""
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent


def test_run_nightly_invokes_the_hub_down_drill_body():
    """run_nightly.sh calls the hub-down drill so a siteless host still
    writes a CheckRun.

    What would make this fail: nightly running only pytest, or invoking a
    stub that never imports run_hub_down_drill.
    """
    script = (REPO / "scripts_dev" / "run_nightly.sh").read_text(encoding="utf-8")
    assert "run_hub_down_drill" in script, script
