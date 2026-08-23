"""Phase 5 schema wave (design note §2, D-072): Target.Kind.AWS_EC2 +
nullable Target.provider_ref.

DnsAccount.Provider.ROUTE53 is a Python TextChoices member — fold the
generated AlterField into this wave. CheckRun kinds aws_iam_scope and
aws_reaper are Python-only; do not AlterField CheckRun. No new tables.
No NetworkZone.kind. No Site.tier. 0011 stays closed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0011_phase4"),
    ]

    operations = [
        migrations.AddField(
            model_name="target",
            name="provider_ref",
            field=models.CharField(blank=True, max_length=64, null=True),
        ),
        migrations.AlterField(
            model_name="target",
            name="kind",
            field=models.CharField(
                choices=[("ssh", "Ssh"), ("aws_ec2", "Aws Ec2")],
                default="ssh",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="dnsaccount",
            name="provider",
            field=models.CharField(
                choices=[("cloudflare", "Cloudflare"), ("route53", "Route53")],
                default="cloudflare",
                max_length=32,
            ),
        ),
    ]
