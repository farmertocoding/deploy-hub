"""raise_alert — classify, fingerprint, file through finding() (D-037/D-038).

Hand-off to the anti-noise engine is a named pass-through. Task 6 implements
hysteresis/flap/storm; until then after_raise is identity, and
monitor.antinoise.after_raise is imported behind a try/guard when that
module exists. antinoise.observe(fingerprint, ok) is Task 6's API and is
not called from here with invented arguments.
"""
from core.findings import finding
from monitor.alert_rules import classify


def after_raise(row):
    """Identity hook. Task 6 replaces this or lands antinoise.after_raise."""
    return row


def _handoff(row):
    try:
        from monitor import antinoise
    except ImportError:
        antinoise = None
    hook = getattr(antinoise, "after_raise", None) if antinoise else None
    if hook is None:
        hook = after_raise
    result = hook(row)
    return row if result is None else result


def raise_alert(kind, entity, **facts):
    """classify → stable fingerprint → finding() → after_raise.

    ``fingerprint`` and ``source_engine`` may be passed in facts; the default
    fingerprint is ``{kind}:{entity}``. title/body/fix_action ride facts
    into finding() (§6.6). Remaining facts are classify() inputs only.
    """
    severity = classify(kind, **facts)
    fingerprint = facts.get("fingerprint") or f"{kind}:{entity}"
    source_engine = facts.get("source_engine", "monitor.alerts")
    row = finding(
        source_engine,
        fingerprint,
        severity=severity,
        entity=entity,
        title=facts.get("title", ""),
        body=facts.get("body", ""),
        fix_action=facts.get("fix_action", ""),
    )
    return _handoff(row)
