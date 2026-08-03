"""§D7 snapshot-then-stream: the snapshot must carry what a dead socket missed.
Regression for the exit-demo gap: snapshot data was hardcoded [] — a reconnecting
panel silently lost every line published while the socket was down."""

import pytest

from realtime.publish import current_seq, publish, topic_history
from realtime.tasks import demo_stream_logs

pytestmark = pytest.mark.django_db


@pytest.mark.req("P0-REALTIME")
def test_snapshot_data_carries_history_for_log_topics(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    u = User.objects.create_user("joseph", password="a-long-dev-password")
    TOTPDevice.objects.create(user=u, name="phone", confirmed=True)  # §6.10 gate
    client.login(username="joseph", password="a-long-dev-password")

    demo_stream_logs("hist-x", delay=0)
    r = client.get("/api/topics/demo.hist-x.log/snapshot/")
    assert r.status_code == 200
    body = r.json()
    assert body["seq"] == current_seq("demo.hist-x.log")
    # 8 lines + done event, oldest first — the reconnect repaint has no gap.
    assert len(body["data"]) == 9
    assert body["data"][0]["event"]["line"].startswith("cloning")
    assert body["data"][-1]["event"]["done"] is True


@pytest.mark.req("P0-REALTIME")
def test_history_is_capped_and_off_by_default():
    for i in range(600):
        publish("demo.cap-x.log", {"line": f"l{i}"}, history=True)
    assert len(topic_history("demo.cap-x.log")) == 500  # HISTORY_CAP

    publish("demo.nohist-x.log", {"line": "ephemeral"})
    assert topic_history("demo.nohist-x.log") == []
