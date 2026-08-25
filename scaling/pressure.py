"""Pure same-axis streak decision (C2). No Django, no I/O."""
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone

from scaling.constants import (
    CONSECUTIVE_MINUTES,
    MAX_SAMPLE_GAP_S,
    MEM_PCT_THRESHOLD,
    WINDOW_S,
)

UTC = timezone.utc


def sustained_pressure(samples, *, now):
    """True when five consecutive distinct UTC minutes share one overflow axis."""
    return _overflow_axis(samples, now=now) is not None


def _overflow_axis(samples, *, now):
    clock = _aware_utc(now)
    if clock is None:
        return None
    buckets = _minute_buckets(samples, now=clock)
    if len(buckets) < CONSECUTIVE_MINUTES:
        return None
    newest_sample = buckets[-1][1]
    newest_ts = _aware_utc(_get(newest_sample, "ts"))
    if newest_ts is None:
        return None
    gap = (clock - newest_ts).total_seconds()
    if gap < 0 or gap > MAX_SAMPLE_GAP_S:
        return None
    trailing = buckets[-CONSECUTIVE_MINUTES:]
    minutes = [minute for minute, _ in trailing]
    if not _consecutive(minutes):
        return None
    five = [sample for _, sample in trailing]
    if all(_ram_over(sample) for sample in five):
        return "ram"
    if all(_load_over(sample) for sample in five):
        return "load"
    return None


def _minute_buckets(samples, *, now):
    window_start = now - timedelta(seconds=WINDOW_S)
    by_minute = {}
    for sample in samples or ():
        ts = _aware_utc(_get(sample, "ts"))
        if ts is None or ts < window_start or ts > now:
            continue
        key = ts.replace(second=0, microsecond=0)
        prev = by_minute.get(key)
        prev_ts = _aware_utc(_get(prev, "ts"))
        if prev is None or prev_ts is None or ts >= prev_ts:
            by_minute[key] = sample
    return sorted(by_minute.items(), key=lambda item: item[0])


def _consecutive(minutes):
    for left, right in zip(minutes, minutes[1:], strict=False):
        if right - left != timedelta(minutes=1):
            return False
    return True


def _aware_utc(ts):
    if not isinstance(ts, datetime):
        return None
    if ts.tzinfo is None:
        return None
    return ts.astimezone(UTC)


def _get(sample, key):
    if isinstance(sample, Mapping):
        return sample.get(key)
    return None


def has_headroom(sample):
    """True when ram is numeric <= 85 and load is numeric and not over."""
    if not isinstance(sample, Mapping):
        return False
    ram = _get(sample, "ram")
    load = _get(sample, "load")
    if ram is None or load is None:
        return False
    if not _is_number(ram) or not _is_number(load):
        return False
    if ram > MEM_PCT_THRESHOLD:
        return False
    cores = _get(sample, "cores")
    if cores is None or not _is_number(cores) or cores < 1:
        return True
    return load <= cores


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _ram_over(sample):
    ram = _get(sample, "ram")
    return ram is not None and ram > MEM_PCT_THRESHOLD


def _load_over(sample):
    cores = _get(sample, "cores")
    load = _get(sample, "load")
    return (
        cores is not None
        and cores >= 1
        and load is not None
        and load > cores
    )
