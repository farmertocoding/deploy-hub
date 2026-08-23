"""O1 classifier reads Partner FK; prod host-down is not partner-aggregate-down.

C12 fingerprints: partner-site hard-down is site-down:{name}; N≥2 is
partner-aggregate-down:{partner.pk}; partner-tier host down reuses
host-down:{host}. Pass fingerprint= explicitly.
"""
from __future__ import annotations

import itertools
from unittest.mock import patch

import pytest

from core.models import Finding

pytestmark = pytest.mark.django_db

_ZONES = itertools.count(1)
_PORTS = itertools.count(21000)


def _fail_until_open(fingerprint, n=3):
    from monitor.antinoise import observe

    row = None
    for _ in range(n):
        row = observe(fingerprint, False)
    return row


def _zone(slug=None, purpose=None):
    from core.models import NetworkZone

    n = next(_ZONES)
    slug = slug or f"o1-{n}"
    kwargs = {"name": slug, "slug": slug}
    if purpose is not None:
        kwargs["purpose"] = purpose
    return NetworkZone.objects.create(**kwargs)


def _target(host, *, zone=None):
    from core.models import Target

    return Target.objects.create(
        zone=zone or _zone(),
        host=host,
        status=Target.Status.READY,
    )


def _site(name, target, *, domain=None):
    from dns_fixtures import default_dns_zone

    from core.models import Project, Site

    project, _ = Project.objects.get_or_create(
        slug=f"proj-{name}",
        defaults={"name": name, "git_url": "https://example.com/repo.git"},
    )
    return Site.objects.create(
        project=project,
        name=name,
        domain=domain or f"{name}.o1.example",
        primary_target=target,
        dns_zone=default_dns_zone(name=f"{name}.o1.example"),
    )


def _partner_bound(name, target, *, partner=None, tenant=None):
    from core.models import Partner, PartnerSite

    partner = partner or Partner.objects.create(slug=f"p-{name}", name=name)
    site = _site(name, target)
    PartnerSite.objects.create(
        partner=partner, site=site, tenant_ref=tenant or name,
    )
    return partner, site


def _kinds(spy):
    return [call.args[0] for call in spy.call_args_list if call.args]


def _fingerprint_kwargs(spy, kind):
    out = []
    for call in spy.call_args_list:
        if call.args and call.args[0] == kind:
            out.append(call.kwargs.get("fingerprint") or "")
    return out


@pytest.mark.req("PART-KILL-SWITCH")
def test_partner_site_hard_down_fingerprint_is_site_down_name():
    """PartnerSite hard-down is P2 kind partner-site-hard-down, fp site-down:{name}.

    What would make this fail: using partner-aggregate-down for a single site,
    a new colour-only status, or default {kind}:{entity}.
    """
    import monitor.antinoise as antinoise

    target = _target("partner-box.o1.example")
    partner, site = _partner_bound("alpha-p", target)
    fp = f"site-down:{site.name}"
    with patch.object(antinoise, "raise_alert", wraps=antinoise.raise_alert) as spy:
        row = _fail_until_open(fp)
    assert row is not None
    assert row.fingerprint == fp
    assert row.severity == Finding.Severity.P2
    assert "partner-site-hard-down" in _kinds(spy)
    assert "prod-site-hard-down" not in _kinds(spy)
    assert "partner-aggregate-down" not in _kinds(spy)
    fps = _fingerprint_kwargs(spy, "partner-site-hard-down")
    assert fp in fps
    src = (antinoise.__file__)
    text = open(src, encoding="utf-8").read()
    assert "fingerprint=" in text
    assert "PartnerSite" in text or "partner_site" in text


@pytest.mark.req("PART-KILL-SWITCH")
def test_n2_aggregate_fingerprint_is_partner_aggregate_down_partner_pk():
    """N≥2 partner sites down files P1 fingerprint partner-aggregate-down:{pk}.

    What would make this fail: classify(..., aggregate=True) on the site-down
    kind alone, or default partner-aggregate-down:partner:{pk}.
    """
    import monitor.antinoise as antinoise
    from core.models import Partner

    target = _target("agg-box.o1.example")
    partner = Partner.objects.create(slug="agg-p", name="agg-p")
    partner.destination_order = [target.pk]
    partner.save(update_fields=["destination_order"])
    _partner_bound("agg-one", target, partner=partner, tenant="t1")
    _partner_bound("agg-two", target, partner=partner, tenant="t2")
    with patch.object(antinoise, "raise_alert", wraps=antinoise.raise_alert) as spy:
        first = _fail_until_open("site-down:agg-one")
        second = _fail_until_open("site-down:agg-two")
    assert first is not None
    assert second is not None
    assert first.fingerprint == "site-down:agg-one"
    assert second.fingerprint == "site-down:agg-two"
    expected = f"partner-aggregate-down:{partner.pk}"
    row = Finding.objects.get(fingerprint=expected)
    assert row.severity == Finding.Severity.P1
    assert "partner-aggregate-down" in _kinds(spy)
    fps = _fingerprint_kwargs(spy, "partner-aggregate-down")
    assert expected in fps
    assert f"partner-aggregate-down:partner:{partner.pk}" not in fps
    src = open(antinoise.__file__, encoding="utf-8").read()
    assert "fingerprint=" in src
    assert "classify(partner-site-hard-down" not in src.replace(" ", "")


@pytest.mark.req("PART-KILL-SWITCH")
def test_partner_tier_host_down_reuses_host_down_fingerprint():
    """Partner-tier host down is P1 partner-aggregate-down, fp host-down:{host}.

    What would make this fail: partner-aggregate-down:{pk} for a single host,
    or requiring a Target.tier column.
    """
    import monitor.antinoise as antinoise
    from core.models import Partner, Target

    assert not hasattr(Target, "tier") or "tier" not in {
        f.name for f in Target._meta.get_fields()
    }
    target = _target("partner-host.o1.example")
    partner = Partner.objects.create(slug="host-p", name="host-p")
    partner.destination_order = [target.pk]
    partner.save(update_fields=["destination_order"])
    _partner_bound("host-site", target, partner=partner)
    fp = f"host-down:{target.host}"
    with patch.object(antinoise, "raise_alert", wraps=antinoise.raise_alert) as spy:
        row = _fail_until_open(fp)
    assert row is not None
    assert row.fingerprint == fp
    assert row.severity == Finding.Severity.P1
    assert "partner-aggregate-down" in _kinds(spy)
    fps = _fingerprint_kwargs(spy, "partner-aggregate-down")
    assert fp in fps
    assert f"partner-aggregate-down:{partner.pk}" not in fps


@pytest.mark.req("PART-KILL-SWITCH")
def test_prod_host_down_is_not_partner_aggregate_down():
    """Prod host-down / zone-down stay the prod classifier.

    What would make this fail: mapping every host-down: or zone-down: onto
    partner-aggregate-down.
    """
    import monitor.antinoise as antinoise
    from core.models import NetworkZone

    zone = _zone("prod-o1", purpose=NetworkZone.Purpose.PROD)
    target = _target("prod-host.o1.example", zone=zone)
    _site("shop-prod", target)
    host_fp = f"host-down:{target.host}"
    with patch.object(antinoise, "raise_alert", wraps=antinoise.raise_alert) as spy:
        row = _fail_until_open(host_fp)
    assert row is not None
    assert row.fingerprint == host_fp
    kinds = _kinds(spy)
    assert "partner-aggregate-down" not in kinds
    assert "prod-site-hard-down" in kinds

    zone_fp = f"zone-down:{zone.slug}"
    with patch.object(antinoise, "raise_alert", wraps=antinoise.raise_alert) as spy2:
        zone_row = _fail_until_open(zone_fp)
    assert zone_row is not None
    assert zone_row.fingerprint == zone_fp
    assert "partner-aggregate-down" not in _kinds(spy2)
    src = open(antinoise.__file__, encoding="utf-8").read()
    assert "PartnerSite" in src or "partner_site" in src
    assert "destination_order" in src
