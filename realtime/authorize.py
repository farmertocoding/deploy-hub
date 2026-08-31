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
    if not (topic in exact or topic.startswith(prefixes)):
        return False
    return _topic_visible(user, topic)


def _has_workspace(user):
    if getattr(user, "pk", None) is None:
        return False
    from core.rbac import resolve_workspace

    return resolve_workspace(user) is not None


def _topic_visible(user, topic):
    if topic in ("findings", "map.graph"):
        return _has_workspace(user)
    if topic.startswith("demo."):
        return True
    parts = topic.split(".")
    if len(parts) < 2 or not parts[1].isdigit():
        return True
    obj_id = int(parts[1])
    kind = parts[0]
    from core.rbac import workspace_membership

    if kind == "site":
        from core.models import Site

        site = Site.objects.filter(pk=obj_id).select_related("project").first()
        return bool(site and workspace_membership(user, site.project.workspace))
    if kind == "host":
        from core.models import Target

        target = Target.objects.filter(pk=obj_id).select_related("zone").first()
        return bool(target and workspace_membership(user, target.zone.workspace))
    if kind == "deploy":
        from deploys.models import Deployment

        dep = Deployment.objects.filter(pk=obj_id).select_related(
            "manifest__site__project",
        ).first()
        return bool(
            dep and workspace_membership(user, dep.manifest.site.project.workspace)
        )
    return True
