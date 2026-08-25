"""Phase 7.2 LAN ghosts: inject seam + map kind (C1–C4, C7).

attach_lan_ghosts appends kind=ghost nodes for lan_scan hosts that are
not enrolled Target.host. Default lan_scan is refuse-closed. Tests wrap
monitor.map_graph.attach_lan_ghosts to inject lan_scan= on GET /api/v1/map/.
"""
import ast
import pathlib
import uuid
from types import SimpleNamespace

import pytest

from core.models import NetworkZone, Target
from monitor.views import MapNodeSerializer

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
LAN_GHOSTS = REPO / "monitor" / "lan_ghosts.py"
BANNED_SOURCE = ("subprocess", "nmap", "scapy", "mdns", "zeroconf")


def _host(host):
    return SimpleNamespace(host=host)


def _lan(*rows):
    return lambda: [dict(row) for row in rows]


def _zone(slug="ghost-lan"):
    return NetworkZone.objects.create(name=slug, slug=slug)


def _target(zone, host):
    return Target.objects.create(
        zone=zone, host=host, status=Target.Status.READY,
    )


def _login(client):
    from django.contrib.auth.models import User
    from django_otp.plugins.otp_totp.models import TOTPDevice

    username = f"joseph-{uuid.uuid4().hex[:8]}"
    user = User.objects.create_user(username, password="a-long-dev-password")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.login(username=username, password="a-long-dev-password")
    return user


def _inject_lan_scan(monkeypatch, rows):
    """Wrap the snapshot callee so GET map never binds a live LAN scan."""
    from monitor import map_graph

    real = map_graph.attach_lan_ghosts

    def injected():
        return [dict(row) for row in rows]

    def wrapped(nodes, targets, *, lan_scan=None):
        return real(nodes, targets, lan_scan=lan_scan or injected)

    monkeypatch.setattr(map_graph, "attach_lan_ghosts", wrapped)
    return injected


@pytest.mark.req("LAN-GHOST-INJECT")
def test_inject_adds_ghost_for_unenrolled_host():
    """Unenrolled lan_scan host becomes ghost:{host} with kind/status ghost.

    What would make this fail: skipping the append, using a host kind, or
    omitting parent when zone_id is set.
    """
    from monitor.lan_ghosts import attach_lan_ghosts

    nodes = [{"id": "hub", "kind": "hub", "label": "Hub", "status": "ok"}]
    out = attach_lan_ghosts(
        nodes,
        [_host("web-1")],
        lan_scan=_lan(
            {"host": "printer.lan", "zone_id": 7},
            {"host": "orphan.lan", "zone_id": None},
        ),
    )
    ghosts = [n for n in out if n.get("kind") == "ghost"]
    by_id = {n["id"]: n for n in ghosts}
    assert "ghost:printer.lan" in by_id
    printer = by_id["ghost:printer.lan"]
    assert printer["kind"] == "ghost"
    assert printer["label"] == "printer.lan"
    assert printer["status"] == "ghost"
    assert printer["parent"] == "zone:7"
    orphan = by_id["ghost:orphan.lan"]
    assert orphan["label"] == "orphan.lan"
    assert "parent" not in orphan


@pytest.mark.req("LAN-GHOST-INJECT")
def test_inject_skips_enrolled_host():
    """A lan_scan host that already equals Target.host is not a ghost.

    What would make this fail: matching case-insensitively or appending
    ghost:web-1 next to the enrolled host.
    """
    from monitor.lan_ghosts import attach_lan_ghosts

    nodes = [{"id": "host:1", "kind": "host", "label": "web-1", "status": "ready"}]
    out = attach_lan_ghosts(
        nodes,
        [_host("web-1")],
        lan_scan=_lan(
            {"host": "web-1", "zone_id": 1},
            {"host": "printer.lan", "zone_id": 1},
        ),
    )
    ids = {n["id"] for n in out}
    assert "ghost:web-1" not in ids
    assert "ghost:printer.lan" in ids
    assert sum(1 for n in out if n.get("kind") == "ghost") == 1


@pytest.mark.req("LAN-GHOST-INJECT")
def test_missing_lan_scan_adds_no_ghosts():
    """lan_scan is None (the default) leaves the graph unchanged.

    What would make this fail: treating missing inject as an empty scan
    that still walks the LAN, or appending a placeholder ghost.
    """
    from monitor.lan_ghosts import attach_lan_ghosts

    nodes = [{"id": "hub", "kind": "hub", "label": "Hub", "status": "ok"}]
    same = attach_lan_ghosts(nodes, [_host("web-1")])
    assert same is nodes or list(same) == nodes
    assert not any(n.get("kind") == "ghost" for n in same)
    explicit = attach_lan_ghosts(nodes, [_host("web-1")], lan_scan=None)
    assert not any(n.get("kind") == "ghost" for n in explicit)


@pytest.mark.req("LAN-GHOST-INJECT")
def test_module_has_no_live_discovery():
    """C7: lan_ghosts must not run nmap/mdns or spawn a subprocess.

    What would make this fail: importing or naming those scanners in
    monitor/lan_ghosts.py.
    """
    src = LAN_GHOSTS.read_text(encoding="utf-8")
    lowered = src.lower()
    for token in BANNED_SOURCE:
        assert token not in lowered, f"lan_ghosts.py contains {token}"
    tree = ast.parse(src)
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert imported.isdisjoint(BANNED_SOURCE), imported & set(BANNED_SOURCE)
    assert "subprocess" not in imported


@pytest.mark.req("LAN-GHOST-MAP-VIEW")
def test_map_snapshot_serializes_ghost_kind(client, monkeypatch):
    """GET /api/v1/map/ serializes kind=ghost when lan_scan is wrapped in.

    What would make this fail: graph_snapshot skipping attach_lan_ghosts,
    or the serializer rejecting kind=ghost so the ghost never reaches JSON.
    """
    zone = _zone("ghost-snap")
    _target(zone, "web-1")
    _inject_lan_scan(monkeypatch, [
        {"host": "web-1", "zone_id": zone.pk},
        {"host": "printer.lan", "zone_id": zone.pk},
    ])
    _login(client)
    r = client.get("/api/v1/map/")
    assert r.status_code == 200, r.content
    nodes = r.json()["data"]["nodes"]
    ghosts = [n for n in nodes if n.get("kind") == "ghost"]
    ids = {n["id"] for n in ghosts}
    assert ids == {"ghost:printer.lan"}
    printer = ghosts[0]
    assert printer["label"] == "printer.lan"
    assert printer["status"] == "ghost"
    assert printer["parent"] == f"zone:{zone.pk}"
    assert "ghost:web-1" not in {n["id"] for n in nodes}


@pytest.mark.req("LAN-GHOST-MAP-VIEW")
def test_map_kind_enum_includes_ghost():
    """MapNodeSerializer + generated KindEnum + _NODE_KINDS include ghost.

    What would make this fail: growing the snapshot kind without the
    serializer / generate-client mirror, so GET map 500s on a ghost node.
    """
    from monitor.map_graph import _NODE_KINDS

    choices = dict(MapNodeSerializer().fields["kind"].choices)
    assert "ghost" in choices
    assert "ghost" in _NODE_KINDS
    zod = (REPO / "frontend" / "src" / "api" / "zod.ts").read_text(encoding="utf-8")
    assert 'z.enum(["zone", "host", "container", "hub", "edge", "ghost"])' in zod
    openapi = (REPO / "frontend" / "src" / "api" / "openapi.yaml").read_text(
        encoding="utf-8",
    )
    assert "- ghost" in openapi
