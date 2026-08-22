"""Finding service layer (§F2, D-038): one attention queue, one filing helper.

The named behaviours here are the model's contract with every engine Task 5/6
wires in: same fingerprint never grows a second row, accept-risk demands a
reason and stays quiet until the fingerprint changes, ack is not resolve, and
every state change leaves an AuditEvent.
"""
from datetime import timedelta

import pytest
from django.utils import timezone

from core.models import AuditEvent, Finding

pytestmark = [pytest.mark.django_db, pytest.mark.req("UX-F2-FINDING-MODEL")]

COPY = dict(
    severity="p1",
    entity="site:shop.example.com",
    title="Site is down",
    body="Three consecutive probes failed; visitors see connection errors.",
    fix_action="Check `docker ps` on the target; restart the container.",
)


def _file(fingerprint="fp-uptime-shop", **overrides):
    from core.findings import finding

    return finding("uptime", fingerprint, **{**COPY, **overrides})


def test_same_fingerprint_updates_last_seen_not_a_second_row():
    """What would make this fail: filing with get_or_create defaults only, or
    keying on anything other than the fingerprint."""
    first = _file()
    # Backdate so the re-file's last_seen bump is observable regardless of
    # clock resolution.
    Finding.objects.filter(pk=first.pk).update(
        last_seen=timezone.now() - timedelta(hours=1))

    again = _file(body="Now four consecutive probes failed.")

    assert Finding.objects.count() == 1
    assert again.pk == first.pk
    assert again.last_seen > timezone.now() - timedelta(minutes=5)
    assert again.body == "Now four consecutive probes failed."


def test_accept_risk_requires_a_reason():
    """§F2: accept-risk without a one-line reason is refused — empty and
    whitespace-only both."""
    from core.findings import accept_risk

    row = _file()
    with pytest.raises(ValueError):
        accept_risk(row, "")
    with pytest.raises(ValueError):
        accept_risk(row, "   \t")
    row.refresh_from_db()
    assert row.state == Finding.State.OPEN

    accept_risk(row, "internal-only site; downtime is acceptable")
    row.refresh_from_db()
    assert row.state == Finding.State.ACCEPTED
    assert row.accepted_reason == "internal-only site; downtime is acceptable"


def test_accepted_risk_resurfaces_when_fingerprint_changes():
    """The grey chip stays grey for the SAME condition; a changed fingerprint is
    a new condition and must open a new row, never revive the accepted one."""
    from core.findings import accept_risk

    row = _file(fingerprint="fp-old")
    accept_risk(row, "accepted: dev-only header missing")

    # Same fingerprint re-fires: stays accepted, no second row, no resurface.
    again = _file(fingerprint="fp-old")
    assert again.pk == row.pk
    assert again.state == Finding.State.ACCEPTED
    assert Finding.objects.count() == 1

    # Changed fingerprint: a NEW open row; the accepted one is untouched.
    fresh = _file(fingerprint="fp-new")
    assert fresh.pk != row.pk
    assert fresh.state == Finding.State.OPEN
    row.refresh_from_db()
    assert row.state == Finding.State.ACCEPTED
    assert Finding.objects.count() == 2


def test_ack_is_not_resolve():
    """Ack means 'a human saw it', nothing more: the finding stays un-resolved
    and resolve remains a distinct, later transition."""
    from core.findings import ack, resolve

    row = _file()
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    assert row.state != Finding.State.RESOLVED

    resolve(row)
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED


def test_resolved_finding_reopens_when_it_fires_again():
    """A resolved condition that recurs must resurface as open — silence after
    resolve would be the one attention queue lying."""
    from core.findings import resolve

    row = _file()
    resolve(row)
    again = _file()
    assert again.pk == row.pk
    assert again.state == Finding.State.OPEN


def test_every_transition_writes_an_audit_event():
    """Each state change is one AuditEvent naming the Finding (§D1)."""
    from core.findings import accept_risk, ack, resolve

    row = _file(fingerprint="fp-audit-1")
    ack(row)
    resolve(row)
    other = _file(fingerprint="fp-audit-2")
    accept_risk(other, "known and accepted")
    reopened = _file(fingerprint="fp-audit-1")  # resolved → open again
    assert reopened.state == Finding.State.OPEN

    for action, pk in [
        ("finding_acked", row.pk),
        ("finding_resolved", row.pk),
        ("finding_risk_accepted", other.pk),
        ("finding_reopened", row.pk),
    ]:
        assert AuditEvent.objects.filter(
            action=action, object_type="Finding", object_id=str(pk)
        ).count() == 1, f"missing audit row for {action}"


def test_finding_copy_carries_what_why_and_exact_fix():
    """§6.6 copy contract via the model's fields: title (what), body (why it
    matters), fix_action (exact fix). The helper refuses blank ones — six
    engines, one voice, no empty amber."""
    for missing in ("title", "body", "fix_action"):
        with pytest.raises(ValueError, match=missing):
            _file(fingerprint=f"fp-copy-{missing}", **{missing: "   "})
    assert Finding.objects.count() == 0

    row = _file(fingerprint="fp-copy-ok")
    assert row.title and row.body and row.fix_action
