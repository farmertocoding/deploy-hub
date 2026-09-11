"""ZT-01 / ZT-05 / ZT-06: explicit membership, finding authority, system admin.

What would make these fail: restoring implicit non-staff membership, mapping
finding transitions to admin_read, or authorizing global partner/AWS mutations
from a tenant owner role.
"""
import json

import pytest
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory

from core.models import (
    Finding,
    NetworkZone,
    Target,
    Workspace,
    WorkspaceMembership,
    default_workspace,
)
from core.rbac import (
    ROLE_CAPABILITIES,
    has_operator_capability,
    user_capabilities,
    user_role,
    workspace_membership,
)

pytestmark = pytest.mark.django_db


def _otp_user(django_user_model, username, *, staff=False, superuser=False):
    from django_otp.plugins.otp_totp.models import TOTPDevice

    if superuser:
        user = django_user_model.objects.create_superuser(
            username, password="pw-1234567890",
        )
    else:
        user = django_user_model.objects.create_user(
            username, password="pw-1234567890", is_staff=staff,
        )
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    return user


def _membership(workspace, user, role):
    return WorkspaceMembership.objects.create(
        workspace=workspace, user=user, role=role,
    )


def _headers(slug):
    return {"HTTP_X_WORKSPACE": slug}


def _finding(workspace, fingerprint="zt-finding"):
    return Finding.objects.create(
        workspace=workspace,
        source_engine="test",
        severity="p1",
        entity="site:zt.example.test",
        title="ZT finding",
        body="why",
        fix_action="fix",
        fingerprint=fingerprint,
    )


def _target(host="zt-box.example.test"):
    zone = NetworkZone.objects.create(
        name=f"lan-{host}", slug=f"lan-{host.replace('.', '-')}",
    )
    return Target.objects.create(
        zone=zone,
        kind=Target.Kind.SSH,
        host=host,
        ssh_user="deploy",
        ssh_key_ref="vault-t1",
        host_key_fingerprint="SHA256:test",
        lifecycle=Target.Lifecycle.PERMANENT,
        status=Target.Status.READY,
    )


@pytest.mark.no_default_membership
def test_staff_without_membership_is_not_default_owner(django_user_model):
    """ZT-18: is_staff / is_superuser is not a WorkspaceMembership."""
    staff = _otp_user(django_user_model, "staff-no-row", staff=True)
    root = _otp_user(django_user_model, "root-no-row", superuser=True)
    workspace = default_workspace()
    assert workspace_membership(staff, workspace) is None
    assert workspace_membership(root, workspace) is None
    assert user_role(staff, workspace) == ""
    assert user_role(root, workspace) == ""
    assert has_operator_capability(staff, "secrets.manage", workspace) is False
    assert has_operator_capability(root, "config.write", workspace) is False


@pytest.mark.no_default_membership
def test_zero_membership_user_has_no_operator_authority(django_user_model):
    user = _otp_user(django_user_model, "nobody")
    workspace = default_workspace()
    assert workspace_membership(user, workspace) is None
    assert user_capabilities(user, workspace) == []
    assert has_operator_capability(user, "config.write", workspace) is False
    assert has_operator_capability(user, "secrets.manage", workspace) is False
    assert has_operator_capability(user, "lifecycle.destroy", workspace) is False
    assert "secrets.manage" in ROLE_CAPABILITIES["owner"]


@pytest.mark.no_default_membership
def test_zero_membership_is_refused_on_reads_and_mutations(client, django_user_model):
    from tests.conftest import t1_ready_session

    user = _otp_user(django_user_model, "nobody")
    client.force_login(user)
    t1_ready_session(client, user)
    workspace = default_workspace()
    finding = _finding(workspace)
    target = _target()

    assert client.get("/api/v1/projects/").status_code == 403
    assert client.get("/api/v1/findings/").status_code == 403
    create = client.post(
        "/api/v1/projects/",
        data=json.dumps({
            "name": "zt-app",
            "git_url": "https://github.com/example/zt.git",
            "domain": "zt.example.test",
        }),
        content_type="application/json",
    )
    assert create.status_code == 403, create.content
    secret = client.post(
        "/api/v1/hud/secrets/",
        data=json.dumps({"value": "zt-secret-value", "owner_type": "site", "owner_id": "0"}),
        content_type="application/json",
    )
    assert secret.status_code == 403, secret.content
    delete = client.post(
        f"/api/v1/targets/{target.pk}/delete/",
        data=json.dumps({"confirm_name": target.host}),
        content_type="application/json",
    )
    assert delete.status_code == 403, delete.content
    assert Target.objects.filter(pk=target.pk).exists()
    ack = client.post(
        f"/api/v1/findings/{finding.pk}/transition/",
        data=json.dumps({"action": "ack"}),
        content_type="application/json",
    )
    assert ack.status_code == 403, ack.content


@pytest.mark.no_default_membership
def test_membership_in_a_does_not_authorize_b(client, django_user_model):
    user = _otp_user(django_user_model, "split")
    alpha = Workspace.objects.create(name="Alpha", slug="alpha")
    beta = Workspace.objects.create(name="Beta", slug="beta")
    _membership(alpha, user, "owner")
    client.force_login(user)
    finding = _finding(beta, "beta-finding")
    listed = client.get("/api/v1/findings/", **_headers("beta"))
    assert listed.status_code in (403, 404), listed.content
    foreign = client.get(f"/api/v1/findings/{finding.pk}/", **_headers("alpha"))
    assert foreign.status_code == 404, foreign.content
    mutate = client.post(
        f"/api/v1/findings/{finding.pk}/transition/",
        data=json.dumps({"action": "ack"}),
        content_type="application/json",
        **_headers("alpha"),
    )
    assert mutate.status_code in (403, 404), mutate.content
    finding.refresh_from_db()
    assert finding.state == Finding.State.OPEN


@pytest.mark.no_default_membership
def test_explicit_roles_match_role_capabilities(django_user_model):
    user = _otp_user(django_user_model, "roles")
    workspace = default_workspace()
    for role, expected in ROLE_CAPABILITIES.items():
        WorkspaceMembership.objects.filter(user=user, workspace=workspace).delete()
        _membership(workspace, user, role)
        got = set(user_capabilities(user, workspace))
        assert got == set(expected), role
        for cap in expected:
            assert has_operator_capability(user, cap, workspace) is True
        for cap in set().union(*ROLE_CAPABILITIES.values()) - set(expected):
            assert has_operator_capability(user, cap, workspace) is False, (role, cap)


@pytest.mark.no_default_membership
def test_viewer_and_auditor_get_findings_but_cannot_transition(client, django_user_model):
    workspace = default_workspace()
    for role in ("viewer", "auditor"):
        user = _otp_user(django_user_model, f"{role}-zt")
        _membership(workspace, user, role)
        client.force_login(user)
        finding = _finding(workspace, f"{role}-fp")
        listed = client.get("/api/v1/findings/")
        assert listed.status_code == 200, listed.content
        titles = {row["title"] for row in listed.json()["data"]}
        assert finding.title in titles
        detail = client.get(f"/api/v1/findings/{finding.pk}/")
        assert detail.status_code == 200, detail.content
        for action, extra in (
            ("ack", {}),
            ("resolve", {}),
            ("accept_risk", {"reason": "accepted for tests"}),
        ):
            body = {"action": action, **extra}
            r = client.post(
                f"/api/v1/findings/{finding.pk}/transition/",
                data=json.dumps(body),
                content_type="application/json",
            )
            assert r.status_code == 403, (role, action, r.content)
        finding.refresh_from_db()
        assert finding.state == Finding.State.OPEN
        client.logout()


@pytest.mark.no_default_membership
def test_operator_may_ack_and_resolve_but_not_accept_risk(client, django_user_model):
    workspace = default_workspace()
    user = _otp_user(django_user_model, "operator-zt")
    _membership(workspace, user, "operator")
    client.force_login(user)
    finding = _finding(workspace, "op-ack")
    ack = client.post(
        f"/api/v1/findings/{finding.pk}/transition/",
        data=json.dumps({"action": "ack"}),
        content_type="application/json",
    )
    assert ack.status_code == 200, ack.content
    assert ack.json()["data"]["state"] == "acked"

    finding = _finding(workspace, "op-resolve")
    resolve = client.post(
        f"/api/v1/findings/{finding.pk}/transition/",
        data=json.dumps({"action": "resolve"}),
        content_type="application/json",
    )
    assert resolve.status_code == 200, resolve.content
    assert resolve.json()["data"]["state"] == "resolved"

    finding = _finding(workspace, "op-accept")
    accept = client.post(
        f"/api/v1/findings/{finding.pk}/transition/",
        data=json.dumps({"action": "accept_risk", "reason": "business accepted"}),
        content_type="application/json",
    )
    assert accept.status_code == 403, accept.content
    finding.refresh_from_db()
    assert finding.state == Finding.State.OPEN


@pytest.mark.no_default_membership
def test_admin_and_owner_may_accept_risk(client, django_user_model):
    workspace = default_workspace()
    for role in ("admin", "owner"):
        user = _otp_user(django_user_model, f"{role}-zt")
        _membership(workspace, user, role)
        client.force_login(user)
        finding = _finding(workspace, f"{role}-accept")
        accept = client.post(
            f"/api/v1/findings/{finding.pk}/transition/",
            data=json.dumps({"action": "accept_risk", "reason": "owner accepted"}),
            content_type="application/json",
        )
        assert accept.status_code == 200, (role, accept.content)
        assert accept.json()["data"]["state"] == "accepted"
        client.logout()


@pytest.mark.no_default_membership
def test_tenant_owner_cannot_mutate_global_partner_flag_or_aws_binding(
    client, django_user_model, settings,
):
    from core.partner_views import partner_api_enabled, set_partner_api_enabled
    from tests.conftest import t1_ready_session

    settings.AWS_CREDENTIALS_REF = "hub-aws"
    tenant = Workspace.objects.create(name="Tenant", slug="tenant-a")
    user = _otp_user(django_user_model, "tenant-owner")
    _membership(tenant, user, "owner")
    client.force_login(user)
    t1_ready_session(client, user)
    set_partner_api_enabled(False)
    kill = client.post(
        "/api/v1/partner-api/kill-switch/",
        data=json.dumps({"confirm_name": "partner-api", "enabled": True}),
        content_type="application/json",
        **_headers("tenant-a"),
    )
    assert kill.status_code == 403, kill.content
    assert partner_api_enabled() is False

    aws = client.post(
        "/api/v1/aws/connect/",
        data=json.dumps({
            "access_key_id": "t1-aws-access-key-id-not-a-credential",
            "secret_access_key": "t1-aws-secret-access-key-not-a-credential",
        }),
        content_type="application/json",
        **_headers("tenant-a"),
    )
    assert aws.status_code == 403, aws.content

    me = client.get("/api/auth/me/", **_headers("tenant-a")).json()
    assert me.get("is_system_admin") is False
    assert "lifecycle.destroy" in me["capabilities"]
    assert "partner.api_kill_switch" not in me["capabilities"]
    assert "aws.connect" not in me["capabilities"]
    assert "system.admin" not in me["capabilities"]

    listed = client.get("/api/v1/partners/", **_headers("tenant-a"))
    assert listed.status_code == 200, listed.content
    assert "api_enabled" not in listed.json() or listed.json().get("api_enabled") is None
    aws_status = client.get("/api/v1/aws/connect/", **_headers("tenant-a"))
    assert aws_status.status_code == 403, aws_status.content


@pytest.mark.no_default_membership
def test_system_admin_can_mutate_globals_independent_of_workspace(
    client, django_user_model,
):
    from core.partner_views import partner_api_enabled, set_partner_api_enabled
    from tests.conftest import t1_ready_session

    tenant = Workspace.objects.create(name="Tenant", slug="tenant-b")
    admin = _otp_user(django_user_model, "sysadmin", superuser=True)
    client.force_login(admin)
    t1_ready_session(client, admin)
    set_partner_api_enabled(False)
    kill = client.post(
        "/api/v1/partner-api/kill-switch/",
        data=json.dumps({"confirm_name": "partner-api", "enabled": True}),
        content_type="application/json",
        **_headers("tenant-b"),
    )
    assert kill.status_code == 200, kill.content
    assert partner_api_enabled() is True
    me = client.get("/api/auth/me/").json()
    assert me["is_system_admin"] is True
    set_partner_api_enabled(False)
    # Selected workspace must not be required for the system plane.
    again = client.post(
        "/api/v1/partner-api/kill-switch/",
        data=json.dumps({"confirm_name": "partner-api", "enabled": True}),
        content_type="application/json",
    )
    assert again.status_code == 200, again.content
    assert partner_api_enabled() is True
    assert tenant.slug == "tenant-b"


def test_bootstrap_owner_creates_one_persisted_membership_and_refuses_conflict(
    django_user_model,
):
    from io import StringIO

    workspace = default_workspace()
    first = django_user_model.objects.create_user("first-owner", password="pw-1234567890")
    second = django_user_model.objects.create_user("second-owner", password="pw-1234567890")
    out = StringIO()
    call_command("bootstrap_owner", username="first-owner", stdout=out)
    row = WorkspaceMembership.objects.get(workspace=workspace, user=first)
    assert row.role == "owner"
    call_command("bootstrap_owner", username="first-owner", stdout=out)
    assert WorkspaceMembership.objects.filter(workspace=workspace, role="owner").count() == 1
    with pytest.raises(CommandError):
        call_command("bootstrap_owner", username="second-owner")
    assert not WorkspaceMembership.objects.filter(user=second).exists()


def test_authorized_action_lists_hide_global_controls_from_tenant_owner(django_user_model):
    from core.hud.common import authorized_action_lists
    from core.rbac import request_workspace

    workspace = default_workspace()
    owner = _otp_user(django_user_model, "list-owner")
    _membership(workspace, owner, "owner")
    factory = RequestFactory()
    request = factory.get("/api/v1/hud/overview/")
    request.user = owner
    request.workspace = workspace
    request.headers = {}
    request.query_params = {}
    assert request_workspace(request) == workspace
    visible, refused = authorized_action_lists(
        request,
        [
            {"id": "project.create", "label": "ADD APPLICATION"},
            {"id": "partner.api_kill_switch", "label": "Disable partner API"},
            {"id": "aws.connect", "label": "Connect AWS"},
        ],
    )
    ids = {row["id"] for row in visible}
    assert "project.create" in ids
    assert "partner.api_kill_switch" not in ids
    assert "aws.connect" not in ids
    refused_ids = {row["id"] for row in refused}
    assert "partner.api_kill_switch" in refused_ids
    assert "aws.connect" in refused_ids


def test_hud_capabilities_unknown_role_is_empty_and_flag_defaults_on():
    """Unknown roles must not TypeError; HUD_UI_V1 defaults on.

    What would make this fail: ROLE_CAPABILITIES.get(role) without (), or
    getattr(settings, "HUD_UI_V1", False) hiding hud_ui_v1 when unset.
    """
    from django.test import override_settings

    from core.rbac import _hud_capabilities, hud_ui_enabled, is_system_admin

    assert _hud_capabilities("not-a-role") == []
    assert "hud_ui_v1" in _hud_capabilities("owner")
    with override_settings(HUD_UI_V1=False):
        assert "hud_ui_v1" not in _hud_capabilities("owner")
        assert hud_ui_enabled() is False
    assert hud_ui_enabled() is True

    class Anon:
        is_authenticated = False
        is_superuser = True

    class SuperNoAuthFlag:
        is_superuser = True

    assert is_system_admin(None) is False
    assert is_system_admin(Anon()) is False
    assert is_system_admin(SuperNoAuthFlag()) is False


def test_resolve_workspace_refuses_unauthenticated_and_empty_ref_uses_membership(
        django_user_model):
    """or vs and on the auth guard; empty ref must not be treated as a slug.

    What would make this fail: `if not user and not auth`, treating "" as a
    workspace slug, or always returning None instead of the membership workspace.
    """
    from core.rbac import request_workspace, resolve_workspace

    owner = _otp_user(django_user_model, "resolve-owner")
    other = Workspace.objects.create(name="Other", slug="other-ws")
    _membership(other, owner, "owner")
    assert resolve_workspace(None) is None
    assert resolve_workspace(owner, "") == other
    assert resolve_workspace(owner, str(other.pk)) == other
    nobody = _otp_user(django_user_model, "resolve-nobody")
    default_workspace()
    assert WorkspaceMembership.objects.filter(user=nobody).count() == 0
    assert resolve_workspace(nobody) is None
    assert resolve_workspace(nobody, "default") is None
    staff = _otp_user(django_user_model, "resolve-staff", staff=True)
    assert resolve_workspace(staff) is None
    factory = RequestFactory()
    request = factory.get("/api/v1/hud/overview/")
    request.user = owner
    request.headers = {}
    request.query_params = {}
    assert request_workspace(request) == other


def test_require_recent_touch_refuses_unauthenticated_and_stale(django_user_model):
    """RequireRecentTouch is two passkeys + a timestamp inside five minutes.

    What would make this fail: minutes=0, n < 1, or treating missing touch as ok.
    """
    from core.permissions import RequireRecentTouch

    user = _otp_user(django_user_model, "touch-user")
    factory = RequestFactory()
    request = factory.post("/api/v1/targets/1/delete/")
    request.user = user
    request.session = {}
    perm = RequireRecentTouch()
    assert perm.has_permission(request, None) is False
    assert perm.message == "Add a passkey before T1 actions are available."


def test_require_recent_touch_allows_two_passkeys_and_fresh_touch(
        client, django_user_model):
    """The success path: mutants that force user=None always refuse.

    What would make this fail: getattr(request, "user", None) becoming None,
    minutes=0, or n < 3.
    """
    from core.permissions import RequireRecentTouch
    from tests.conftest import t1_ready_session

    user = _otp_user(django_user_model, "touch-ok")
    t1_ready_session(client, user)
    factory = RequestFactory()
    request = factory.post("/api/v1/targets/1/delete/")
    request.user = user
    request.session = client.session
    assert RequireRecentTouch().has_permission(request, None) is True


def test_require_recent_touch_ignores_other_users_and_unconfirmed(
        client, django_user_model):
    """Passkeys are per-user and must be confirmed.

    What would make this fail: filter(confirmed=True) without user=, or
    dropping confirmed=True so unconfirmed keys count.
    """
    from datetime import datetime, timedelta

    from django.utils import timezone
    from django_otp_webauthn.models import WebAuthnCredential

    from core.permissions import RequireRecentTouch
    from tests.conftest import t1_ready_session

    victim = _otp_user(django_user_model, "touch-victim")
    other = _otp_user(django_user_model, "touch-other")
    t1_ready_session(client, other)
    factory = RequestFactory()
    request = factory.post("/api/v1/targets/1/delete/")
    request.user = victim
    request.session = client.session
    perm = RequireRecentTouch()
    assert perm.has_permission(request, None) is False
    assert perm.message == "Add a passkey before T1 actions are available."

    import os
    for name in ("u1", "u2"):
        WebAuthnCredential.objects.create(
            user=victim, name=name, confirmed=False,
            credential_id=os.urandom(16), public_key=os.urandom(32),
            aaguid="00000000-0000-0000-0000-000000000000", transports=["usb"],
        )
    assert perm.has_permission(request, None) is False

    t1_ready_session(client, victim)
    request.session = client.session
    request.session["hardware_touch_at"] = (
        timezone.now() - timedelta(minutes=6)
    ).isoformat()
    request.session.save()
    stale = RequireRecentTouch()
    assert stale.has_permission(request, None) is False
    assert stale.message == "Recent hardware touch required."

    request.session["hardware_touch_at"] = (
        timezone.now() + timedelta(minutes=1)
    ).isoformat()
    request.session.save()
    future = RequireRecentTouch()
    assert future.has_permission(request, None) is False
    assert future.message == "Recent hardware touch required."

    request.session = {
        "hardware_touch_at": datetime.now().replace(tzinfo=None),
    }
    naive = RequireRecentTouch()
    assert naive.has_permission(request, None) is True

    missing = RequireRecentTouch()
    request.session = {}
    assert missing.has_permission(request, None) is False
    assert missing.message == "Recent hardware touch required."
    request.session = {"hardware_touch_at": "not-a-timestamp"}
    invalid = RequireRecentTouch()
    assert invalid.has_permission(request, None) is False
    assert invalid.message == "Recent hardware touch required."

    from unittest.mock import patch
    fixed = timezone.now()
    request.session = {"hardware_touch_at": (fixed - timedelta(minutes=5)).isoformat()}
    with patch("core.permissions.timezone.now", return_value=fixed):
        assert RequireRecentTouch().has_permission(request, None) is True
    request.session = {"hardware_touch_at": fixed.isoformat()}
    with patch("core.permissions.timezone.now", return_value=fixed):
        assert RequireRecentTouch().has_permission(request, None) is True

    request.user = None
    assert RequireRecentTouch().has_permission(request, None) is False


def test_workspace_payload_unique_ids_and_unauthenticated_empty(django_user_model):
    """Staff flags must not invent a default-workspace row.

    What would make this fail: getattr(None, "is_authenticated"), item["XXidXX"],
    skipping membership rows, or restoring staff bootstrap.
    """
    from django.contrib.auth.models import AnonymousUser

    from core.rbac import workspace_payload

    assert workspace_payload(None) == []
    assert workspace_payload(AnonymousUser()) == []
    owner = _otp_user(django_user_model, "payload-owner")
    extra = Workspace.objects.create(name="Extra", slug="extra-ws")
    _membership(extra, owner, "owner")
    payload = workspace_payload(owner)
    ids = [item["id"] for item in payload]
    assert extra.pk in ids
    assert len(ids) == len(set(ids))
    assert all(item["slug"] and item["role"] for item in payload)
    staff = _otp_user(django_user_model, "payload-staff", staff=True)
    staff_ids = [item["id"] for item in workspace_payload(staff)]
    assert default_workspace().pk not in staff_ids
    assert len(staff_ids) == len(set(staff_ids))
    keys = {"id", "slug", "name", "role", "capabilities"}
    for item in payload:
        assert set(item) == keys
        assert item["name"]
        assert item["slug"]
        assert item["role"] in ROLE_CAPABILITIES
        assert "hud_ui_v1" in item["capabilities"]
    staff_payload = workspace_payload(staff)
    assert staff_payload == []
    superuser = _otp_user(django_user_model, "payload-root", superuser=True)
    root_payload = workspace_payload(superuser)
    assert [item["id"] for item in root_payload].count(default_workspace().pk) == 0
    _membership(default_workspace(), staff, "admin")
    again = workspace_payload(staff)
    assert [item["id"] for item in again].count(default_workspace().pk) == 1

    early = Workspace.objects.create(name="Zed", slug="zzz-ws")
    late = Workspace.objects.create(name="Aaa", slug="aaa-ws")
    ordered = _otp_user(django_user_model, "payload-order")
    _membership(early, ordered, "viewer")
    _membership(late, ordered, "owner")
    slugs = [item["slug"] for item in workspace_payload(ordered)]
    assert slugs.index("aaa-ws") < slugs.index("zzz-ws")
    from core.rbac import resolve_workspace
    assert resolve_workspace(ordered).slug == "aaa-ws"


def test_finding_cannot_ack_after_resolve(django_user_model):
    """RESOLVED is terminal for operator transitions.

    What would make this fail: inverting `to_state not in _ALLOWED[row.state]`.
    """
    from core.findings import ack, resolve

    workspace = default_workspace()
    row = _finding(workspace, fingerprint="zt-term")
    resolve(row)
    with pytest.raises(ValueError, match="cannot move"):
        ack(row)


def test_request_workspace_header_id_cache_and_ref_flag(django_user_model):
    """X-Workspace-Id selects; a cached request.workspace is not re-resolved.

    What would make this fail: dropping X-Workspace-Id, inverting
    workspace_ref_requested, or ignoring a pre-set request.workspace.
    """
    from core.rbac import (
        has_operator_capability,
        request_workspace,
        resolve_workspace,
        user_capabilities,
        user_role,
    )

    owner = _otp_user(django_user_model, "hdr-owner")
    first = Workspace.objects.create(name="First", slug="aaa-hdr")
    second = Workspace.objects.create(name="Second", slug="zzz-hdr")
    _membership(first, owner, "viewer")
    _membership(second, owner, "owner")
    factory = RequestFactory()
    request = factory.get("/api/v1/hud/overview/", HTTP_X_WORKSPACE_ID=second.slug)
    request.user = owner
    request.query_params = {}
    assert request_workspace(request) == second
    assert request.workspace_ref_requested is True

    request2 = factory.get("/api/v1/hud/overview/")
    request2.user = owner
    request2.headers = {}
    request2.query_params = {}
    request2.workspace = first
    assert request_workspace(request2) is first

    bare = factory.get("/api/v1/hud/overview/")
    bare.user = owner
    bare.headers = {}
    bare.query_params = {}
    resolved = request_workspace(bare)
    assert resolved == first
    assert bare.workspace_ref_requested is False

    assert user_role(owner, second) == "owner"
    assert user_role(owner, first) == "viewer"
    nobody = _otp_user(django_user_model, "hdr-none")
    assert user_role(nobody) == ""
    assert has_operator_capability(owner, "admin_read") is True
    assert user_capabilities(owner) == user_capabilities(owner, resolved)
    assert user_role(owner) == "viewer"
    staff = _otp_user(django_user_model, "hdr-staff", staff=True)
    assert user_role(staff, default_workspace()) == ""
    from django.contrib.auth.models import AnonymousUser
    assert resolve_workspace(AnonymousUser()) is None
    numeric = Workspace.objects.create(name="Numeric", slug="999001")
    _membership(numeric, owner, "owner")
    assert resolve_workspace(owner, "999001") == numeric
    empty = factory.get("/api/v1/hud/overview/")
    empty.user = owner
    empty.headers = {}
    empty.query_params = {"workspace": ""}
    request_workspace(empty)
    assert empty.workspace_ref_requested is False


def test_require_action_unmapped_is_false_and_message_names_cap(django_user_model):
    """Unmapped action_id fails closed; missing cap names the capability.

    What would make this fail: returning True when ACTION_CAPABILITY misses,
    or wiping self.message.
    """
    from core.permissions import RequireAction, RequireSystemAdmin
    from core.rbac import request_workspace

    owner = _otp_user(django_user_model, "act-owner")
    workspace = default_workspace()
    _membership(workspace, owner, "owner")
    factory = RequestFactory()
    request = factory.post("/api/v1/projects/")
    request.user = owner
    request.headers = {}
    request.query_params = {}
    request.workspace = workspace
    assert request_workspace(request) == workspace

    class Unmapped:
        action_id = "not.a.real.action"

    perm = RequireAction()
    assert perm.has_permission(request, Unmapped()) is False

    class Create:
        action_id = "project.create"

    viewer = _otp_user(django_user_model, "act-viewer")
    _membership(workspace, viewer, "viewer")
    request.user = viewer
    denied = RequireAction()
    assert denied.has_permission(request, Create()) is False
    assert denied.message == "config.write required."

    request.user = owner
    admin = RequireSystemAdmin()
    assert admin.has_permission(request, None) is False
    root = _otp_user(django_user_model, "act-root", superuser=True)
    request.user = root
    assert RequireSystemAdmin().has_permission(request, None) is True
