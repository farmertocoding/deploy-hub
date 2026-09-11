"""T1 scale-in overflow + 24h ephemeral reaper.

Unjoin then terminate via RecordingCloud. Reaper flags, does not terminate.
Attack does not block. Partner refuses. Tests inject FakeDns + RecordingCloud.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import timedelta

import pytest
from django.utils import timezone
from test_attack_playbook import _attack_shaped
from test_aws_enroll import _t1_user, _touch
from test_aws_terminate import RecordingCloud
from test_overflow_enroll import _accepted_overflow
from test_overflow_join import (
    OVERFLOW_IP,
    PRIMARY_IP,
    _ephemeral_ready,
    _plant_ipv4s,
    _running_copy,
)
from test_scale_evaluator import (
    AST_PATHS,
    BANNED_IMPORTS,
    BANNED_REAPER_CALLERS,
    EVALUATOR_REAPER_AST_PATHS,
    NOW,
    _ast_hits,
    _minutes,
    _overflow_after_cheap,
    _plant,
    _ready_site,
)

from core.models import (
    AuditEvent,
    CheckRun,
    DnsRecord,
    Finding,
    SiteInstance,
    Target,
)
from deploys.models import Deployment
from providers.fakes import FakeDnsProvider

pytestmark = pytest.mark.django_db

SCALE_IN_URL = "/api/v1/sites/{pk}/overflow-scale-in/"
INSTANCE_WORD = re.compile(r"\binstance\b")
TITLE = "Forgotten ephemeral overflow (past 24 hours)"
REAPER_FIX = "Scale in overflow to stop billing."
REF_ID = "i-ovf-scale"


@pytest.fixture(autouse=True)
def _reset_pager():
    from monitor.pager import reset_pager

    reset_pager()
    yield
    reset_pager()


def _inject_scale_in(monkeypatch, *, replica=None):
    from deploys.overflow import scale_in_overflow as real

    dns = FakeDnsProvider()
    cloud = RecordingCloud()
    cloud.instances[REF_ID] = {
        "id": REF_ID, "state": "running", "spec": {"tags": {}},
    }

    def patched(site, target, **kwargs):
        kwargs.setdefault("dns", dns)
        kwargs.setdefault("provider", cloud)
        if replica is not None:
            kwargs.setdefault("replica", replica)
        return real(site, target, **kwargs)

    monkeypatch.setattr("deploys.overflow.scale_in_overflow", patched)
    return dns, cloud


def _post_scale_in(client, site, target, *, confirm_name=None):
    body = {
        "target": target.pk,
        "confirm_name": target.host if confirm_name is None else confirm_name,
    }
    return client.post(
        SCALE_IN_URL.format(pk=site.pk),
        data=json.dumps(body),
        content_type="application/json",
    )


def _snapshot():
    return (
        Deployment.objects.count(),
        Finding.objects.count(),
        CheckRun.objects.count(),
    )


def _plant_joined_dns(site, overflow, dns):
    DnsRecord.objects.update_or_create(
        site=site, name=site.domain, rtype="A",
        defaults={"value": f"{PRIMARY_IP},{OVERFLOW_IP}"},
    )
    dns.upsert_record(
        site.dns_zone, site.domain, "A",
        [PRIMARY_IP, OVERFLOW_IP], proxied=True,
    )
    dns.calls.clear()


def _ready_scale(slug):
    site, _row = _accepted_overflow(slug)
    overflow = _ephemeral_ready(site, host=f"{slug}-ovf.lan")
    _plant_ipv4s(site, overflow)
    overflow.provider_ref = REF_ID
    overflow.save(update_fields=["host", "provider_ref"])
    _running_copy(site, overflow)
    return site, overflow


def _birth(target, *, ago_h, now):
    row = AuditEvent.objects.create(
        action="instance.create",
        object_type="Target",
        object_id=str(target.pk),
        source=AuditEvent.Source.SYSTEM,
        severity=AuditEvent.Severity.INFO,
    )
    AuditEvent.objects.filter(pk=row.pk).update(ts=now - timedelta(hours=ago_h))
    return row


@pytest.mark.req("SCALE-OVERFLOW-SCALE-IN")
def test_overflow_scale_in_unjoins_and_terminates(client, monkeypatch):
    """Joined TEST-NET-3 pair → 200; A is primary-only; VM gone on Fake.

    What would make this fail: skipping unjoin, leaving overflow in dns_set,
    retargeting primary, or not calling terminate_instance.
    """
    from core.actions import ACTION_TIERS
    from core.views import OverflowScaleInSerializer, OverflowScaleInView
    from deploys.pipeline import _assemble_desired
    from deploys.testing import PipelineTransport

    dns, cloud = _inject_scale_in(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, overflow = _ready_scale("ovf-sin")
    _plant_joined_dns(site, overflow, dns)
    primary_id = site.primary_target_id
    from test_overflow_deploy import _plant_live_tag
    planted, _tag, _computed = _plant_live_tag(site)
    before_dep = Deployment.objects.count()

    response = _post_scale_in(client, site, overflow)
    assert response.status_code == 200, response.content
    body = response.json()
    assert body == {"target": overflow.pk, "unjoined": "dns"}
    assert Deployment.objects.count() == before_dep

    site.refresh_from_db()
    overflow.refresh_from_db()
    assert site.primary_target_id == primary_id
    assert overflow.status == Target.Status.DECOMMISSIONED
    assert cloud.get_instance(REF_ID) is None
    assert ("terminate_instance", REF_ID) in cloud.calls

    upserts = [c for c in dns.calls if c[0] == "upsert_record"]
    assert upserts
    assert upserts[-1][4] == [PRIMARY_IP]
    rec = DnsRecord.objects.get(site=site, name=site.domain, rtype="A")
    assert rec.value == PRIMARY_IP

    inst = SiteInstance.objects.get(site=site, target=overflow)
    assert inst.desired_state == SiteInstance.DesiredState.ABSENT
    assert inst.observed_state == SiteInstance.ObservedState.ABSENT

    desired = _assemble_desired(
        planted, transport=PipelineTransport(), dns=FakeDnsProvider(),
        sleep=lambda _s: None,
    )
    assert desired["dns_values"] == [PRIMARY_IP]
    dumped = json.loads(desired["dns_set"])
    assert dumped[0]["values"] == [PRIMARY_IP]
    assert "127.0.0.1" not in dumped[0]["values"]
    assert OVERFLOW_IP not in dumped[0]["values"]

    row = Finding.objects.get(fingerprint=f"scale-out-proposal:{site.pk}")
    assert row.state == Finding.State.RESOLVED

    action = next(r for r in ACTION_TIERS if r["id"] == "site.overflow_scale_in")
    assert action == {
        "id": "site.overflow_scale_in",
        "tier": "T1",
        "label": "Scale in overflow",
    }
    assert INSTANCE_WORD.search(action["label"]) is None
    assert set(OverflowScaleInSerializer().get_fields()) == {
        "target", "confirm_name",
    }
    view_src = inspect.getsource(OverflowScaleInView)
    assert "ssh_key_ref" not in view_src
    assert "replica" not in view_src
    assert "token" not in view_src


@pytest.mark.req("SCALE-OVERFLOW-SCALE-IN")
def test_tunnel_mode_home_scale_in_skips_a_still_terminates(client, monkeypatch):
    """Tunnel home: no A upsert; replica called; still terminate."""
    calls = []

    def recording(site, target, transport=None):
        calls.append((site.pk, target.pk))

    dns, cloud = _inject_scale_in(monkeypatch, replica=recording)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-sin-tun")
    overflow = _ephemeral_ready(site, host="ovf-sin-tun-ovf.lan")
    overflow.provider_ref = REF_ID
    overflow.save(update_fields=["provider_ref"])
    _running_copy(site, overflow)
    primary = site.primary_target
    primary.kind = Target.Kind.SSH
    primary.collect_payload = {"tunnel": True}
    primary.save(update_fields=["kind", "collect_payload"])

    response = _post_scale_in(client, site, overflow)
    assert response.status_code == 200, response.content
    assert response.json() == {"target": overflow.pk, "unjoined": "tunnel"}
    assert calls == [(site.pk, overflow.pk)]
    assert not any(c[0] == "upsert_record" for c in dns.calls)
    overflow.refresh_from_db()
    assert overflow.status == Target.Status.DECOMMISSIONED
    assert cloud.get_instance(REF_ID) is None


@pytest.mark.req("SCALE-OVERFLOW-SCALE-IN")
def test_attack_does_not_block_overflow_scale_in(client, monkeypatch):
    """Attack playbook engaged → scale-in still 200."""
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection

    dns, cloud = _inject_scale_in(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, overflow = _ready_scale("ovf-sin-atk")
    _plant_joined_dns(site, overflow, dns)
    _attack_shaped(site)
    run(site, FakeEdgeProtection())

    response = _post_scale_in(client, site, overflow)
    assert response.status_code == 200, response.content
    overflow.refresh_from_db()
    assert overflow.status == Target.Status.DECOMMISSIONED


@pytest.mark.req("SCALE-OVERFLOW-SCALE-IN")
def test_partner_site_refuses_overflow_scale_in(client, monkeypatch):
    """PartnerSite + engaged playbook → 4xx; no terminate."""
    from core.models import Partner, PartnerSite
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection

    dns, cloud = _inject_scale_in(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, overflow = _ready_scale("ovf-sin-part")
    _plant_joined_dns(site, overflow, dns)
    partner = Partner.objects.create(slug="ovf-sin-part-p", name="ovf-sin-part-p")
    PartnerSite.objects.create(
        partner=partner, site=site, tenant_ref="ovf-sin-part-t",
    )
    _attack_shaped(site)
    run(site, FakeEdgeProtection())
    before = _snapshot()

    response = _post_scale_in(client, site, overflow)
    assert 400 <= response.status_code < 500, response.content
    blob = response.content.decode()
    assert INSTANCE_WORD.search(blob) is None
    assert "Approve" not in blob
    assert Deployment.objects.count() == before[0]
    overflow.refresh_from_db()
    assert overflow.status == Target.Status.READY
    assert cloud.get_instance(REF_ID) is not None
    assert not any(c[0] == "terminate_instance" for c in cloud.calls)


@pytest.mark.req("SCALE-OVERFLOW-SCALE-IN")
@pytest.mark.req("SCALE-OVERFLOW-EPHEMERAL-REAPER")
def test_evaluate_site_still_does_not_terminate():
    """evaluate_site does not terminate; AST bans scale-in/reaper/terminate."""
    from core.findings import accept_risk
    from scaling.evaluator import evaluate_site

    site = _ready_site("ovf-eval-sin")
    before = Target.objects.filter(status=Target.Status.DECOMMISSIONED).count()
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    accept_risk(row, "cheap+overflow already accepted")
    evaluate_site(site, now=NOW)
    assert Target.objects.filter(
        status=Target.Status.DECOMMISSIONED,
    ).count() == before
    hits = _ast_hits(AST_PATHS, BANNED_IMPORTS)
    assert hits == [], hits
    assert "scale_in_overflow" in BANNED_IMPORTS
    assert "reap_stale_ephemerals" in BANNED_REAPER_CALLERS
    assert _ast_hits(EVALUATOR_REAPER_AST_PATHS, BANNED_REAPER_CALLERS) == []
    assert "terminate_aws_target" in BANNED_IMPORTS


def test_overflow_scale_in_still_requires_recent_touch(client, monkeypatch):
    """No touch → 403; no terminate."""
    dns, cloud = _inject_scale_in(monkeypatch)
    _t1_user(client)
    site, overflow = _ready_scale("ovf-sin-touch")
    before = _snapshot()

    response = _post_scale_in(client, site, overflow)
    assert response.status_code == 403, response.content
    assert Deployment.objects.count() == before[0]
    overflow.refresh_from_db()
    assert overflow.status == Target.Status.READY
    assert cloud.get_instance(REF_ID) is not None


@pytest.mark.req("SCALE-OVERFLOW-EPHEMERAL-REAPER")
def test_reaper_flags_ephemeral_older_than_24h():
    """25h birth flags; 23h does not. Target stays READY."""
    from monitor.overflow_reaper import reap_stale_ephemerals

    now = timezone.now()
    site, overflow = _ready_scale("ovf-reap-25")
    _birth(overflow, ago_h=25, now=now)
    young = _ephemeral_ready(site, host="ovf-reap-23.lan")
    young.kind = Target.Kind.AWS_EC2
    young.lifecycle = Target.Lifecycle.EPHEMERAL
    young.save()
    _birth(young, ago_h=23, now=now)

    rows = reap_stale_ephemerals(now=now)
    fps = {r.fingerprint for r in rows}
    assert f"ephemeral-overflow-orphan:{overflow.pk}" in fps
    assert f"ephemeral-overflow-orphan:{young.pk}" not in fps
    flagged = Finding.objects.get(
        fingerprint=f"ephemeral-overflow-orphan:{overflow.pk}",
    )
    assert flagged.title == TITLE
    assert flagged.fix_action == REAPER_FIX
    assert "Ack does not stop billing" in flagged.body
    assert INSTANCE_WORD.search(flagged.title) is None
    assert INSTANCE_WORD.search(flagged.fix_action) is None
    overflow.refresh_from_db()
    assert overflow.status == Target.Status.READY


@pytest.mark.req("SCALE-OVERFLOW-EPHEMERAL-REAPER")
def test_reaper_does_not_terminate():
    """25h flag exists; status still READY; not DECOMMISSIONED."""
    from monitor.overflow_reaper import reap_stale_ephemerals

    now = timezone.now()
    site, overflow = _ready_scale("ovf-reap-noterm")
    _birth(overflow, ago_h=25, now=now)
    reap_stale_ephemerals(now=now)
    overflow.refresh_from_db()
    assert overflow.status == Target.Status.READY
    assert Finding.objects.filter(
        fingerprint=f"ephemeral-overflow-orphan:{overflow.pk}",
    ).exists()


@pytest.mark.req("SCALE-OVERFLOW-EPHEMERAL-REAPER")
def test_reaper_skips_missing_birth_audit():
    """No instance.create AuditEvent and no provider_ref → no Finding."""
    from monitor.overflow_reaper import reap_stale_ephemerals

    site, overflow = _ready_scale("ovf-reap-skip")
    overflow.provider_ref = ""
    overflow.save(update_fields=["provider_ref"])
    now = timezone.now()
    reap_stale_ephemerals(now=now)
    assert not Finding.objects.filter(
        fingerprint=f"ephemeral-overflow-orphan:{overflow.pk}",
    ).exists()
    overflow.refresh_from_db()
    assert overflow.status == Target.Status.READY


def test_overflow_scale_in_view_does_not_import_deploys():
    """ARCH-D4: view uses the core port."""
    import pathlib

    repo = pathlib.Path(__file__).resolve().parent.parent
    banned = re.compile(r"^\s*(?:from|import)\s+deploys\b", re.M)
    for rel in ("core/views.py", "core/overflow_deploys.py"):
        src = (repo / rel).read_text(encoding="utf-8")
        assert banned.search(src) is None, rel


@pytest.mark.req("SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT")
def test_beat_entry_runs_reaper_daily_on_queue_probes():
    """ephemeral-overflow-reaper-daily exists, names the wrapper, 86400s,
    rides queue probes, and carries no kwargs.

    What would make this fail: a callable reaper with no scheduler owner
    (D-113's forgotten-billing slip), or conflating this with
    drill-reaper-weekly / evaluate-scale-proposals.
    """
    from django.conf import settings

    from monitor import tasks as monitor_tasks

    entry = settings.CELERY_BEAT_SCHEDULE["ephemeral-overflow-reaper-daily"]
    assert entry["task"] == monitor_tasks.reap_stale_overflow_ephemerals.name
    assert float(entry["schedule"]) == 86400.0
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "control"
    assert "kwargs" not in entry
    beat = settings.CELERY_BEAT_SCHEDULE
    assert entry["task"] != beat["evaluate-scale-proposals"]["task"]
    assert entry["task"] != beat["drill-reaper-weekly"]["task"]


@pytest.mark.req("SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT")
def test_beat_task_flags_and_does_not_terminate():
    """Task with no args flags a 25h leftover; target stays READY; no CheckRun."""
    from core.models import CheckRun, Finding
    from monitor.tasks import reap_stale_overflow_ephemerals

    now = timezone.now()
    site, overflow = _ready_scale("ovf-reap-beat")
    _birth(overflow, ago_h=25, now=now)
    before_cr = CheckRun.objects.count()
    outcome = reap_stale_overflow_ephemerals()
    assert set(outcome) == {"ok", "n"}
    assert outcome["ok"] is True
    assert outcome["n"] >= 1
    assert Finding.objects.filter(
        fingerprint=f"ephemeral-overflow-orphan:{overflow.pk}",
    ).exists()
    overflow.refresh_from_db()
    assert overflow.status == Target.Status.READY
    assert CheckRun.objects.count() == before_cr


@pytest.mark.req("SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT")
def test_evaluate_scale_proposals_does_not_call_reaper():
    """evaluate_scale_proposals / scaling / host_metrics do not name the reaper."""
    import ast

    from test_scale_evaluator import (
        BANNED_REAPER_CALLERS,
        EVALUATOR_REAPER_AST_PATHS,
        REPO,
        _ast_hits,
    )

    hits = _ast_hits(EVALUATOR_REAPER_AST_PATHS, BANNED_REAPER_CALLERS)
    assert hits == [], hits
    tasks_src = (REPO / "monitor" / "tasks.py").read_text(encoding="utf-8")
    task_fn = next(
        node
        for node in ast.parse(tasks_src).body
        if isinstance(node, ast.FunctionDef)
        and node.name == "evaluate_scale_proposals"
    )
    for node in ast.walk(task_fn):
        if isinstance(node, ast.Name) and node.id in {
            "reap_stale_ephemerals", "overflow_reaper",
        }:
            pytest.fail("evaluate_scale_proposals names the reaper")
        if isinstance(node, ast.Attribute) and node.attr in {
            "reap_stale_ephemerals", "overflow_reaper",
        }:
            pytest.fail("evaluate_scale_proposals attributes the reaper")

