"""Insert HostMetric rows from collector payloads (C3 / D-094)."""
import math

from django.utils import timezone

from core.models import HostMetric


def persist_sample(target, payload, *, now):
    """Write one HostMetric. ts is Hub `now`, never payload["ts"]."""
    metrics = payload.get("metrics") if isinstance(payload, dict) else None
    if not isinstance(metrics, dict):
        return
    HostMetric.objects.create(
        target=target,
        ts=now or timezone.now(),
        cpu=None,
        ram=_pct(metrics.get("mem_pct")),
        disk=_pct(metrics.get("disk_pct")),
        load=_finite_float(metrics.get("load1")),
        cores=_cores(metrics.get("cores")),
    )


def _finite_float(value):
    if isinstance(value, bool) or value is None:
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _pct(value):
    number = _finite_float(value)
    if number is None or number < 0 or number > 100:
        return None
    return number


def _cores(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        return None
    return value
