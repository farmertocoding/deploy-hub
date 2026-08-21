"""ensure_dns: mesh_only skips; public list-then-diff upsert (D6)."""
import pytest

from core.transport import FakeTransport
from providers.fakes import FakeDnsProvider

DOMAIN = "app.example.com"
ZONE = "example.com"
ORIGIN = "127.0.0.1"


class CountingDns(FakeDnsProvider):
    """Records list/upsert order so tests can see list-then-diff, not blind upsert."""

    def __init__(self):
        super().__init__()
        self.ops = []
        self.upserts = []

    def list_records(self, zone):
        self.ops.append("list")
        return super().list_records(zone)

    def upsert_record(self, zone, name, rtype, values, *, proxied=False, ttl=None):
        self.ops.append("upsert")
        self.upserts.append({
            "zone": zone, "name": name, "rtype": rtype,
            "values": list(values), "proxied": proxied, "ttl": ttl,
        })
        return super().upsert_record(
            zone, name, rtype, values, proxied=proxied, ttl=ttl,
        )


def _seed(dns, *, values, name=DOMAIN, rtype="A"):
    records = dns.zones.setdefault(ZONE, {})
    records["rec-seed"] = {
        "id": "rec-seed", "name": name, "rtype": rtype,
        "values": list(values), "proxied": True, "ttl": None,
    }


def _desired(dns, *, exposure="public", site=None, transport=None):
    desired = {
        "transport": transport if transport is not None else FakeTransport(),
        "site_slug": "app",
        "deployment_id": 4,
        "manifest_body": {"exposure": exposure, "domain": DOMAIN},
        "dns": dns,
        "zone": ZONE,
        "domain": DOMAIN,
        "dns_values": [ORIGIN],
    }
    if site is not None:
        desired["site"] = site
    return desired


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.django_db
def test_mesh_only_skips_dns():
    """mesh_only must not list or upsert DNS — there is no public record to converge.

    What would make this fail: calling upsert_record (or list_records) when
    exposure is mesh_only on the Manifest body or on Site.exposure.
    """
    from core.models import Project, Site
    from deploys.steps import ensure_dns

    dns = CountingDns()
    ensure_dns(_desired(dns, exposure="mesh_only"))
    assert dns.upserts == []
    assert dns.ops == []

    project = Project.objects.create(name="mesh", slug="p-dns-mesh")
    site = Site.objects.create(
        project=project, name="mesh", exposure=Site.Exposure.MESH_ONLY,
    )
    dns = CountingDns()
    ensure_dns(_desired(dns, exposure="public", site=site))
    assert dns.upserts == []
    assert "upsert" not in dns.ops

    public_site = Site.objects.create(
        project=project, name="mesh-body", exposure=Site.Exposure.PUBLIC,
    )
    dns = CountingDns()
    ensure_dns(_desired(dns, exposure="mesh_only", site=public_site))
    assert dns.upserts == []
    assert dns.ops == []


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
@pytest.mark.django_db
def test_public_list_then_diff_upsert():
    """Public DNS lists first, then upserts only when (name, rtype) values differ.

    What would make this fail: upserting without list_records, upserting a
    matching (name, rtype), or skipping the upsert when listed values differ.
    """
    from core.models import DnsRecord, Project, Site
    from deploys.steps import ensure_dns

    project = Project.objects.create(name="pub", slug="p-dns-pub")
    site = Site.objects.create(project=project, name="pub", domain=DOMAIN)
    dns = CountingDns()
    _seed(dns, values=["1.1.1.1"])
    ensure_dns(_desired(dns, site=site))

    assert dns.ops[0] == "list"
    assert "upsert" in dns.ops
    assert dns.upserts
    hit = dns.upserts[0]
    assert hit["zone"] == ZONE
    assert hit["name"] == DOMAIN
    assert hit["rtype"] == "A"
    assert ORIGIN in hit["values"]

    row = DnsRecord.objects.get(site=site, name=DOMAIN, rtype="A")
    assert ORIGIN in row.value

    dns.ops.clear()
    dns.upserts.clear()
    _seed(dns, values=[ORIGIN])
    ensure_dns(_desired(dns, site=site))
    assert dns.ops[0] == "list"
    assert dns.upserts == []


@pytest.mark.req("PIPE-D6-IDEMPOTENT-STEPS")
def test_second_dns_zero_mutating_calls():
    """A second ensure_dns against an already-matching set records no upserts.

    What would make this fail: upserting on the second call, or any Transport
    run/put for a step that only talks to DnsProvider.
    """
    from deploys.steps import ensure_dns

    dns = CountingDns()
    transport = FakeTransport()
    desired = _desired(dns, transport=transport)
    ensure_dns(desired)
    assert dns.upserts, "first call must upsert an empty zone so the second can skip"

    dns.ops.clear()
    dns.upserts.clear()
    transport.calls.clear()
    ensure_dns(desired)
    assert dns.upserts == []
    assert "upsert" not in dns.ops
    assert transport.mutating_calls() == []
