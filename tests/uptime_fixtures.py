"""Shared Site/Target rows for the Task 8 probe-cycle tests (§5, §O3).

Kept out of the test modules so test_deadman / test_canary /
test_uptime_events build the same fleet the same way. Public sites attach
the dns_fixtures zone (D-033 check constraint); mesh_only sites carry no
zone and no public domain — the Hub reaches them over tailnet HTTP.
"""


def make_site(name, *, exposure="public", domain="", host=None, ws_payload=None):
    from dns_fixtures import default_dns_zone

    from core.models import NetworkZone, Project, Site, Target

    project, _ = Project.objects.get_or_create(
        slug="uptime-fixture", defaults={"name": "uptime-fixture",
                                         "git_url": "https://example.com/repo.git"},
    )
    zone, _ = NetworkZone.objects.get_or_create(
        slug="uptime-net", defaults={"name": "uptime-net"},
    )
    target = Target.objects.create(
        zone=zone,
        host=host or f"{name}.tail.example",
        status=Target.Status.READY,
        collect_payload=ws_payload,
    )
    if exposure == "public" and not domain:
        domain = f"{name}.example.com"
    site = Site.objects.create(
        project=project,
        name=name,
        domain=domain,
        exposure=exposure,
        primary_target=target,
        dns_zone=default_dns_zone() if exposure == "public" else None,
    )
    return site
