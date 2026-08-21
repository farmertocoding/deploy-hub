"""Apply a catalog entry through Transport; same-version re-apply is a no-op."""
import ipaddress
import os
from pathlib import Path

from catalog.models import AppliedCatalogEntry
from core.hubfs import ensure_hub_dir, hub_join, ssh_user_from

JAIL_TEMPLATE = Path(__file__).resolve().parent / "files" / "jail.local"
PLACEHOLDER_IP = "100.64.1.1"
LIVE_JAIL = "/etc/fail2ban/jail.local"


def argv_steps(field):
    """A flat argv (first element a str) is one command; a list of lists is a sequence."""
    if not field:
        raise ValueError("argv field must be a non-empty list")
    if isinstance(field[0], (list, tuple)):
        return [list(step) for step in field]
    return [list(field)]


def apply_entry(target, entry, transport):
    """Run `entry.fix` and write AppliedCatalogEntry.

    If this (target, entry.id) already has this version as the latest row,
    probe `entry.check` and skip — zero mutating Transport calls.

    A failed step stops the sequence; no AppliedCatalogEntry is written, so a
    failed `sshd -t` does not install and does not count as applied.
    """
    if entry.id == "fail2ban-ignoreip":
        return _apply_fail2ban(target, entry, transport)
    return _apply_generic(target, entry, transport)


def _latest_row(target, entry):
    return (
        AppliedCatalogEntry.objects.filter(target=target, entry_id=entry.id)
        .order_by("-applied_at", "-pk")
        .first()
    )


def _skip_if_current(target, entry, transport):
    latest = _latest_row(target, entry)
    if latest is not None and latest.version == entry.version:
        for step in argv_steps(entry.check):
            transport.probe(step)
        return latest
    return None


def _record(target, entry, last):
    return AppliedCatalogEntry.objects.create(
        target=target,
        entry_id=entry.id,
        version=entry.version,
        mode="apply",
        result={"ok": last.ok, "exit_code": last.exit_code},
    )


def _apply_generic(target, entry, transport):
    skipped = _skip_if_current(target, entry, transport)
    if skipped is not None:
        return skipped

    results = []
    for step in argv_steps(entry.fix):
        result = transport.run(step)
        results.append(result)
        if not result.ok:
            return None

    return _record(target, entry, results[-1])


def parse_hub_mesh_ip(raw=None):
    """Singular IPv4, same rules as scripts/harden-ubuntu.sh require_hub_mesh_ip."""
    if raw is None:
        raw = os.environ.get("HUB_MESH_IP")
    if raw is None:
        return None
    if not raw or any(ch.isspace() for ch in raw) or "/" in raw:
        return None
    try:
        addr = ipaddress.ip_address(raw)
    except ValueError:
        return None
    if not isinstance(addr, ipaddress.IPv4Address):
        return None
    return str(addr)


def _is_hub_jail_source(part):
    """Catalog / hub_join staging path only — never the live fail2ban dest."""
    return str(part).endswith("/.hub/jail.local")


def _jail_pin_paths(entry):
    pins = set()
    for step in argv_steps(entry.fix):
        for part in step:
            if _is_hub_jail_source(part):
                pins.add(part)
    return pins


def _rewrite_jail_paths(step, staging, pins):
    return [staging if part in pins else part for part in step]


def _live_jail_dest_collapsed(original, rewritten):
    if not original or original[0] != "install":
        return False
    if LIVE_JAIL not in original:
        return False
    return LIVE_JAIL not in rewritten


def _apply_fail2ban(target, entry, transport):
    """Substitute HUB_MESH_IP into jail.local at put time; refuse if missing."""
    skipped = _skip_if_current(target, entry, transport)
    if skipped is not None:
        return skipped

    mesh_ip = parse_hub_mesh_ip()
    if not mesh_ip:
        return None

    rendered = JAIL_TEMPLATE.read_text(encoding="utf-8").replace(PLACEHOLDER_IP, mesh_ip)
    for line in rendered.splitlines():
        live = line.split("#", 1)[0].strip()
        if live.startswith("ignoreip") and PLACEHOLDER_IP in live:
            return None

    user = ssh_user_from(target)
    staging = hub_join("jail.local", ssh_user=user)
    ensure_hub_dir(transport, user)
    transport.put(rendered.encode(), staging, mode=0o644)

    pins = _jail_pin_paths(entry)
    results = []
    for step in argv_steps(entry.fix):
        run = _rewrite_jail_paths(step, staging, pins)
        if _live_jail_dest_collapsed(step, run):
            return None
        result = transport.run(run)
        results.append(result)
        if not result.ok:
            return None
    return _record(target, entry, results[-1])


def rollback_entry(target, entry, transport):
    """Run `entry.rollback`. fail2ban substitutes HUB_MESH_IP; refuse if missing."""
    if entry.id == "fail2ban-ignoreip":
        return _rollback_fail2ban(target, entry, transport)
    results = []
    for step in argv_steps(entry.rollback):
        result = transport.run(step)
        results.append(result)
        if not result.ok:
            return None
    return results[-1] if results else None


def _rollback_fail2ban(target, entry, transport):
    mesh_ip = parse_hub_mesh_ip()
    if not mesh_ip:
        return None
    results = []
    for step in argv_steps(entry.rollback):
        run = [mesh_ip if part == PLACEHOLDER_IP else part for part in step]
        if PLACEHOLDER_IP in run:
            return None
        result = transport.run(run)
        results.append(result)
        if not result.ok:
            return None
    return results[-1] if results else None
