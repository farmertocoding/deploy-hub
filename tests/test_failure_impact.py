"""UX-F4-FAILURE-IMPACT: one table, every step, both strategies, ≤3 actions.

The alert body, the break-glass runbook (Task 16) and the Deploys UI all
read `deploys.failure_impact.IMPACT`. A second copy of these strings is the
bug this file exists to catch.
"""
import pytest

from deploys.models import DeploymentStep

pytestmark = pytest.mark.req("UX-F4-FAILURE-IMPACT")

STEPS = list(DeploymentStep.Name.values)
STRATEGIES = ("blue_green", "recreate")
# Recreate stops the old writer at start_green (§N1 / ensure_start).
RECREATE_DOWN_STEPS = (
    "start_green", "health_check", "dns", "route_tls", "smoke_test", "cutover",
)


def test_every_step_has_an_impact_line():
    """What would make this fail: a named §D2 step (or a strategy) missing
    from the table, or an empty/whitespace impact line."""
    from deploys import failure_impact as fi

    assert len(STEPS) == 9
    for step in STEPS:
        for strategy in STRATEGIES:
            assert (step, strategy) in fi.IMPACT, (step, strategy)
            line = fi.impact_line(step, strategy)
            assert line and line.strip() == line
            assert (
                "Old version still serving — site unaffected" in line
                or "Site may be unreachable" in line
                or "Site is down" in line
            ), line


def test_recreate_strategy_says_site_is_down_not_old_version_serving():
    """N1: recreate rows after the old writer stops are 'site IS down',
    never 'old version still serving'."""
    from deploys import failure_impact as fi

    for step in RECREATE_DOWN_STEPS:
        line = fi.impact_line(step, "recreate")
        assert "old version still serving" not in line.lower(), (step, line)
        assert "down" in line.lower() or "unreachable" in line.lower(), line

    # Blue-green before cutover still has an old version on the wire.
    assert "old version still serving" in fi.impact_line(
        "health_check", "blue_green").lower()


def test_alert_body_ui_and_runbook_read_the_same_table():
    """What would make this fail: alert / UI / runbook growing their own
    copy of the impact strings."""
    from deploys import failure_impact as fi

    assert fi.alert_impact is fi.IMPACT
    assert fi.ui_impact is fi.IMPACT
    assert fi.runbook_impact is fi.IMPACT
    for step in STEPS:
        for strategy in STRATEGIES:
            line = fi.impact_line(step, strategy)
            assert line == fi.ui_line(step, strategy)
            assert line in fi.alert_body(step, strategy)
            assert line in fi.runbook_line(step, strategy)


def test_failure_offers_at_most_three_actions():
    """Retry from step N / Roll back / Abort & clean up — each names what
    it will do, and the table never offers a fourth."""
    from deploys import failure_impact as fi

    for step in STEPS:
        for strategy in STRATEGIES:
            actions = fi.failure_actions(step, strategy)
            assert 1 <= len(actions) <= 3, (step, strategy, actions)
            labels = [a["label"].lower() for a in actions]
            does = [a["does"] for a in actions]
            assert all(does), (step, "an action has no 'what it will do'")
            assert any("retry" in label for label in labels)
            assert any("roll back" in label for label in labels)
            assert any("abort" in label and "clean" in label for label in labels)
            assert any(step.replace("_", " ") in label or step in label
                       or any(ch.isdigit() for ch in label)
                       for label in labels), labels
