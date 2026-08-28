from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0016_partner_api_flag"),
    ]

    operations = [
        migrations.CreateModel(
            name="Workspace",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=128)),
                ("slug", models.SlugField(max_length=128, unique=True)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
        ),
        migrations.CreateModel(
            name="WorkspaceMembership",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("role", models.CharField(
                    choices=[
                        ("viewer", "Viewer"),
                        ("auditor", "Auditor"),
                        ("operator", "Operator"),
                        ("deployer", "Deployer"),
                        ("admin", "Admin"),
                        ("owner", "Owner"),
                    ],
                    default="operator",
                    max_length=16,
                )),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("user", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="workspace_memberships",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="memberships",
                    to="core.workspace",
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="workspacemembership",
            constraint=models.UniqueConstraint(
                fields=("workspace", "user"), name="uniq_workspace_membership",
            ),
        ),
    ]
