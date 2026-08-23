"""authorize_topic — the single choke point every subscribe passes (§A1/§D7)."""
import re

# Topic string = Channels group name verbatim; enforce the allowed charset (§D7).
TOPIC_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,90}$")

# Phase 0 topics. Later phases append here — never bypass this table.
# D-045 `alerts` alias of `findings` retired in Phase 4 (D-061).
ALLOWED_PREFIXES = (
    "demo.",       # demo job log streams
    "site.",       # site.{id}.status (warming, data-stale, recreate-down)
    "deploy.",     # deploy.{id}.status (named §D2 step failure)
    "findings",    # the one attention stream (§F2, D-038) — canonical
    "host.",       # host.{id}.metrics (collector load/mem/disk, §C4)
                   # site.{id}.traffic (minute TrafficStat rows, §C4) rides "site."
    "map.graph",   # topology snapshot/topic (§9.6.1, D-041) — table-backed
)


def authorize_topic(user, topic):
    if not (user and user.is_authenticated):
        return False
    if not TOPIC_RE.match(topic):
        return False
    prefixes = tuple(p for p in ALLOWED_PREFIXES if p.endswith("."))
    exact = tuple(p for p in ALLOWED_PREFIXES if not p.endswith("."))
    return topic in exact or topic.startswith(prefixes)
