"""HUD administration read models and command authorization."""
import pytest
from django.test import override_settings
from dns_fixtures import default_dns_zone

from core.models import (
    AuditEvent,
    Finding,
    HudCommandOutbox,
    HudOperation,
    NetworkZone,
    Project,
    Site,
    Target,
    default_workspace,
)
from deploys.models import Deployment, DeploymentArtifact, DeploymentStep, Manifest
from vault.models import Secret
from vault.service import put as vault_put

pytestmark = pytest.mark.django_db


@pytest.fixture
def operator(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(username="op", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return user


@pytest.fixture
def admin(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    user = django_user_model.objects.create_user(
        username="admin", password="pw-1234567890", is_staff=True, is_superuser=True,
    )
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    return user


def _site(name="prod", project_name="shop", host=None):
    zone = default_dns_zone()
    net, _ = NetworkZone.objects.get_or_create(name="hud-net", slug="hud-net")
    target = Target.objects.create(
        zone=net, host=host or f"{name}.example.test", status="ready",
    )
    project, _ = Project.objects.get_or_create(
        name=project_name, slug=project_name,
    )
    return Site.objects.create(
        project=project, name=name, domain=f"{name}.example.test",
        dns_zone=zone, primary_target=target, exposure="mesh_only",
    )


@pytest.mark.no_default_membership
def test_operator_is_forbidden_on_hud_overview(operator, client):
    r = client.get("/api/v1/hud/overview/")
    assert r.status_code == 403


def test_overview_is_one_workspace_read_model(admin, client):
    site = _site()
    Finding.objects.create(
        workspace=default_workspace(),
        source_engine="uptime", severity="p1", entity="site:shop.example.test",
        title="Probe failed", body="why", fix_action="restart",
        fingerprint="hud-p1",
    )
    r = client.get("/api/v1/hud/overview/")
    assert r.status_code == 200
    body = r.json()
    assert "observed_at" in body
    assert body["findings"]["p1"] == 1
    assert any(a["id"] == "project.create" for a in body["allowed_actions"])
    assert "site_health" in body
    assert site.name


def test_sites_fleet_row_actions_are_server_authorized(admin, client):
    _site()
    r = client.get("/api/v1/hud/sites/")
    assert r.status_code == 200
    row = r.json()["results"][0]
    assert any(a["id"] == "site.view_details" for a in row["allowed_actions"])
    disabled = {d["id"]: d for d in row["disabled_actions"]}
    assert "site.delete" in disabled
    assert disabled["site.delete"]["reason"]


def test_deployment_detail_always_emits_nine_steps(admin, client):
    site = _site()
    manifest = Manifest.objects.create(site=site, version=4, body={})
    dep = Deployment.objects.create(manifest=manifest, status="running")
    DeploymentStep.objects.create(
        deployment=dep, seq=1, name="build", status="succeeded",
    )
    r = client.get(f"/api/v1/hud/deployments/{dep.pk}/")
    assert r.status_code == 200
    names = [s["name"] for s in r.json()["steps"]]
    assert names == [
        "build", "ship", "migrate", "start_green", "health_check",
        "dns", "route_tls", "smoke_test", "cutover",
    ]
    assert r.json()["steps"][1]["state"] == "pending"
    ids = {a["id"] for a in r.json()["allowed_actions"]}
    assert "deployment.abort" in ids
    assert "site.view_health" in ids
    assert "deployment.delete" not in ids


def test_no_deployment_delete_route(admin, client):
    site = _site()
    manifest = Manifest.objects.create(site=site, version=1, body={})
    dep = Deployment.objects.create(manifest=manifest, status="failed")
    r = client.delete(f"/api/v1/hud/deployments/{dep.pk}/")
    assert r.status_code in (404, 405)
    r = client.post(
        f"/api/v1/hud/deployments/{dep.pk}/commands/",
        data={"action": "deployment.delete"},
        content_type="application/json",
    )
    assert r.status_code == 403


def test_secrets_metadata_omits_ciphertext_and_search_misses_values(admin, client):
    vault_put(
        kind=Secret.Kind.API_TOKEN,
        owner_type="dns_account",
        owner_id="2",
        plaintext=b"super-secret-token-do-not-leak",
    )
    r = client.get("/api/v1/hud/secrets/")
    assert r.status_code == 200
    raw = r.content.decode()
    assert "super-secret-token-do-not-leak" not in raw
    assert "ciphertext" not in raw
    assert "wrapped_dek" not in raw
    assert "nonce" not in raw
    row = r.json()["results"][0]
    assert "fingerprint" in row
    assert "plaintext" not in row
    miss = client.get("/api/v1/hud/secrets/?q=super-secret-token-do-not-leak")
    assert miss.status_code == 200
    assert miss.json()["results"] == []


def test_last_owner_cannot_be_retired(admin, client):
    r = client.get("/api/v1/hud/members/")
    assert r.status_code == 200
    reasons = [d["reason"] for d in r.json()["disabled_actions"]]
    assert any("last Owner" in x for x in reasons)
    gone = client.delete("/api/v1/hud/members/")
    assert gone.status_code == 409


@pytest.mark.no_default_membership
def test_me_capabilities_follow_hud_flag(operator, client):
    r = client.get("/api/auth/me/")
    assert r.status_code == 200
    assert "hud_ui_v1" not in r.json()["capabilities"]
    assert "admin_read" not in r.json()["capabilities"]
    assert r.json()["hud_ui"] is True
    assert r.json()["role"] == ""
    with override_settings(HUD_UI_V1=False):
        r = client.get("/api/auth/me/")
        assert "hud_ui_v1" not in r.json()["capabilities"]
        assert r.json()["hud_ui"] is False


def test_anonymous_me_shape_unchanged(client):
    r = client.get("/api/auth/me/")
    assert r.status_code == 200
    assert r.json() == {"authenticated": False}


def test_rollback_queues_named_previous_manifest_not_current(admin, client):
    """Failed v4 with succeeded v3 must queue v3's Manifest, not another v4."""
    site = _site()
    v3 = Manifest.objects.create(site=site, version=3, body={"release": "three"})
    v4 = Manifest.objects.create(site=site, version=4, body={"release": "four"})
    Deployment.objects.create(manifest=v3, status=Deployment.Status.SUCCEEDED)
    failed = Deployment.objects.create(manifest=v4, status=Deployment.Status.FAILED)
    r = client.post(
        f"/api/v1/hud/deployments/{failed.pk}/commands/",
        data={"action": "deployment.rollback"},
        content_type="application/json",
    )
    assert r.status_code == 202, r.content
    body = r.json()
    assert body["rollback_target"] == "v3"
    created = Deployment.objects.get(pk=body["operation_id"])
    assert created.manifest_id == v3.pk
    assert created.manifest.version == 3
    assert created.manifest_id != v4.pk
    assert created.manifest.body == {"release": "three"}
    assert created.rollback_of_id == failed.pk
    assert created.status == Deployment.Status.QUEUED


def test_sites_fleet_sort_and_page_round_trip(admin, client):
    _site(name="zeta", project_name="zulu")
    _site(name="alpha", project_name="mike")
    _site(name="mu", project_name="alpha")
    named = client.get("/api/v1/hud/sites/?sort=name&page=1&page_size=2")
    assert named.status_code == 200
    body = named.json()
    assert body["sort"] == "name"
    assert body["page"] == 1
    assert body["count"] == 3
    assert [row["name"] for row in body["results"]] == ["alpha", "mu"]
    assert body["next"] == "2"
    page2 = client.get("/api/v1/hud/sites/?sort=name&page=2&page_size=2")
    assert [row["name"] for row in page2.json()["results"]] == ["zeta"]
    assert page2.json()["next"] is None
    by_project = client.get("/api/v1/hud/sites/?sort=project&page=1&page_size=50")
    assert [row["project"] for row in by_project.json()["results"]] == [
        "alpha", "mike", "zulu",
    ]


def test_rotate_plan_names_affected_objects_without_secret_material(admin, client):
    site = _site()
    secret = vault_put(
        kind=Secret.Kind.API_TOKEN,
        owner_type="site",
        owner_id=str(site.pk),
        plaintext=b"super-secret-token-do-not-leak",
    )
    r = client.get(f"/api/v1/hud/secrets/{secret.pk}/rotate-plan/")
    assert r.status_code == 200
    body = r.json()
    raw = r.content.decode()
    assert "super-secret-token-do-not-leak" not in raw
    assert "ciphertext" not in raw
    assert body["secret_id"] == secret.pk
    names = [item["name"] for item in body["affected"]]
    assert any("prod" in n for n in names)
    ids = {a["id"] for a in body["disabled_actions"]}
    assert "secret.rotate_activate" in ids
    listed = client.get("/api/v1/hud/secrets/")
    row = next(x for x in listed.json()["results"] if x["id"] == secret.pk)
    assert any(a["id"] == "secret.rotate_plan" for a in row["allowed_actions"])


@pytest.mark.no_default_membership
def test_operator_is_forbidden_on_remaining_hud_collections(operator, client):
    for path in (
        "/api/v1/hud/projects/",
        "/api/v1/hud/targets/",
        "/api/v1/hud/findings/",
        "/api/v1/hud/partners/",
        "/api/v1/hud/integrations/",
        "/api/v1/hud/audit/",
        "/api/v1/hud/search/?q=shop",
        "/api/v1/hud/shell/",
    ):
        r = client.get(path)
        assert r.status_code == 403, path


def test_overview_scoped_counts_and_add_application(admin, client):
    _site()
    r = client.get("/api/v1/hud/overview/")
    assert r.status_code == 200
    body = r.json()
    assert "observed_at" in body
    assert "p1" in body["findings"]
    assert "queued" in body["deployments"]
    assert "running" in body["deployments"]
    assert "waiting_for_lock" in body["deployments"]
    assert "healthy" in body["site_health"]
    assert "warming" in body["site_health"]
    assert "unhealthy" in body["site_health"]
    assert "stale" in body["site_health"]
    assert "ready" in body["target_readiness"]
    assert "pressured" in body["target_readiness"]
    assert "unreachable" in body["target_readiness"]
    assert "decommissioned" in body["target_readiness"]
    ids = {a["id"] for a in body["allowed_actions"]}
    assert "project.create" in ids


def test_remaining_collections_include_actions_and_observed_at(admin, client):
    site = _site()
    from core.models import AuditEvent, Partner

    Partner.objects.create(slug="acme", name="Acme")
    Finding.objects.create(
        workspace=default_workspace(),
        source_engine="uptime", severity="p1", entity=f"site:{site.domain}",
        title="Probe failed", body="why", fix_action="restart",
        fingerprint="hud-p1-b",
    )
    AuditEvent.objects.create(
        source=AuditEvent.Source.UI, action="site.deploy",
        object_type="deployment", object_id="11",
        actor=admin,
    )
    for path in (
        "/api/v1/hud/projects/",
        "/api/v1/hud/targets/",
        "/api/v1/hud/findings/",
        "/api/v1/hud/partners/",
        "/api/v1/hud/integrations/",
        "/api/v1/hud/audit/",
        "/api/v1/hud/deployments/",
        "/api/v1/hud/shell/",
    ):
        r = client.get(path)
        assert r.status_code == 200, (path, r.content)
        body = r.json()
        assert "observed_at" in body, path
        assert "allowed_actions" in body or (
            body.get("results") and "allowed_actions" in body["results"][0]
        ), path


def test_sites_row_actions_include_contract_verbs(admin, client):
    site = _site()
    Finding.objects.create(
        workspace=default_workspace(),
        source_engine="uptime", severity="p1", entity=f"site:{site.name}",
        title="Probe failed", body="why", fix_action="restart",
        fingerprint="hud-blockers",
    )
    r = client.get("/api/v1/hud/sites/")
    row = r.json()["results"][0]
    ids = {a["id"] for a in row["allowed_actions"]}
    assert "site.view_details" in ids
    assert "site.open_live" in ids
    assert "site.fix_blockers" in ids
    disabled = {d["id"] for d in row["disabled_actions"]}
    assert "site.delete" in disabled
    assert r.json().get("allowed_actions") is not None


def test_global_search_groups_authorized_objects(admin, client):
    site = _site()
    r = client.get("/api/v1/hud/search/?q=shop")
    assert r.status_code == 200
    body = r.json()
    kinds = {g["kind"] for g in body["groups"]}
    assert "project" in kinds
    assert "site" in kinds
    names = [item["label"] for g in body["groups"] for item in g["results"]]
    assert any("shop" in n.lower() or site.domain in n for n in names)


def test_findings_facet_p1p2_and_export_and_commands(admin, client):
    site = _site()
    Finding.objects.create(
        workspace=default_workspace(),
        source_engine="uptime", severity="p1", entity=f"site:{site.name}",
        title="Probe failed", body="why", fix_action="restart",
        fingerprint="hud-cmd-p1",
    )
    Finding.objects.create(
        workspace=default_workspace(),
        source_engine="uptime", severity="p3", entity=f"site:{site.name}",
        title="noise", body="why", fix_action="n",
        fingerprint="hud-cmd-p3",
    )
    listed = client.get("/api/v1/hud/findings/?facet=p1p2")
    assert listed.status_code == 200
    sevs = {row["severity"] for row in listed.json()["results"]}
    assert "p3" not in sevs
    assert "p1" in sevs
    exported = client.get("/api/v1/hud/sites/?export=csv")
    assert exported.status_code == 200
    assert "csv" in exported.json()
    assert "project,name" in exported.json()["csv"]
    src = client.get("/api/v1/hud/projects/test-source/?git_url=git@example/shop")
    assert src.status_code == 200
    assert src.json().get("ok") is not True
    assert "observed_at" in src.json()


def test_retry_abort_do_not_delete_history(admin, client):
    site = _site()
    from deploys.models import Deployment, Manifest

    manifest = Manifest.objects.create(site=site, version=2, body={})
    failed = Deployment.objects.create(manifest=manifest, status=Deployment.Status.FAILED)
    retry = client.post(
        f"/api/v1/hud/deployments/{failed.pk}/commands/",
        data={"action": "deployment.retry"},
        content_type="application/json",
    )
    assert retry.status_code == 202
    assert Deployment.objects.filter(pk=failed.pk).exists()
    running = Deployment.objects.create(manifest=manifest, status=Deployment.Status.RUNNING)
    abort = client.post(
        f"/api/v1/hud/deployments/{running.pk}/commands/",
        data={"action": "deployment.abort"},
        content_type="application/json",
    )
    assert abort.status_code == 202
    assert Deployment.objects.filter(pk=running.pk).exists()


def _get_operation(client, body):
    op_id = body["operation_id"]
    status_url = body.get("status_url") or f"/api/v1/hud/operations/{op_id}/"
    fetched = client.get(status_url)
    assert fetched.status_code == 200, (status_url, fetched.content)
    assert fetched.json()["operation_id"] == op_id
    return fetched.json()


def test_target_create_persists_a_fetchable_operation(admin, client):
    from core.models import NetworkZone, Target
    from tests.conftest import t1_ready_session

    t1_ready_session(client, admin)
    zone, _ = NetworkZone.objects.get_or_create(name="hud-net", slug="hud-net")
    before = Target.objects.count()
    refused = client.post(
        "/api/v1/hud/targets/commands/",
        data={"action": "target.create"},
        content_type="application/json",
    )
    assert refused.status_code in (400, 409), refused.content
    assert refused.status_code != 202
    r = client.post(
        "/api/v1/hud/targets/commands/",
        data={"action": "target.create", "host": "edge-new.example.test", "zone_id": zone.pk},
        content_type="application/json",
    )
    assert r.status_code == 202, r.content
    body = r.json()
    assert body["operation_id"] != 1 or Target.objects.count() > before
    _get_operation(client, body)
    created = Target.objects.get(host="edge-new.example.test")
    assert created.pk != 1 or before == 0
    assert Target.objects.count() == before + 1


def test_partner_create_persists_or_refuses_honestly(admin, client):
    from core.models import Partner
    from tests.conftest import t1_ready_session

    t1_ready_session(client, admin)
    refused = client.post(
        "/api/v1/hud/partners/commands/",
        data={"action": "partner.create"},
        content_type="application/json",
    )
    assert refused.status_code in (400, 409), refused.content
    assert refused.status_code != 202
    r = client.post(
        "/api/v1/hud/partners/commands/",
        data={"action": "partner.create", "slug": "acme-hud", "name": "Acme HUD"},
        content_type="application/json",
    )
    assert r.status_code == 202, r.content
    body = r.json()
    fetched = _get_operation(client, body)
    partner = Partner.objects.get(slug="acme-hud")
    assert fetched["action"] == "partner.create"
    object_id = str(fetched.get("object_id") or "")
    assert object_id in ("", str(partner.pk)) or fetched["operation_id"] == body["operation_id"]


def test_site_create_persists_or_refuses_honestly(admin, client):
    from core.models import Project, Site

    refused = client.post(
        "/api/v1/hud/sites/commands/",
        data={"action": "site.create"},
        content_type="application/json",
    )
    assert refused.status_code in (400, 409), refused.content
    project, _ = Project.objects.get_or_create(name="shop", slug="shop")
    r = client.post(
        "/api/v1/hud/sites/commands/",
        data={
            "action": "site.create",
            "project_id": project.pk,
            "name": "mesh-hud",
            "exposure": "mesh_only",
        },
        content_type="application/json",
    )
    assert r.status_code == 202, r.content
    body = r.json()
    _get_operation(client, body)
    site = Site.objects.get(name="mesh-hud")
    assert site.project_id == project.pk
    assert body["operation_id"] not in (None, "")
    # Hard-coded 1 with nothing created is the defect; a real first row may be pk=1.
    assert Site.objects.filter(pk=body.get("object_id", site.pk)).exists()


def test_integration_verify_is_durable_or_refused(admin, client):
    from core.models import DnsAccount

    DnsAccount.objects.all().delete()
    refused = client.post(
        "/api/v1/hud/integrations/commands/",
        data={"action": "aws.verify"},
        content_type="application/json",
    )
    assert refused.status_code in (400, 409), refused.content
    assert refused.status_code != 202
    DnsAccount.objects.create(provider="cloudflare", label="cf-live")
    r = client.post(
        "/api/v1/hud/integrations/commands/",
        data={"action": "cloudflare.verify"},
        content_type="application/json",
    )
    assert r.status_code == 202, r.content
    body = r.json()
    assert body["operation_id"] != 1 or client.get(
        body.get("status_url") or f"/api/v1/hud/operations/{body['operation_id']}/"
    ).status_code == 200
    fetched = _get_operation(client, body)
    assert fetched["action"] in ("cloudflare.verify", "integration.verify")


def test_sites_and_deployments_do_not_invent_tls_or_releases(admin, client):
    site = _site()
    from deploys.models import Manifest

    Manifest.objects.create(site=site, version=4, body={"release": "four"})
    fleet = client.get("/api/v1/hud/sites/").json()["results"][0]
    assert fleet["tls"] in ("unknown", "missing", "degraded")
    assert fleet["tls"] != "ok"
    assert fleet["desired_release"] in ("v4", "")
    assert fleet["live_release"] in ("", "unknown")
    assert fleet["live_release"] != fleet["desired_release"] or fleet["live_release"] == ""
    assert fleet["observed_at"]
    from deploys.models import Deployment

    dep = Deployment.objects.create(manifest=site.manifests.get(version=4), status="running")
    detail = client.get(f"/api/v1/hud/deployments/{dep.pk}/").json()
    assert detail["desired_release"] == "v4"
    assert detail["live_release"] != "v3"
    assert detail["live_release"] in ("", "unknown")
    assert detail["observed_at"]


@pytest.mark.no_default_membership
def test_workspace_membership_grants_admin_read_not_global_staff_alone(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import Workspace, WorkspaceMembership

    user = django_user_model.objects.create_user(username="auditor", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    client.force_login(user)
    denied = client.get("/api/v1/hud/overview/")
    assert denied.status_code == 403
    workspace, _ = Workspace.objects.get_or_create(
        slug="default", defaults={"name": "Default workspace"},
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="auditor")
    allowed = client.get("/api/v1/hud/overview/")
    assert allowed.status_code == 200
    me = client.get("/api/auth/me/").json()
    assert "admin_read" in me["capabilities"]
    assert me["role"] in ("auditor", "owner", "admin")
    assert me["workspaces"]


def test_viewer_membership_cannot_mutate_hud_commands(client, django_user_model, admin):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import NetworkZone, Workspace, WorkspaceMembership

    user = django_user_model.objects.create_user(
        username="viewer", password="pw-1234567890", is_staff=True,
    )
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    workspace, _ = Workspace.objects.get_or_create(
        slug="default", defaults={"name": "Default workspace"},
    )
    WorkspaceMembership.objects.create(workspace=workspace, user=user, role="viewer")
    # staff still bootstraps owner caps; a non-staff viewer is the real deny path
    user.is_staff = False
    user.save()
    client.force_login(user)
    zone, _ = NetworkZone.objects.get_or_create(name="hud-net", slug="hud-net")
    r = client.post(
        "/api/v1/hud/targets/commands/",
        data={"action": "target.create", "host": "nope.example.test", "zone_id": zone.pk},
        content_type="application/json",
    )
    assert r.status_code == 403
    caps = client.get("/api/auth/me/").json()["capabilities"]
    assert "admin_read" in caps
    assert "config.write" not in caps


def test_workspace_querysets_and_object_routes_are_isolated(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import AuditEvent, Partner, Workspace, WorkspaceMembership
    from deploys.models import Manifest

    user = django_user_model.objects.create_user(username="multi", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    alpha = Workspace.objects.create(name="Alpha", slug="alpha")
    beta = Workspace.objects.create(name="Beta", slug="beta")
    WorkspaceMembership.objects.create(workspace=alpha, user=user, role="owner")
    WorkspaceMembership.objects.create(workspace=beta, user=user, role="viewer")

    alpha_zone = NetworkZone.objects.create(workspace=alpha, name="Alpha net", slug="alpha-net")
    beta_zone = NetworkZone.objects.create(workspace=beta, name="Beta net", slug="beta-net")
    alpha_target = Target.objects.create(zone=alpha_zone, host="alpha.example.test", status="ready")
    beta_target = Target.objects.create(zone=beta_zone, host="beta.example.test", status="ready")
    alpha_project = Project.objects.create(workspace=alpha, name="Alpha app", slug="alpha-app")
    beta_project = Project.objects.create(workspace=beta, name="Beta app", slug="beta-app")
    alpha_site = Site.objects.create(
        project=alpha_project, name="alpha-site", exposure="mesh_only",
        primary_target=alpha_target,
    )
    beta_site = Site.objects.create(
        project=beta_project, name="beta-site", exposure="mesh_only",
        primary_target=beta_target,
    )
    alpha_deployment = Deployment.objects.create(
        manifest=Manifest.objects.create(site=alpha_site, version=1, body={}),
        status="running",
    )
    beta_deployment = Deployment.objects.create(
        manifest=Manifest.objects.create(site=beta_site, version=1, body={}),
        status="running",
    )
    Finding.objects.create(
        workspace=alpha, source_engine="test", severity="p1", entity="alpha-site",
        title="alpha finding", fingerprint="alpha-finding",
    )
    Finding.objects.create(
        workspace=beta, source_engine="test", severity="p1", entity="beta-site",
        title="beta finding", fingerprint="beta-finding",
    )
    Partner.objects.create(workspace=alpha, name="Alpha partner", slug="alpha-partner")
    Partner.objects.create(workspace=beta, name="Beta partner", slug="beta-partner")
    AuditEvent.objects.create(
        workspace=alpha, source="api", action="alpha.event", object_type="site",
        object_id=str(alpha_site.pk),
    )
    AuditEvent.objects.create(
        workspace=beta, source="api", action="beta.event", object_type="site",
        object_id=str(beta_site.pk),
    )
    client.force_login(user)

    headers = {"HTTP_X_WORKSPACE": "alpha"}
    collections = {
        "/api/v1/hud/projects/": ("results", "name", "Alpha app", "Beta app"),
        "/api/v1/hud/sites/": ("results", "name", "alpha-site", "beta-site"),
        "/api/v1/hud/targets/": ("results", "host", "alpha.example.test", "beta.example.test"),
        "/api/v1/hud/findings/": ("results", "title", "alpha finding", "beta finding"),
        "/api/v1/hud/partners/": ("results", "name", "Alpha partner", "Beta partner"),
        "/api/v1/hud/audit/": ("results", "action", "alpha.event", "beta.event"),
    }
    for path, (result_key, field, visible, hidden) in collections.items():
        response = client.get(path, **headers)
        assert response.status_code == 200, (path, response.content)
        values = {row[field] for row in response.json()[result_key]}
        assert visible in values, path
        assert hidden not in values, path

    deployments = client.get("/api/v1/hud/deployments/", **headers).json()["results"]
    assert {row["id"] for row in deployments} == {alpha_deployment.pk}
    assert client.get(f"/api/v1/hud/sites/{beta_site.pk}/", **headers).status_code == 404
    assert client.get(
        f"/api/v1/hud/deployments/{beta_deployment.pk}/", **headers,
    ).status_code == 404
    search = client.get("/api/v1/hud/search/?q=Beta", **headers).json()
    assert search["groups"] == []


def test_capabilities_do_not_union_across_workspaces(client, django_user_model):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import Workspace, WorkspaceMembership

    user = django_user_model.objects.create_user(username="split-role", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    owner_ws = Workspace.objects.create(name="Owner space", slug="owner-space")
    viewer_ws = Workspace.objects.create(name="Viewer space", slug="viewer-space")
    WorkspaceMembership.objects.create(workspace=owner_ws, user=user, role="owner")
    WorkspaceMembership.objects.create(workspace=viewer_ws, user=user, role="viewer")
    viewer_zone = NetworkZone.objects.create(
        workspace=viewer_ws, name="Viewer net", slug="viewer-net",
    )
    client.force_login(user)

    owner_caps = client.get("/api/auth/me/?workspace=owner-space").json()["capabilities"]
    viewer_caps = client.get("/api/auth/me/?workspace=viewer-space").json()["capabilities"]
    assert "config.write" in owner_caps
    assert "admin_read" in viewer_caps
    assert "config.write" not in viewer_caps

    denied = client.post(
        "/api/v1/hud/targets/commands/?workspace=viewer-space",
        data={"action": "target.create", "host": "blocked.test", "zone_id": viewer_zone.pk},
        content_type="application/json",
    )
    assert denied.status_code == 403
    assert client.get(
        "/api/v1/hud/overview/", HTTP_X_WORKSPACE="not-a-membership",
    ).status_code == 403


def test_site_detail_and_shell_build_are_authoritative(admin, client, settings):
    site = _site()
    settings.HUD_BUILD_ID = "abc123deadbeef"
    detail = client.get(f"/api/v1/hud/sites/{site.pk}/")
    assert detail.status_code == 200
    body = detail.json()
    assert body["id"] == site.pk
    assert "overview" in body["tabs"]
    assert "removal" in body["tabs"]
    assert "observed_at" in body
    shell = client.get("/api/v1/hud/shell/").json()
    assert shell["build_id"] == "abc123deadbeef"


def test_hud_command_idempotency_replays_the_same_operation(admin, client):
    from core.models import NetworkZone, Target
    from tests.conftest import t1_ready_session

    t1_ready_session(client, admin)
    zone, _ = NetworkZone.objects.get_or_create(name="hud-net", slug="hud-net")
    first = client.post(
        "/api/v1/hud/targets/commands/",
        data={
            "action": "target.create",
            "host": "idem.example.test",
            "zone_id": zone.pk,
            "idempotency_key": "create-once",
        },
        content_type="application/json",
    )
    assert first.status_code == 202, first.content
    op = first.json()["operation_id"]
    second = client.post(
        "/api/v1/hud/targets/commands/",
        data={
            "action": "target.create",
            "host": "idem.example.test",
            "zone_id": zone.pk,
            "idempotency_key": "create-once",
        },
        content_type="application/json",
    )
    assert second.status_code == 202, second.content
    assert second.json()["operation_id"] == op
    assert second.json().get("replayed") is True
    assert Target.objects.filter(host="idem.example.test").count() == 1


def test_operations_include_age_and_heartbeat(admin, client):
    from core.models import OperationLock

    OperationLock.objects.create(
        scope=OperationLock.Scope.SITE, object_id="1",
        kind=OperationLock.Kind.DEPLOY, holder="worker-1",
    )
    r = client.get("/api/v1/hud/findings/")
    assert r.status_code == 200
    ops = r.json()["operations"]
    assert ops
    assert "age_s" in ops[0]
    assert "heartbeat_at" in ops[0]
    assert ops[0]["holder"] == "worker-1"


def test_overview_vault_and_source_test_are_not_invented(admin, client):
    from vault.models import Secret

    Secret.objects.all().delete()
    overview = client.get("/api/v1/hud/overview/").json()
    assert overview["integrations"]["vault"] != "connected"
    assert overview["integrations"]["vault"] in ("unknown", "missing", "degraded")
    assert overview["observed_at"]
    shaped = client.get("/api/v1/hud/projects/test-source/?git_url=git@example.com/shop.git")
    assert shaped.status_code == 200
    body = shaped.json()
    assert body["ok"] is not True
    assert body.get("state") in ("unknown", "missing", "degraded")
    assert "observed_at" in body


def _two_workspaces(django_user_model, client):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from core.models import Workspace, WorkspaceMembership

    user = django_user_model.objects.create_user(username="iso", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    alpha = Workspace.objects.create(name="Alpha", slug="alpha-iso")
    beta = Workspace.objects.create(name="Beta", slug="beta-iso")
    WorkspaceMembership.objects.create(workspace=alpha, user=user, role="owner")
    WorkspaceMembership.objects.create(workspace=beta, user=user, role="owner")
    client.force_login(user)
    return user, alpha, beta


def test_slugs_are_unique_per_workspace_not_globally(client, django_user_model):
    _user, alpha, beta = _two_workspaces(django_user_model, client)
    Project.objects.create(workspace=alpha, name="App", slug="app")
    Project.objects.create(workspace=beta, name="App", slug="app")
    assert Project.objects.filter(slug="app").count() == 2


@override_settings(HUB_ALLOW_LOCAL_SOURCES=True, HUB_LOCAL_SOURCE_ROOT="/tmp")
def test_project_create_does_not_bind_a_foreign_workspace_target(client, django_user_model):
    _user, alpha, beta = _two_workspaces(django_user_model, client)
    zone = NetworkZone.objects.create(workspace=beta, name="Beta net", slug="beta-iso-net")
    Target.objects.create(zone=zone, host="beta-only.example.test", status="ready")
    refused = client.post(
        "/api/v1/hud/projects/",
        data={
            "name": "alpha-app",
            "local_path": "/tmp/alpha-app",
            "exposure": "mesh_only",
        },
        content_type="application/json",
        HTTP_X_WORKSPACE="alpha-iso",
    )
    assert refused.status_code == 409, refused.content
    assert b"no enrolled target" in refused.content
    assert not Project.objects.filter(workspace=alpha, slug="alpha-app").exists()


def test_integration_verify_does_not_use_another_workspace_account(client, django_user_model):
    from core.models import DnsAccount

    _user, _alpha, beta = _two_workspaces(django_user_model, client)
    DnsAccount.objects.create(workspace=beta, provider="cloudflare", label="beta-cf")
    refused = client.post(
        "/api/v1/hud/integrations/commands/",
        data={"action": "cloudflare.verify"},
        content_type="application/json",
        HTTP_X_WORKSPACE="alpha-iso",
    )
    assert refused.status_code == 409, refused.content
    assert b"No Cloudflare account" in refused.content


def test_durable_outbox_processes_once_and_records_terminal_state(admin, client):
    from core.hud.operations import process_outbox
    from tests.conftest import t1_ready_session

    t1_ready_session(client, admin)
    zone, _ = NetworkZone.objects.get_or_create(name="worker-net", slug="worker-net")
    accepted = client.post(
        "/api/v1/hud/targets/commands/",
        data={
            "action": "target.create",
            "host": "worker-once.example.test",
            "zone_id": zone.pk,
            "idempotency_key": "worker-once",
        },
        content_type="application/json",
    )
    assert accepted.status_code == 202, accepted.content
    operation = HudOperation.objects.get(pk=accepted.json()["operation_id"])
    outbox = HudCommandOutbox.objects.get(operation=operation)
    assert outbox.payload == {"operation_id": operation.pk}
    assert outbox.state == HudCommandOutbox.State.PENDING

    result = process_outbox(outbox.pk)
    operation.refresh_from_db()
    outbox.refresh_from_db()
    assert result["ok"] is True
    assert operation.state == HudOperation.State.SUCCEEDED
    assert operation.started_at and operation.finished_at and operation.heartbeat_at
    assert outbox.state == HudCommandOutbox.State.SUCCEEDED
    assert outbox.attempts == 1
    assert outbox.completed_at

    assert process_outbox(outbox.pk) == result
    outbox.refresh_from_db()
    assert outbox.attempts == 1


def test_signed_log_download_is_actor_bound_audited_and_not_cached(
    admin, client, django_user_model,
):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    site = _site(name="download")
    manifest = Manifest.objects.create(site=site, version=1, body={})
    deployment = Deployment.objects.create(manifest=manifest, status="failed")
    DeploymentStep.objects.create(
        deployment=deployment,
        seq=1,
        name=DeploymentStep.Name.BUILD,
        status=DeploymentStep.Status.FAILED,
        log_text="build failed safely\n",
    )
    granted = client.post(
        f"/api/v1/hud/deployments/{deployment.pk}/downloads/",
        data={"resource": "log", "step": "build"},
        content_type="application/json",
    )
    assert granted.status_code == 200, granted.content
    download_url = granted.json()["url"]
    assert "build failed safely" not in granted.content.decode()
    assert AuditEvent.objects.filter(
        action="deployment-download-granted", object_id=str(deployment.pk), actor=admin,
    ).exists()

    downloaded = client.get(download_url)
    assert downloaded.status_code == 200
    assert b"".join(downloaded.streaming_content) == b"build failed safely\n"
    assert downloaded["Cache-Control"] == "private, no-store, max-age=0"
    assert downloaded["X-Content-Type-Options"] == "nosniff"
    assert "attachment" in downloaded["Content-Disposition"]
    assert AuditEvent.objects.filter(
        action="deployment-download-completed", object_id=str(deployment.pk), actor=admin,
    ).exists()

    other = django_user_model.objects.create_user(
        username="other-admin", password="pw-1234567890", is_staff=True,
    )
    TOTPDevice.objects.create(user=other, name="phone", confirmed=True)
    client.force_login(other)
    assert client.get(download_url).status_code == 404


@override_settings(HUD_DOWNLOAD_MAX_BYTES=4)
def test_signed_artifact_download_enforces_size_limit(admin, client):
    site = _site(name="large-artifact")
    manifest = Manifest.objects.create(site=site, version=1, body={})
    deployment = Deployment.objects.create(manifest=manifest, status="failed")
    artifact = DeploymentArtifact.objects.create(
        deployment=deployment, kind="diagnostic", content="too-large",
    )
    granted = client.post(
        f"/api/v1/hud/deployments/{deployment.pk}/downloads/",
        data={"resource": "artifact", "artifact_id": artifact.pk},
        content_type="application/json",
    )
    assert granted.status_code == 200, granted.content
    refused = client.get(granted.json()["url"])
    assert refused.status_code == 413
    assert refused.json()["code"] == "download_too_large"
