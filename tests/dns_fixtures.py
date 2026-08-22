"""Shared DnsAccount/DnsZone fixture rows (Phase 3 Task 1).

Every public Site now requires a DnsZone (check-constrained, D-033); tests
that need a public Site but are not about DNS attach this default zone. The
refs are vault owner ids that own nothing — tests that exercise the vault
seam store their own token first (see test_dns_zone_wall.py).
"""


def default_dns_zone(name="example.com", *, purpose="prod", provider_zone_id=None):
    from core.models import DnsAccount, DnsZone

    account, _ = DnsAccount.objects.get_or_create(
        provider=DnsAccount.Provider.CLOUDFLARE, label="test-fixture",
    )
    zone, created = DnsZone.objects.get_or_create(
        account=account,
        name=name,
        defaults={
            "provider_zone_id": provider_zone_id or f"zid-{name}",
            "purpose": purpose,
        },
    )
    if not created and zone.purpose != purpose:
        # Never hand back a zone of the wrong purpose silently — a test asking
        # for purpose=test must not receive the shared prod row (§B9).
        zone.purpose = purpose
        zone.save(update_fields=["purpose"])
    return zone
