"""z-score attack detector over TrafficStat minute rows (SEC-L5, D-057)."""
import math
import statistics
from dataclasses import dataclass
from datetime import timedelta

from django.utils import timezone

WINDOW_MINUTES = 60
MIN_SAMPLES = 10
Z_TRIP = 3.0
Z_RELAX = 1.5
MIN_REQUESTS = 30


@dataclass(frozen=True)
class AttackSignal:
    z: float
    requests: int
    ips: tuple


def detect(site, *, now=None):
    """Return an AttackSignal when the latest minute is attack-shaped."""
    score = score_site(site, now=now)
    if score is None or score.requests < MIN_REQUESTS:
        return None
    if score.z >= Z_TRIP:
        return score
    return None


def should_relax(site, *, now=None):
    score = score_site(site, now=now)
    if score is None:
        return False
    return score.z < Z_RELAX


def score_site(site, *, now=None):
    from core.models import TrafficStat

    now = (now or timezone.now()).replace(second=0, microsecond=0)
    since = now - timedelta(minutes=WINDOW_MINUTES)
    rows = list(
        TrafficStat.objects.filter(
            site=site,
            granularity=TrafficStat.Granularity.MINUTE,
            bucket_start__gte=since,
            bucket_start__lte=now,
        ).order_by("bucket_start")
    )
    if len(rows) < MIN_SAMPLES + 1:
        return None
    latest = rows[-1]
    baseline = [row.requests for row in rows[:-1]]
    mean = statistics.mean(baseline)
    stdev = statistics.pstdev(baseline) if len(baseline) > 1 else 0.0
    if stdev == 0:
        z = math.inf if latest.requests > mean else 0.0
    else:
        z = (latest.requests - mean) / stdev
    return AttackSignal(z=float(z), requests=int(latest.requests), ips=tuple(_ips(site)))


def _ips(site):
    target = getattr(site, "primary_target", None)
    if target is None:
        return ()
    payload = getattr(target, "collect_payload", None) or {}
    if not isinstance(payload, dict):
        return ()
    chunk = payload.get("log_chunk") if isinstance(payload.get("log_chunk"), dict) else {}
    summary = chunk.get("summary") or payload.get("summary") or {}
    if not isinstance(summary, dict):
        return ()
    out = []
    for item in summary.get("top_ips") or []:
        if isinstance(item, (list, tuple)) and item:
            ip = str(item[0]).strip()
        elif isinstance(item, str):
            ip = item.strip()
        else:
            continue
        if ip:
            out.append(ip)
    return tuple(out)
