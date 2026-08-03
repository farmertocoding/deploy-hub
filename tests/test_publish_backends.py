"""Backend parity for the publish path (round-2 finding: the atomic Lua branch —
the very code the seq/history race fix consists of — never executed in the suite;
only the process-local fallback did). fakeredis[lua] runs the real script."""
import json

import fakeredis
import pytest

import realtime.publish as pub

pytestmark = pytest.mark.django_db


@pytest.fixture
def redis_backend(settings, monkeypatch):
    settings.CHANNEL_LAYERS = {
        # InMemory layer keeps group_send local; the BACKEND string is what
        # routes seq/history through Redis — exactly the prod split under test.
        "default": {"BACKEND": "channels_redis.core.RedisChannelLayer_fake_for_test"}
    }
    server = fakeredis.FakeServer()
    monkeypatch.setattr(pub, "_redis", lambda: fakeredis.FakeStrictRedis(server=server))
    monkeypatch.setattr(pub, "get_channel_layer", lambda *a, **k: _NullLayer())
    return server


class _NullLayer:
    async def group_send(self, *a, **k):
        return None


def test_lua_publish_assigns_seq_and_history_atomically(redis_backend):
    assert pub._uses_redis()
    s1 = pub.publish("demo.lua-x.log", {"line": "one"}, history=True)
    s2 = pub.publish("demo.lua-x.log", {"line": 'two "quoted" %s %d 半形'}, history=True)
    s3 = pub.publish("demo.lua-x.log", {"ephemeral": True})  # no history
    assert (s1, s2, s3) == (1, 2, 3)
    assert pub.current_seq("demo.lua-x.log") == 3

    hist = pub.topic_history("demo.lua-x.log")
    assert [h["seq"] for h in hist] == [1, 2]
    assert hist[1]["event"]["line"] == 'two "quoted" %s %d 半形'


def test_lua_history_cap(redis_backend):
    for i in range(pub.HISTORY_CAP + 20):
        pub.publish("demo.lua-cap.log", {"n": i}, history=True)
    hist = pub.topic_history("demo.lua-cap.log")
    assert len(hist) == pub.HISTORY_CAP
    assert hist[-1]["event"]["n"] == pub.HISTORY_CAP + 19
    assert hist[-1]["seq"] == pub.HISTORY_CAP + 20


def test_backends_produce_identical_history_shape(redis_backend):
    """The in-memory fallback independently reimplements the semantics — the two
    must never drift (round-2 finding)."""
    events = [{"line": "a"}, {"done": True, "n": 2}]
    for e in events:
        pub.publish("demo.parity.log", e, history=True)
    redis_hist = pub.topic_history("demo.parity.log")
    redis_seq = pub.current_seq("demo.parity.log")

    # Same operations through the process-local fallback.
    pub._local_seqs.pop("demo.parity.log", None)
    pub._local_history.pop("demo.parity.log", None)
    orig = pub._uses_redis
    pub._uses_redis = lambda: False
    try:
        for e in events:
            pub.publish("demo.parity.log", e, history=True)
        local_hist = pub.topic_history("demo.parity.log")
        local_seq = pub.current_seq("demo.parity.log")
    finally:
        pub._uses_redis = orig

    assert json.dumps(local_hist, sort_keys=True) == json.dumps(redis_hist, sort_keys=True)
    assert local_seq == redis_seq
