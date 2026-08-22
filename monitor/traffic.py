"""Minute TrafficStat rows from the collector's log chunk (§C4, MON-TRAFFIC-INGEST).

Raw chunks are parsed line by line; a sampled summary (the byte-cap degrade
path) is ingested as-is with `sampled=True` carried through, never dropped.
Malformed lines and hosts that match no Site are counters, not exceptions —
and never leave raw log content in events, audits, or logs. Re-ingesting the
same (inode, offset) window is a no-op: the cursor rides the Target's
collect_payload, which the next collect overwrites anyway.

Publishing goes through core.events (realtime registers the real publisher at
startup): monitor/ must not import the realtime package, whose consumers.py
scanner import would read as a monitor -> scanner edge under ARCH-V6.
"""
import json
from datetime import UTC, datetime

from django.db.models import Model
from django.utils import timezone

from core.events import publish

CURSOR_KEY = "traffic_cursor"


def ingest(target, payload):
    """Land minute TrafficStat rows and publish the topics for this pull.

    Returns {"ok", "rows", "malformed", "unmatched", "deduped"}. Publishes
    ``site.{id}.traffic`` per touched row and ``host.{id}.metrics`` when the
    payload carries metrics. Never raises on bad log content.
    """
    chunk = (payload or {}).get("log_chunk") or {}
    cursor = [_int(chunk.get("inode")), _int(chunk.get("offset"))]
    stored = getattr(target, "collect_payload", None)
    if isinstance(stored, dict) and stored.get(CURSOR_KEY) == cursor:
        return {"ok": True, "rows": 0, "malformed": 0, "unmatched": 0,
                "deduped": True}

    fallback = _payload_minute(payload)
    if chunk.get("sampled"):
        agg, malformed, unmatched = _from_summary(chunk, fallback)
    else:
        agg, malformed, unmatched = _from_lines(chunk, fallback)

    rows = _land(agg)
    _publish_metrics(target, payload)
    _remember_cursor(target, cursor)
    return {"ok": True, "rows": rows, "malformed": malformed,
            "unmatched": unmatched, "deduped": False}


def _int(raw):
    try:
        return int(raw or 0)
    except (TypeError, ValueError):
        return 0


def _payload_minute(payload):
    raw = (payload or {}).get("ts") or ""
    try:
        at = datetime.strptime(str(raw), "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
    except ValueError:
        at = timezone.now()
    return at.replace(second=0, microsecond=0)


def _sites_by_domain():
    from core.models import Site

    return {
        site.domain.lower(): site
        for site in Site.objects.exclude(domain="")
    }


def _from_lines(chunk, fallback_minute):
    """(site, minute) → {requests, bytes, status_counts, sampled} from raw lines."""
    sites = _sites_by_domain()
    agg = {}
    malformed = unmatched = 0
    for line in (chunk.get("bytes") or "").splitlines():
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError:
            malformed += 1
            continue
        if not isinstance(record, dict) or "status" not in record:
            malformed += 1
            continue
        req = record.get("request") if isinstance(record.get("request"), dict) else {}
        host = str(req.get("host") or "").rsplit(":", 1)[0].lower()
        site = sites.get(host)
        if site is None:
            unmatched += 1
            continue
        minute = _line_minute(record, fallback_minute)
        bucket = agg.setdefault(
            (site, minute),
            {"requests": 0, "bytes": 0, "status_counts": {}, "sampled": False},
        )
        bucket["requests"] += 1
        bucket["bytes"] += _int(record.get("size"))
        status = str(record.get("status"))
        bucket["status_counts"][status] = bucket["status_counts"].get(status, 0) + 1
    return agg, malformed, unmatched


def _line_minute(record, fallback_minute):
    ts = record.get("ts")
    if isinstance(ts, (int, float)):
        return datetime.fromtimestamp(float(ts), UTC).replace(second=0, microsecond=0)
    return fallback_minute


def _from_summary(chunk, minute):
    """The degrade path: per-host aggregates land as sampled rows, never dropped."""
    sites = _sites_by_domain()
    summary = chunk.get("summary") if isinstance(chunk.get("summary"), dict) else {}
    agg = {}
    unmatched = 0
    for host, data in (summary.get("hosts") or {}).items():
        if not isinstance(data, dict):
            continue
        site = sites.get(str(host).lower())
        if site is None:
            unmatched += _int(data.get("requests"))
            continue
        counts = data.get("status_counts") if isinstance(
            data.get("status_counts"), dict) else {}
        agg[(site, minute)] = {
            "requests": _int(data.get("requests")),
            "bytes": _int(data.get("bytes")),
            "status_counts": {str(k): _int(v) for k, v in counts.items()},
            "sampled": True,
        }
    return agg, _int(summary.get("malformed")), unmatched


def _land(agg):
    """Upsert minute rows, accumulate counters, publish one event per row."""
    from core.models import TrafficStat

    rows = 0
    for (site, minute), data in agg.items():
        row, created = TrafficStat.objects.get_or_create(
            site=site,
            bucket_start=minute,
            granularity=TrafficStat.Granularity.MINUTE,
            defaults={
                "requests": data["requests"],
                "bytes": data["bytes"],
                "status_counts": data["status_counts"],
                "sampled": data["sampled"],
            },
        )
        if not created:
            row.requests += data["requests"]
            row.bytes += data["bytes"]
            merged = dict(row.status_counts or {})
            for status, n in data["status_counts"].items():
                merged[status] = merged.get(status, 0) + n
            row.status_counts = merged
            row.sampled = row.sampled or data["sampled"]
            row.save(update_fields=["requests", "bytes", "status_counts", "sampled"])
        rows += 1
        publish(f"site.{site.pk}.traffic", {
            "bucket_start": row.bucket_start.isoformat(),
            "granularity": row.granularity,
            "requests": row.requests,
            "bytes": row.bytes,
            "status_counts": row.status_counts,
            "sampled": row.sampled,
        })
    return rows


def _publish_metrics(target, payload):
    metrics = (payload or {}).get("metrics")
    if not isinstance(metrics, dict) or not metrics:
        return
    publish(f"host.{target.pk}.metrics", {"ts": (payload or {}).get("ts"), **metrics})


def _remember_cursor(target, cursor):
    stored = getattr(target, "collect_payload", None)
    if not isinstance(stored, dict):
        stored = {}
    stored[CURSOR_KEY] = cursor
    target.collect_payload = stored
    if isinstance(target, Model):
        target.save(update_fields=["collect_payload"])
