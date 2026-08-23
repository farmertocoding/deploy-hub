"""Phase 3b schema: Site.edge_owner only (design note §2).

CheckRun.Kind.ADOPT is a Python TextChoices member on an existing CharField —
do not AlterField CheckRun here. Adopt progress lives in CheckRun.results
(closed schema, S2). No new tables. No Site.tier.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0009_phase3"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="edge_owner",
            field=models.CharField(
                choices=[("host_caddy", "Host Caddy"), ("site_caddy", "Site Caddy")],
                default="host_caddy",
                max_length=16,
            ),
        ),
    ]
