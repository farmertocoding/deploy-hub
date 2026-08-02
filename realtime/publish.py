"""publish(topic, event) — the only API producers need (§3.5/§D7).

One Redis INCR for the per-topic sequence, one group_send. Nothing else stored.
Snapshot REST endpoints return {seq, data} read from the same counter.
"""
from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings


def _next_seq(topic):
    if settings.REDIS_PASSWORD:
        import redis

        r = redis.Redis.from_url(settings.REDIS_URL)
        return int(r.incr(f"evt:seq:{topic}"))
    # Dev fallback (in-memory channel layer): process-local counter.
    _local_seqs[topic] = _local_seqs.get(topic, 0) + 1
    return _local_seqs[topic]


_local_seqs = {}


def current_seq(topic):
    if settings.REDIS_PASSWORD:
        import redis

        r = redis.Redis.from_url(settings.REDIS_URL)
        return int(r.get(f"evt:seq:{topic}") or 0)
    return _local_seqs.get(topic, 0)


def publish(topic, event):
    seq = _next_seq(topic)
    layer = get_channel_layer()
    async_to_sync(layer.group_send)(
        topic, {"type": "topic.event", "topic": topic, "seq": seq, "event": event}
    )
    return seq
