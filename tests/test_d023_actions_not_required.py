"""D-023: the Phase 2.5 gate is local `make conformance-2.5`, not a GitHub Check.

Paid Actions are disabled (D-022). A test that asserted a green GitHub Check
would require the billing we ruled out. This file only asks whether the Makefile
declares the local all-tiers target and whether review-round stays T1.
"""
import pathlib
import re

import gates

REPO = pathlib.Path(__file__).resolve().parent.parent


def _recipe(target):
    """First recipe line of a simple `target:\\n\\tcmd` Makefile rule."""
    text = (REPO / "Makefile").read_text(encoding="utf-8")
    match = re.search(rf"^{re.escape(target)}:\n\t(.+)$", text, re.M)
    return match.group(1) if match else None


def test_phase_2_5_gate_is_make_conformance_2_5_not_a_gha_check():
    """What would make this fail: no `conformance-2.5` target, or review-round
    demanding it (which would pull Multipass into the T1 Cloud Agent).

    Does not assert any GitHub Check is green — D-023 forbids that gate.
    """
    targets = gates.makefile_targets(REPO)
    assert "conformance-2.5" in targets, (
        "Makefile must declare conformance-2.5 as the all-tiers phase-2.5 gate"
    )

    all_tiers = _recipe("conformance-2.5")
    assert all_tiers is not None, "conformance-2.5 has no recipe"
    assert "--phase 2.5" in all_tiers, all_tiers
    assert "--exclude-tier" not in all_tiers, (
        f"conformance-2.5 must grade every tier, not omit t3:\n{all_tiers}"
    )

    t1_gate = _recipe("conformance")
    assert t1_gate is not None, "conformance has no recipe"
    assert "--phase 2.5" in t1_gate, t1_gate
    assert "--exclude-tier t3" in t1_gate, (
        f"review-round conformance must omit t3 so it does not demand Multipass:\n"
        f"{t1_gate}"
    )

    prereqs = gates.review_round_prerequisites(REPO)
    assert "conformance" in prereqs
    assert "conformance-2.5" not in prereqs, (
        "review-round must not require conformance-2.5 (D-022 / D-023)"
    )
