"""One SSH session per target per minute: put a script, probe it once (C3)."""
import hashlib
import json
import time
from pathlib import Path

SCHEMA_VERSION = 1
REMOTE_SCRIPT = "/tmp/hub-collect-once"
_SCRIPT_PATH = Path(__file__).with_name("collect_once.py")


def jitter_s(target_id):
    """Stable 0..59 second offset so fleet SSH is not aligned on the minute."""
    digest = hashlib.sha256(str(target_id).encode("utf-8")).digest()
    return int.from_bytes(digest[:8], "big") % 60


def _target_id(target):
    return target.pk


def collect(target, transport, *, now=None, sleep=None):
    """Put the collector script, probe it once, return the pinned JSON dict.

    ``sleep`` is jitter (T1 injects a no-op). ``now`` is accepted for callers
    that already thread a clock; the script's ``ts`` is authoritative unless
    ``now`` is passed.
    """
    sleeper = time.sleep if sleep is None else sleep
    tid = _target_id(target)
    sleeper(jitter_s(tid))
    transport.put(_SCRIPT_PATH.read_bytes(), REMOTE_SCRIPT, mode=0o755)
    result = transport.probe([REMOTE_SCRIPT, str(tid)])
    if not result.ok:
        raise RuntimeError(result.stderr or "collector script failed")
    payload = json.loads(result.stdout)
    payload["target_id"] = tid
    payload["schema_version"] = SCHEMA_VERSION
    if now is not None:
        payload["ts"] = now.isoformat() if hasattr(now, "isoformat") else str(now)
    return payload
