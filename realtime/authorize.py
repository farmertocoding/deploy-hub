"""authorize_topic — the single choke point every subscribe passes (§A1/§D7)."""
import re

# Topic string = Channels group name verbatim; enforce the allowed charset (§D7).
TOPIC_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,90}$")

# Phase 0 topics. Later phases append here — never bypass this table.
ALLOWED_PREFIXES = (
    "demo.",       # demo job log streams
    "alerts",
    "site.",       # site.{id}.status (warming, data-stale, recreate-down)
    "deploy.",     # deploy.{id}.status (named §D2 step failure)
)


def authorize_topic(user, topic):
    if not (user and user.is_authenticated):
        return False
    if not TOPIC_RE.match(topic):
        return False
    prefixes = tuple(p for p in ALLOWED_PREFIXES if p.endswith("."))
    return topic == "alerts" or topic.startswith(prefixes)
