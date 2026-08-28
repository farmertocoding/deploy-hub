import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0022_finding_alert_audit_tenancy"),
    ]

    operations = [
        migrations.AlterField(
            model_name="finding",
            name="workspace",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="findings",
                to="core.workspace",
            ),
        ),
        migrations.AlterField(
            model_name="alertstate",
            name="workspace",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name="alert_states",
                to="core.workspace",
            ),
        ),
    ]
