"""Per-site break-glass runbook on the target (§P5). No secrets."""


def write_runbook(desired):
    """Put markdown at /srv/sites/{slug}/BREAK-GLASS.md with mode 0400."""
    transport = desired["transport"]
    slug = desired["site_slug"]
    path = f"/srv/sites/{slug}/BREAK-GLASS.md"
    transport.put(_render_runbook(desired).encode(), path, mode=0o400)
    return {"status": "written", "path": path}


def _render_runbook(desired):
    slug = desired["site_slug"]
    domain = desired.get("domain") or ""
    image = desired.get("image_tag") or ""
    container = f"site-{slug}-{desired.get('deployment_id', '')}"
    old = desired.get("old_container") or ""
    text = (
        f"# Break-glass: {slug}\n\n"
        f"- domain: {domain}\n"
        f"- image: {image}\n"
        f"- container: {container}\n\n"
        "## Restart\n\n"
        f"    docker start {container}\n\n"
        "## Rollback\n\n"
        f"    docker stop {container}\n"
    )
    if old:
        text += f"    docker start {old}\n"
    text += (
        "\n## DNS\n\n"
        "    # upsert the site record via the Hub DnsProvider; no tokens on this host\n"
    )
    return text
