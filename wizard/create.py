"""Create a Project + Site in one transaction, bound to one workspace."""
from django.conf import settings
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.utils.text import slugify
from rest_framework.exceptions import ValidationError

from core.exception_handlers import django_validation_to_drf_detail
from core.hud.ports import FleetRefuse
from core.models import DnsZone, Project, Site, Target, default_workspace


def eligible_dns_zones(workspace=None):
    """purpose=prod, or purpose=test under the test-plane triple key (I-purpose)."""
    from django.db.models import Q

    prod = Q(purpose=DnsZone.Purpose.PROD)
    qs = DnsZone.objects.all()
    if workspace is not None:
        qs = qs.filter(account__workspace=workspace)
    if getattr(settings, "HUB_TEST_MODE", False):
        slugs = list(getattr(settings, "HUB_TEST_ZONE_SLUGS", None) or [])
        return qs.filter(prod | Q(purpose=DnsZone.Purpose.TEST, name__in=slugs))
    return qs.filter(prod)


def _bind_dns_zone(exposure, requested_pk, workspace=None):
    eligible = list(eligible_dns_zones(workspace))
    if requested_pk is not None:
        match = next((zone for zone in eligible if zone.pk == requested_pk), None)
        if match is None:
            raise FleetRefuse("dns_zone", "requested zone is not an eligible public zone")
        return match
    if exposure == Site.Exposure.MESH_ONLY:
        return None
    if len(eligible) == 1:
        return eligible[0]
    if not eligible:
        raise FleetRefuse("dns_zone", "no eligible DNS zone is connected")
    raise FleetRefuse("dns_zone", "several eligible zones; dns_zone is required")


def _bind_primary_target(requested_pk, workspace=None):
    enrolled = Target.objects.all()
    if workspace is not None:
        enrolled = enrolled.filter(zone__workspace=workspace)
    enrolled = list(enrolled)
    if requested_pk is not None:
        match = next((row for row in enrolled if row.pk == requested_pk), None)
        if match is None:
            raise ValidationError(
                {"primary_target": "primary_target must be an enrolled Target"}
            )
        return match
    if len(enrolled) == 1:
        return enrolled[0]
    if not enrolled:
        raise FleetRefuse("primary_target", "no enrolled target")
    raise FleetRefuse("primary_target", "several targets; primary_target is required")


def create_project(data, *, user=None, workspace=None):
    """Persist Project + Site for one workspace. ``data`` is ProjectCreateSerializer output."""
    workspace = workspace or default_workspace()
    zone = _bind_dns_zone(data["exposure"], data.get("dns_zone"), workspace)
    target = _bind_primary_target(data.get("primary_target"), workspace)

    slug = slugify(data["name"])
    if not slug:
        raise ValidationError({"name": "name must produce a slug"})
    source_kind = (
        Project.Source.LOCAL_PATH if data["local_path"] else Project.Source.GIT
    )
    environment = (data.get("environment") or "").strip() or Site.Environment.PRODUCTION
    if environment not in Site.Environment.values:
        environment = Site.Environment.PRODUCTION
    try:
        with transaction.atomic():
            project = Project(
                workspace=workspace,
                name=data["name"],
                slug=slug,
                source_kind=source_kind,
                git_url=data["git_url"],
                git_ref=data["git_ref"],
                local_path=data["local_path"],
                created_by=user,
            )
            project.full_clean()
            project.save()
            site_name = (data.get("site_name") or "").strip() or data["name"]
            site = Site(
                project=project,
                name=site_name,
                domain=data["domain"],
                exposure=data["exposure"],
                environment=environment,
                proxied=data["proxied"],
                dns_zone=zone,
                primary_target=target,
                deploy_strategy=data.get("deploy_strategy") or Site.DeployStrategy.BLUE_GREEN,
                deploy_policy=data.get("deploy_policy") or Site.DeployPolicy.AUTO,
                deploy_window_cron=data.get("deploy_window_cron") or "",
                created_by=user,
            )
            site.full_clean()
            site.save()
    except DjangoValidationError as exc:
        raise ValidationError(django_validation_to_drf_detail(exc)) from exc
    return project
