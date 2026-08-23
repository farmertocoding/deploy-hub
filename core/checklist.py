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


def first_run_progress():
    from core.models import DnsAccount, Project, Site, Target

    first = Site.objects.order_by("pk").first()
    mesh_only_first = (
        first is not None and first.exposure == Site.Exposure.MESH_ONLY
    )
    has_proxied_public = Site.objects.filter(
        exposure=Site.Exposure.PUBLIC, proxied=True,
    ).exists()
    items = [
        {
            "id": "enroll_target",
            "applicable": True,
            "done": Target.objects.exists(),
        },
        {
            "id": "connect_cloudflare",
            "applicable": not mesh_only_first,
            "done": DnsAccount.objects.exists(),
        },
        {
            "id": "plant_origin_ca",
            "applicable": (not mesh_only_first) and has_proxied_public,
            "done": DnsAccount.objects.exclude(origin_ca_key_ref="").exists(),
        },
        {
            "id": "add_project",
            "applicable": True,
            "done": Project.objects.exists(),
        },
    ]
    return {
        "owns_home": any(row["applicable"] and not row["done"] for row in items),
        "items": items,
    }
