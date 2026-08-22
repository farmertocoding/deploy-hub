"""The canary rule (alert-protocol §5.3): before the Hub declares a mass
outage it probes a known-good external endpoint — a blind Hub sends one
"Hub egress degraded" P2, never N false site-down pages.
"""
import pytest
from django.conf import settings

pytestmark = pytest.mark.django_db


class RecordingGet:
    def __init__(self, status=200):
        self.status = status
        self.calls = []

    def __call__(self, url, *, host=None, timeout=None):
        self.calls.append(url)
        if isinstance(self.status, Exception):
            raise self.status
        return self.status


def test_canary_failure_collapses_n_site_alerts_to_one_p2():
    from monitor.deadman import declare_mass_outage

    candidates = ["site:blog", "site:scan", "site:shop"]
    alerts = declare_mass_outage(
        candidates, http_get=RecordingGet(status=OSError("egress down")),
    )

    assert len(alerts) == 1
    alert = alerts[0]
    assert alert["severity"] == "p2"
    assert alert["kind"] == "hub-egress-degraded"
    # The one alert carries the would-have-paged list, so the operator sees
    # what the collapse swallowed.
    assert alert["suppressed"] == candidates


def test_canary_success_lets_real_site_alerts_through():
    from monitor.deadman import declare_mass_outage

    candidates = ["site:blog", "site:scan"]
    alerts = declare_mass_outage(candidates, http_get=RecordingGet(status=200))

    assert len(alerts) == 2
    assert [alert["entity"] for alert in alerts] == candidates
    assert all(alert["kind"] == "site-down" for alert in alerts)


def test_canary_is_probed_before_the_declaration_not_after():
    from monitor.deadman import declare_mass_outage

    events = []

    def http_get(url, *, host=None, timeout=None):
        events.append("canary")
        assert url == settings.HUB_CANARY_URL
        assert timeout is not None, "canary timeout must be bounded"
        return 200

    def candidates():
        events.append("declared")
        yield "site:blog"

    alerts = declare_mass_outage(candidates(), http_get=http_get)

    assert len(alerts) == 1
    assert events.index("canary") < events.index("declared"), (
        "the canary must be probed BEFORE any declaration is built"
    )
