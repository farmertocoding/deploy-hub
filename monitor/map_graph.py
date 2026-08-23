"""Live topology graph — derived from models, never a stored blob (§D3, D-041).

A zone node is a NetworkZone (the network targets sit in). DnsZone is a
DNS-provider object and never a parent on this graph. Hub and the Cloudflare
edge are distinct nodes. Edges carry path ∈ {public, mesh} from Site.exposure.

Seq is read from the same counter other snapshots use (§D7) BEFORE the table
walk, through core.events — monitor must not import realtime (ARCH-V6).
"""
from core import events
from core.models import NetworkZone, Site, SiteInstance, Target

TOPIC = "map.graph"

_NODE_KINDS = ("zone", "host", "container", "hub", "edge")


def advise_topology():
    """Re-run r1–r5 without bumping map.graph (collector payload writes)."""
    try:
        from monitor.topology import evaluate

        evaluate()
    except Exception:
        import logging

        logging.getLogger(__name__).exception("topology advisor failed")


def notify_graph_changed():
    """Bump map.graph so snapshot-then-stream clients refetch the tables.

    r1–r5 re-evaluate on every graph change (§9.6.2) so the advisor cannot
    drift behind the SVG. Failures in the advisor must not swallow the bump.
    """
    events.publish(TOPIC, {"kind": "changed"}, history=False)
    advise_topology()


def graph_snapshot():
    """Return {seq, nodes, edges} built from live rows.

    seq FIRST: an event racing the query is then delivered twice (harmless
    client upsert), never lost.
    """
    seq = events.current_seq(TOPIC)
    nodes, edges = _derive()
    from monitor.topology import attach_findings

    attach_findings(nodes)
    return {"seq": seq, "nodes": nodes, "edges": edges}


def _derive():
    zones = list(NetworkZone.objects.order_by("pk"))
    targets = list(Target.objects.select_related("zone").order_by("pk"))
    instances = list(
        SiteInstance.objects.select_related("site", "target").order_by("pk")
    )
    sites = list(Site.objects.select_related("primary_target").order_by("pk"))

    nodes = [
        _node("hub", "hub", "Hub", "ok"),
        _node("edge", "edge", "Cloudflare", "ok"),
    ]
    for zone in zones:
        nodes.append(_node(f"zone:{zone.pk}", "zone", zone.name, "ok"))
    for target in targets:
        nodes.append(_node(
            f"host:{target.pk}", "host", target.host, target.status,
            parent=f"zone:{target.zone_id}",
        ))
    for inst in instances:
        nodes.append(_node(
            f"container:{inst.pk}", "container", inst.site.name,
            inst.observed_state, parent=f"host:{inst.target_id}",
        ))

    host_ids = {t.pk: f"host:{t.pk}" for t in targets}
    edges = []
    seen = set()
    for site in sites:
        path = "public" if site.exposure == Site.Exposure.PUBLIC else "mesh"
        src = "edge" if path == "public" else "hub"
        for target_id in _site_target_ids(site, instances):
            host_id = host_ids.get(target_id)
            if not host_id:
                continue
            key = (src, host_id, path)
            if key in seen:
                continue
            seen.add(key)
            edges.append({"a": src, "b": host_id, "path": path})
    return nodes, edges


def _site_target_ids(site, instances):
    ids = {inst.target_id for inst in instances if inst.site_id == site.pk}
    if site.primary_target_id:
        ids.add(site.primary_target_id)
    return ids


def _node(nid, kind, label, status, parent=None):
    assert kind in _NODE_KINDS  # nosec B101 — closed kind set, not a test assert
    row = {"id": nid, "kind": kind, "label": label, "status": status}
    if parent:
        row["parent"] = parent
    return row
