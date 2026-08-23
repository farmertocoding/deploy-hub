"""Topology advisor r1–r5 as Findings (TOPO-R1-R5-FINDINGS, D-041, C5).

The advisor reads map_graph.graph_snapshot plus Site/Target/SiteInstance and
files one Finding per C5 fingerprint. It must not grow a graph library; map
chips (optional) deep-link #/findings/<id>. Accept-risk still needs a reason.
"""
import ast
import pathlib
import sys

import pytest
from django.test import override_settings

from core.models import (
    BackupUnit,
    Finding,
    NetworkZone,
    Project,
    Site,
    SiteInstance,
    Target,
)

pytestmark = [pytest.mark.django_db, pytest.mark.req("TOPO-R1-R5-FINDINGS")]

REPO = pathlib.Path(__file__).resolve().parent.parent
HUB_URL = "https://hub.example.test"
HUB_HOST = "hub.example.test"

# Python graph libraries a topology walk might reach for. Stdlib `graphlib` is
# not on this list — and the advisor must not need it either (plain loops).
_GRAPH_LIBS = frozenset({
    "networkx", "igraph", "graph_tool", "pygraphviz", "pydot", "graphviz",
    "rustworkx", "nx", "pyvis", "grandalf", "graphillion", "pynetworkx",
})


def _project():
    return Project.objects.create(name="topo-fleet", slug="topo-fleet")


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


def _copy_ok(row):
    assert row.title.strip(), "§6.6 title (what) is blank"
    assert row.body.strip(), "§6.6 body (why it matters) is blank"
    assert row.fix_action.strip(), "§6.6 fix_action (exact fix) is blank"


@override_settings(HUB_PUBLIC_URL=HUB_URL)
def test_hub_colocated_with_public_site_is_critical():
    """r1: Hub on the same host as a public origin is a P1 isolation Finding.

    What would make this fail: treating the Hub as just another container, or
    filing a digest-tier row for a crown-jewel colocation.
    """
    from core.findings import accept_risk
    from monitor.topology import evaluate

    project = _project()
    zone = _zone("home-lan", "topo-r1-lan")
    hub_box = _target(zone, HUB_HOST)
    shop = _site(project, "shop", hub_box)
    _instance(shop, hub_box, 20000)

    evaluate()

    row = Finding.objects.get(fingerprint="topology-hub-isolation:hub")
    assert row.severity == Finding.Severity.P1
    assert row.source_engine == "topology"
    assert row.entity == "hub"
    _copy_ok(row)

    from monitor.map_graph import graph_snapshot

    hub_node = next(n for n in graph_snapshot()["nodes"] if n["id"] == "hub")
    assert any(chip["id"] == row.pk for chip in hub_node.get("findings") or []), (
        "optional SVG chips read findings off the hub node so the map can "
        "link #/findings/<id>"
    )

    with pytest.raises(ValueError, match="reason"):
        accept_risk(row, "")
    with pytest.raises(ValueError, match="reason"):
        accept_risk(row, "   \t")
    accept_risk(row, "lab colocates hub and demo site on purpose")
    row.refresh_from_db()
    assert row.state == Finding.State.ACCEPTED
    evaluate()
    row.refresh_from_db()
    assert row.state == Finding.State.ACCEPTED
    assert Finding.objects.filter(fingerprint="topology-hub-isolation:hub").count() == 1


def test_blast_radius_finding():
    """r2: two sites on one target share fate — fingerprint is per target pk."""
    from monitor.topology import evaluate

    project = _project()
    zone = _zone("prod", "topo-r2-prod")
    box = _target(zone, "shared-1.example")
    shop = _site(project, "shop", box)
    api = _site(project, "api", box)
    _instance(shop, box, 20000)
    _instance(api, box, 20001)

    evaluate()

    fp = f"topology-blast-radius:{box.pk}"
    row = Finding.objects.get(fingerprint=fp)
    assert row.severity == Finding.Severity.P2
    assert row.source_engine == "topology"
    _copy_ok(row)
    assert "shop" in row.body or "2" in row.title or "2" in row.body


def test_missing_per_site_docker_network_finding():
    """r3 T1 protocol: a deployed site with no observed dedicated Docker
    network files topology-site-network:{site_pk}. Live inspect on T2 is the
    named slip — collect_payload is enough here.
    """
    from monitor.topology import evaluate

    project = _project()
    zone = _zone("prod", "topo-r3-prod")
    box = _target(zone, "web-1.example")
    shop = _site(project, "shop", box)
    _instance(shop, box, 20000)

    evaluate()

    fp = f"topology-site-network:{shop.pk}"
    row = Finding.objects.get(fingerprint=fp)
    assert row.severity == Finding.Severity.P2
    _copy_ok(row)

    box.collect_payload = {"networks": [f"site-{shop.pk}"]}
    box.save(update_fields=["collect_payload"])
    evaluate()
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED


def test_db_off_mesh_finding():
    """r4: a public-origin site that holds a database is off-mesh for r4."""
    from monitor.topology import evaluate

    project = _project()
    zone = _zone("prod", "topo-r4-prod")
    public_box = _target(zone, "origin-1.example")
    mesh_box = _target(zone, "db-1.example")
    shop = _site(project, "shop", public_box)
    db = _site(project, "shop-db", mesh_box, exposure="mesh_only")
    _instance(shop, public_box, 20000)
    _instance(db, mesh_box, 20000)
    BackupUnit.objects.create(site=shop, kind=BackupUnit.Kind.POSTGRES)
    BackupUnit.objects.create(site=db, kind=BackupUnit.Kind.POSTGRES)

    evaluate()

    fp = f"topology-db-mesh-only:{shop.pk}"
    row = Finding.objects.get(fingerprint=fp)
    assert row.severity == Finding.Severity.P2
    _copy_ok(row)
    assert not Finding.objects.filter(
        fingerprint=f"topology-db-mesh-only:{db.pk}",
    ).exists()


@override_settings(HUB_PUBLIC_URL=HUB_URL)
def test_hub_and_public_origin_same_lan_finding():
    """r5: Hub and a public origin in the same NetworkZone — even on two hosts."""
    from monitor.topology import evaluate

    project = _project()
    home = _zone("home-lan", "topo-r5-home")
    other = _zone("cloud", "topo-r5-cloud")
    hub_box = _target(home, HUB_HOST)
    lan_box = _target(home, "public-1.example")
    cloud_box = _target(other, "public-2.example")
    _site(project, "hub", hub_box, exposure="mesh_only", domain=HUB_HOST)
    shop = _site(project, "shop", lan_box)
    isolated = _site(project, "cdn", cloud_box)
    _instance(shop, lan_box, 20000)
    _instance(isolated, cloud_box, 20000)

    evaluate()

    fp = f"topology-lan-segment:{home.pk}"
    row = Finding.objects.get(fingerprint=fp)
    assert row.severity == Finding.Severity.P2
    _copy_ok(row)
    assert not Finding.objects.filter(
        fingerprint=f"topology-lan-segment:{other.pk}",
    ).exists()
    assert not Finding.objects.filter(
        fingerprint="topology-hub-isolation:hub",
    ).exists()


def test_topology_does_not_import_a_graph_library():
    """D-041: r1–r5 walk the snapshot with plain loops, not networkx et al."""
    path = REPO / "monitor" / "topology.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(_GRAPH_LIBS), imported

    import monitor.topology  # noqa: F401 — load so sys.modules sees the closure

    loaded = {name.split(".")[0] for name in sys.modules}
    assert loaded.isdisjoint(_GRAPH_LIBS), loaded & _GRAPH_LIBS
