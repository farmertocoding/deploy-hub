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


def test_phase_gate_is_local_make_conformance_3_not_a_gha_check():
    """What would make this fail: no `conformance-3` target, or review-round
    demanding it (which would pull Multipass into the T1 Cloud Agent).

    Phase 2.5 closed; `conformance-3` is the all-tiers local gate now
    (phase-3 Task 0) and `conformance-2.5` is deleted with it. Does not
    assert any GitHub Check is green — D-023 forbids that gate.
    """
    targets = gates.makefile_targets(REPO)
    assert "conformance-3" in targets, (
        "Makefile must declare conformance-3 as the all-tiers phase-3 gate"
    )
    assert "conformance-2.5" not in targets, (
        "conformance-2.5 is deleted (phase 2.5 closed); conformance-3 replaces it"
    )

    all_tiers = _recipe("conformance-3")
    assert all_tiers is not None, "conformance-3 has no recipe"
    assert "--phase 3" in all_tiers, all_tiers
    assert "--exclude-tier" not in all_tiers, (
        f"conformance-3 must grade every tier, not omit t3:\n{all_tiers}"
    )

    t1_gate = _recipe("conformance")
    assert t1_gate is not None, "conformance has no recipe"
    assert "--phase 3" in t1_gate, t1_gate
    assert "--exclude-tier t3" in t1_gate, (
        f"review-round conformance must omit t3 so it does not demand Multipass:\n"
        f"{t1_gate}"
    )

    prereqs = gates.review_round_prerequisites(REPO)
    assert "conformance" in prereqs
    assert "conformance-3" not in prereqs, (
        "review-round must not require conformance-3 (D-022 / D-023)"
    )
