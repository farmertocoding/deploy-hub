"""Phase 7.3 schema wave (design note §2, D-132): Site.preview_of + preview_ref.

0014 stays closed. No ScalePolicy. CheckRun kinds stay Python TextChoices —
do not AlterField them here.
"""

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0014_phase6"),
    ]

    operations = [
        migrations.AddField(
            model_name="site",
            name="preview_of",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="previews",
                to="core.site",
            ),
        ),
        migrations.AddField(
            model_name="site",
            name="preview_ref",
            field=models.CharField(blank=True, default="", max_length=128),
        ),
    ]
