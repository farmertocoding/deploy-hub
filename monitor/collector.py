"""One SSH session per target per minute: put a script, probe it once (C3)."""
import hashlib
import json
import time
from pathlib import Path

from core.hubfs import ensure_hub_dir, hub_join, ssh_user_from

SCHEMA_VERSION = 1
REMOTE_SCRIPT = hub_join("collect-once")
_SCRIPT_PATH = Path(__file__).with_name("collect_once.py")


def jitter_s(target_id):
    """Stable 0..59 second offset so fleet SSH is not aligned on the minute."""
    digest = hashlib.sha256(str(target_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 60


def _target_id(target):
    return target.pk


def remote_script(target):
    """On-target collector path: ~/.hub/collect-once (mode 0700), never /tmp."""
    return hub_join("collect-once", ssh_user=ssh_user_from(target))


def collect(target, transport, *, now=None, sleep=None, tick_started=None, monotonic=None):
    """Put the collector script, probe it once, return the pinned JSON dict.

    ``sleep`` is jitter (T1 injects a no-op). Jitter is an offset from
    ``tick_started`` so collect_all does not stack full sleeps. ``now`` is
    accepted for callers that already thread a clock; the script's ``ts`` is
    authoritative unless ``now`` is passed.
    """
    sleeper = time.sleep if sleep is None else sleep
    mono = monotonic or time.monotonic
    tid = _target_id(target)
    if tick_started is None:
        sleeper(jitter_s(tid))
    else:
        sleeper(max(0, jitter_s(tid) - (mono() - tick_started)))
    user = ssh_user_from(target)
    ensure_hub_dir(transport, user)
    remote = hub_join("collect-once", ssh_user=user)
    transport.put(_SCRIPT_PATH.read_bytes(), remote, mode=0o700)
    # argv[3] "-" keeps the target's default log path; argv[4] is the stored
    # inode so the script resets to byte 0 when the file was rotated (§C4).
    result = transport.probe([
        remote, str(tid), str(_stored_offset(target)), "-",
        str(_stored_inode(target)),
    ])
    if not result.ok:
        raise RuntimeError(result.stderr or "collector script failed")
    payload = json.loads(result.stdout)
    payload["target_id"] = tid
    payload["schema_version"] = SCHEMA_VERSION
    if now is not None:
        payload["ts"] = now.isoformat() if hasattr(now, "isoformat") else str(now)
    _persist_collect(target, payload, now=now)
    return payload


def _stored_offset(target):
    raw = getattr(target, "collect_log_offset", None)
    if raw in (None, ""):
        return 0
    return int(raw)


def _stored_inode(target):
    raw = getattr(target, "collect_log_inode", None)
    if raw in (None, ""):
        return 0
    return int(raw)


def _persist_collect(target, payload, *, now=None):
    """Remember inode/offset and the JSON so the reconciler can ride this minute."""
    chunk = payload.get("log_chunk") or {}
    try:
        inode = int(chunk.get("inode") or 0)
    except (TypeError, ValueError):
        inode = 0
    try:
        offset = int(chunk.get("offset") or 0)
    except (TypeError, ValueError):
        offset = 0
    target.collect_log_inode = inode
    target.collect_log_offset = offset
    stored = dict(payload)
    chunk = dict(stored.get("log_chunk") or {})
    chunk.pop("bytes", None)
    stored["log_chunk"] = chunk
    target.collect_payload = stored
    from django.db.models import Model
    from django.utils import timezone

    collected_at = timezone.now()
    target.collect_at = collected_at
    if not isinstance(target, Model):
        return
    target.save(update_fields=[
        "collect_log_inode", "collect_log_offset", "collect_payload", "collect_at",
    ])
    try:
        from monitor.host_metrics import persist_sample

        persist_sample(target, payload, now=now)
    except Exception as exc:
        from core.audit import audit

        audit(
            "host-metric-persist-failed",
            target,
            source="system",
            severity="warning",
            error=type(exc).__name__,
        )
