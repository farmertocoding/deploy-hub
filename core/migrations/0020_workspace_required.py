from django.db import migrations, models
import django.db.models.deletion

from core.models.workspace import default_workspace_id


def backfill_null_workspaces(apps, schema_editor):
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
        ("core", "0019_workspace_resource_scope"),
    ]

    operations = [
        migrations.RunPython(backfill_null_workspaces, migrations.RunPython.noop),
        migrations.AddField(
            model_name="site",
            name="environment",
            field=models.CharField(
                choices=[
                    ("production", "Production"),
                    ("staging", "Staging"),
                    ("development", "Development"),
                    ("preview", "Preview"),
                ],
                default="production",
                max_length=16,
            ),
        ),
        migrations.AlterField(
            model_name="auditevent",
            name="workspace",
            field=models.ForeignKey(
                default=default_workspace_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="audit_events",
                to="core.workspace",
            ),
        ),
        migrations.AlterField(
            model_name="project",
            name="workspace",
            field=models.ForeignKey(
                default=default_workspace_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="projects",
                to="core.workspace",
            ),
        ),
        migrations.AlterField(
            model_name="project",
            name="slug",
            field=models.SlugField(max_length=128),
        ),
        migrations.AddConstraint(
            model_name="project",
            constraint=models.UniqueConstraint(
                fields=("workspace", "slug"), name="uniq_project_workspace_slug",
            ),
        ),
        migrations.AlterField(
            model_name="networkzone",
            name="workspace",
            field=models.ForeignKey(
                default=default_workspace_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="network_zones",
                to="core.workspace",
            ),
        ),
        migrations.AlterField(
            model_name="networkzone",
            name="slug",
            field=models.SlugField(max_length=128),
        ),
        migrations.AddConstraint(
            model_name="networkzone",
            constraint=models.UniqueConstraint(
                fields=("workspace", "slug"), name="uniq_networkzone_workspace_slug",
            ),
        ),
        migrations.AlterField(
            model_name="dnsaccount",
            name="workspace",
            field=models.ForeignKey(
                default=default_workspace_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="dns_accounts",
                to="core.workspace",
            ),
        ),
        migrations.AlterField(
            model_name="partner",
            name="workspace",
            field=models.ForeignKey(
                default=default_workspace_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="partners",
                to="core.workspace",
            ),
        ),
        migrations.AlterField(
            model_name="partner",
            name="slug",
            field=models.SlugField(max_length=64),
        ),
        migrations.AddConstraint(
            model_name="partner",
            constraint=models.UniqueConstraint(
                fields=("workspace", "slug"), name="uniq_partner_workspace_slug",
            ),
        ),
        migrations.AlterField(
            model_name="operationlock",
            name="workspace",
            field=models.ForeignKey(
                default=default_workspace_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="operation_locks",
                to="core.workspace",
            ),
        ),
        migrations.AlterField(
            model_name="finding",
            name="workspace",
            field=models.ForeignKey(
                default=default_workspace_id,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="findings",
                to="core.workspace",
            ),
        ),
    ]
