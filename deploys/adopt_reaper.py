"""Beat `adopt-temp-reaper` — abandon TTL for CheckRun(kind=adopt).

Design note §1.1(c) / §7 S4. `cleanup` in adopt_flow is the one owner.
This module only selects stale rows, reconstructs seams, and calls cleanup.

Load Site from results["site_id"]. Rebuild the provider via
`dns_provider_for(site.dns_zone)` (public) or `resolve_production_seams`
(mesh_only → (None, None)). Never persist a token on the CheckRun or here.
The 24 h window is an abandon TTL, not a Hub-down and not REL-P2.
"""
from datetime import timedelta

from django.utils import timezone
from django.utils.dateparse import parse_datetime

from core.models import CheckRun, Site
from deploys.adopt_flow import cleanup
from deploys.pipeline import _default_transport
from deploys.seams import resolve_production_seams
from providers.registry import dns_provider_for

TTL = timedelta(hours=24)


def reap(*, now=None):
    """Call cleanup for adopt CheckRuns whose results.started_at is older than 24 h."""
    now = now or timezone.now()
    cutoff = now - TTL
    reaped = []
    for run in CheckRun.objects.filter(kind=CheckRun.Kind.ADOPT).order_by("pk"):
        results = run.results or {}
        if results.get("stage") == "cleanup":
            continue
        started = _parse_started(results.get("started_at"))
        if started is None or started > cutoff:
            continue
        site_id = results.get("site_id")
        if not site_id:
            continue
        try:
            site = Site.objects.select_related(
                "dns_zone", "dns_zone__account", "primary_target",
            ).get(pk=site_id)
        except Site.DoesNotExist:
            continue
        temp = results.get("temp_name") or ""
        if not temp and getattr(site, "exposure", None) != "mesh_only":
            continue
        try:
            _reap_one(site)
        except Exception:
            # cleanup files adopt-temp-orphan then re-raises. One bad row
            # must not abort the hourly sweep.
            continue  # nosec B112
        reaped.append(run.pk)
    return {"reaped": reaped}


def _reap_one(site):
    cleanup({
        "site": site,
        "site_slug": site.name,
        "dns": _reconstruct_dns(site),
        "transport": _default_transport(site),
    })


def _reconstruct_dns(site):
    if getattr(site, "exposure", None) == "mesh_only" or not site.dns_zone_id:
        dns, _issuer = resolve_production_seams(site)
        return dns
    return dns_provider_for(site.dns_zone)


def _parse_started(raw):
    if raw is None or raw == "":
        return None
    started = raw if hasattr(raw, "tzinfo") else parse_datetime(str(raw))
    if started is None:
        return None
    if timezone.is_naive(started):
        started = timezone.make_aware(started, timezone.utc)
    return started
