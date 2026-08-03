from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0001_initial"),
    ]

    operations = [
        migrations.AlterField(
            model_name="auditevent",
            name="source",
            field=models.CharField(
                choices=[("ui", "Ui"), ("api", "Api"), ("celery", "Celery"),
                         ("reconciler", "Reconciler"), ("system", "System"), ("ws", "Ws")],
                max_length=16,
            ),
        ),
        migrations.CreateModel(
            name="RecoveryCode",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name="ID")),
                ("code_hash", models.CharField(db_index=True, max_length=64)),
                ("created", models.DateTimeField(auto_now_add=True)),
                ("used_at", models.DateTimeField(null=True, blank=True)),
                ("user", models.ForeignKey(on_delete=django.db.models.deletion.CASCADE,
                                           related_name="recovery_codes",
                                           to=settings.AUTH_USER_MODEL)),
            ],
        ),
        migrations.AddConstraint(
            model_name="recoverycode",
            constraint=models.UniqueConstraint(fields=("user", "code_hash"),
                                               name="uniq_user_code_hash"),
        ),
    ]
