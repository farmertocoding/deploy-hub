"""Optional LAN discovery ghosts on the fleet map.

Hosts that a caller-injected scan reports, and that are not enrolled
Targets, append as kind=ghost nodes. Missing lan_scan leaves the graph
unchanged (refuse-closed).
"""


def attach_lan_ghosts(nodes, targets, *, lan_scan=None):
    if lan_scan is None:
        return nodes
    enrolled = {t.host for t in targets}
    out = list(nodes)
    for row in lan_scan():
        host = row["host"]
        if host in enrolled:
            continue
        ghost = {
            "id": f"ghost:{host}",
            "kind": "ghost",
            "label": host,
            "status": "ghost",
        }
        zone_id = row.get("zone_id")
        if zone_id is not None:
            ghost["parent"] = f"zone:{zone_id}"
        out.append(ghost)
    return out
