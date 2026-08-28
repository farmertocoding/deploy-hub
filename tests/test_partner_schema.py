"""Phase 5.5 schema wave: Partner + PartnerSite + Hub replay/idempotency.

0013_phase55.py is the only Hub migration this phase. CheckRun kinds and
Secret.Kind.WEBHOOK_SECRET are Python choices. No Site.tier, Site.partner_id,
Target.tier, NetworkZone.kind, or PartnerTemplate table. 0012 stays closed.
"""
import importlib

import pytest
from django.db import IntegrityError, migrations, transaction
from django.db.models import (
    SET_NULL,
    CharField,
    ForeignKey,
    IntegerField,
    JSONField,
    OneToOneField,
    TextField,
)

pytestmark = pytest.mark.django_db


def _partner(slug, **kwargs):
    from core.models import Partner

    kwargs.setdefault("name", slug)
    return Partner.objects.create(slug=slug, **kwargs)


def _site(name):
    from core.models import Project, Site

    project = Project.objects.create(name=name, slug=name)
    return Site.objects.create(
        project=project,
        name=name,
        exposure=Site.Exposure.MESH_ONLY,
    )


def test_partner_and_partnersite_exist():
    """Partner and PartnerSite persist; isolation is the binding, not Site.tier.

    What would make this fail: omitting either table, a Site.partner_id FK
    instead of PartnerSite, missing pubkey slots, a private-key column, or
    destination_order defaulting to something other than [].
    """
    from core.models import Partner, PartnerSite

    slug_field = Partner._meta.get_field("slug")
    assert slug_field.max_length == 64
    assert slug_field.unique is False
    assert "uniq_partner_workspace_slug" in {
        c.name for c in Partner._meta.constraints
    }
    assert isinstance(Partner._meta.get_field("pubkey_current"), TextField)
    assert isinstance(Partner._meta.get_field("pubkey_previous"), TextField)
    dest = Partner._meta.get_field("destination_order")
    assert isinstance(dest, JSONField)
    assert dest.default is list
    names = {f.name for f in Partner._meta.get_fields()}
    assert "private_key" not in names
    assert not any("private" in n for n in names)

    partner = _partner(
        "schema-partner",
        pubkey_current="ed25519-current",
        pubkey_previous="ed25519-previous",
        webhook_url="",
    )
    partner.refresh_from_db()
    assert partner.destination_order == []
    assert partner.suspended is False
    assert partner.webhook_url == ""
    assert partner.pubkey_current == "ed25519-current"
    assert partner.pubkey_previous == "ed25519-previous"
    assert partner.created_at is not None

    site = _site("schema-site")
    binding = PartnerSite.objects.create(
        partner=partner, site=site, tenant_ref="tenant-a",
    )
    binding.refresh_from_db()
    assert isinstance(PartnerSite._meta.get_field("partner"), ForeignKey)
    assert isinstance(PartnerSite._meta.get_field("site"), OneToOneField)
    assert binding.partner_id == partner.pk
    assert binding.site_id == site.pk
    assert binding.tenant_ref == "tenant-a"
    assert site.partner_site.pk == binding.pk


def test_partnersite_unique_tenant_ref_per_partner():
    """(partner, tenant_ref) is unique; two partners may reuse a tenant_ref.

    What would make this fail: uniqueness on tenant_ref alone (cross-partner
    collision) or no DB unique so a skipped clean() could double-bind.
    """
    from core.models import PartnerSite

    a = _partner("uniq-ps-a")
    b = _partner("uniq-ps-b")
    site_a = _site("uniq-ps-site-a")
    site_b = _site("uniq-ps-site-b")
    site_c = _site("uniq-ps-site-c")
    PartnerSite.objects.create(partner=a, site=site_a, tenant_ref="shared")
    PartnerSite.objects.create(partner=b, site=site_b, tenant_ref="shared")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PartnerSite.objects.create(partner=a, site=site_c, tenant_ref="shared")
    assert PartnerSite.objects.filter(tenant_ref="shared").count() == 2


def test_replay_nonce_unique_per_partner():
    """(partner, nonce) is unique so a Hub replay cache cannot store twice.

    What would make this fail: uniqueness on nonce alone, or no unique so a
    forwarded replay could insert a second row for the same partner.
    """
    from core.models import PartnerReplayNonce

    a = _partner("uniq-nonce-a")
    b = _partner("uniq-nonce-b")
    PartnerReplayNonce.objects.create(partner=a, nonce="n-1")
    PartnerReplayNonce.objects.create(partner=b, nonce="n-1")
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PartnerReplayNonce.objects.create(partner=a, nonce="n-1")
    assert PartnerReplayNonce.objects.filter(nonce="n-1").count() == 2


def test_idempotency_key_unique_per_partner():
    """(partner, key) is unique and stores params_hash plus the first response.

    What would make this fail: uniqueness on key alone, dropping params_hash,
    or not persisting status_code/response so a 24 h replay has nothing to
    return verbatim.
    """
    from core.models import PartnerIdempotencyKey

    hash_field = PartnerIdempotencyKey._meta.get_field("params_hash")
    assert isinstance(hash_field, CharField)
    assert hash_field.max_length == 64

    a = _partner("uniq-idem-a")
    b = _partner("uniq-idem-b")
    params = "a" * 64
    first = PartnerIdempotencyKey.objects.create(
        partner=a,
        key="idem-1",
        params_hash=params,
        status_code=201,
        response={"ok": True},
    )
    first.refresh_from_db()
    assert first.params_hash == params
    assert first.status_code == 201
    assert first.response == {"ok": True}
    PartnerIdempotencyKey.objects.create(
        partner=b,
        key="idem-1",
        params_hash=params,
        status_code=201,
        response={"ok": True},
    )
    with pytest.raises(IntegrityError):
        with transaction.atomic():
            PartnerIdempotencyKey.objects.create(
                partner=a,
                key="idem-1",
                params_hash="b" * 64,
                status_code=422,
                response={"ok": False},
            )
    assert PartnerIdempotencyKey.objects.filter(key="idem-1").count() == 2


def test_auditevent_partner_fk_replaces_stub():
    """AuditEvent.partner is a nullable SET_NULL FK; partner_id_stub is gone.

    What would make this fail: leaving the IntegerField stub, a CASCADE that
    deletes the audit row, or a non-nullable FK that every event must fill.
    """
    from core.models import AuditEvent, Partner

    names = {f.name for f in AuditEvent._meta.get_fields()}
    assert "partner_id_stub" not in names
    field = AuditEvent._meta.get_field("partner")
    assert isinstance(field, ForeignKey)
    assert not isinstance(field, IntegerField)
    assert field.null is True
    assert field.blank is True
    assert field.remote_field.on_delete is SET_NULL
    assert field.remote_field.model is Partner

    partner = _partner("audit-fk")
    event = AuditEvent.objects.create(
        source=AuditEvent.Source.SYSTEM,
        action="partner-schema",
        partner=partner,
    )
    event.refresh_from_db()
    assert event.partner_id == partner.pk
    partner.delete()
    event.refresh_from_db()
    assert event.partner_id is None
    assert AuditEvent.objects.filter(pk=event.pk).exists()


def test_checkrun_kinds_partner_reaper_and_intake_poll_exist():
    """partner_reaper and intake_poll persist on the existing CheckRun table.

    What would make this fail: omitting a named kind so later tasks edit
    models.py, or AlterField-ing CheckRun.kind in 0013.
    """
    from core.models import CheckRun

    assert CheckRun.Kind.PARTNER_REAPER == "partner_reaper"
    assert CheckRun.Kind.INTAKE_POLL == "intake_poll"

    for kind in (CheckRun.Kind.PARTNER_REAPER, CheckRun.Kind.INTAKE_POLL):
        run = CheckRun.objects.create(
            kind=kind,
            status=CheckRun.Status.SUCCEEDED,
            results={"schema_version": 1},
        )
        run.refresh_from_db()
        assert run.kind == kind


def test_no_site_tier_and_no_networkzone_kind():
    """0013 does not grow Site.tier, NetworkZone.kind, or a PartnerTemplate table.

    What would make this fail: D-053 Site.tier, NetworkZone.kind, a Hub
    template table, reopening closed 0012, or AlterField CheckRun.
    """
    from django.apps import apps

    from core import models as core_models
    from core.models import NetworkZone, Site

    assert "kind" not in {f.name for f in NetworkZone._meta.get_fields()}
    assert "tier" not in {f.name for f in Site._meta.get_fields()}
    assert not hasattr(core_models, "PartnerTemplate")
    assert "PartnerTemplate" not in {m.__name__ for m in apps.get_models()}

    closed = importlib.import_module("core.migrations.0012_phase5").Migration
    assert closed.dependencies == [("core", "0011_phase4")]

    wave = importlib.import_module("core.migrations.0013_phase55").Migration
    assert wave.dependencies == [("core", "0012_phase5")]
    assert not any(
        isinstance(op, migrations.AlterField)
        and getattr(op, "model_name", "") == "checkrun"
        for op in wave.operations
    )
    created = {
        op.name
        for op in wave.operations
        if isinstance(op, migrations.CreateModel)
    }
    assert created == {
        "Partner",
        "PartnerSite",
        "PartnerReplayNonce",
        "PartnerIdempotencyKey",
    }
    removed = {
        (op.model_name, op.name)
        for op in wave.operations
        if isinstance(op, migrations.RemoveField)
    }
    assert ("auditevent", "partner_id_stub") in removed
    added = {
        (op.model_name, op.name)
        for op in wave.operations
        if isinstance(op, migrations.AddField)
    }
    assert ("auditevent", "partner") in added
    assert not any(
        isinstance(op, (migrations.AddField, migrations.AlterField))
        and getattr(op, "model_name", "") in {"networkzone", "site", "target"}
        for op in wave.operations
    )


def test_no_site_partner_id():
    """Isolation is PartnerSite, not a Site.partner_id column.

    What would make this fail: adding Site.partner or Site.partner_id so
    querysets filter a denormalized FK the design forbids.
    """
    from core.models import Site

    names = {f.name for f in Site._meta.get_fields()}
    concrete = {f.name for f in Site._meta.concrete_fields}
    assert "partner_id" not in names
    assert "partner" not in names
    assert "partner_id" not in concrete
    assert "partner" not in concrete


def test_no_target_tier():
    """Partner-tier is pk ∈ some destination_order, not Target.tier.

    What would make this fail: a Target.tier column that later tasks would
    have to keep in sync with Partner.destination_order.
    """
    from core.models import Target

    assert "tier" not in {f.name for f in Target._meta.get_fields()}


def test_partner_quota_defaults_are_5_50_5():
    """U2 floors persist as Partner defaults: max_sites=5, deploys/day=50, domains=5.

    What would make this fail: null defaults (unbounded), different numbers,
    or requiring the caller to pass quotas on every create.
    """
    from core.models import Partner

    assert Partner._meta.get_field("max_sites").default == 5
    assert Partner._meta.get_field("deploys_per_day").default == 50
    assert Partner._meta.get_field("domains").default == 5
    assert Partner._meta.get_field("max_sites").null is False
    assert Partner._meta.get_field("deploys_per_day").null is False
    assert Partner._meta.get_field("domains").null is False

    partner = _partner("quota-defaults")
    partner.refresh_from_db()
    assert partner.max_sites == 5
    assert partner.deploys_per_day == 50
    assert partner.domains == 5


def test_secret_kind_webhook_secret_exists():
    """whsec_ lands as Secret.Kind.WEBHOOK_SECRET, not a Partner column.

    What would make this fail: omitting the kind so Task 5 invents HMAC or
    stores the secret on Partner.
    """
    from vault.models import Secret

    assert Secret.Kind.WEBHOOK_SECRET == "webhook_secret"
    assert "webhook_secret" in Secret.Kind.values


def test_secret_kind_has_no_hmac():
    """HMAC vault kind waits on the slip; it does not land this wave.

    What would make this fail: adding hmac / hmac_secret / HMAC as a Kind
    so enablement sneaks in with the webhook_secret AlterField.
    """
    from vault.models import Secret

    assert all("hmac" not in value.lower() for value in Secret.Kind.values)
    assert all("hmac" not in name.lower() for name in Secret.Kind.names)
