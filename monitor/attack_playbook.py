"""L5 attack playbook: Under-Attack → ban_ip → pager → auto-relax (D-057).

Takes EdgeProtection | None and degrades to notify-only in code — never a
silent no-op when the detector has tripped. Construction is
edge_protection_for(zone); this module never loads a token ref.
"""
from core.findings import resolve
from core.models import Finding
from monitor.alerts import raise_alert
from monitor.attack_detector import detect, should_relax_zone

KIND = "attack-playbook-engaged"
SOURCE = "attack_playbook"
UNDER_ATTACK = "under_attack"
RELAX_LEVEL = "medium"
NOTIFY_ONLY = "notify-only"


def fingerprint_for(zone):
    return f"{KIND}:{zone.pk}"


def engaged_finding(zone):
    if zone is None:
        return None
    workspace = getattr(getattr(zone, "account", None), "workspace", None)
    row = Finding.objects.filter(
        workspace=workspace, fingerprint=fingerprint_for(zone),
    ).first()
    if row is None or row.state == Finding.State.RESOLVED:
        return None
    return row


def run(site, edge, *, now=None, ips=None):
    """Detect, engage, or auto-relax. `edge` is EdgeProtection | None."""
    zone = getattr(site, "dns_zone", None)
    if zone is None:
        return None
    signal = detect(site, now=now)
    if signal is not None:
        chosen = list(ips) if ips is not None else list(signal.ips)
        return engage(site, edge, ips=chosen)
    current = engaged_finding(zone)
    if current is not None and should_relax_zone(zone, now=now):
        return relax(site, edge)
    return current


def engage(site, edge, *, ips=()):
    zone = site.dns_zone
    if edge is not None:
        _set_under_attack(edge, zone)
        _ban_new(edge, zone, ips)
        body = (
            f"Under-Attack mode flipped on {zone.name}; "
            f"banned {', '.join(str(ip) for ip in ips) or 'no IPs yet'}. "
            "Attack-shaped load must not scale."
        )
        fix = (
            "Leave Under-Attack mode until traffic returns to baseline; "
            "do not scale this zone."
        )
    else:
        body = (
            f"{NOTIFY_ONLY}: DnsAccount has no edge_token_ref for {zone.name}, "
            "so Under-Attack mode was not set and no IP was banned. "
            "The site is still under attack-shaped load."
        )
        fix = (
            "Connect an edge_token_ref on the DnsAccount so the playbook can "
            "set Under-Attack and ban IPs."
        )
    existing = engaged_finding(zone)
    if existing is not None:
        return existing
    return raise_alert(
        "attack-playbook-engaged",
        f"dns_zone:{zone.name}",
        workspace=zone.account.workspace,
        fingerprint=fingerprint_for(zone),
        source_engine=SOURCE,
        title="Attack playbook engaged",
        body=body,
        fix_action=fix,
    )


def relax(site, edge):
    """Drop Under-Attack at the edge, then resolve the zone Finding.

    Always call set_security_level: a fresh CloudflareEdge has an empty
    in-memory cache, and GET-then-skip lives on the client (collect_all
    constructs a new one every tick).
    """
    zone = site.dns_zone
    row = engaged_finding(zone)
    if edge is not None:
        edge.set_security_level(zone, RELAX_LEVEL)
    if row is not None:
        resolve(row, source="system")
    return row


def run_for_target(target):
    from core.models import Site
    from providers.registry import ScopeError, edge_protection_for

    sites = Site.objects.filter(primary_target=target).select_related(
        "dns_zone", "dns_zone__account",
    )
    cache = {}
    for site in sites:
        zone = site.dns_zone
        if zone is None:
            run(site, None)
            continue
        if zone.pk not in cache:
            try:
                cache[zone.pk] = edge_protection_for(zone)
            except ScopeError:
                cache[zone.pk] = None
        run(site, cache[zone.pk])


def _set_under_attack(edge, zone):
    current = getattr(edge, "security_level", {}).get(zone)
    if current != UNDER_ATTACK:
        edge.set_security_level(zone, UNDER_ATTACK)


def _ban_new(edge, zone, ips):
    banned = {
        item[1]
        for item in getattr(edge, "banned", [])
        if item and item[0] == zone
    }
    for ip in ips:
        if ip and ip not in banned:
            edge.ban_ip(zone, ip, note="attack-playbook")
            banned.add(ip)
