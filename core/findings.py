"""finding() — the one-line filing helper §F2 demands, like audit() (§D1).

Every engine emits through here so the attention queue keeps one voice: the
§6.6 copy contract (title = what, body = why it matters, fix_action = exact
fix) is enforced at filing time, the fingerprint is the identity (same
fingerprint updates last_seen, never a second row — D-038), and every create
and every state change writes an AuditEvent and publishes on the canonical
`findings` topic (D-045), so the inbox, the audit trail and the realtime
stream can never disagree.

Accept-risk semantics (§F2): requires a one-line reason; an accepted row stays
quiet when the SAME fingerprint re-fires and re-surfaces only as a NEW row
when the fingerprint changes. A RESOLVED row that re-fires reopens — silence
after resolve would be the queue lying.
"""
from django.db import IntegrityError
from django.utils import timezone

from .audit import audit
from .models import Finding

FINDINGS_TOPIC = "findings"

# The stream port. core may not import realtime — realtime imports scanner for
# its wire escaping (R19-ARCH-1), and the ARCH-V6 gates keep core and monitor
# scanner-free — so the dependency points the only legal direction:
# realtime/apps.py::ready() calls register_stream(publish, current_seq) at
# startup. Filing or transitioning before that wiring is a boot-order bug and
# fails loud rather than dropping events silently.
_stream = None


def register_stream(publish_fn, current_seq_fn):
    global _stream
    _stream = (publish_fn, current_seq_fn)


def findings_seq():
    """Current seq of the `findings` topic — the {seq, data} snapshot half (§D7)."""
    return _require_stream()[1](FINDINGS_TOPIC)


def _require_stream():
    if _stream is None:
        raise RuntimeError(
            "findings stream not wired — realtime.apps.RealtimeConfig.ready() "
            "must call core.findings.register_stream()")
    return _stream

# Copy fields the §6.6 contract requires non-blank at filing time.
_COPY_FIELDS = ("title", "body", "fix_action")

# state -> states a transition may leave it for. RESOLVED is terminal for the
# operator (a recurrence reopens it via finding(), not via a transition).
_ALLOWED = {
    Finding.State.OPEN: {Finding.State.ACKED, Finding.State.RESOLVED,
                         Finding.State.ACCEPTED},
    Finding.State.ACKED: {Finding.State.RESOLVED, Finding.State.ACCEPTED},
    Finding.State.ACCEPTED: {Finding.State.RESOLVED},
    Finding.State.RESOLVED: set(),
}


def finding_event(row, action):
    """The wire shape published on `findings` and consumed by Task 13's inbox."""
    return {
        "kind": "finding",
        "action": action,
        "id": row.pk,
        "source_engine": row.source_engine,
        "severity": row.severity,
        "entity": row.entity,
        "title": row.title,
        "body": row.body,
        "fix_action": row.fix_action,
        "state": row.state,
        "fingerprint": row.fingerprint,
        "first_seen": row.first_seen.isoformat(),
        "last_seen": row.last_seen.isoformat(),
    }


def _publish(row, action):
    _require_stream()[0](FINDINGS_TOPIC, finding_event(row, action))


def finding(source_engine, fingerprint, **fields):
    """Upsert by fingerprint. One line to emit:

        finding("uptime", fp, severity="p1", entity="site:x",
                title=..., body=..., fix_action=...)

    Create publishes `filed`; a re-fire of the same fingerprint refreshes
    last_seen and the copy fields in place (never a second row); a re-fire of
    a RESOLVED row reopens it (audited + published); an ACCEPTED row stays
    accepted until the fingerprint itself changes (§F2).
    """
    now = timezone.now()
    existing = Finding.objects.filter(fingerprint=fingerprint).first()
    if existing is None:
        # Validate the copy BEFORE the row exists — a refused filing must
        # leave nothing behind.
        _require_copy_values({name: fields.get(name, "") for name in _COPY_FIELDS})
        try:
            row = Finding.objects.create(
                fingerprint=fingerprint, source_engine=source_engine,
                first_seen=now, last_seen=now, **fields,
            )
        except IntegrityError:
            # Two engines filing the same fingerprint concurrently: the loser
            # takes the update path — still never a second row.
            return finding(source_engine, fingerprint, **fields)
        audit("finding_filed", row, source="system",
              fingerprint=fingerprint, severity=row.severity)
        _publish(row, "filed")
        return row

    row = existing
    row.source_engine = source_engine
    row.last_seen = now
    for name, value in fields.items():
        setattr(row, name, value)
    reopened = row.state == Finding.State.RESOLVED
    if reopened:
        row.state = Finding.State.OPEN
    _require_copy_values({name: getattr(row, name) for name in _COPY_FIELDS})
    row.save()
    if reopened:
        audit("finding_reopened", row, source="system", fingerprint=fingerprint)
        _publish(row, "reopened")
    return row


def _require_copy_values(copy):
    """§6.6: what / why it matters / exact fix — an empty one is a filing bug."""
    for name, value in copy.items():
        if not (value or "").strip():
            raise ValueError(
                f"a Finding must carry a non-blank {name} "
                "(§6.6 copy: what / why it matters / exact fix)")


def ack(row, *, actor=None, source="api"):
    """A human saw it. Nothing more — ack is not resolve (§F2)."""
    return _transition(row, Finding.State.ACKED, "finding_acked",
                       "acked", actor=actor, source=source)


def resolve(row, *, actor=None, source="api"):
    return _transition(row, Finding.State.RESOLVED, "finding_resolved",
                       "resolved", actor=actor, source=source)


def accept_risk(row, reason, *, actor=None, source="api"):
    """Refuses an empty/whitespace reason (§F2): the grey chip must say why."""
    reason = (reason or "").strip()
    if not reason:
        raise ValueError("accept-risk requires a one-line reason (§F2)")
    row.accepted_reason = reason
    return _transition(row, Finding.State.ACCEPTED, "finding_risk_accepted",
                       "accepted", actor=actor, source=source, reason=reason)


def _transition(row, to_state, action, event_action, *, actor, source, **detail):
    if to_state not in _ALLOWED[row.state]:
        raise ValueError(
            f"cannot move a {row.state} finding to {to_state}")
    from_state = row.state
    row.state = to_state
    row.save()
    audit(action, row, actor=actor, source=source,
          from_state=from_state, to_state=str(to_state),
          fingerprint=row.fingerprint, **detail)
    _publish(row, event_action)
    return row
