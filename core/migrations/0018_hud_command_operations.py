from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ("core", "0017_workspace_rbac"),
    ]

    operations = [
        migrations.CreateModel(
            name="HudOperation",
            fields=[
                ("audit_event", models.OneToOneField(
                    on_delete=django.db.models.deletion.PROTECT,
                    primary_key=True,
                    related_name="hud_operation",
                    serialize=False,
                    to="core.auditevent",
                )),
                ("action", models.CharField(db_index=True, max_length=64)),
                ("object_type", models.CharField(blank=True, default="", max_length=64)),
                ("object_id", models.CharField(blank=True, default="", max_length=64)),
                ("state", models.CharField(
                    choices=[
                        ("queued", "Queued"),
                        ("running", "Running"),
                        ("succeeded", "Succeeded"),
                        ("failed", "Failed"),
                        ("cancelled", "Cancelled"),
                    ],
                    db_index=True,
                    default="queued",
                    max_length=16,
                )),
                ("idempotency_key", models.CharField(blank=True, max_length=128, null=True)),
                ("result", models.JSONField(blank=True, default=dict)),
                ("error_code", models.CharField(blank=True, default="", max_length=64)),
                ("error_message", models.CharField(blank=True, default="", max_length=512)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                ("started_at", models.DateTimeField(blank=True, null=True)),
                ("heartbeat_at", models.DateTimeField(blank=True, null=True)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("actor", models.ForeignKey(
                    blank=True,
                    null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name="hud_operations",
                    to=settings.AUTH_USER_MODEL,
                )),
                ("workspace", models.ForeignKey(
                    on_delete=django.db.models.deletion.PROTECT,
                    related_name="hud_operations",
                    to="core.workspace",
                )),
            ],
        ),
        migrations.CreateModel(
            name="HudCommandOutbox",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("topic", models.CharField(max_length=64)),
                ("payload", models.JSONField(blank=True, default=dict)),
                ("state", models.CharField(
                    choices=[
                        ("pending", "Pending"),
                        ("processing", "Processing"),
                        ("succeeded", "Succeeded"),
                        ("failed", "Failed"),
                    ],
                    db_index=True,
                    default="pending",
                    max_length=16,
                )),
                ("available_at", models.DateTimeField(db_index=True, default=django.utils.timezone.now)),
                ("claimed_at", models.DateTimeField(blank=True, null=True)),
                ("completed_at", models.DateTimeField(blank=True, null=True)),
                ("attempts", models.PositiveIntegerField(default=0)),
                ("last_error", models.CharField(blank=True, default="", max_length=512)),
                ("operation", models.OneToOneField(
                    on_delete=django.db.models.deletion.CASCADE,
                    related_name="outbox",
                    to="core.hudoperation",
                )),
            ],
        ),
        migrations.AddConstraint(
            model_name="hudoperation",
            constraint=models.UniqueConstraint(
                fields=("workspace", "actor", "action", "idempotency_key"),
                name="uniq_hud_operation_idempotency",
            ),
        ),
        migrations.AddIndex(
            model_name="hudoperation",
            index=models.Index(fields=["workspace", "state", "-created_at"], name="core_hudop_workspa_ef6115_idx"),
        ),
        migrations.AddIndex(
            model_name="hudoperation",
            index=models.Index(fields=["object_type", "object_id"], name="core_hudop_object__795aa1_idx"),
        ),
        migrations.AddIndex(
            model_name="hudcommandoutbox",
            index=models.Index(fields=["state", "available_at"], name="core_hudco_state_47ed1d_idx"),
        ),
    ]
