"""Per-site break-glass runbook on the target (§P5). No secrets."""
import json
from datetime import datetime, timezone

from deploys.failure_impact import runbook_line

SCHEMA_VERSION = 1

_ADVISORY = (
    "ADVISORY ONLY — re-read from the Findings inbox (over Tailscale) "
    "before typing; never execute a command whose only provenance is a "
    "push notification."
)


def write_runbook(desired):
    """Put markdown at /srv/sites/{slug}/BREAK-GLASS.md with mode 0400."""
    transport = desired["transport"]
    slug = desired["site_slug"]
    path = f"/srv/sites/{slug}/BREAK-GLASS.md"
    # Root-owned 0400 cannot be overwritten by the deploy user. Put a
    # deploy-writable temp, then sudo mv onto the final path (certs._atomic_write).
    tmp = f"{path}.tmp"
    transport.put(_render_runbook(desired).encode(), tmp, mode=0o400)
    transport.run(["sudo", "mv", tmp, path])
    transport.run(["sudo", "chown", "root:root", path])
    transport.run(["sudo", "chmod", "0400", path])
    return {"status": "written", "path": path}


def _render_runbook(desired):
    slug = desired["site_slug"]
    domain = desired.get("domain") or ""
    image = desired.get("image_tag") or ""
    deployment_id = desired.get("deployment_id", "")
    container = f"site-{slug}-{deployment_id}"
    old = desired.get("old_container") or ""
    step, strategy = _step_and_strategy(desired)
    cert_mode, cert_expiry = _cert_fields(desired)
    generated_at = _timestamp(desired.get("generated_at"))

    lines = [
        f"# Break-glass: {slug}",
        "",
        f"- generated_at: {generated_at}",
        f"- deployment_id: {deployment_id}",
        f"- image: {image}",
        f"- schema_version: {SCHEMA_VERSION}",
        f"- domain: {domain}",
        f"- container: {container}",
    ]
    if cert_mode:
        lines.append(f"- cert_mode: {cert_mode}")
    if cert_expiry:
        lines.append(f"- cert_expiry: {cert_expiry}")
    lines.extend([
        "",
        runbook_line(step, strategy),
        "",
        _ADVISORY,
        "",
        "## Restart",
        "",
        f"    docker start {container}",
        "",
        "## Rollback",
        "",
        f"    docker stop {container}",
    ])
    if old:
        lines.append(f"    docker start {old}")
    lines.extend([
        "",
        "## DNS (Hub-side only)",
        "",
        "A token-bearing DNS command on this host is forbidden.",
        "Run the adapter on the Hub:",
        "",
        *_dns_command_lines(desired),
        "",
    ])
    return "\n".join(lines)


def _step_and_strategy(desired):
    step = desired.get("failed_step") or desired.get("step") or desired.get("current_step")
    strategy = desired.get("strategy") or desired.get("deploy_strategy")
    if not step:
        step = _step_from_deployment(desired.get("deployment"))
    if not strategy:
        body = desired.get("manifest_body") or {}
        strategy = body.get("deploy_strategy")
    if not strategy:
        site = desired.get("site")
        strategy = getattr(site, "deploy_strategy", None) if site is not None else None
    return _as_step_name(step) or "cutover", _as_strategy(strategy) or "blue_green"


def _as_step_name(step):
    if step is None:
        return None
    if isinstance(step, str):
        return step
    name = getattr(step, "name", None)
    if isinstance(name, str) and name:
        return name
    return None


def _as_strategy(strategy):
    if strategy is None:
        return None
    if isinstance(strategy, str):
        return strategy
    value = getattr(strategy, "value", None)
    if isinstance(value, str) and value:
        return value
    return None


def _step_from_deployment(deployment):
    if deployment is None:
        return None
    manager = getattr(deployment, "steps", None)
    if manager is None or not hasattr(manager, "filter"):
        return None
    failed = manager.filter(status="failed").order_by("seq").first()
    if failed is not None:
        return failed.name
    latest = manager.exclude(status="pending").order_by("-seq").first()
    if latest is not None:
        return latest.name
    return None


def _cert_fields(desired):
    mode = desired.get("cert_mode") or desired.get("tls_mode")
    expiry = desired.get("cert_expiry") or desired.get("not_after")
    cert = desired.get("tls_certificate")
    if isinstance(cert, dict):
        mode = mode or cert.get("mode")
        expiry = expiry or cert.get("not_after") or cert.get("cert_expiry")
    elif cert is not None:
        mode = mode or getattr(cert, "mode", None)
        expiry = expiry or getattr(cert, "not_after", None)
    if not mode or not expiry:
        site = desired.get("site")
        manager = getattr(site, "tls_certificates", None) if site is not None else None
        if manager is not None and hasattr(manager, "order_by"):
            row = manager.order_by("-pushed_at", "-pk").first()
            if row is not None:
                mode = mode or row.mode
                expiry = expiry or row.not_after
    return mode or "", _timestamp(expiry) if expiry else ""


def _timestamp(value):
    if value is None or value == "":
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    return str(value)


def _dns_command_lines(desired):
    zone = _zone_name(desired)
    lines = []
    for rec in _dns_records(desired):
        name = rec.get("name") or ""
        rtype = rec.get("rtype") or "A"
        values = list(rec.get("values") or [])
        proxied = rec.get("proxied", True)
        lines.append(
            f"    dns.upsert_record("
            f"{zone!r}, {name!r}, {rtype!r}, {values!r}, proxied={proxied!r})"
        )
    return lines or [
        "    # no DNS records for this site — Hub-side DnsProvider only",
    ]


def _zone_name(desired):
    zone = desired.get("dns_zone") or desired.get("zone")
    if zone is None:
        return ""
    name = getattr(zone, "name", None)
    if name:
        return str(name)
    if isinstance(zone, str):
        return zone
    return ""


def _dns_records(desired):
    overlay = desired.get("dns_set")
    if isinstance(overlay, str) and overlay.strip():
        try:
            overlay = json.loads(overlay)
        except json.JSONDecodeError:
            overlay = None
    if isinstance(overlay, list) and overlay:
        return overlay
    domain = desired.get("domain") or ""
    site = desired.get("site")
    if not domain and site is not None:
        domain = getattr(site, "domain", None) or ""
    values = list(desired.get("dns_values") or ["127.0.0.1"])
    return [{
        "name": domain,
        "rtype": desired.get("dns_rtype") or "A",
        "values": values,
        "proxied": desired.get("dns_proxied", True),
    }]
