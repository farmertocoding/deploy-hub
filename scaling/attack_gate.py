"""Named refuse: attack-shaped load never scales (C4, D-057, SEC-L5-NEVER-SCALE-ATTACK).

Phase 6 must call refuse_if_attack(site). Phase 4 tests the refuse. No scaler loop.
Partner overflow also refuses (design-note §7 C5), even when the playbook is not
engaged. Do not remove refuse_if_attack.
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


class PartnerOverflowRefuse(RuntimeError):
    """Partner sites never overflow-scale, attack playbook or not."""

    def __init__(self, site):
        self.site = site
        super().__init__(f"refusing to scale {site.name}: partner overflow is out")


def refuse_if_partner_overflow(site):
    """Raise PartnerOverflowRefuse when the site is bound by PartnerSite."""
    from core.models import PartnerSite

    if PartnerSite.objects.filter(site=site).exists():
        raise PartnerOverflowRefuse(site)
    return None


def refuse_if_attack(site):
    """Raise AttackRefuse when the playbook is engaged for the site's zone.

    Returns None when the site is not under attack. Partner overflow still
    refuses (in addition). Phase 6 must call this before provisioning; a
    forgotten check is a raise, not a missed return.
    """
    zone = getattr(site, "dns_zone", None)
    row = engaged_finding(zone)
    if row is not None:
        raise AttackRefuse(site, row)
    refuse_if_partner_overflow(site)
    return None
