"""Topology advisor r1–r5 as Findings (D-041, C5).

Reads map_graph.graph_snapshot() plus Site/Target/SiteInstance and files the
C5 fingerprints. No graph library — the snapshot is a node/edge list, and the
rules are loops over those lists. Live docker-network inspect on T2 is the
named slip; r3's T1 protocol is collect_payload networks.
"""
from urllib.parse import urlparse

from django.conf import settings

from core.findings import finding, resolve
from core.models import BackupUnit, Finding, Site, SiteInstance, Target

SOURCE_ENGINE = "topology"

_FP_HUB = "topology-hub-isolation:hub"
_FP_BLAST = "topology-blast-radius:{pk}"
_FP_NET = "topology-site-network:{pk}"
_FP_DB = "topology-db-mesh-only:{pk}"
_FP_LAN = "topology-lan-segment:{pk}"

_DB_KINDS = frozenset({BackupUnit.Kind.POSTGRES, BackupUnit.Kind.SQLITE_FILE})
_OURS = (
    "topology-hub-isolation:",
    "topology-blast-radius:",
    "topology-site-network:",
    "topology-db-mesh-only:",
    "topology-lan-segment:",
)


def evaluate():
    """Walk the live graph and file/refresh r1–r5. Resolve OPEN/ACKED rows
    whose fingerprint is no longer active. ACCEPTED stays until the operator
    resolves it (same fingerprint must not resurface as a second row).
    """
    from monitor.map_graph import graph_snapshot

    graph = graph_snapshot()
    sites = list(Site.objects.select_related("primary_target").order_by("pk"))
    targets = list(Target.objects.select_related("zone").order_by("pk"))
    instances = list(SiteInstance.objects.order_by("pk"))
    hostname = _hub_hostname()
    hub_site_pks = {s.pk for s in sites if _is_hub_site(s, hostname)}
    hub_target_pks = _hub_target_pks(hostname, sites, targets, instances)
    public_hosts = {
        edge["b"] for edge in graph.get("edges") or []
        if edge.get("path") == "public" and edge.get("b")
    }
    nodes_by_id = {n["id"]: n for n in graph.get("nodes") or []}
    active = set()

    _rule_hub_isolation(
        sites, hub_site_pks, hub_target_pks, public_hosts, active,
    )
    _rule_blast_radius(sites, targets, instances, hub_site_pks, active)
    _rule_site_network(sites, targets, instances, hub_site_pks, active)
    _rule_db_mesh_only(sites, active)
    _rule_lan_segment(hub_target_pks, public_hosts, nodes_by_id, active)
    _clear_stale(active)
    return active


def attach_findings(nodes):
    """Optional chips: OPEN/ACKED topology Findings keyed onto snapshot nodes."""
    if not nodes:
        return
    instances = list(SiteInstance.objects.only("pk", "site_id"))
    chips = {}
    rows = Finding.objects.filter(
        source_engine=SOURCE_ENGINE,
        state__in=(Finding.State.OPEN, Finding.State.ACKED),
    )
    for row in rows:
        for nid in _node_ids_for(row.fingerprint, instances):
            chips.setdefault(nid, []).append(
                {"id": row.pk, "severity": row.severity},
            )
    for node in nodes:
        extra = chips.get(node["id"])
        if extra:
            node["findings"] = extra


def _rule_hub_isolation(sites, hub_site_pks, hub_target_pks, public_hosts, active):
    hub_host_ids = {f"host:{pk}" for pk in hub_target_pks}
    colocated = bool(hub_host_ids & public_hosts)
    hub_public = any(
        s.pk in hub_site_pks and s.exposure == Site.Exposure.PUBLIC
        for s in sites
    )
    if not (colocated or hub_public):
        return
    active.add(_FP_HUB)
    _file(
        _FP_HUB,
        severity=Finding.Severity.P1,
        entity="hub",
        title="Hub is colocated with a public origin",
        body=(
            "A public origin on the Hub host can reach fleet SSH keys, the "
            "vault, and the broker. Hub isolation (§9.6.2 r1) requires a "
            "dedicated host with no public exposure."
        ),
        fix_action=(
            "Move the public site to another target, or migrate the Hub "
            "to its own host."
        ),
    )


def _rule_blast_radius(sites, targets, instances, hub_site_pks, active):
    sites_by_pk = {s.pk: s for s in sites}
    for target in targets:
        site_ids = _site_ids_on_target(target.pk, sites, instances) - hub_site_pks
        if len(site_ids) < 2:
            continue
        fp = _FP_BLAST.format(pk=target.pk)
        active.add(fp)
        names = [sites_by_pk[pk].name for pk in sorted(site_ids) if pk in sites_by_pk]
        listed = ", ".join(names) or f"{len(site_ids)} sites"
        _file(
            fp,
            severity=Finding.Severity.P2,
            entity=f"target:{target.host}",
            title=f"{target.host} hosts {len(site_ids)} sites",
            body=(
                f"{listed} share {target.host}. Compromise of one container "
                "is the blast radius of all of them (§9.6.2 r2)."
            ),
            fix_action=(
                "Move all but one site off this target so each host is a "
                "single blast radius."
            ),
        )


def _rule_site_network(sites, targets, instances, hub_site_pks, active):
    targets_by_pk = {t.pk: t for t in targets}
    for site in sites:
        if site.pk in hub_site_pks:
            continue
        t_ids = {inst.target_id for inst in instances if inst.site_id == site.pk}
        if not t_ids:
            continue
        dedicated = _dedicated_network_names(site)
        missing = False
        for tid in t_ids:
            observed = _observed_networks(targets_by_pk.get(tid))
            if observed is None or not (observed & dedicated):
                missing = True
                break
        if not missing:
            continue
        fp = _FP_NET.format(pk=site.pk)
        active.add(fp)
        _file(
            fp,
            severity=Finding.Severity.P2,
            entity=f"site:{site.name}",
            title=f"{site.name} has no dedicated Docker network",
            body=(
                "Containers on the default bridge can reach each other. A "
                "per-site Docker network contains a break to that site "
                "(§9.6.2 r3)."
            ),
            fix_action=(
                f"Create Docker network site-{site.pk} and attach only "
                "this site's containers."
            ),
        )


def _rule_db_mesh_only(sites, active):
    db_site_ids = set(
        BackupUnit.objects.filter(kind__in=_DB_KINDS).values_list("site_id", flat=True)
    )
    for site in sites:
        if site.pk not in db_site_ids:
            continue
        if site.exposure != Site.Exposure.PUBLIC:
            continue
        fp = _FP_DB.format(pk=site.pk)
        active.add(fp)
        _file(
            fp,
            severity=Finding.Severity.P2,
            entity=f"site:{site.name}",
            title=f"Database for {site.name} is reachable off the mesh",
            body=(
                "A public-origin path to the database expands the blast "
                "radius to the internet. Databases stay mesh-only (§9.6.2 r4)."
            ),
            fix_action=(
                "Move the database to a mesh_only site so it has no public "
                "edge path."
            ),
        )


def _rule_lan_segment(hub_target_pks, public_hosts, nodes_by_id, active):
    if not hub_target_pks:
        return
    hub_zones = set()
    for pk in hub_target_pks:
        parent = nodes_by_id.get(f"host:{pk}", {}).get("parent")
        if parent:
            hub_zones.add(parent)
    for zone_id in hub_zones:
        public_on_lan = any(
            nodes_by_id.get(hid, {}).get("parent") == zone_id
            for hid in public_hosts
        )
        if not public_on_lan:
            continue
        try:
            zone_pk = int(str(zone_id).split(":", 1)[1])
        except (IndexError, ValueError):
            continue
        fp = _FP_LAN.format(pk=zone_pk)
        active.add(fp)
        label = nodes_by_id.get(zone_id, {}).get("label") or zone_id
        _file(
            fp,
            severity=Finding.Severity.P2,
            entity=f"zone:{label}",
            title=f"Hub and a public origin share LAN {label}",
            body=(
                "A device on this LAN can reach both the Hub and a public "
                "origin. Home-LAN segmentation keeps the Hub off the same L2 "
                "as public workloads (§9.6.2 r5)."
            ),
            fix_action=(
                "Move the public origin or the Hub to a different NetworkZone."
            ),
        )


def _clear_stale(active):
    rows = Finding.objects.filter(source_engine=SOURCE_ENGINE)
    for row in rows:
        if not any(row.fingerprint.startswith(p) for p in _OURS):
            continue
        if row.fingerprint in active:
            continue
        if row.state in (Finding.State.OPEN, Finding.State.ACKED):
            resolve(row, source="system")


def _file(fingerprint, **fields):
    return finding(SOURCE_ENGINE, fingerprint, **fields)


def _hub_hostname():
    raw = (getattr(settings, "HUB_PUBLIC_URL", "") or "").strip()
    if not raw:
        return ""
    return (urlparse(raw).hostname or "").casefold()


def _is_hub_site(site, hostname):
    return bool(hostname) and (site.domain or "").casefold() == hostname


def _hub_target_pks(hostname, sites, targets, instances):
    if not hostname:
        return set()
    pks = {t.pk for t in targets if (t.host or "").casefold() == hostname}
    for site in sites:
        if _is_hub_site(site, hostname):
            pks.update(_site_target_ids(site, instances))
    return pks


def _site_target_ids(site, instances):
    ids = {inst.target_id for inst in instances if inst.site_id == site.pk}
    if site.primary_target_id:
        ids.add(site.primary_target_id)
    return ids


def _site_ids_on_target(target_id, sites, instances):
    ids = {inst.site_id for inst in instances if inst.target_id == target_id}
    for site in sites:
        if site.primary_target_id == target_id:
            ids.add(site.pk)
    return ids


def _dedicated_network_names(site):
    names = {f"site-{site.pk}"}
    slug = (site.name or "").strip()
    if slug:
        names.add(f"site-{slug}")
    return names


def _observed_networks(target):
    """Return a set of network names, or None when nothing was observed.

    None is fail-closed missing (T1 protocol; live inspect is the T2 slip).
    """
    if target is None:
        return None
    payload = getattr(target, "collect_payload", None)
    if not isinstance(payload, dict):
        return None
    names = set()
    observed = False
    raw = payload.get("networks")
    if raw is not None:
        observed = True
        names.update(_network_names(raw))
    for container in payload.get("containers") or []:
        if not isinstance(container, dict):
            continue
        nets = container.get("networks")
        if nets is None:
            continue
        observed = True
        names.update(_network_names(nets))
    return names if observed else None


def _network_names(raw):
    if isinstance(raw, str):
        raw = [raw]
    names = set()
    for item in raw or []:
        if isinstance(item, str) and item.strip():
            names.add(item.strip())
        elif isinstance(item, dict):
            name = item.get("name")
            if isinstance(name, str) and name.strip():
                names.add(name.strip())
    return names


def _node_ids_for(fingerprint, instances):
    kind, _, rest = fingerprint.partition(":")
    if kind == "topology-hub-isolation":
        return ["hub"]
    if kind == "topology-blast-radius":
        return [f"host:{rest}"]
    if kind == "topology-lan-segment":
        return [f"zone:{rest}"]
    if kind in {"topology-site-network", "topology-db-mesh-only"}:
        try:
            site_pk = int(rest)
        except ValueError:
            return []
        return [
            f"container:{inst.pk}" for inst in instances if inst.site_id == site_pk
        ]
    return []
