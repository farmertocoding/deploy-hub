"""Regression tests for 2026-08-31 High zero-trust blockers.

What would make these fail: default-workspace dumping, probes refusing
empty KEK, unsigned deploys, skip-by-default prod audit, or membership-blind
findings/map.graph subscribe.
"""
import importlib
from pathlib import Path

import pytest
import yaml
from django.core.exceptions import ImproperlyConfigured
from django.test import override_settings

from core.models import Finding, Workspace, WorkspaceMembership, default_workspace

pytestmark = pytest.mark.django_db

REPO = Path(__file__).resolve().parent.parent


def test_antinoise_workspace_helper_does_not_invent_default():
    """ZT-13 residual: storm/flap helpers must not silently own the default tenant."""
    from monitor.antinoise import _workspace

    with pytest.raises(TypeError, match="workspace"):
        _workspace()


def test_observe_without_workspace_is_refused():
    """ZT-13: hysteresis must not invent the default tenant.

    What would make this fail: `workspace = workspace or default_workspace()`.
    """
    from monitor.antinoise import observe

    with pytest.raises(TypeError, match="workspace"):
        observe("site-down:zt-block", False)


def test_uptime_files_in_the_site_workspace_not_default():
    """ZT-13: a down site in workspace B must not open a default-workspace row."""
    from uptime_fixtures import make_site

    from monitor.uptime import probe_cycle

    other = Workspace.objects.create(name="Other", slug="zt-uptime-other")
    site = make_site("zt-other-shop")
    site.project.workspace = other
    site.project.save(update_fields=["workspace"])
    site.primary_target.zone.workspace = other
    site.primary_target.zone.save(update_fields=["workspace"])

    class Down:
        def __call__(self, url, *, host=None, timeout=None):
            return 503

    for _ in range(3):
        probe_cycle(http_get=Down())

    fp = f"site-down:{site.name}"
    assert Finding.objects.filter(workspace=other, fingerprint=fp).exists()
    assert not Finding.objects.filter(
        workspace=default_workspace(), fingerprint=fp,
    ).exists()


def test_topology_blast_radius_stays_in_the_target_workspace():
    """ZT-13: r2 files against the target's workspace, not default."""
    from core.models import NetworkZone, Project, Site, SiteInstance, Target
    from monitor.topology import evaluate

    other = Workspace.objects.create(name="Topo", slug="zt-topo-other")
    project = Project.objects.create(
        workspace=other, name="zt-topo", slug="zt-topo",
    )
    zone = NetworkZone.objects.create(
        workspace=other, name="zt-topo-net", slug="zt-topo-net",
    )
    box = Target.objects.create(
        zone=zone, host="zt-shared.example.test", status=Target.Status.READY,
    )
    shop = Site.objects.create(
        project=project, name="zt-shop", primary_target=box, exposure="mesh_only",
    )
    api = Site.objects.create(
        project=project, name="zt-api", primary_target=box, exposure="mesh_only",
    )
    SiteInstance.objects.create(site=shop, target=box, internal_port=20000)
    SiteInstance.objects.create(site=api, target=box, internal_port=20001)

    evaluate()

    fp = f"topology-blast-radius:{box.pk}"
    assert Finding.objects.filter(workspace=other, fingerprint=fp).exists()
    assert not Finding.objects.filter(
        workspace=default_workspace(), fingerprint=fp,
    ).exists()


@override_settings(DEBUG=False, VAULT_KEYFILE="", VAULT_SKIP_STARTUP_CHECK=False)
def test_empty_vault_keyfile_skips_startup_check():
    """ZT-14: probe workers set HUB_VAULT_KEYFILE="" and must still boot."""
    from django.apps import apps

    apps.get_app_config("vault").ready()


def test_ensure_keyfile_skips_when_env_is_explicitly_empty(tmp_path, monkeypatch):
    import vault.ensure_keyfile as ensure_keyfile

    monkeypatch.setenv("HUB_VAULT_KEYFILE", "")
    monkeypatch.chdir(tmp_path)
    assert ensure_keyfile.ensure() is None
    assert not (tmp_path / "etc" / "deploy-hub" / "vault.key").exists()


def test_compose_db_creates_the_probes_role():
    """ZT-14: hub_probes must exist as a real Postgres role, not just an env name."""
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    db = compose["services"]["db"]
    volumes = db.get("volumes") or []
    joined = " ".join(str(item) for item in volumes)
    assert "postgres-init" in joined or "docker-entrypoint-initdb.d" in joined
    init = REPO / "scripts" / "postgres-init" / "01-hub-probes.sh"
    assert init.is_file()
    text = init.read_text()
    assert "hub_probes" in text
    assert "POSTGRES_PASSWORD_PROBES" in text
    assert "REVOKE" in text
    assert "vault_secret" in text
    assert "core_workspacemembership" in text
    assert "GRANT SELECT ON ALL TABLES" in text
    assert "GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES" not in text
    assert "deploys_manifest" in text
    assert "core_project" in text
    assert "undefined_table" not in text
    assert "to_regclass" in text


def test_unsigned_run_deploy_is_refused():
    """ZT-15: Celery must not execute a deploy from a bare integer id."""
    from deploys.tasks import run_deploy

    assert run_deploy(1) == {"ok": False, "reason": "envelope"}


def test_hud_envelope_does_not_authorize_a_different_resource():
    """ZT-15: consume binds task + resource_id, not only workspace."""
    from core.models import Project
    from core.task_envelope import EnvelopeError, reauthorize, wrap

    workspace = Workspace.objects.create(name="Env", slug="zt-env-ws")
    a = Project.objects.create(workspace=workspace, name="a", slug="zt-env-a")
    b = Project.objects.create(workspace=workspace, name="b", slug="zt-env-b")
    envelope = wrap(
        task="scan",
        workspace_id=workspace.pk,
        resource_type="project",
        resource_id=a.pk,
    )
    with pytest.raises(EnvelopeError, match="resource"):
        reauthorize(envelope, resource=b, task="scan", resource_id=str(b.pk))


def test_prod_refuses_to_boot_without_an_audit_bucket(monkeypatch):
    """ZT-16: prod skip-by-default is not fail-closed."""
    monkeypatch.setenv("HUB_SECRET_KEY", "x" * 50)
    monkeypatch.setenv("HUB_VAULT_KEK_BACKEND", "local")
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://hub.example.test")
    monkeypatch.setenv("HUB_TASK_ENVELOPE_SECRET", "e" * 50)
    monkeypatch.delenv("HUB_AUDIT_S3_BUCKET", raising=False)
    monkeypatch.delenv("HUB_REQUIRE_AUDIT_SHIP", raising=False)
    from hub.settings import base as base_settings

    importlib.reload(base_settings)
    with pytest.raises(ImproperlyConfigured, match="AUDIT"):
        importlib.reload(importlib.import_module("hub.settings.prod"))


def test_s3_put_sends_object_lock_headers(monkeypatch):
    """ZT-16: Object Lock must be on the PutObject call, not a local boolean."""
    captured = {}

    class FakeClient:
        def get_object_lock_configuration(self, **kwargs):
            return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Enabled"}}

        def get_bucket_versioning(self, **kwargs):
            return {"Status": "Enabled"}

        def put_object(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setattr(
        "providers.aws_creds.boto3_client", lambda *a, **k: FakeClient(),
    )
    from providers.audit_store import S3AuditStore

    store = S3AuditStore(
        bucket="hub-audit",
        access_key_id="AKIATEST",
        secret_access_key="secret",
        object_lock=True,
        versioning=True,
    )
    store.put("audit/1.json", b"{}")
    assert captured["ObjectLockMode"] in {"GOVERNANCE", "COMPLIANCE"}
    assert "ObjectLockRetainUntilDate" in captured


def test_findings_topic_requires_workspace_membership(django_user_model):
    """ZT-17: a 2FA user with no membership cannot subscribe to findings."""
    from django_otp.plugins.otp_totp.models import TOTPDevice

    from realtime.authorize import authorize_topic

    user = django_user_model.objects.create_user("zt-ws-none", password="pw-1234567890")
    TOTPDevice.objects.create(user=user, name="phone", confirmed=True)
    assert authorize_topic(user, "findings") is False
    assert authorize_topic(user, "map.graph") is False

    other = Workspace.objects.create(name="ZT", slug="zt-ws-member")
    WorkspaceMembership.objects.create(workspace=other, user=user, role="viewer")
    assert authorize_topic(user, "findings") is True
    assert authorize_topic(user, "map.graph") is True


def test_findings_event_without_workspace_id_is_dropped():
    """ZT-17: missing workspace_id must fail closed, not fan out."""
    import inspect

    from realtime.consumers import EventsConsumer

    src = inspect.getsource(EventsConsumer.topic_event)
    assert "if not ws_id or not" in src


@override_settings(HUB_ALLOW_LOCAL_SOURCES=True, HUB_LOCAL_SOURCE_ROOT="")
def test_local_path_requires_configured_root():
    """Containment: enabling local sources without a root must not open the host."""
    from core.local_sources import LocalSourceError, refuse_api_local_path

    with pytest.raises(LocalSourceError, match="HUB_LOCAL_SOURCE_ROOT"):
        refuse_api_local_path("/var/lib/deploy-hub/sources/app")


def test_overflow_orphan_stays_in_the_target_workspace():
    """ZT-13: ephemeral leftovers must not dump into default."""
    from core.models import NetworkZone, Target
    from monitor.overflow_reaper import reap_stale_ephemerals

    other = Workspace.objects.create(name="B", slug="zt-overflow-other")
    zone = NetworkZone.objects.create(workspace=other, name="z", slug="zt-ov-z")
    target = Target.objects.create(
        zone=zone, host="b.example.test", kind=Target.Kind.AWS_EC2,
        lifecycle=Target.Lifecycle.EPHEMERAL, status=Target.Status.READY,
        provider_ref="i-b",
    )
    reap_stale_ephemerals()
    fp = f"ephemeral-overflow-orphan:{target.pk}"
    assert Finding.objects.filter(workspace=other, fingerprint=fp).exists()
    assert not Finding.objects.filter(
        workspace=default_workspace(), fingerprint=fp,
    ).exists()


def test_digest_does_not_email_another_workspace():
    """ZT-13: a P3 in workspace B must not appear in workspace A's digest mail."""
    from django.core import mail

    from core.findings import finding
    from core.models import Finding as FindingModel
    from monitor.digest import build_digest

    alpha = Workspace.objects.create(name="A", slug="a-dig")
    beta = Workspace.objects.create(name="B", slug="b-dig")
    finding(
        "t", "p3-a", workspace=alpha, severity=FindingModel.Severity.P3,
        entity="site:a", title="Alpha only", body="why it matters", fix_action="fix",
    )
    finding(
        "t", "p3-b", workspace=beta, severity=FindingModel.Severity.P3,
        entity="site:b", title="Beta secret", body="why it matters", fix_action="fix",
    )
    mail.outbox.clear()
    build_digest("2026-09-02", workspace=alpha)
    body = mail.outbox[-1].body
    assert "Alpha only" in body
    assert "Beta secret" not in body


def test_unsigned_provision_host_is_refused():
    """ZT-15: Celery must not SSH-provision from a bare integer id."""
    from provision.tasks import provision_host

    assert provision_host(1) == {"ok": False, "reason": "envelope"}


def _redis_user_acl():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    tokens = compose["services"]["redis"].get("command") or []
    idx = tokens.index("--user")
    return str(tokens[idx + 1])


def test_compose_redis_probes_user_is_not_admin():
    """ZT-07: hub_probes ACL is one Redis --user string, not +@all on every key."""
    acl = _redis_user_acl()
    parts = acl.split()
    assert parts[0] == "hub_probes"
    assert "-@all" in parts
    assert "+@all" not in parts
    globs = [part for part in parts if part.startswith("~")]
    assert globs, acl
    assert "~*" not in globs
    assert any(part.startswith("~probes") for part in globs)
    assert all("deploys" not in glob and "control" not in glob for glob in globs)
    assert all("task-envelope-nonce" not in glob for glob in globs)


def test_probes_worker_cannot_sign_deploy_envelopes():
    """Probe isolation: worker-probes must not inherit HUB_TASK_ENVELOPE_SECRET."""
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    env = compose["services"]["worker-probes"]["environment"]
    secret = str(env.get("HUB_TASK_ENVELOPE_SECRET") or "")
    assert secret
    assert "HUB_TASK_ENVELOPE_SECRET" in str(
        compose["services"]["worker-deploys"].get("environment") or "",
    )
    hub_env = compose["services"]["web"]["environment"]
    assert secret != str(hub_env.get("HUB_TASK_ENVELOPE_SECRET") or "")


def test_unsigned_rotate_and_backup_are_refused():
    """ZT-15 residual: Beat mutators must not run from a bare broker publish."""
    from provision.tasks import rotate_ssh_keys, run_backup_nightly

    assert rotate_ssh_keys() == {"ok": False, "reason": "envelope"}
    assert run_backup_nightly() == {"ok": False, "reason": "envelope"}


def test_unsigned_collect_tick_and_poll_git_are_refused():
    """ZT-15 residual: collect/reconcile/poll must not run from a bare publish."""
    from deploys.tasks import poll_git
    from monitor.tasks import collect_all
    from reconcile.tasks import tick_all

    assert collect_all() == {"ok": False, "reason": "envelope"}
    assert tick_all() == {"ok": False, "reason": "envelope"}
    assert poll_git() == {"ok": False, "reason": "envelope"}


def test_prod_refuses_fake_pager(monkeypatch):
    monkeypatch.setenv("HUB_SECRET_KEY", "x" * 50)
    monkeypatch.setenv("HUB_VAULT_KEK_BACKEND", "local")
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://hub.example.test")
    monkeypatch.setenv("HUB_TASK_ENVELOPE_SECRET", "e" * 50)
    monkeypatch.setenv("HUB_AUDIT_S3_BUCKET", "hub-audit-test")
    monkeypatch.delenv("HUB_PAGER_BACKEND", raising=False)
    monkeypatch.delenv("HUB_REQUIRE_LIVE_PAGER", raising=False)
    from hub.settings import base as base_settings

    importlib.reload(base_settings)
    with pytest.raises(ImproperlyConfigured, match="PAGER"):
        importlib.reload(importlib.import_module("hub.settings.prod"))


def test_prod_refuses_missing_public_url(monkeypatch):
    monkeypatch.setenv("HUB_SECRET_KEY", "x" * 50)
    monkeypatch.setenv("HUB_VAULT_KEK_BACKEND", "local")
    monkeypatch.setenv("HUB_TASK_ENVELOPE_SECRET", "e" * 50)
    monkeypatch.setenv("HUB_AUDIT_S3_BUCKET", "hub-audit-test")
    monkeypatch.setenv("HUB_PAGER_BACKEND", "ntfy")
    monkeypatch.delenv("HUB_PUBLIC_URL", raising=False)
    from hub.settings import base as base_settings

    importlib.reload(base_settings)
    with pytest.raises(ImproperlyConfigured, match="HUB_PUBLIC_URL"):
        importlib.reload(importlib.import_module("hub.settings.prod"))


def test_prod_refuses_empty_vault_keyfile(monkeypatch):
    monkeypatch.setenv("HUB_SECRET_KEY", "x" * 50)
    monkeypatch.setenv("HUB_VAULT_KEK_BACKEND", "local")
    monkeypatch.setenv("HUB_PUBLIC_URL", "https://hub.example.test")
    monkeypatch.setenv("HUB_TASK_ENVELOPE_SECRET", "e" * 50)
    monkeypatch.setenv("HUB_AUDIT_S3_BUCKET", "hub-audit-test")
    monkeypatch.setenv("HUB_PAGER_BACKEND", "ntfy")
    monkeypatch.setenv("HUB_VAULT_KEYFILE", "")
    monkeypatch.delenv("HUB_ALLOW_EMPTY_VAULT_KEYFILE", raising=False)
    from hub.settings import base as base_settings

    importlib.reload(base_settings)
    with pytest.raises(ImproperlyConfigured, match="VAULT_KEYFILE"):
        importlib.reload(importlib.import_module("hub.settings.prod"))


def test_compose_redis_default_user_is_not_admin():
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    tokens = compose["services"]["redis"].get("command") or []
    users = []
    for i, tok in enumerate(tokens):
        if tok == "--user" and i + 1 < len(tokens):
            users.append(str(tokens[i + 1]))
    default = next(acl for acl in users if acl.startswith("default "))
    assert "-@admin" in default.split() or "-flushall" in default.split()
    assert "-flushall" in default.split()
    assert "-config" in default.split()


def test_s3_put_requires_live_object_lock_configuration(monkeypatch):
    class Unlocked:
        def get_object_lock_configuration(self, **kwargs):
            return {"ObjectLockConfiguration": {"ObjectLockEnabled": "Disabled"}}

        def get_bucket_versioning(self, **kwargs):
            return {"Status": "Enabled"}

        def put_object(self, **kwargs):
            raise AssertionError("put must not run without lock")

    monkeypatch.setattr(
        "providers.aws_creds.boto3_client", lambda *a, **k: Unlocked(),
    )
    from core.audit_ship import AuditShipError
    from providers.audit_store import S3AuditStore

    store = S3AuditStore(
        bucket="hub-audit",
        access_key_id="AKIATEST",
        secret_access_key="secret",
        object_lock=True,
        versioning=True,
    )
    with pytest.raises(AuditShipError, match="object lock"):
        store.put("audit/1.json", b"{}")


def test_docker_run_extra_refuses_privileged():
    from deploys.steps import _sanitize_docker_run_extra

    assert _sanitize_docker_run_extra(["-p", "127.0.0.1:20000:80"]) == [
        "-p", "127.0.0.1:20000:80",
    ]
    with pytest.raises(ValueError, match="refused"):
        _sanitize_docker_run_extra(["--privileged"])
    with pytest.raises(ValueError, match="refused"):
        _sanitize_docker_run_extra(["-v", "/:/host"])


def test_hub_root_refuses_path_ssh_user():
    from core.hubfs import hub_root

    assert hub_root("deploy") == "/home/deploy/.hub"
    with pytest.raises(ValueError, match="ssh_user"):
        hub_root("../etc")
    with pytest.raises(ValueError, match="ssh_user"):
        hub_root("root/../../tmp")


def test_django_check_is_clean():
    import subprocess
    import sys

    result = subprocess.run(
        [sys.executable, str(REPO / "manage.py"), "check", "--settings=hub.settings.dev"],
        cwd=REPO,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_otp_admin_site_wraps_django_admin():
    from django.contrib import admin
    from django_otp.admin import OTPAdminSite

    assert admin.site.__class__ is OTPAdminSite or issubclass(
        admin.site.__class__, OTPAdminSite,
    )


def test_public_dns_prefers_joinable_target_host():
    """First public deploy must use the primary target's public IPv4, not loopback."""
    from dns_fixtures import default_dns_zone

    from core.models import NetworkZone, Project, Site, Target
    from deploys.pipeline import _origin_ipv4

    other = Workspace.objects.create(name="DNS", slug="zt-dns-origin")
    project = Project.objects.create(workspace=other, name="shop", slug="zt-dns-shop")
    zone = NetworkZone.objects.create(workspace=other, name="z", slug="zt-dns-z")
    target = Target.objects.create(
        zone=zone, host="203.0.113.50", status=Target.Status.READY,
    )
    site = Site.objects.create(
        project=project, name="shop", primary_target=target, exposure="public",
        dns_zone=default_dns_zone(),
    )
    assert _origin_ipv4(site) == "203.0.113.50"


def test_create_project_requires_workspace():
    with pytest.raises(TypeError, match="workspace"):
        from wizard.create import create_project

        create_project({
            "name": "x", "exposure": "mesh_only",
            "git_url": "", "git_ref": "", "local_path": "",
        })
