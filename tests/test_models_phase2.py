"""Phase-2 core/deploys/catalog model shape (§D2/§D3/§N5)."""
import pytest
from django.db.utils import IntegrityError

pytestmark = pytest.mark.django_db

D2_DEPLOYMENT_STATUSES = {
    "queued",
    "running",
    "succeeded",
    "failed",
    "rolled_back",
    "cancelled",
    "superseded",
}

D2_STEP_NAMES = {
    "build",
    "ship",
    "migrate",
    "start_green",
    "health_check",
    "dns",
    "route_tls",
    "smoke_test",
    "cutover",
}


def _site(*, name="prod"):
    from core.models import Project, Site

    project = Project.objects.create(name="p", slug=f"p-{name}")
    return Site.objects.create(project=project, name=name)


def _target():
    from core.models import NetworkZone, Target

    zone = NetworkZone.objects.create(name="lan", slug="lan")
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host="10.0.0.8",
        ssh_user="deploy",
        ssh_key_ref="vault-owner-1",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


def test_deployment_status_enum_matches_d2():
    """Deployment.status is the pinned §D2 set, neither a subset nor a superset.

    What would make this fail: renaming a status or adding a fourth-wave value
    that is not in the addendum.
    """
    from deploys.models import Deployment

    assert set(Deployment.Status.values) == D2_DEPLOYMENT_STATUSES


def test_step_name_enum_matches_d2():
    """DeploymentStep.name is the pinned §D2 pipeline step list.

    What would make this fail: dropping a step or inventing a name the
    state machine does not use.
    """
    from deploys.models import DeploymentStep

    assert set(DeploymentStep.Name.values) == D2_STEP_NAMES


def test_site_instance_observed_warming():
    """observed_state includes warming so readiness-gated cutover has a home.

    What would make this fail: omitting warming from ObservedState, or
    refusing to persist it.
    """
    from core.models import SiteInstance

    inst = SiteInstance.objects.create(
        site=_site(),
        target=_target(),
        desired_image_tag="app:1",
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.WARMING,
        internal_port=20000,
    )
    inst.refresh_from_db()
    assert inst.observed_state == "warming"
    assert "warming" in SiteInstance.ObservedState.values
    assert "unhealthy" in SiteInstance.ObservedState.values


def test_site_volume_is_per_site_not_per_deployment():
    """Volumes belong to a Site (name unique per site), never to a Deployment.

    What would make this fail: an FK to Deployment, or uniqueness that is
    not (site, name) — so two sites could not share a volume name, or one
    site could register the same name twice.
    """
    from core.models import SiteVolume

    fk_models = {
        f.related_model.__name__
        for f in SiteVolume._meta.get_fields()
        if getattr(f, "many_to_one", False) and f.related_model is not None
    }
    assert "Site" in fk_models
    assert "Deployment" not in fk_models

    site = _site(name="prod")
    other = _site(name="other")
    SiteVolume.objects.create(
        site=site,
        name="data",
        container_path="/var/lib/app",
        backup_policy=SiteVolume.BackupPolicy.DIRECTORY_SYNC,
    )
    SiteVolume.objects.create(
        site=other,
        name="data",
        container_path="/var/lib/app",
        backup_policy=SiteVolume.BackupPolicy.NONE,
    )
    with pytest.raises(IntegrityError):
        SiteVolume.objects.create(
            site=site,
            name="data",
            container_path="/elsewhere",
            backup_policy=SiteVolume.BackupPolicy.NONE,
        )


def test_applied_catalog_entry_keeps_version_history():
    """§D8: every execution writes a row; current version is latest applied_at.

    What would make this fail: a unique (target, entry_id) constraint that
    refuses version 2 after version 1, so drift cannot see applied history.
    """
    from catalog.models import AppliedCatalogEntry

    target = _target()
    AppliedCatalogEntry.objects.create(
        target=target, entry_id="harden-ubuntu", version=1, mode="apply",
    )
    AppliedCatalogEntry.objects.create(
        target=target, entry_id="harden-ubuntu", version=2, mode="apply",
    )
    rows = list(
        AppliedCatalogEntry.objects.filter(
            target=target, entry_id="harden-ubuntu",
        ).order_by("applied_at", "pk")
    )
    assert [row.version for row in rows] == [1, 2]
