"""DnsZone (provider, name) is one identity at the DB (D-033 leftover, D-056).

clean() already refuses a second account of the same provider claiming a zone
name. Phase 4 denormalizes DnsZone.provider and adds
uniq_dnszone_provider_name so a save() that skips clean() cannot split the
identity.
"""
import pytest
from django.db import IntegrityError, transaction

pytestmark = pytest.mark.django_db


def test_two_accounts_cannot_share_a_provider_zone_name():
    """(provider, name) is unique on the table, not only through clean().

    What would make this fail: uniqueness remaining a Python check on
    account__provider, so two Cloudflare accounts could both hold
    example.com if they skipped full_clean(), and dns_provider_for would
    have two candidate credentials for one zone.
    """
    from django.core.exceptions import ValidationError

    from core.models import DnsAccount, DnsZone

    names = {c.name for c in DnsZone._meta.constraints}
    assert "uniq_dnszone_provider_name" in names
    assert "uniq_dnszone_account_name" in names

    first = DnsAccount.objects.create(provider="cloudflare", label="acct-a")
    second = DnsAccount.objects.create(provider="cloudflare", label="acct-b")
    zone = DnsZone.objects.create(
        account=first, name="shared.example", provider_zone_id="z-1",
    )
    stored_provider = (
        DnsZone.objects.filter(pk=zone.pk).values_list("provider", flat=True).get()
    )
    assert stored_provider == first.provider

    with pytest.raises(ValidationError):
        DnsZone.objects.create(
            account=second, name="shared.example", provider_zone_id="z-2",
        )

    with pytest.raises(IntegrityError):
        with transaction.atomic():
            DnsZone.objects.bulk_create(
                [
                    DnsZone(
                        account=second,
                        name="shared.example",
                        provider=stored_provider,
                        provider_zone_id="z-3",
                    ),
                ]
            )
    assert DnsZone.objects.filter(name="shared.example").count() == 1


def test_dnszone_save_copies_account_provider():
    """save() and full_clean() denormalize account.provider onto the row.

    What would make this fail: provider remaining a @property that is never
    stored, so UniqueConstraint(provider, name) cannot exist, or a save()
    that leaves the column empty when the caller omitted provider=.
    """
    from django.db.models import CharField

    from core.models import DnsAccount, DnsZone

    field = DnsZone._meta.get_field("provider")
    assert isinstance(field, CharField)
    assert not field.is_relation

    account = DnsAccount.objects.create(provider="cloudflare", label="copy-src")
    zone = DnsZone(account=account, name="copied.example", provider_zone_id="z-copy")
    zone.full_clean()
    assert zone.provider == account.provider
    zone.save()
    zone.refresh_from_db()
    stored = DnsZone.objects.filter(pk=zone.pk).values_list("provider", flat=True).get()
    assert stored == "cloudflare"
    assert stored == account.provider
