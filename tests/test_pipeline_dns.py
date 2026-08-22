"""ensure_dns over the DnsZone hand-off (Task 1 → Task 3 seam).

desired["dns_zone"] carries the Site.dns_zone row; ensure_dns passes it to
the injected DnsProvider. Idempotence holds across the new hand-off: a
second run against a converged zone records zero mutating provider calls.
"""
import pytest
from dns_fixtures import default_dns_zone

pytestmark = pytest.mark.django_db

DOMAIN = "app.handoff.example"


def _site():
    from core.models import Project, Site

    project = Project.objects.create(name="handoff", slug="p-dns-handoff")
    return Site.objects.create(
        project=project, name="handoff", domain=DOMAIN,
        dns_zone=default_dns_zone("handoff.example"),
    )


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_ensure_dns_twice_records_zero_mutating_calls():
    """Second ensure_dns over the same DnsZone: list only, no upsert/delete.

    What would make this fail: ensure_dns blind-writing through the DnsZone
    path, or diffing against a zone key other than the one it upserts to.
    """
    from core.models import DnsZone
    from deploys.steps import ensure_dns
    from providers.fakes import FakeDnsProvider

    site = _site()
    dns = FakeDnsProvider()
    desired = {
        "site": site,
        "site_slug": site.name,
        "manifest_body": {"exposure": "public", "domain": DOMAIN},
        "dns": dns,
        "dns_zone": site.dns_zone,
        "zone": "handoff.example",
        "domain": DOMAIN,
        "dns_values": ["203.0.113.7"],
    }

    ensure_dns(desired)
    assert dns.mutating_calls(), "first run must converge the empty zone"
    zones_seen = {id(call[1]) for call in dns.calls}
    assert zones_seen == {id(site.dns_zone)}, (
        "every provider call must receive the DnsZone hand-off object"
    )
    assert isinstance(site.dns_zone, DnsZone)

    dns.calls.clear()
    ensure_dns(desired)
    assert dns.mutating_calls() == []
    assert [call[0] for call in dns.calls] == ["list_records"]
