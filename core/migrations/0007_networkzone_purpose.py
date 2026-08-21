from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0006_target_collect_cursor"),
    ]

    operations = [
        migrations.AddField(
            model_name="networkzone",
            name="purpose",
            field=models.CharField(
                choices=[("prod", "Prod"), ("test", "Test")],
                default="prod",
                max_length=16,
            ),
        ),
    ]
