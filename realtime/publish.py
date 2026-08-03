"""publish(topic, event, history=False) — the only API producers need (§3.5/§D7).

One atomic Redis operation (Lua) assigns the per-topic sequence and, for
history=True topics, appends the {seq, event} entry to a capped history list —
so a snapshot can never observe a seq whose history entry isn't written yet
(round-1 finding: INCR→RPUSH as two steps let a reconnecting client permanently
drop the in-between event). The snapshot endpoint returns those entries; panels
repaint from them, then stream from seq. Real product topics (Phase 2+) snapshot
from their own tables instead; history is for log-style topics.

Backend selection keys on the configured channel layer (round-1 finding: keying
on REDIS_PASSWORD misroutes a passwordless-Redis deployment into process-local
counters while events fan out cross-process).
"""
import json

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

HISTORY_CAP = 500  # per topic; log-style topics only

# KEYS[1]=seq key, KEYS[2]=history key; ARGV[1]=event json, ARGV[2]=history flag
_PUBLISH_LUA = """
local seq = redis.call('INCR', KEYS[1])
if ARGV[2] == '1' then
  redis.call('RPUSH', KEYS[2], string.format('{"seq":%d,"event":%s}', seq, ARGV[1]))
  redis.call('LTRIM', KEYS[2], -__CAP__, -1)
end
return seq
""".replace("__CAP__", str(HISTORY_CAP))


def _uses_redis():
    backend = settings.CHANNEL_LAYERS["default"]["BACKEND"]
    return "redis" in backend.lower()


def _redis():
    import redis

    return redis.Redis.from_url(settings.REDIS_URL)


_local_seqs = {}
_local_history = {}


def _next_seq(topic, event, history):
    if _uses_redis():
        return int(_redis().eval(
            _PUBLISH_LUA, 2, f"evt:seq:{topic}", f"evt:log:{topic}",
            json.dumps(event), "1" if history else "0",
        ))
    # Dev fallback (in-memory channel layer): process-local counter.
    _local_seqs[topic] = _local_seqs.get(topic, 0) + 1
    seq = _local_seqs[topic]
    if history:
        _local_history.setdefault(topic, []).append({"seq": seq, "event": event})
        del _local_history[topic][:-HISTORY_CAP]
    return seq


def current_seq(topic):
    if _uses_redis():
        return int(_redis().get(f"evt:seq:{topic}") or 0)
    return _local_seqs.get(topic, 0)


def topic_history(topic):
    """[{seq, event}] recorded with history=True, oldest first (snapshot `data`)."""
    if _uses_redis():
        raw = _redis().lrange(f"evt:log:{topic}", 0, -1)
        return [json.loads(x) for x in raw]
    return list(_local_history.get(topic, []))


def publish(topic, event, history=False):
    seq = _next_seq(topic, event, history)
    layer = get_channel_layer()
    async_to_sync(layer.group_send)(
        topic, {"type": "topic.event", "topic": topic, "seq": seq, "event": event}
    )
    return seq
