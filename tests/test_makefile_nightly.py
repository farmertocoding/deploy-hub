"""D-023: review-round stays T1; local `make nightly` is the T3 mechanical gate."""
import pathlib
import re

import gates

REPO = pathlib.Path(__file__).resolve().parent.parent


def _target_prereqs(target):
    """Prerequisite names of a simple `target: a b c` Makefile rule.

    Same shape as `gates.review_round_prerequisites`, for `nightly`.
    """
    text = gates.makefile_text(REPO)
    match = re.search(rf"^{re.escape(target)}:((?:[^\n]*\\\n)*[^\n]*)", text, re.M)
    return set(match.group(1).replace("\\", " ").split()) if match else set()


def test_review_round_prereqs_exclude_test_t3_and_all_tiers_conformance():
    """What would make this fail: adding test-t3 or the all-tiers conformance-3
    (or a resurrected conformance-2.5) to review-round, which would pull
    Multipass into the T1 Cloud Agent (D-022 / D-023).
    """
    prereqs = gates.review_round_prerequisites(REPO)
    assert "test" in prereqs
    assert "conformance" in prereqs
    assert "test-t3" not in prereqs, (
        "review-round must not require test-t3 (D-022 / D-023)"
    )
    assert "conformance-3" not in prereqs, (
        "review-round must not require conformance-3 (D-022 / D-023)"
    )
    assert "conformance-2.5" not in prereqs, (
        "conformance-2.5 is deleted (phase-3 Task 0); it must not come back "
        "as a review-round prerequisite"
    )


def test_nightly_grades_one_all_tiers_session_feeding_conformance_3():
    """Panel F2 ruling (2.5, carried to phase 3): nightly is ONE all-tiers
    pytest session (`test-all`, bare `pytest -q`) followed by conformance-3
    reading that session's full_run report. Three narrowed sessions (test,
    test-t2, test-t3) each left a full_run:false report the gate hard-refuses,
    so a narrowed prereq list could never exit 0 even when everything passed.

    `nightly` itself is a wrapper so a failed prereq still files a bundle.
    """
    targets = gates.makefile_targets(REPO)
    assert "nightly" in targets, "Makefile must declare nightly as the local T3 gate"
    assert "nightly-gates" in targets, (
        "Makefile must declare nightly-gates so the wrapper can run the list "
        "and still file a bundle when a gate fails"
    )
    assert "test-t3" in targets, "Makefile must declare test-t3 (ad-hoc T3 runs)"
    assert "test-all" in targets, "Makefile must declare the all-tiers session"

    all_recipe = gates.recipe(REPO, "test-all")
    assert re.search(r"pytest -q\s*$", all_recipe), (
        f"test-all must be a bare all-tiers `pytest -q` (no markexpr, no "
        f"narrowing): {all_recipe!r}"
    )

    prereqs = _target_prereqs("nightly-gates")
    assert prereqs == {
        "lint",
        "log-scrub",
        "scripts-lint",
        "test-all",
        "conformance-3",
    }, prereqs
    for narrowed in ("test", "test-t2", "test-t3"):
        assert narrowed not in prereqs, (
            f"nightly-gates runs the narrowed `{narrowed}` session — its "
            f"run-report is full_run:false and conformance-3 refuses it"
        )

    # GNU make never runs a target's recipe when a prerequisite fails. The
    # public `nightly` target must therefore invoke the filer from its recipe
    # (or a helper that recipe calls), not list the gates as its own prereqs.
    assert "test-all" not in _target_prereqs("nightly")
    assert "conformance-3" not in _target_prereqs("nightly")
    nightly_recipe = gates.recipe(REPO, "nightly")
    helper_text = ""
    helper = REPO / "scripts_dev" / "run_nightly.sh"
    if helper.is_file():
        helper_text = helper.read_text(encoding="utf-8")
    combined = nightly_recipe + "\n" + helper_text
    assert "file_nightly_failure.py" in combined, (
        "make nightly must call file_nightly_failure.py on a non-zero gate run"
    )
    assert "nightly-gates" in combined, combined

    phony = gates.phony_targets(REPO)
    assert "nightly" in phony, "nightly must be .PHONY"
    assert "nightly-gates" in phony, "nightly-gates must be .PHONY"
    assert "test-t3" in phony, "test-t3 must be .PHONY"
    assert "test-all" in phony, "test-all must be .PHONY"


def test_test_target_markexpr_excludes_t2_and_t3():
    """What would make this fail: `make test` collecting t2 or t3, which would
    pull containers / Multipass into review-round.
    """
    recipe = gates.recipe(REPO, "test")
    assert recipe, "Makefile has no `test` recipe"
    assert 'pytest -q -m "not t2 and not t3"' in recipe, recipe


def test_review_round_conformance_is_phase_4_minus_live_tiers():
    """The review-round gate grades phase 4 without the live tiers: t3
    (Multipass) and t2 (docker) stay out so the T1 report is graded honestly
    (D-060). `conformance` is the recipe review-round runs.
    """
    recipe = gates.recipe(REPO, "conformance")
    assert recipe, "Makefile has no `conformance` recipe"
    assert "--phase 4" in recipe, recipe
    assert "--phase 3.5" not in recipe, (
        f"review-round conformance must be phase 4, not 3.5:\n{recipe}")
    assert "--phase 3" not in recipe, (
        f"conformance still grades phase 3 — the phase-4 gate never arms:\n{recipe}")
    assert "--exclude-tier t3" in recipe, (
        f"review-round conformance must omit t3 (no Multipass on the T1 host):\n{recipe}")
    assert "--exclude-tier t2" in recipe, (
        f"review-round conformance must omit t2 (no docker on the T1 host):\n{recipe}")


def test_nightly_gates_use_conformance_3():
    """conformance-3 is the all-tiers phase-3 gate and nightly-gates runs it;
    conformance-2.5 is deleted in the same change (2.5 is closed — grading it
    forever would let phase-3 obligations rot ungraded on the nightly host).
    """
    targets = gates.makefile_targets(REPO)
    assert "conformance-3" in targets, (
        "Makefile must declare conformance-3 as the all-tiers phase-3 gate")
    assert "conformance-2.5" not in targets, (
        "conformance-2.5 must be deleted in the same change that adds "
        "conformance-3 — two all-tiers gates is one gate nobody runs")

    full = gates.recipe(REPO, "conformance-3")
    assert "--phase 3" in full, full
    assert "--exclude-tier" not in full, (
        f"conformance-3 must grade every tier, not omit t2/t3:\n{full}")

    prereqs = _target_prereqs("nightly-gates")
    assert "conformance-3" in prereqs, (
        f"nightly-gates must run conformance-3: {prereqs}")
    assert "conformance-2.5" not in prereqs, prereqs


def test_conformance_3_5_target_exists():
    """What would make this fail: no `conformance-3.5` target, or leaving it
    off `.PHONY` so a same-named file could skip the recipe.
    """
    targets = gates.makefile_targets(REPO)
    assert "conformance-3.5" in targets, (
        "Makefile must declare conformance-3.5 as the phase-3.5 gate")
    phony = gates.phony_targets(REPO)
    assert "conformance-3.5" in phony, "conformance-3.5 must be .PHONY"


def test_conformance_3_5_is_phase_3_5_minus_live_tiers():
    """conformance-3.5 is the 3b gate: --phase 3.5 minus t2/t3. Not all-tiers.

    What would make this fail: an all-tiers 3.5 recipe, or grading phase 3.
    """
    recipe = gates.recipe(REPO, "conformance-3.5")
    assert recipe, "Makefile has no `conformance-3.5` recipe"
    assert "--phase 3.5" in recipe, recipe
    assert "--exclude-tier t2" in recipe, (
        f"conformance-3.5 must omit t2 (no docker on the T1 host):\n{recipe}")
    assert "--exclude-tier t3" in recipe, (
        f"conformance-3.5 must omit t3 (no Multipass on the T1 host):\n{recipe}")


def test_conformance_4_target_exists():
    """What would make this fail: no `conformance-4` target, or leaving it
    off `.PHONY` so a same-named file could skip the recipe.
    """
    targets = gates.makefile_targets(REPO)
    assert "conformance-4" in targets, (
        "Makefile must declare conformance-4 as the phase-4 gate")
    phony = gates.phony_targets(REPO)
    assert "conformance-4" in phony, "conformance-4 must be .PHONY"


def test_conformance_4_is_phase_4_minus_live_tiers():
    """conformance-4 is the phase-4 gate: --phase 4 minus t2/t3. Not all-tiers.

    What would make this fail: an all-tiers 4 recipe, or still grading phase 3.
    """
    recipe = gates.recipe(REPO, "conformance-4")
    assert recipe, "Makefile has no `conformance-4` recipe"
    assert "--phase 4" in recipe, recipe
    assert "--exclude-tier t2" in recipe, (
        f"conformance-4 must omit t2 (no docker on the T1 host):\n{recipe}")
    assert "--exclude-tier t3" in recipe, (
        f"conformance-4 must omit t3 (no Multipass on the T1 host):\n{recipe}")


def test_conformance_3_still_all_tiers_phase_3():
    """conformance-3 stays all-tiers Phase 3 (nightly). Do not claim it
    excludes live tiers. Do not add an all-tiers 4 gate (D-060).
    """
    recipe = gates.recipe(REPO, "conformance-3")
    assert recipe, "Makefile has no `conformance-3` recipe"
    assert "--phase 3" in recipe, recipe
    assert "--exclude-tier" not in recipe, (
        f"conformance-3 stays all-tiers Phase 3 — do not claim it excludes "
        f"live tiers:\n{recipe}")


def test_conformance_4_is_not_a_nightly_gates_prereq():
    """nightly-gates keeps conformance-3. conformance-4 is the review-round
    / phase-4 gate, not the nightly all-tiers Phase 3 gate (D-060).
    """
    prereqs = _target_prereqs("nightly-gates")
    assert "conformance-4" not in prereqs, (
        f"nightly-gates must not run conformance-4: {prereqs}")
    assert "conformance-3" in prereqs, (
        f"nightly-gates must still run conformance-3: {prereqs}")
