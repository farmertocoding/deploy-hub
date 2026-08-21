"""Per-deployment snapshots of generated artifacts (§P4). Names, not values."""
import json


def snapshot_artifacts(desired):
    """Write Dockerfile, Caddy route, DNS set, env names, and firewall argv rows."""
    from deploys.models import DeploymentArtifact

    deployment = desired["deployment"]
    rows = {
        "dockerfile": desired.get("dockerfile") or "",
        "caddy_route": desired.get("caddy_route") or "",
        "dns": _dns_content(desired),
        "env_names": json.dumps(list(desired.get("env_names") or [])),
        "firewall_argv": json.dumps(list(desired.get("firewall_argv") or [])),
    }
    for kind, content in rows.items():
        DeploymentArtifact.objects.create(
            deployment=deployment, kind=kind, content=content,
        )
    return {"status": "snapshotted", "kinds": list(rows)}


def _dns_content(desired):
    dns_set = desired.get("dns_set")
    if dns_set is None:
        return "[]"
    if isinstance(dns_set, str):
        return dns_set
    return json.dumps(dns_set)
