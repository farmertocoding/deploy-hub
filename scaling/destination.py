"""SELECT-only overflow home pick (C5/C5b). Never provisions."""
from datetime import timedelta
from urllib.parse import urlparse

from django.conf import settings

from core.models import HostMetric, Partner, Target
from scaling.constants import (
    IDLE_COST_USD,
    IDLE_SIZE,
    MAX_SAMPLE_GAP_S,
    OVERFLOW_HOURLY_USD,
    OVERFLOW_SIZE,
)
from scaling.pressure import has_headroom


def pick_overflow_home(site, *, now):
    """Return (host_or_none, cost, size). SELECT only; miss is the t3 quote."""
    partner_pks = _partner_destination_pks()
    hub = _hub_hostname()
    window_start = now - timedelta(seconds=MAX_SAMPLE_GAP_S)
    candidates = (
        Target.objects.filter(
            status=Target.Status.READY,
            lifecycle=Target.Lifecycle.PERMANENT,
        )
        .exclude(pk=site.primary_target_id)
        .order_by("pk")
    )
    for target in candidates:
        if target.pk in partner_pks:
            continue
        if hub and (target.host or "").casefold() == hub:
            continue
        sample = _latest_in_window(target, now=now, window_start=window_start)
        if sample is None:
            continue
        if not has_headroom(sample):
            continue
        return (target.host, IDLE_COST_USD, IDLE_SIZE)
    return (None, OVERFLOW_HOURLY_USD, OVERFLOW_SIZE)


def _latest_in_window(target, *, now, window_start):
    row = (
        HostMetric.objects.filter(
            target_id=target.pk,
            ts__gte=window_start,
            ts__lte=now,
        )
        .order_by("-ts")
        .first()
    )
    if row is None:
        return None
    return {"ram": row.ram, "load": row.load, "cores": row.cores}


def _partner_destination_pks():
    pks = set()
    for order in Partner.objects.values_list("destination_order", flat=True):
        for x in order or ():
            try:
                pks.add(int(x))
            except (TypeError, ValueError):
                continue
    return pks


def _hub_hostname():
    raw = (getattr(settings, "HUB_PUBLIC_URL", "") or "").strip()
    if not raw:
        return ""
    return (urlparse(raw).hostname or "").casefold()
