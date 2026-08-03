"""publish(topic, event, history=False) — the only API producers need (§3.5/§D7).

One Redis INCR for the per-topic sequence, one group_send. With history=True the
event is also appended to a capped per-topic history list, which is what the
snapshot endpoint returns — snapshot-then-stream reconnect (§D7) repaints from it,
so lines published while a socket was dead are not lost. Real product topics
(Phase 2+) snapshot from their own tables instead; history is for log-style topics.
"""
import json

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

HISTORY_CAP = 500  # per topic; demo/log topics only


def _redis():
    import redis

    return redis.Redis.from_url(settings.REDIS_URL)


def _next_seq(topic):
    if settings.REDIS_PASSWORD:
        return int(_redis().incr(f"evt:seq:{topic}"))
    # Dev fallback (in-memory channel layer): process-local counter.
    _local_seqs[topic] = _local_seqs.get(topic, 0) + 1
    return _local_seqs[topic]


_local_seqs = {}
_local_history = {}


def current_seq(topic):
    if settings.REDIS_PASSWORD:
        return int(_redis().get(f"evt:seq:{topic}") or 0)
    return _local_seqs.get(topic, 0)


def topic_history(topic):
    """Events recorded with history=True, oldest first (snapshot `data`)."""
    if settings.REDIS_PASSWORD:
        raw = _redis().lrange(f"evt:log:{topic}", 0, -1)
        return [json.loads(x) for x in raw]
    return list(_local_history.get(topic, []))


def publish(topic, event, history=False):
    seq = _next_seq(topic)
    if history:
        if settings.REDIS_PASSWORD:
            r = _redis()
            r.rpush(f"evt:log:{topic}", json.dumps(event))
            r.ltrim(f"evt:log:{topic}", -HISTORY_CAP, -1)
        else:
            _local_history.setdefault(topic, []).append(event)
            del _local_history[topic][:-HISTORY_CAP]
    layer = get_channel_layer()
    async_to_sync(layer.group_send)(
        topic, {"type": "topic.event", "topic": topic, "seq": seq, "event": event}
    )
    return seq
