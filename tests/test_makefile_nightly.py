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


def test_nightly_prereqs_include_test_t3_and_conformance_2_5():
    """What would make this fail: no nightly target, or nightly omitting the T3
    suite / all-tiers conformance gate that D-023 named as the host of record.
    """
    targets = gates.makefile_targets(REPO)
    assert "nightly" in targets, "Makefile must declare nightly as the local T3 gate"
    assert "test-t3" in targets, "Makefile must declare test-t3"

    prereqs = _target_prereqs("nightly")
    assert "test-t3" in prereqs, prereqs
    assert "conformance-2.5" in prereqs, prereqs
    assert prereqs == {
        "lint",
        "log-scrub",
        "scripts-lint",
        "test",
        "test-t2",
        "test-t3",
        "conformance-2.5",
    }, prereqs

    phony = gates.phony_targets(REPO)
    assert "nightly" in phony, "nightly must be .PHONY"
    assert "test-t3" in phony, "test-t3 must be .PHONY"


def test_test_target_markexpr_excludes_t2_and_t3():
    """What would make this fail: `make test` collecting t2 or t3, which would
    pull containers / Multipass into review-round.
    """
    recipe = gates.recipe(REPO, "test")
    assert recipe, "Makefile has no `test` recipe"
    assert 'pytest -q -m "not t2 and not t3"' in recipe, recipe
