"""Snapshot endpoint rides the same authorize_topic() choke point as the socket
(round-1 finding, flagged independently by three reviewers: the HTTP read path
bypassed §D7's single authorization point)."""

import pytest

pytestmark = pytest.mark.django_db


def _enrolled_client(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    u = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=u, name="phone", confirmed=True)
    client.login(username="joseph", password="a-long-dev-password")
    return client


@pytest.mark.req("P0-AUTHZ-TOPIC")
def test_snapshot_requires_authentication(client):
    assert client.get("/api/topics/demo.x.log/snapshot/").status_code == 403


@pytest.mark.req("P0-AUTHZ-TOPIC")
def test_snapshot_refuses_unauthorized_topic(client):
    _enrolled_client(client)
    # Disallowed prefix and bad charset both fail exactly like a ws subscribe would.
    assert client.get("/api/topics/vault.secrets/snapshot/").status_code == 403
    r = client.get("/api/topics/demo.ok.log/snapshot/")
    assert r.status_code == 200
    assert set(r.json()) == {"seq", "data"}


@pytest.mark.req("P0-REALTIME")
def test_snapshot_history_entries_carry_seq(client):
    """History entries are {seq, event} written atomically with the counter
    (round-1 finding: a snapshot could observe seq N with event N missing)."""
    from realtime.tasks import demo_stream_logs

    _enrolled_client(client)
    demo_stream_logs("seq-x", delay=0)
    body = client.get("/api/topics/demo.seq-x.log/snapshot/").json()
    seqs = [e["seq"] for e in body["data"]]
    assert seqs == sorted(seqs) and len(seqs) == 9
    assert body["seq"] == seqs[-1]
    assert body["data"][0]["event"]["line"].startswith("cloning")
