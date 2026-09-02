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


def test_compose_redis_probes_user_is_not_admin():
    """ZT-07: hub_probes must not get Redis +@all (FLUSHALL / CONFIG)."""
    compose = yaml.safe_load((REPO / "docker-compose.yml").read_text())
    tokens = compose["services"]["redis"].get("command") or []
    assert "+@all" not in tokens
    assert "-@all" in tokens
    assert "hub_probes" in tokens


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
