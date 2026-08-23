"""T1 Fake partner-site reaper.

Plant leftover partner sites (gone / kill-switched / quota-expired) then
stop containers and detach Caddy routes. Not the VM prefix reaper and not
the cloud tagged-instance reaper.
"""
from __future__ import annotations

import itertools

from core.models import (
    CheckRun,
    NetworkZone,
    Partner,
    PartnerSite,
    Project,
    Site,
    SiteInstance,
    Target,
)
from core.transport import FakeTransport
from monitor.drills import RESULTS_SCHEMA_VERSION, record_run

_SEQ = itertools.count(1)
_PLANTED = []


def plant_orphan(*, transport=None, reason="partner-gone"):
    """Create a partner site with a Fake container+route, then orphan it."""
    transport = transport or FakeTransport()
    n = next(_SEQ)
    slug = f"orphan-{reason}-{n}"
    zone = NetworkZone.objects.create(name=f"z-{slug}", slug=f"z-{slug}")
    target = Target.objects.create(
        zone=zone,
        host=f"{slug}.test",
        status=Target.Status.READY,
    )
    partner = Partner.objects.create(slug=slug, name=slug, pubkey_current="ed25519")
    partner.destination_order = [target.pk]
    partner.save(update_fields=["destination_order"])
    project = Project.objects.create(name=slug, slug=slug)
    site = Site.objects.create(
        project=project,
        name=f"{slug}-site",
        domain=f"app.{slug}.test",
        exposure=Site.Exposure.MESH_ONLY,
        primary_target=target,
    )
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref=slug)
    SiteInstance.objects.create(
        site=site,
        target=target,
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.RUNNING,
        internal_port=20000 + (n % 9000),
    )
    container = f"site-{site.name}"
    route_id = f"site-{site.name}"
    transport.run(["docker", "run", "-d", "--name", container, "partner-orphan"])
    transport.run([
        "curl", "-sf", "-X", "PUT",
        f"http://127.0.0.1:2019/id/{route_id}",
    ])
    rec = {
        "container": container,
        "route_id": route_id,
        "reason": reason,
        "site_id": site.pk,
        "transport": transport,
    }
    if reason == "partner-gone":
        partner.delete()
    elif reason == "kill-switched":
        partner.suspended = True
        partner.save(update_fields=["suspended"])
    elif reason == "quota-expired":
        rec["quota_expired"] = True
    _PLANTED.append(rec)
    return rec


def _stop_named(transport, container, route_id):
    transport.run(["docker", "stop", container])
    transport.run([
        "curl", "-sf", "-X", "DELETE",
        f"http://127.0.0.1:2019/id/{route_id}",
    ])


def reap_orphans(*, transport=None, transport_for=None):
    """Stop leftover partner containers and detach routes. Persist PARTNER_REAPER."""
    cleaned = []
    seen = set()
    for rec in list(_PLANTED):
        t = rec.get("transport") or transport
        if t is None:
            continue
        key = rec["container"]
        if key in seen:
            continue
        seen.add(key)
        _stop_named(t, rec["container"], rec["route_id"])
        cleaned.append(key)
    _PLANTED.clear()

    factory = transport_for
    if factory is None and transport is not None:
        def factory(target, _transport=transport):
            return _transport
    if factory is not None:
        qs = PartnerSite.objects.filter(partner__suspended=True).select_related(
            "site", "site__primary_target",
        )
        for ps in qs:
            site = ps.site
            name = f"site-{site.name}"
            if name in seen:
                continue
            _stop_named(factory(site.primary_target), name, name)
            SiteInstance.objects.filter(site=site).update(
                desired_state=SiteInstance.DesiredState.STOPPED,
                observed_state=SiteInstance.ObservedState.STOPPED,
            )
            seen.add(name)
            cleaned.append(name)

    return record_run(
        CheckRun.Kind.PARTNER_REAPER,
        CheckRun.Status.SUCCEEDED,
        {
            "schema_version": RESULTS_SCHEMA_VERSION,
            "n": len(cleaned),
            "cleaned": cleaned,
        },
    )
