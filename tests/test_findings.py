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
    from core.models import default_workspace

    workspace = overrides.pop("workspace", default_workspace())
    return finding(
        "uptime", fingerprint, workspace=workspace, **{**COPY, **overrides},
    )


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
    with pytest.raises(ValueError, match=r"^accept-risk requires a one-line reason \(§F2\)$"):
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


def test_transition_audit_keeps_actor_source_workspace_and_states():
    """_transition kwargs are the audit trail. Dropping them is a silent gap.

    What would make this fail: actor=None, source omitted, workspace=None,
    or dropping from_state / to_state / fingerprint.
    """
    from django.contrib.auth import get_user_model

    from core.findings import accept_risk, ack, resolve

    user = get_user_model().objects.create_user(
        "finding-actor", password="pw-1234567890",
    )
    row = _file(fingerprint="fp-transition-kw")
    ack(row, actor=user)
    ev = AuditEvent.objects.get(action="finding_acked", object_id=str(row.pk))
    assert ev.actor_id == user.pk
    assert ev.source == "api"
    assert ev.workspace_id == row.workspace_id
    assert ev.detail["from_state"] == Finding.State.OPEN
    assert ev.detail["to_state"] == str(Finding.State.ACKED)
    assert ev.detail["fingerprint"] == "fp-transition-kw"

    resolve(row, actor=user)
    resolved = AuditEvent.objects.get(action="finding_resolved", object_id=str(row.pk))
    assert resolved.actor_id == user.pk
    assert resolved.source == "api"

    other = _file(fingerprint="fp-accept-kw")
    accept_risk(other, "because-risk", actor=user)
    accepted = AuditEvent.objects.get(
        action="finding_risk_accepted", object_id=str(other.pk),
    )
    assert accepted.actor_id == user.pk
    assert accepted.source == "api"
    assert accepted.workspace_id == other.workspace_id
    assert accepted.detail["reason"] == "because-risk"


def test_accept_risk_publishes_accepted_action(monkeypatch):
    """The stream event action is `accepted`, not the audit action name.

    What would make this fail: _publish(..., None) or "ACCEPTED"/"XXacceptedXX".
    """
    from core.findings import accept_risk, ack, resolve

    captured = []
    monkeypatch.setattr(
        "core.findings.events.publish",
        lambda topic, event, history=False: captured.append(event) or 1,
    )
    row = _file(fingerprint="fp-pub-action")
    ack(row)
    resolve(_file(fingerprint="fp-pub-res"))
    accept_risk(_file(fingerprint="fp-pub-acc"), "ok")
    resolved = _file(fingerprint="fp-pub-reopen")
    resolve(resolved)
    _file(fingerprint="fp-pub-reopen")
    actions = [event["action"] for event in captured]
    assert "acked" in actions
    assert "resolved" in actions
    assert "accepted" in actions
    assert "reopened" in actions
    assert None not in actions
    assert "REOPENED" not in actions
    assert "XXreopenedXX" not in actions
    filed = next(event for event in captured if event["action"] == "filed")
    assert set(filed) == {
        "kind", "action", "id", "source_engine", "severity", "entity",
        "title", "body", "fix_action", "state", "fingerprint",
        "first_seen", "last_seen", "workspace_id",
    }
    assert filed["kind"] == "finding"
    assert filed["id"] == row.pk
    assert filed["fingerprint"] == "fp-pub-action"
    assert filed["workspace_id"] == row.workspace_id


def test_audit_severity_column_stays_in_its_enum():
    """Round-2 fix pin: audit() has its own named `severity` (info/warning/
    security). Passing the finding's p1/p2/p3 through that kwarg silently
    stored a value outside the enum in the append-only table — the finding's
    severity must travel in detail, never the column."""
    from core.findings import accept_risk, ack

    row = _file(fingerprint="fp-sev-1")   # p1
    ack(row)
    other = _file(fingerprint="fp-sev-2")
    accept_risk(other, "known and accepted")

    allowed = {c for c, _ in AuditEvent.Severity.choices}
    for event in AuditEvent.objects.filter(object_type="Finding"):
        assert event.severity in allowed, (
            f"{event.action} wrote severity {event.severity!r} outside the enum")

    filed = AuditEvent.objects.get(action="finding_filed", object_id=str(row.pk))
    assert filed.detail["finding_severity"] == "p1"
    assert filed.source == "system"
    assert filed.workspace_id == row.workspace_id
    assert filed.detail["fingerprint"] == "fp-sev-1"


def test_concurrent_create_retry_survives_an_open_transaction(monkeypatch):
    """The lookup-miss/create race, forced, INSIDE an atomic block (the shape
    of every django_db test and any Celery task under transaction.atomic()):
    the loser's IntegrityError must be contained by a savepoint so the retry's
    update path still has a usable transaction — a bare except leaves it
    broken and the retry dies with TransactionManagementError."""
    from django.db import transaction

    winner = _file(fingerprint="fp-race")

    real_filter = Finding.objects.filter
    state = {"missed": False}

    def stale_filter(*args, **kwargs):
        # The loser's existence check races the winner's commit and sees
        # nothing — exactly once; the retry's lookup sees the truth.
        if not state["missed"]:
            state["missed"] = True
            return Finding.objects.none()
        return real_filter(*args, **kwargs)

    monkeypatch.setattr(Finding.objects, "filter", stale_filter)

    with transaction.atomic():
        row = _file(fingerprint="fp-race", body="the loser's fresher copy")
        assert row.pk == winner.pk

    assert Finding.objects.count() == 1
    assert Finding.objects.get(fingerprint="fp-race").body == \
        "the loser's fresher copy"


def test_finding_copy_carries_what_why_and_exact_fix():
    """§6.6 copy contract via the model's fields: title (what), body (why it
    matters), fix_action (exact fix). The helper refuses blank ones — six
    engines, one voice, no empty amber."""
    for missing in ("title", "body", "fix_action"):
        with pytest.raises(ValueError, match=missing):
            _file(fingerprint=f"fp-copy-{missing}", **{missing: "   "})
        with pytest.raises(ValueError, match=missing):
            _file(fingerprint=f"fp-copy-empty-{missing}", **{missing: ""})
        with pytest.raises(ValueError, match=missing):
            _file(fingerprint=f"fp-copy-none-{missing}", **{missing: None})
    assert Finding.objects.count() == 0

    row = _file(fingerprint="fp-copy-ok")
    assert row.title and row.body and row.fix_action


_COPY_REFUSAL = (
    r"^a Finding must carry a non-blank title "
    r"\(§6.6 copy: what / why it matters / exact fix\)$"
)


def test_finding_refuses_explicit_none_workspace():
    """workspace=None must fail inside finding(), not only as a missing kwarg.

    What would make this fail: dropping the None guard, or raising TypeError
    with a mutated / empty message.
    """
    from core.findings import finding

    with pytest.raises(TypeError, match=r"^finding\(\) requires workspace$"):
        finding("uptime", "fp-none-ws", workspace=None, **COPY)


def test_finding_copy_refuses_empty_none_and_omitted_fields():
    """Whitespace-only is already pinned; empty, None, and a missing key
    must refuse too — `or "XXXX"` would accept them.

    What would make this fail: `fields.get(name, "XXXX")`, `(value or "XXXX")`,
    or a mutated §6.6 refusal string.
    """
    from core.findings import finding
    from core.models import default_workspace

    for blank, fingerprint in (("", "fp-copy-empty"), (None, "fp-copy-none")):
        with pytest.raises(ValueError, match=_COPY_REFUSAL):
            _file(fingerprint=fingerprint, title=blank)

    kwargs = {k: v for k, v in COPY.items() if k != "title"}
    with pytest.raises(ValueError, match=_COPY_REFUSAL):
        finding(
            "uptime", "fp-copy-omit",
            workspace=default_workspace(), **kwargs,
        )
    assert Finding.objects.filter(
        fingerprint__in=("fp-copy-empty", "fp-copy-none", "fp-copy-omit"),
    ).count() == 0


def test_omitted_copy_field_is_validated_as_empty_string(monkeypatch):
    """The create path must pass `""` for a missing copy field, not None.

    What would make this fail: `fields.get(name, None)` or dropping the
    default so `.get` returns None.
    """
    import core.findings as findings
    from core.models import default_workspace

    seen = []
    real = findings._require_copy_values

    def wrapped(copy):
        seen.append(dict(copy))
        return real(copy)

    monkeypatch.setattr(findings, "_require_copy_values", wrapped)
    kwargs = {k: v for k, v in COPY.items() if k != "title"}
    with pytest.raises(ValueError, match=_COPY_REFUSAL):
        findings.finding(
            "uptime", "fp-copy-get-default",
            workspace=default_workspace(), **kwargs,
        )
    assert seen
    assert seen[0]["title"] == ""
    assert seen[0]["body"] == COPY["body"]
    assert seen[0]["fix_action"] == COPY["fix_action"]


def test_finding_event_wire_shape_is_the_inbox_contract():
    """Task 13 inbox keys. Renaming a wire key is a silent consumer break.

    What would make this fail: `"XXkindXX"` / `"KIND"` or any other key
    decoration on the published event dict.
    """
    from core.findings import finding_event

    row = _file(fingerprint="fp-wire")
    assert finding_event(row, "filed") == {
        "kind": "finding",
        "action": "filed",
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
        "workspace_id": row.workspace_id,
    }


def test_finding_create_passes_first_seen_and_last_seen(monkeypatch):
    """Filing must set both timestamps at the create() call, not rely on
    the model default happening to match.

    What would make this fail: dropping first_seen=now or last_seen=now
    from Finding.objects.create.
    """
    captured = {}
    real = Finding.objects.create

    def wrapped(*args, **kwargs):
        captured.update(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(Finding.objects, "create", wrapped)
    row = _file(fingerprint="fp-seen")
    assert "first_seen" in captured
    assert "last_seen" in captured
    assert captured["first_seen"] == captured["last_seen"]
    assert row.first_seen == captured["first_seen"]
    assert row.last_seen == captured["last_seen"]


def test_finding_filed_and_reopened_audit_call_kwargs(monkeypatch):
    """finding() must pass source, workspace, and fingerprint into audit().

    Stored-row inference would hide workspace=None; the call site is the
    contract. What would make this fail: source omitted/"XXsystemXX"/"SYSTEM",
    workspace=None, or dropping fingerprint=.
    """
    import core.findings as findings
    from core.findings import resolve

    calls = []
    real_audit = findings.audit

    def wrapped(*args, **kwargs):
        calls.append(kwargs)
        return real_audit(*args, **kwargs)

    monkeypatch.setattr(findings, "audit", wrapped)
    row = _file(fingerprint="fp-filed-kw")
    filed = calls[0]
    assert filed["source"] == "system"
    assert filed["workspace"] == row.workspace
    assert filed["fingerprint"] == "fp-filed-kw"
    assert filed["finding_severity"] == "p1"

    resolve(row)
    calls.clear()
    again = _file(fingerprint="fp-filed-kw")
    assert again.pk == row.pk
    assert again.state == Finding.State.OPEN
    reopened = calls[0]
    assert reopened["source"] == "system"
    assert reopened["workspace"] == row.workspace
    assert reopened["fingerprint"] == "fp-filed-kw"
