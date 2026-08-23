"""K6: partner router maps to no ACTION_TIERS T1/T2 internal id; V3 no job cmds.

Operator chrome may have those ids (Task 5/7). The partner router must not
call them. Function-level PART-K6-NO-INTERNAL-ACTIONS only.
"""
import ast
import pathlib

import pytest

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent

# Standing list from Task 4. partner.* operator ids land in ACTION_TIERS later;
# the router must not map to them even before that row exists.
BANNED_INTERNAL = frozenset({
    "target.delete",
    "key.export",
    "kek.rotate",
    "ssh.rotate",
    "instance.create",
    "instance.terminate",
    "dns.change",
    "site.auto_mode",
    "partner.create",
    "partner.suspend",
    "partner.api_kill_switch",
    "partner.site_takedown",
    "partner.destination_rank",
})
ROUTER_FILES = (
    REPO / "core" / "partner_jobs.py",
    REPO / "intake" / "app.py",
)


def _string_constants(path):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            found.add(node.value)
    return found


@pytest.mark.req("PART-K6-NO-INTERNAL-ACTIONS")
def test_partner_router_maps_to_no_action_tiers_t1_t2():
    """The partner router maps to no ACTION_TIERS T1/T2 internal id.

    What would make this fail: dispatching site.create to target.delete /
    dns.change / partner.suspend (or any other T1/T2 operator id) so a
    machine caller reaches step-up actions.
    """
    from core.partner_jobs import PARTNER_ROUTER

    from core.actions import ACTION_TIERS

    t1_t2 = {row["id"] for row in ACTION_TIERS if row["tier"] in {"T1", "T2"}}
    banned = t1_t2 | BANNED_INTERNAL
    mapped = set(PARTNER_ROUTER.values()) | set(PARTNER_ROUTER.keys())
    overlap = mapped & banned
    assert not overlap, f"partner router maps to internal ids: {sorted(overlap)}"
    for path in ROUTER_FILES:
        assert path.is_file(), path
        found = _string_constants(path) & banned
        assert not found, f"{path.name} names internal ACTION_TIERS ids: {sorted(found)}"
    handlers = set(PARTNER_ROUTER.values())
    assert handlers
    assert all(isinstance(name, str) and name.startswith("partner_job.") for name in handlers)


@pytest.mark.req("PART-K6-NO-INTERNAL-ACTIONS")
def test_scheduled_job_create_on_partnersite_refuses():
    """Scheduled-job create/edit on a PartnerSite is prohibited (V3).

    What would make this fail: allowing docker-exec job commands on a partner
    site, which is the machine-caller path around the partner router allowlist.
    """
    from core.partner_jobs import PartnerRefuse, refuse_scheduled_job

    from core.models import NetworkZone, Partner, PartnerSite, Project, Site, Target

    zone = NetworkZone.objects.create(name="k6-zone", slug="k6-zone")
    target = Target.objects.create(
        zone=zone, host="k6.lan", kind=Target.Kind.AWS_EC2,
        status=Target.Status.READY,
    )
    partner = Partner.objects.create(
        slug="k6-p", name="k6-p", destination_order=[target.pk],
    )
    project = Project.objects.create(name="k6-site", slug="k6-site")
    site = Site.objects.create(
        project=project, name="k6-site", exposure=Site.Exposure.MESH_ONLY,
        primary_target=target,
    )
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref="k6-t")
    with pytest.raises(PartnerRefuse) as create_exc:
        refuse_scheduled_job(site, action="create")
    assert create_exc.value.reason == "scheduled-job"
    with pytest.raises(PartnerRefuse) as edit_exc:
        refuse_scheduled_job(site, action="edit")
    assert edit_exc.value.reason == "scheduled-job"

    plain_project = Project.objects.create(name="k6-plain", slug="k6-plain")
    plain = Site.objects.create(
        project=plain_project, name="k6-plain", exposure=Site.Exposure.MESH_ONLY,
    )
    assert refuse_scheduled_job(plain, action="create") is None
