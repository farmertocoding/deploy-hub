"""Allowlisted read-only WAN probe adapters (Wave 4).

Selected from Target.collect_payload["wan_probe_adapter"], never from the
request body. Unknown or missing names return None (refuse-closed).
"""
ALLOWED = frozenset({"empty"})


def wan_probe_for(target):
    """Return a zero-arg callable ``{"forwards": [...]}`` or None."""
    raw = getattr(target, "collect_payload", None)
    payload = raw if isinstance(raw, dict) else {}
    name = str(payload.get("wan_probe_adapter") or "").strip()
    if name not in ALLOWED:
        return None
    if name == "empty":
        return lambda: {"forwards": []}
    return None
