"""Map v1 graph: derived from models, {seq, data} snapshot, map.graph topic.

MAP-96-GRAPH-V1 / D-041: zones → hosts → containers + Hub + Cloudflare edge
from one table-backed snapshot. A zone node is a NetworkZone, never a DnsZone.
No stored JSON blob (§D3). Seq is the same counter other snapshots read (§D7).
"""
import pytest
from django.apps import apps
from django.db import models as dj_models

from core.models import NetworkZone, Project, Site, SiteInstance, Target

pytestmark = [pytest.mark.django_db, pytest.mark.req("MAP-96-GRAPH-V1")]


def _project():
    return Project.objects.create(name="map-fleet", slug="map-fleet")


def _zone(name, slug):
    return NetworkZone.objects.create(name=name, slug=slug)


def _target(zone, host, **kwargs):
    return Target.objects.create(
        zone=zone, host=host, status=Target.Status.READY, **kwargs,
    )


def _site(project, name, target, *, exposure="public", domain=""):
    from dns_fixtures import default_dns_zone

    if exposure == "public" and not domain:
        domain = f"{name}.example.com"
    return Site.objects.create(
        project=project,
        name=name,
        domain=domain,
        exposure=exposure,
        primary_target=target,
        dns_zone=default_dns_zone() if exposure == "public" else None,
    )


def _instance(site, target, port):
    return SiteInstance.objects.create(
        site=site,
        target=target,
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.RUNNING,
        internal_port=port,
    )


def _kinds(graph):
    return {n["kind"] for n in graph["nodes"]}


def _by_kind(graph, kind):
    return [n for n in graph["nodes"] if n["kind"] == kind]


def _labels(graph, kind=None):
    nodes = graph["nodes"] if kind is None else _by_kind(graph, kind)
    return {n["label"] for n in nodes}


def test_graph_is_derived_from_models_not_a_stored_blob():
    """A rename on a Target must show up on the next snapshot — a stored
    graph blob would keep the old hostname. Fail this if someone adds a
    MapGraph/topology JSONField and serves that instead of the live rows."""
    from monitor.map_graph import graph_snapshot

    stored = []
    for model in apps.get_models():
        if "graph" in model.__name__.lower() or "topology" in model.__name__.lower():
            stored.append(model.__name__)
        for field in model._meta.get_fields():
            if not isinstance(field, dj_models.Field):
                continue
            if field.name in {"graph", "map_graph", "topology"}:
                stored.append(f"{model.__name__}.{field.name}")
    assert stored == [], stored

    project = _project()
    zone = _zone("lan", "lan-derive")
    target = _target(zone, "web-old.example")
    site = _site(project, "shop", target)
    _instance(site, target, 20000)

    first = graph_snapshot()
    assert "web-old.example" in _labels(first, "host")
    assert "shop" in _labels(first, "container")
    assert zone.name in _labels(first, "zone")

    target.host = "web-new.example"
    target.save(update_fields=["host"])

    second = graph_snapshot()
    assert "web-new.example" in _labels(second, "host")
    assert "web-old.example" not in _labels(second, "host")


def test_zone_nodes_are_networkzones_not_dnszones():
    """Site.dns_zone is a detail field. Putting it on the topology as a parent
    node is the D-041 mix-up this test exists to catch."""
    from dns_fixtures import default_dns_zone

    from monitor.map_graph import graph_snapshot

    project = _project()
    net = _zone("prod-vlan", "prod-vlan")
    dns = default_dns_zone(name="customers.example")
    target = _target(net, "edge-1.example")
    site = Site.objects.create(
        project=project, name="store", domain="store.customers.example",
        exposure=Site.Exposure.PUBLIC, primary_target=target, dns_zone=dns,
    )
    _instance(site, target, 20000)

    graph = graph_snapshot()
    zone_labels = _labels(graph, "zone")
    assert net.name in zone_labels
    assert dns.name not in zone_labels
    assert "customers.example" not in zone_labels
    for node in _by_kind(graph, "zone"):
        assert node["id"] == f"zone:{net.pk}"


def test_hub_is_a_distinct_node():
    """Hub is its own kind — not a zone, not a host — even on an empty fleet."""
    from monitor.map_graph import graph_snapshot

    empty = graph_snapshot()
    hubs = _by_kind(empty, "hub")
    assert len(hubs) == 1
    assert hubs[0]["id"] == "hub"
    assert hubs[0]["kind"] == "hub"
    assert hubs[0]["label"] == "Hub"
    assert _kinds(empty) >= {"hub", "edge"}

    project = _project()
    zone = _zone("lan", "lan-hub")
    target = _target(zone, "box-1")
    site = _site(project, "app", target)
    _instance(site, target, 20000)
    full = graph_snapshot()
    assert len(_by_kind(full, "hub")) == 1
    assert "hub" in {n["id"] for n in full["nodes"]}


def test_mesh_paths_are_marked_mesh_and_public_public():
    """Site.exposure is the path: public → Cloudflare edge (solid),
    mesh_only → Hub (dashed). Mixing those up draws the wrong lines."""
    from monitor.map_graph import graph_snapshot

    project = _project()
    zone = _zone("lan", "lan-paths")
    public_host = _target(zone, "public-1")
    mesh_host = _target(zone, "mesh-1")
    pub = _site(project, "www", public_host, exposure="public")
    mesh = _site(project, "internal", mesh_host, exposure="mesh_only")
    _instance(pub, public_host, 20000)
    _instance(mesh, mesh_host, 20000)

    graph = graph_snapshot()
    host_id = {n["label"]: n["id"] for n in _by_kind(graph, "host")}
    paths = {(e["a"], e["b"], e["path"]) for e in graph["edges"]}

    assert ("edge", host_id["public-1"], "public") in paths
    assert ("hub", host_id["mesh-1"], "mesh") in paths
    # A public origin is not a mesh path, and a mesh-only host is not public.
    assert not any(
        e["path"] == "mesh" and e["b"] == host_id["public-1"]
        for e in graph["edges"]
    )
    assert not any(
        e["path"] == "public" and e["b"] == host_id["mesh-1"]
        for e in graph["edges"]
    )
    assert {e["path"] for e in graph["edges"]} <= {"public", "mesh"}


def _enrolled(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    User.objects.create_user("joseph", password="a-long-dev-password")
    u = User.objects.get(username="joseph")
    TOTPDevice.objects.create(user=u, name="phone", confirmed=True)
    client.login(username="joseph", password="a-long-dev-password")
    return u


def test_snapshot_returns_seq_and_data(client):
    """Table-backed §D7: {seq, data}, seq from the map.graph counter, read
    before the rows. findings stays the alert topic — this one is map.graph."""
    from django.contrib.auth.models import AnonymousUser

    from core import events
    from monitor.map_graph import graph_snapshot, notify_graph_changed
    from realtime.authorize import authorize_topic
    from realtime.publish import current_seq as pub_seq

    assert client.get("/api/v1/map/").status_code == 403

    user = _enrolled(client)
    assert authorize_topic(AnonymousUser(), "map.graph") is False
    assert authorize_topic(user, "map.graph") is True
    assert authorize_topic(user, "findings") is True

    project = _project()
    zone = _zone("lan", "lan-snap")
    target = _target(zone, "snap-1")
    site = _site(project, "snap-app", target)
    _instance(site, target, 20000)

    before = events.current_seq("map.graph")
    notify_graph_changed()
    assert events.current_seq("map.graph") == before + 1
    assert pub_seq("map.graph") == events.current_seq("map.graph")

    # Seq first: the snapshot's seq is the counter as it stood before the
    # table walk, matching graph_snapshot() — not a private increment.
    snap = graph_snapshot()
    r = client.get("/api/v1/map/")
    assert r.status_code == 200
    body = r.json()
    assert set(body) == {"seq", "data"}
    assert body["seq"] == snap["seq"] == events.current_seq("map.graph")
    assert set(body["data"]) == {"nodes", "edges"}
    assert {n["kind"] for n in body["data"]["nodes"]} >= {
        "zone", "host", "container", "hub", "edge",
    }
    assert "snap-1" in {n["label"] for n in body["data"]["nodes"]}


def test_thirty_node_fleet_renders_within_the_snapshot_contract():
    """D-041 keeps the §J3 library open until a 30-node fleet outgrows the
    snapshot. Thirty nodes must still be {nodes, edges} with the five kinds
    and public/mesh paths — not a new blob or a truncated page."""
    from monitor.map_graph import graph_snapshot

    project = _project()
    zones = [_zone(f"z{i}", f"z{i}-thirty") for i in range(2)]
    hosts = []
    for i in range(10):
        hosts.append(_target(zones[i % 2], f"host-{i}.example"))
    # 16 containers + 10 hosts + 2 zones + hub + edge = 30.
    for i in range(16):
        host = hosts[i % 10]
        exposure = "public" if i < 8 else "mesh_only"
        site = _site(project, f"site-{i}", host, exposure=exposure)
        _instance(site, host, 20000 + i)

    graph = graph_snapshot()
    assert set(graph) >= {"seq", "nodes", "edges"}
    assert len(graph["nodes"]) == 30
    assert _kinds(graph) == {"zone", "host", "container", "hub", "edge"}
    assert len(_by_kind(graph, "hub")) == 1
    assert len(_by_kind(graph, "edge")) == 1
    assert len(_by_kind(graph, "zone")) == 2
    assert len(_by_kind(graph, "host")) == 10
    assert len(_by_kind(graph, "container")) == 16
    assert {e["path"] for e in graph["edges"]} == {"public", "mesh"}
    assert "example.com" not in _labels(graph, "zone")
    for node in graph["nodes"]:
        assert {"id", "kind", "label", "status"} <= set(node)
    for edge in graph["edges"]:
        assert set(edge) == {"a", "b", "path"}


def test_collect_cursor_save_does_not_publish_map_graph():
    """Collector writes inode/offset every pull — that is not a topology
    change. Publishing map.graph on those saves would stampede the map."""
    from core import events

    zone = _zone("lan", "lan-collect")
    target = _target(zone, "collect-1")
    before = events.current_seq("map.graph")
    target.collect_log_offset = 99
    target.save(update_fields=["collect_log_offset"])
    assert events.current_seq("map.graph") == before
    target.host = "collect-1-renamed"
    target.save(update_fields=["host"])
    assert events.current_seq("map.graph") == before + 1
