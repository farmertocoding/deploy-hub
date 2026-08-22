"""Site.dns_zone + DnsZone identity (D-033): the schema wave's constraints.

A public Site without a DnsZone cannot exist — refused at the DB (check
constraint) and in clean(). mesh_only is the one exposure that may skip DNS.
DnsZone is unique on (provider, name) through its account, so two accounts of
the same provider can never both claim a zone name.
"""
import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

pytestmark = pytest.mark.django_db


def _project(slug):
    from core.models import Project

    return Project.objects.create(name=slug, slug=slug)


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_public_site_without_dns_zone_is_refused_by_constraint():
    """Both enforcement layers refuse: the DB constraint and Site.clean().

    What would make this fail: dns_zone nullable with no condition, or a
    clean() that never looks at exposure.
    """
    from core.models import Site

    project = _project("p3-pub-nozone")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            Site.objects.create(project=project, name="pub", domain="pub.example.com")

    site = Site(project=project, name="pub2", exposure=Site.Exposure.PUBLIC)
    with pytest.raises(ValidationError) as exc:
        site.full_clean()
    assert "dns_zone" in exc.value.message_dict


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_mesh_only_site_may_have_no_dns_zone():
    """mesh_only is the one exposure the FK is nullable for.

    What would make this fail: a constraint that requires dns_zone on every
    row, which would force a DNS-provider object onto tailnet-only sites.
    """
    from core.models import Site

    project = _project("p3-mesh-nozone")
    site = Site.objects.create(
        project=project, name="mesh", exposure=Site.Exposure.MESH_ONLY,
    )
    site.full_clean()
    assert site.dns_zone is None
    assert site.proxied is True  # the Site default, mesh or not


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_dns_zone_unique_per_provider_and_name():
    """(provider, name) is one identity even across two accounts (D-033).

    What would make this fail: uniqueness scoped to the account row only, so
    two Cloudflare accounts could both hold example.com and dns_provider_for
    would have two candidate credentials for one zone.
    """
    from core.models import DnsAccount, DnsZone

    first = DnsAccount.objects.create(provider="cloudflare", label="acct-a")
    second = DnsAccount.objects.create(provider="cloudflare", label="acct-b")
    DnsZone.objects.create(account=first, name="dup.example", provider_zone_id="z-1")

    with pytest.raises(ValidationError):
        DnsZone.objects.create(
            account=second, name="dup.example", provider_zone_id="z-2",
        )
    with pytest.raises(ValidationError):
        DnsZone.objects.create(
            account=first, name="dup.example", provider_zone_id="z-3",
        )
    assert DnsZone.objects.filter(name="dup.example").count() == 1


@pytest.mark.req("DNS-CF-PRODUCT-ADAPTER")
def test_pipeline_passes_a_dnszone_not_a_networkzone():
    """The DNS step hands the provider Site.dns_zone, never a NetworkZone.

    What would make this fail: _assemble_desired still deriving the zone from
    Site.primary_target.zone (a NetworkZone, from which no DNS client is
    constructible — panel r2) or from the manifest-body string only.
    """
    from pipeline_fakes import PipelineTransport, fixture_body, queued_deployment

    from core.models import DnsZone, NetworkZone
    from deploys.models import Deployment
    from deploys.pipeline import execute
    from providers.fakes import FakeDnsProvider

    slug = "dnszone-handoff"
    _site, deployment = queued_deployment(slug, body=fixture_body(slug))
    dns = FakeDnsProvider()
    execute(deployment.pk, transport=PipelineTransport(), dns=dns)
    deployment.refresh_from_db()
    assert deployment.status == Deployment.Status.SUCCEEDED

    zones_seen = [call[1] for call in dns.calls if call[0] == "upsert_record"]
    assert zones_seen, "the public deploy must have upserted at least one record"
    for zone in zones_seen:
        assert isinstance(zone, DnsZone), zone
        assert not isinstance(zone, NetworkZone)
