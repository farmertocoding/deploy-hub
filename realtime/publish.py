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

Phase 3 (§C4) topics: ``site.{id}.traffic`` (minute TrafficStat aggregates —
counts, never raw log lines) and ``host.{id}.metrics`` (collector
load/mem/disk). Producers live in monitor/ and reach publish() through
core.events (see core/events.py for why the import is inverted); both topics
snapshot from their own tables, so neither keeps history here.

Phase 3 map (§9.6.1): ``map.graph`` is the same shape — table-backed from
NetworkZone/Target/SiteInstance, published on graph change, no history list.
"""
import json

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings

from .authorize import DEPRECATED_ALIASES

HISTORY_CAP = 500  # per topic; log-style topics only

# D-045: a deprecated alias IS its canonical topic — one seq counter, one
# history, and every publish fans out to the alias group names so a Phase-0
# `alerts` subscriber receives exactly what a `findings` subscriber does.
# Delete alongside the DEPRECATED_ALIASES table in Phase 4.
_ALIAS_GROUPS = {}
for _alias, _canonical in DEPRECATED_ALIASES.items():
    _ALIAS_GROUPS.setdefault(_canonical, []).append(_alias)


def _canonical(topic):
    return DEPRECATED_ALIASES.get(topic, topic)

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
    topic = _canonical(topic)
    if _uses_redis():
        return int(_redis().get(f"evt:seq:{topic}") or 0)
    return _local_seqs.get(topic, 0)


def topic_history(topic):
    """[{seq, event}] recorded with history=True, oldest first (snapshot `data`)."""
    topic = _canonical(topic)
    if _uses_redis():
        raw = _redis().lrange(f"evt:log:{topic}", 0, -1)
        return [json.loads(x) for x in raw]
    return list(_local_history.get(topic, []))


def publish(topic, event, history=False):
    topic = _canonical(topic)
    seq = _next_seq(topic, event, history)
    layer = get_channel_layer()
    # Canonical group first, then its deprecated alias groups (D-045): same
    # seq, same event; only the topic label differs, so a subscriber's own
    # filter-by-topic keeps working on either name.
    for group in (topic, *_ALIAS_GROUPS.get(topic, ())):
        async_to_sync(layer.group_send)(
            group, {"type": "topic.event", "topic": group, "seq": seq, "event": event}
        )
    return seq
