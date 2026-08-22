"""authorize_topic — the single choke point every subscribe passes (§A1/§D7)."""
import re

# Topic string = Channels group name verbatim; enforce the allowed charset (§D7).
TOPIC_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,90}$")

# Phase 0 topics. Later phases append here — never bypass this table.
ALLOWED_PREFIXES = (
    "demo.",       # demo job log streams
    "alerts",      # DEPRECATED alias of `findings` (D-045) — see DEPRECATED_ALIASES
    "site.",       # site.{id}.status (warming, data-stale, recreate-down)
    "deploy.",     # deploy.{id}.status (named §D2 step failure)
    "findings",    # the one attention stream (§F2, D-038) — canonical since phase 3
)

# D-045: `findings` is canonical; the Phase-0 `alerts` topic stays authorized
# for exactly one phase as a deprecated alias mapping to the SAME group — same
# seq counter, same payload (realtime/publish.py fans out). Remove the alias
# (this entry and its ALLOWED_PREFIXES row) in Phase 4.
DEPRECATED_ALIASES = {"alerts": "findings"}


def authorize_topic(user, topic):
    if not (user and user.is_authenticated):
        return False
    if not TOPIC_RE.match(topic):
        return False
    prefixes = tuple(p for p in ALLOWED_PREFIXES if p.endswith("."))
    exact = tuple(p for p in ALLOWED_PREFIXES if not p.endswith("."))
    return topic in exact or topic.startswith(prefixes)
