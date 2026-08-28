"""§F3 first-run progress — derived from the fleet, not a topic.

Home owns the checklist until every applicable item is done. Applicability:
enroll first Target; connect Cloudflare unless the first Site is mesh_only;
plant Origin-CA only once a proxied public Site exists (skip mesh-only and
unproxied-until-refused); add a Project (the POST that binds dns_zone and
primary_target). `site-dns-unbound` is not a state this can observe.
"""

ITEM_IDS = (
    "enroll_target",
    "connect_cloudflare",
    "plant_origin_ca",
    "add_project",
)


def first_run_progress(workspace=None):
    from core.models import DnsAccount, Project, Site, Target

    sites = Site.objects.order_by("pk")
    targets = Target.objects.all()
    accounts = DnsAccount.objects.all()
    projects = Project.objects.all()
    if workspace is not None:
        sites = sites.filter(project__workspace=workspace)
        targets = targets.filter(zone__workspace=workspace)
        accounts = accounts.filter(workspace=workspace)
        projects = projects.filter(workspace=workspace)
    first = sites.first()
    mesh_only_first = (
        first is not None and first.exposure == Site.Exposure.MESH_ONLY
    )
    has_proxied_public = sites.filter(
        exposure=Site.Exposure.PUBLIC, proxied=True,
    ).exists()
    items = [
        {
            "id": "enroll_target",
            "applicable": True,
            "done": targets.exists(),
        },
        {
            "id": "connect_cloudflare",
            "applicable": not mesh_only_first,
            "done": accounts.exists(),
        },
        {
            "id": "plant_origin_ca",
            "applicable": (not mesh_only_first) and has_proxied_public,
            "done": accounts.exclude(origin_ca_key_ref="").exists(),
        },
        {
            "id": "add_project",
            "applicable": True,
            "done": projects.exists(),
        },
    ]
    return {
        "owns_home": any(row["applicable"] and not row["done"] for row in items),
        "items": items,
    }
