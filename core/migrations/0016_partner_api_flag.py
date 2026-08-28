"""H4: durable partner API kill-switch row the poller re-reads."""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0015_phase73"),
    ]

    operations = [
        migrations.CreateModel(
            name="PartnerApiFlag",
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
                ("enabled", models.BooleanField(default=False)),
            ],
        ),
    ]
