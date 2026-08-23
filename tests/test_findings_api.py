"""Findings inbox API + the canonical `findings` topic (§F2, D-045, §D7).

The list/detail endpoints are the table-backed snapshot half of
snapshot-then-stream; the topic (and its deprecated `alerts` alias) is the
stream half. Both must ride the same seq counter or a reconnecting inbox
repaints from a snapshot the stream can contradict.
"""
import pytest

import realtime.publish as pub
from core.models import Finding

pytestmark = [pytest.mark.django_db, pytest.mark.req("UX-F2-FINDING-MODEL")]

COPY = dict(
    severity="p1",
    entity="site:shop.example.com",
    title="Site is down",
    body="Three consecutive probes failed; visitors see connection errors.",
    fix_action="Check `docker ps` on the target; restart the container.",
)


def _file(fingerprint="fp-api-shop", **overrides):
    from core.findings import finding

    return finding("uptime", fingerprint, **{**COPY, **overrides})


def _enrolled_client(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    u = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=u, name="phone", confirmed=True)
    client.login(username="joseph", password="a-long-dev-password")
    return u


class _RecordingLayer:
    def __init__(self):
        self.sent = []

    async def group_send(self, group, message):
        self.sent.append((group, message))


@pytest.fixture
def recorded_layer(monkeypatch):
    layer = _RecordingLayer()
    monkeypatch.setattr(pub, "get_channel_layer", lambda *a, **k: layer)
    # Fresh per-test counters for the canonical topic (process-local fallback).
    pub._local_seqs.pop("findings", None)
    pub._local_history.pop("findings", None)
    return layer


def test_list_requires_session(client):
    """Findings name what is broken and where — operator-only, like every
    sibling endpoint (session + 2FA, §6.10)."""
    assert client.get("/api/v1/findings/").status_code == 403


def test_transition_endpoint_validates_through_serializer(client):
    """§4.5: bad input comes back as the {errors: {field: [{code,message,hint}]}}
    contract, produced by the serializer — not ad-hoc view code."""
    _enrolled_client(client)
    row = _file()

    r = client.post(f"/api/v1/findings/{row.pk}/transition/",
                    {"action": "explode"}, content_type="application/json")
    assert r.status_code == 400
    assert "action" in r.json()["errors"]

    # accept_risk without a reason is refused BY THE SERIALIZER (§F2).
    r = client.post(f"/api/v1/findings/{row.pk}/transition/",
                    {"action": "accept_risk", "reason": "  "},
                    content_type="application/json")
    assert r.status_code == 400
    assert "reason" in r.json()["errors"]
    row.refresh_from_db()
    assert row.state == Finding.State.OPEN

    r = client.post(f"/api/v1/findings/{row.pk}/transition/",
                    {"action": "ack"}, content_type="application/json")
    assert r.status_code == 200
    assert r.json()["data"]["state"] == "acked"


def test_transition_endpoint_refuses_impossible_transitions(client):
    """A resolved finding cannot be acked; the refusal is a 409, not a 500."""
    _enrolled_client(client)
    row = _file()
    from core.findings import resolve

    resolve(row)
    r = client.post(f"/api/v1/findings/{row.pk}/transition/",
                    {"action": "ack"}, content_type="application/json")
    assert r.status_code == 409


def test_findings_topic_requires_authorize_topic(client):
    """`findings` (and the alias) pass the same §D7 choke point as every topic:
    anonymous fails, an enrolled session passes, and the snapshot endpoint
    enforces it identically to the socket."""
    from django.contrib.auth.models import AnonymousUser

    from realtime.authorize import authorize_topic

    assert authorize_topic(AnonymousUser(), "findings") is False
    assert client.get("/api/topics/findings/snapshot/").status_code == 403

    user = _enrolled_client(client)
    assert authorize_topic(user, "findings") is True
    assert authorize_topic(user, "alerts") is True
    assert client.get("/api/topics/findings/snapshot/").status_code == 200


def test_alerts_alias_delivers_the_same_payload_as_findings(recorded_layer):
    """D-045: one attention stream. A filed Finding lands on BOTH group names
    with the same seq and the same event — a Phase-0 `alerts` subscriber and a
    `findings` subscriber can never disagree."""
    _file()

    by_group = {group: msg for group, msg in recorded_layer.sent}
    assert set(by_group) == {"findings", "alerts"}
    assert by_group["findings"]["event"] == by_group["alerts"]["event"]
    assert by_group["findings"]["seq"] == by_group["alerts"]["seq"]
    # The alias shares the canonical seq counter — its snapshot can't drift.
    assert pub.current_seq("alerts") == pub.current_seq("findings")


def test_alerts_topic_is_unauthorized(client):
    """D-045 alias retired (D-061): `alerts` is no longer a subscribe-able topic.

    What would make this fail: leaving `alerts` in ALLOWED_PREFIXES or mapping
    it through DEPRECATED_ALIASES so a Phase-0 subscriber still attaches.
    """
    from realtime.authorize import ALLOWED_PREFIXES, authorize_topic

    user = _enrolled_client(client)
    assert "alerts" not in ALLOWED_PREFIXES
    assert authorize_topic(user, "alerts") is False
    assert client.get("/api/topics/alerts/snapshot/").status_code == 403


def test_findings_topic_unchanged(client, recorded_layer):
    """`findings` stays the one attention stream; publish does not fan out.

    What would make this fail: dropping `findings` from the allow list, or
    keeping an `alerts` alias group so a filed Finding still lands twice.
    """
    from django.contrib.auth.models import AnonymousUser

    from realtime.authorize import ALLOWED_PREFIXES, authorize_topic

    assert "findings" in ALLOWED_PREFIXES
    assert authorize_topic(AnonymousUser(), "findings") is False
    user = _enrolled_client(client)
    assert authorize_topic(user, "findings") is True
    assert client.get("/api/topics/findings/snapshot/").status_code == 200

    _file()
    groups = {group for group, _msg in recorded_layer.sent}
    assert "findings" in groups
    assert "alerts" not in groups
    assert pub.current_seq("findings") >= 1


def test_transitions_publish_on_the_findings_topic(recorded_layer):
    """Every create AND every transition is an event on the canonical topic."""
    from core.findings import ack, resolve

    row = _file()
    ack(row)
    resolve(row)
    actions = [msg["event"]["action"] for group, msg in recorded_layer.sent
               if group == "findings"]
    assert actions == ["filed", "acked", "resolved"]
    seqs = [msg["seq"] for group, msg in recorded_layer.sent if group == "findings"]
    assert seqs == sorted(seqs)


def test_snapshot_returns_seq_and_data(client, recorded_layer):
    """§D7 for a table-backed topic: list and detail return {seq, data}, seq
    from the SAME counter the stream stamps its events with."""
    _enrolled_client(client)
    row = _file()
    other = _file(fingerprint="fp-api-p2", severity="p2",
                  entity="host:web-1", title="Disk 85% full")

    r = client.get("/api/v1/findings/")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"seq", "data"}
    assert body["seq"] == pub.current_seq("findings")
    assert {f["id"] for f in body["data"]} == {row.pk, other.pk}
    assert {"id", "source_engine", "severity", "entity", "title", "body",
            "fix_action", "state", "first_seen", "last_seen",
            "fingerprint"} <= set(body["data"][0])

    # Filters: state / severity / entity (§F2 — every panel is a filtered view).
    assert [f["id"] for f in client.get(
        "/api/v1/findings/?severity=p2").json()["data"]] == [other.pk]
    assert [f["id"] for f in client.get(
        "/api/v1/findings/?entity=host:web-1").json()["data"]] == [other.pk]
    from core.findings import ack

    ack(row)
    assert [f["id"] for f in client.get(
        "/api/v1/findings/?state=acked").json()["data"]] == [row.pk]

    detail = client.get(f"/api/v1/findings/{row.pk}/").json()
    assert set(detail) == {"seq", "data"}
    assert detail["data"]["id"] == row.pk
