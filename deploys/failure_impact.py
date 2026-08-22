"""§F4 partial-states table: failed step × strategy → impact line + actions.

The alert body, the break-glass runbook (Task 16) and the Deploys UI all
read IMPACT from this module. Do not copy the strings elsewhere.
"""
from deploys.models import DeploymentStep

OLD_VERSION_SERVING = "Old version still serving — site unaffected"
SITE_UNREACHABLE = "Site may be unreachable"
SITE_IS_DOWN = "Site is down — old version is not serving"

# Blue-green keeps the previous container on the wire until cutover.
_BLUE_GREEN_DOWN = frozenset({DeploymentStep.Name.CUTOVER})
# Recreate stops the old writer at start_green (ensure_start, review3 §N1).
_RECREATE_DOWN = frozenset({
    DeploymentStep.Name.START_GREEN,
    DeploymentStep.Name.HEALTH_CHECK,
    DeploymentStep.Name.DNS,
    DeploymentStep.Name.ROUTE_TLS,
    DeploymentStep.Name.SMOKE_TEST,
    DeploymentStep.Name.CUTOVER,
})


def _line_for(step, strategy):
    if strategy == "recreate" and step in _RECREATE_DOWN:
        return SITE_IS_DOWN
    if strategy == "blue_green" and step in _BLUE_GREEN_DOWN:
        return SITE_UNREACHABLE
    return OLD_VERSION_SERVING


# THE table. alert / UI / runbook aliases must stay bound to this object.
IMPACT = {
    (name, strategy): _line_for(name, strategy)
    for name in DeploymentStep.Name.values
    for strategy in ("blue_green", "recreate")
}

alert_impact = IMPACT
ui_impact = IMPACT
runbook_impact = IMPACT


def impact_line(step, strategy):
    return IMPACT[(step, strategy)]


def ui_line(step, strategy):
    return IMPACT[(step, strategy)]


def alert_body(step, strategy, *, site="the site"):
    return f"{site}: deploy failed at {step}. {IMPACT[(step, strategy)]}"


def runbook_line(step, strategy):
    return f"Impact: {IMPACT[(step, strategy)]}"


def failure_actions(step, strategy):
    """At most three: Retry from step N / Roll back / Abort & clean up."""
    seq = list(DeploymentStep.Name.values).index(step) + 1
    return [
        {
            "id": "retry",
            "label": f"Retry from step {seq} ({step})",
            "does": (
                f"Resume the deploy at {step} ({strategy}); "
                "earlier succeeded steps are not re-run."
            ),
        },
        {
            "id": "rollback",
            "label": "Roll back",
            "does": "Restore the previous release and stop this deploy.",
        },
        {
            "id": "abort",
            "label": "Abort & clean up",
            "does": "Cancel this deploy and remove in-progress green resources.",
        },
    ]
