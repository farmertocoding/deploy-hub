"""Named refuse: attack-shaped load never scales (C4, D-057, SEC-L5-NEVER-SCALE-ATTACK).

Phase 6 must call refuse_if_attack(site). Phase 4 tests the refuse. No scaler loop.
"""
from monitor.attack_playbook import engaged_finding


class AttackRefuse(RuntimeError):
    """Playbook is engaged for this site's zone — do not scale."""

    def __init__(self, site, finding):
        self.site = site
        self.finding = finding
        super().__init__(
            f"refusing to scale {site.name}: attack playbook engaged "
            f"({finding.fingerprint})"
        )


def refuse_if_attack(site):
    """Raise AttackRefuse when the playbook is engaged for the site's zone.

    Returns None when the site is not under attack. Phase 6 must call this
    before provisioning; a forgotten check is a raise, not a missed return.
    """
    zone = getattr(site, "dns_zone", None)
    row = engaged_finding(zone)
    if row is None:
        return None
    raise AttackRefuse(site, row)
