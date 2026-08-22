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


def test_review_round_prereqs_exclude_test_t3_and_conformance_2_5():
    """What would make this fail: adding test-t3 or conformance-2.5 to review-round,
    which would pull Multipass into the T1 Cloud Agent (D-022 / D-023).
    """
    prereqs = gates.review_round_prerequisites(REPO)
    assert "test" in prereqs
    assert "conformance" in prereqs
    assert "test-t3" not in prereqs, (
        "review-round must not require test-t3 (D-022 / D-023)"
    )
    assert "conformance-2.5" not in prereqs, (
        "review-round must not require conformance-2.5 (D-022 / D-023)"
    )


def test_nightly_grades_one_all_tiers_session_feeding_conformance_2_5():
    """Panel F2 ruling: nightly is ONE all-tiers pytest session (`test-all`,
    bare `pytest -q`) followed by conformance-2.5 reading that session's
    full_run report. Three narrowed sessions (test, test-t2, test-t3) each
    left a full_run:false report the gate hard-refuses, so the old prereq
    list could never exit 0 even when everything passed.

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
        "conformance-2.5",
    }, prereqs
    for narrowed in ("test", "test-t2", "test-t3"):
        assert narrowed not in prereqs, (
            f"nightly-gates runs the narrowed `{narrowed}` session — its "
            f"run-report is full_run:false and conformance-2.5 refuses it"
        )

    # GNU make never runs a target's recipe when a prerequisite fails. The
    # public `nightly` target must therefore invoke the filer from its recipe
    # (or a helper that recipe calls), not list the gates as its own prereqs.
    assert "test-all" not in _target_prereqs("nightly")
    assert "conformance-2.5" not in _target_prereqs("nightly")
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
