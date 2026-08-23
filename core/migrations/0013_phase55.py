"""Phase 5.5 schema wave (design note §2, D-076): Partner, PartnerSite,
PartnerReplayNonce, PartnerIdempotencyKey, and AuditEvent.partner FK.

CheckRun kinds partner_reaper and intake_poll are Python TextChoices on an
existing CharField — do not AlterField CheckRun here. 0012 stays closed.
No Site.tier, Site.partner_id, Target.tier, NetworkZone.kind, or
PartnerTemplate table.
"""

import django.core.validators
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0012_phase5"),
    ]

    operations = [
        migrations.RemoveField(
            model_name="auditevent",
            name="partner_id_stub",
        ),
        migrations.CreateModel(
            name="Partner",
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
                ("slug", models.SlugField(max_length=64, unique=True)),
                ("name", models.CharField(max_length=128)),
                ("pubkey_current", models.TextField(blank=True, default="")),
                ("pubkey_previous", models.TextField(blank=True, default="")),
                (
                    "max_sites",
                    models.PositiveIntegerField(
                        default=5,
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "deploys_per_day",
                    models.PositiveIntegerField(
                        default=50,
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                (
                    "domains",
                    models.PositiveIntegerField(
                        default=5,
                        validators=[django.core.validators.MinValueValidator(1)],
                    ),
                ),
                ("destination_order", models.JSONField(default=list)),
                ("suspended", models.BooleanField(default=False)),
                (
                    "webhook_url",
                    models.CharField(blank=True, default="", max_length=2048),
                ),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "constraints": [
                    models.CheckConstraint(
                        condition=models.Q(
                            ("max_sites__gte", 1),
                            ("deploys_per_day__gte", 1),
                            ("domains__gte", 1),
                        ),
                        name="partner_quotas_finite",
                    ),
                ],
            },
        ),
        migrations.AddField(
            model_name="auditevent",
            name="partner",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name="audit_events",
                to="core.partner",
            ),
        ),
        migrations.CreateModel(
            name="PartnerIdempotencyKey",
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
                ("key", models.CharField(max_length=255)),
                ("params_hash", models.CharField(max_length=64)),
                ("status_code", models.PositiveSmallIntegerField()),
                ("response", models.JSONField(default=dict)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "partner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="idempotency_keys",
                        to="core.partner",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("partner", "key"),
                        name="uniq_partner_idempotency_key",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PartnerReplayNonce",
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
                ("nonce", models.CharField(max_length=128)),
                ("seen_at", models.DateTimeField(auto_now_add=True)),
                (
                    "partner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="replay_nonces",
                        to="core.partner",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("partner", "nonce"),
                        name="uniq_partner_replay_nonce",
                    ),
                ],
            },
        ),
        migrations.CreateModel(
            name="PartnerSite",
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
                ("tenant_ref", models.CharField(max_length=128)),
                (
                    "partner",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="partner_sites",
                        to="core.partner",
                    ),
                ),
                (
                    "site",
                    models.OneToOneField(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="partner_site",
                        to="core.site",
                    ),
                ),
            ],
            options={
                "constraints": [
                    models.UniqueConstraint(
                        fields=("partner", "tenant_ref"),
                        name="uniq_partnersite_partner_tenant_ref",
                    ),
                ],
            },
        ),
    ]
