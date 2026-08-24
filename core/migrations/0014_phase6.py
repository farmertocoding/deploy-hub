"""Phase 6 schema wave (design note §2, D-087): HostMetric + Site.scale_ready.

0013 stays closed. No ScalePolicy table. CheckRun kinds and OperationLock
kinds are Python TextChoices on existing CharFields — do not AlterField
either here. No Site.tier, Site.partner_id, or Target.tier. No data
migration backfill of scale_ready.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0013_phase55"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="scale_ready",
            field=models.BooleanField(default=False),
        ),
        migrations.CreateModel(
            name="HostMetric",
            fields=[
                (
                    "id",
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name="ID",
                    ),
                ),
                ("ts", models.DateTimeField(db_index=True)),
                ("cpu", models.FloatField(null=True)),
                ("ram", models.FloatField(null=True)),
                ("disk", models.FloatField(null=True)),
                ("load", models.FloatField(null=True)),
                ("cores", models.PositiveIntegerField(null=True)),
                (
                    "target",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="host_metrics",
                        to="core.target",
                    ),
                ),
            ],
            options={
                "indexes": [
                    models.Index(
                        fields=["target", "-ts"],
                        name="core_hostme_target__b2d32c_idx",
                    ),
                ],
            },
        ),
    ]
