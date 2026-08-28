from django.db import migrations, models
import django.db.models.deletion


def assign_legacy_resources(apps, schema_editor):
    Workspace = apps.get_model("core", "Workspace")
    workspace, _ = Workspace.objects.get_or_create(
        slug="default", defaults={"name": "Default workspace"},
    )
    for model_name in (
        "AuditEvent", "Project", "NetworkZone", "DnsAccount", "Partner",
        "OperationLock", "Finding",
    ):
        apps.get_model("core", model_name).objects.filter(
            workspace__isnull=True,
        ).update(workspace=workspace)


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0018_hud_command_operations"),
    ]

    operations = [
        migrations.AddField(
            model_name="auditevent",
            name="workspace",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="audit_events", to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="project",
            name="workspace",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="projects", to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="networkzone",
            name="workspace",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="network_zones", to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="dnsaccount",
            name="workspace",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="dns_accounts", to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="partner",
            name="workspace",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="partners", to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="operationlock",
            name="workspace",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="operation_locks", to="core.workspace",
            ),
        ),
        migrations.AddField(
            model_name="finding",
            name="workspace",
            field=models.ForeignKey(
                blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                related_name="findings", to="core.workspace",
            ),
        ),
        migrations.RunPython(assign_legacy_resources, migrations.RunPython.noop),
    ]
