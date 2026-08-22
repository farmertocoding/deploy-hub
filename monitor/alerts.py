"""raise_alert — classify, fingerprint, file through finding() (D-037/D-038).

after_raise is the one hand-off seam. monitor.antinoise installs its hook
over this name at import / AppConfig.ready(). observe(fingerprint, ok) is
the probe-level hysteresis API and is not called from here.
"""
from core.findings import finding
from monitor.alert_rules import classify


def after_raise(row):
    """Identity until monitor.antinoise replaces this with its hook."""
    return row


def _handoff(row):
    result = after_raise(row)
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
