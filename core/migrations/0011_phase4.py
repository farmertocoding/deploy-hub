"""Phase 4 schema wave (design note §2, D-056): DnsZone.provider + unique
(provider, name); AuditEvent.prev_hash + nullable shipped_at.

CheckRun kinds are Python TextChoices on an existing CharField — do not
AlterField CheckRun here. BACKUP closed results live in clean(). No new
tables. No Site.tier. No CheckRun Site FK.
"""

from django.db import migrations, models


def _copy_dnszone_provider_from_account(apps, schema_editor):
    DnsZone = apps.get_model("core", "DnsZone")
    db_alias = schema_editor.connection.alias
    for zone in DnsZone.objects.using(db_alias).select_related("account").iterator():
        DnsZone.objects.using(db_alias).filter(pk=zone.pk).update(
            provider=zone.account.provider,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0010_phase3b"),
    ]

    operations = [
        migrations.AddField(
            model_name="dnszone",
            name="provider",
            field=models.CharField(blank=True, default="", max_length=32),
        ),
        migrations.RunPython(
            _copy_dnszone_provider_from_account,
            reverse_code=migrations.RunPython.noop,
        ),
        migrations.AddConstraint(
            model_name="dnszone",
            constraint=models.UniqueConstraint(
                fields=("provider", "name"),
                name="uniq_dnszone_provider_name",
            ),
        ),
        migrations.AddField(
            model_name="auditevent",
            name="prev_hash",
            field=models.CharField(blank=True, default="", max_length=64),
        ),
        migrations.AddField(
            model_name="auditevent",
            name="shipped_at",
            field=models.DateTimeField(blank=True, null=True),
        ),
    ]
