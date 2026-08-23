"""Phase 5.5: Secret.Kind.WEBHOOK_SECRET. HMAC kind does not land.

Folded AlterField on Secret.kind into this vault wave — not a second Hub
core migration. 0012 stays closed.
"""

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("vault", "0002_backupunit_and_secret_kinds"),
    ]

    operations = [
        migrations.AlterField(
            model_name="secret",
            name="kind",
            field=models.CharField(
                choices=[
                    ("env_bundle", "Env Bundle"),
                    ("ssh_private_key", "Ssh Private Key"),
                    ("tls_private_key", "Tls Private Key"),
                    ("cloud_credential", "Cloud Credential"),
                    ("api_token", "Api Token"),
                    ("database_url", "Database Url"),
                    ("backup_key", "Backup Key"),
                    ("webhook_secret", "Webhook Secret"),
                ],
                max_length=32,
            ),
        ),
    ]
