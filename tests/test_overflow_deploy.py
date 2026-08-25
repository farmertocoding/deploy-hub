"""T1 same-image overflow deploy (SCALE-OVERFLOW-SAME-IMAGE).

ACCEPTED overflow + ephemeral READY target + prior succeeded image_tag pins
the live tag, skips BUILD and DNS, runs SHIP. OPEN/ACKED/missing/RESOLVED
refuse with the exact FIX. Attack and PartnerSite refuse. Evaluator and
enroll still never create a Deployment. Tests inject PipelineTransport.
"""

from __future__ import annotations

import inspect
import json
import re

import pytest
from django.utils import timezone
from pipeline_fakes import fixture_body
from test_aws_enroll import _t1_user, _touch
from test_overflow_enroll import (
    _accepted_overflow,
    _inject_overflow_enroll,
    _open_overflow,
    _post_overflow,
)
from test_scale_evaluator import (
    AST_PATHS,
    BANNED_IMPORTS,
    NOW,
    _ast_hits,
    _minutes,
    _overflow_after_cheap,
    _plant,
    _ready_site,
)

from core.models import CheckRun, Finding, OperationLock, SiteInstance, Target
from deploys.models import Deployment, DeploymentArtifact, DeploymentStep, Manifest
from deploys.steps import image_tag
from deploys.testing import PipelineTransport
from providers.fakes import FakeDnsProvider

pytestmark = pytest.mark.django_db

OVERFLOW_URL = "/api/v1/sites/{pk}/overflow-deploy/"
FIX = "Ack is not launch. Propose-mode does not launch."
IDLE_REFUSE = "idle registered machine exists; do not rent"
PINNED_TAG = "pinned-live-from-history"
INSTANCE_WORD = re.compile(r"\binstance\b")


@pytest.fixture(autouse=True)
def _reset_pager():
    from monitor.pager import reset_pager

    reset_pager()
    yield
    reset_pager()


def _inject_overflow_deploy(monkeypatch):
    """Wrap real deploy_overflow_copy; PipelineTransport + FakeDns, never live SSH."""
    from deploys.overflow import deploy_overflow_copy as real

    transport = PipelineTransport()
    dns = FakeDnsProvider()

    def patched(site, target, **kwargs):
        kwargs.setdefault("transport", transport)
        kwargs.setdefault("dns", dns)
        return real(site, target, **kwargs)

    monkeypatch.setattr("deploys.overflow.deploy_overflow_copy", patched)
    return transport, dns


def _ephemeral_ready(site, host="ovf-copy.lan"):
    return Target.objects.create(
        zone=site.primary_target.zone,
        host=host,
        ssh_key_ref=f"ssh-{host}",
        kind=Target.Kind.AWS_EC2,
        lifecycle=Target.Lifecycle.EPHEMERAL,
        status=Target.Status.READY,
    )


def _plant_live_tag(site, tag=PINNED_TAG):
    body = fixture_body(site.name)
    computed = image_tag(body["git_sha"], body)
    assert tag != computed
    manifest = Manifest.objects.create(site=site, version=1, body=body)
    deployment = Deployment.objects.create(
        manifest=manifest,
        status=Deployment.Status.SUCCEEDED,
    )
    DeploymentStep.objects.create(
        deployment=deployment,
        seq=1,
        name=DeploymentStep.Name.BUILD,
        status=DeploymentStep.Status.SUCCEEDED,
    )
    DeploymentArtifact.objects.create(
        deployment=deployment, kind="image_tag", content=tag,
    )
    return deployment, tag, computed


def _snapshot():
    return (
        Deployment.objects.count(),
        Finding.objects.count(),
        CheckRun.objects.count(),
    )


def _post_deploy(client, site, target, *, confirm_name=None):
    body = {
        "target": target.pk,
        "confirm_name": target.host if confirm_name is None else confirm_name,
    }
    return client.post(
        OVERFLOW_URL.format(pk=site.pk),
        data=json.dumps(body),
        content_type="application/json",
    )


def _assert_refused(response, before, *, detail=None):
    assert 400 <= response.status_code < 500, response.content
    blob = response.content.decode()
    if detail is not None:
        assert response.json()["detail"] == detail
    assert Deployment.objects.count() == before[0]
    assert Finding.objects.count() == before[1]
    assert CheckRun.objects.count() == before[2]
    assert INSTANCE_WORD.search(blob) is None
    assert "Approve" not in blob
    assert "Launch" not in blob


def _spy_locks(monkeypatch):
    from core import locks as locks_mod

    acquires = []
    real_acquire = locks_mod.acquire

    def spy_acquire(scope, object_id, kind, holder):
        acquires.append((scope, str(object_id), str(kind), str(holder)))
        return real_acquire(scope, object_id, kind, holder)

    monkeypatch.setattr(locks_mod, "acquire", spy_acquire)

    held = {}
    from deploys import pipeline as pipeline_mod

    real_begin = pipeline_mod.begin_deploy

    def wrap_begin(deployment, *, target=None):
        ok = real_begin(deployment, target=target)
        holder = str(deployment.pk)
        rows = list(
            OperationLock.objects.filter(
                kind=OperationLock.Kind.DEPLOY, holder=holder,
            )
        )
        held["holder"] = holder
        held["rows"] = {(row.scope, str(row.object_id)) for row in rows}
        return ok

    monkeypatch.setattr(pipeline_mod, "begin_deploy", wrap_begin)
    return acquires, held


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_overflow_deploy_pins_live_tag_skips_build_and_dns(client, monkeypatch):
    """ACCEPTED overflow, ephemeral READY target, prior succeeded image_tag.

    PipelineTransport; BUILD SKIPPED; DNS SKIPPED; SHIP not skipped.
    deployment SUCCEEDED; primary_target unchanged; SiteInstance exists.
    no docker build in mutating_calls; FakeDns no upsert_record.

    What would make this fail: rebuilding from current git_sha, joining DNS,
    locking primary_target, bumping Manifest, or skipping SHIP with BUILD.
    """
    from core.actions import ACTION_TIERS
    from core.views import OverflowDeploySerializer, OverflowDeployView
    from deploys.tasks import run_deploy

    monkeypatch.setattr(
        run_deploy, "delay",
        lambda *a, **k: pytest.fail("run_deploy.delay must not run"),
    )
    transport, dns = _inject_overflow_deploy(monkeypatch)
    acquires, held = _spy_locks(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-pin")
    primary_id = site.primary_target_id
    _prior, stored, computed = _plant_live_tag(site)
    overflow = _ephemeral_ready(site)
    manifest_count = site.manifests.count()
    manifest_version = site.manifests.order_by("-version").first().version
    before_dep = Deployment.objects.count()

    response = _post_deploy(client, site, overflow)
    assert response.status_code == 201, response.content
    body = response.json()
    assert body == {"deployment": body["deployment"], "target": overflow.pk}
    assert Deployment.objects.count() == before_dep + 1
    deployment = Deployment.objects.get(pk=body["deployment"])
    assert deployment.status == Deployment.Status.SUCCEEDED
    by_name = {step.name: step.status for step in deployment.steps.order_by("seq")}
    assert by_name[DeploymentStep.Name.BUILD] == DeploymentStep.Status.SKIPPED
    assert by_name[DeploymentStep.Name.DNS] == DeploymentStep.Status.SKIPPED
    assert by_name[DeploymentStep.Name.SHIP] != DeploymentStep.Status.SKIPPED
    assert by_name[DeploymentStep.Name.SHIP] == DeploymentStep.Status.SUCCEEDED
    for name in (
        DeploymentStep.Name.MIGRATE,
        DeploymentStep.Name.START_GREEN,
        DeploymentStep.Name.HEALTH_CHECK,
        DeploymentStep.Name.ROUTE_TLS,
        DeploymentStep.Name.SMOKE_TEST,
        DeploymentStep.Name.CUTOVER,
    ):
        assert by_name[name] == DeploymentStep.Status.SUCCEEDED, name

    site.refresh_from_db()
    assert site.primary_target_id == primary_id
    assert site.manifests.count() == manifest_count
    assert deployment.manifest.version == manifest_version

    row = SiteInstance.objects.get(site=site, target=overflow)
    assert row.desired_image_tag == stored
    assert row.desired_state == SiteInstance.DesiredState.RUNNING
    assert row.observed_state == SiteInstance.ObservedState.RUNNING
    assert row.internal_port == 20000

    inspects = [
        argv for kind, argv in transport.calls
        if kind == "probe" and argv[:3] == ["docker", "image", "inspect"]
    ]
    assert inspects
    assert any(stored in argv for argv in inspects)
    assert not any(computed in argv for argv in inspects)
    runs = [
        argv for kind, argv in transport.calls
        if kind == "run" and argv[:2] == ["docker", "run"]
    ]
    assert runs
    assert stored in runs[0]
    assert computed not in runs[0]
    assert not any(
        kind == "run" and list(argv[:2]) == ["docker", "build"]
        for kind, argv in transport.mutating_calls()
    )
    assert not any(call[0] == "upsert_record" for call in dns.calls)

    holder = str(deployment.pk)
    assert ("site", str(site.pk), "deploy", holder) in acquires
    assert ("target", str(overflow.pk), "deploy", holder) in acquires
    assert ("target", str(primary_id), "deploy", holder) not in acquires
    assert ("site", str(site.pk)) in held["rows"]
    assert ("target", str(overflow.pk)) in held["rows"]
    assert ("target", str(primary_id)) not in held["rows"]

    row = next(r for r in ACTION_TIERS if r["id"] == "site.overflow_deploy")
    assert row == {
        "id": "site.overflow_deploy",
        "tier": "T1",
        "label": "Deploy overflow copy",
    }
    assert INSTANCE_WORD.search(row["label"]) is None
    assert set(OverflowDeploySerializer().get_fields()) == {"target", "confirm_name"}
    view_src = inspect.getsource(OverflowDeployView)
    assert "ssh_key_ref" not in view_src
    assert "image_tag" not in view_src
    assert "provider" not in view_src
    from deploys import overflow as overflow_mod

    src = inspect.getsource(overflow_mod)
    assert "run_deploy.delay" not in src
    assert "_default_transport" not in src


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_open_overflow_refuses_deploy_with_ack_is_not_launch(client, monkeypatch):
    """OPEN → 4xx; FIX exact; no Deployment; Finding/CheckRun unchanged.

    What would make this fail: treating OPEN as launch, or a consolation
    Finding / CheckRun / Approve / Launch / instance word on the 4xx blob.
    """
    _inject_overflow_deploy(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, row = _open_overflow("ovf-open-dep")
    assert row.state == Finding.State.OPEN
    _plant_live_tag(site)
    overflow = _ephemeral_ready(site)
    before = _snapshot()

    response = _post_deploy(client, site, overflow)
    _assert_refused(response, before, detail=FIX)


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_acked_overflow_refuses_deploy_with_ack_is_not_launch(client, monkeypatch):
    """ACKED (not ACCEPTED) → 4xx; FIX; count unchanged.

    What would make this fail: Ack launching, or a consolation Finding on refuse.
    """
    from core.findings import ack

    _inject_overflow_deploy(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, row = _open_overflow("ovf-acked-dep")
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    _plant_live_tag(site)
    overflow = _ephemeral_ready(site)
    before = _snapshot()

    response = _post_deploy(client, site, overflow)
    _assert_refused(response, before, detail=FIX)


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_missing_overflow_finding_refuses_deploy(client, monkeypatch):
    """No scale-out-proposal:{pk} row; T1 POST → 4xx; FIX.

    What would make this fail: missing Finding treated as ACCEPTED.
    """
    _inject_overflow_deploy(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site = _ready_site("ovf-miss-dep")
    overflow = _ephemeral_ready(site)
    before = _snapshot()

    response = _post_deploy(client, site, overflow)
    _assert_refused(response, before, detail=FIX)


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_resolved_overflow_refuses_deploy_with_ack_is_not_launch(client, monkeypatch):
    """RESOLVED row → 4xx; FIX; count unchanged.

    What would make this fail: a resolved proposal launching on retry.
    """
    from core.findings import resolve

    _inject_overflow_deploy(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, row = _open_overflow("ovf-res-dep")
    resolve(row)
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    _plant_live_tag(site)
    overflow = _ephemeral_ready(site)
    before = _snapshot()

    response = _post_deploy(client, site, overflow)
    _assert_refused(response, before, detail=FIX)


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_attack_refuses_overflow_deploy(client, monkeypatch):
    """ACCEPTED overflow + attack playbook engaged → 4xx; count unchanged.

    What would make this fail: skipping refuse_if_attack so attack still deploys.
    """
    from test_attack_playbook import _attack_shaped

    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection

    _inject_overflow_deploy(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-atk-dep")
    _plant_live_tag(site)
    overflow = _ephemeral_ready(site)
    _attack_shaped(site)
    run(site, FakeEdgeProtection())
    before = _snapshot()

    response = _post_deploy(client, site, overflow)
    _assert_refused(response, before)


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_partner_site_refuses_overflow_deploy(client, monkeypatch):
    """PartnerSite bound, ACCEPTED overflow planted, playbook quiet → 4xx.

    What would make this fail: only gating on the playbook so partner still deploys.
    """
    from core.models import Partner, PartnerSite

    _inject_overflow_deploy(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-part-dep")
    _plant_live_tag(site)
    overflow = _ephemeral_ready(site)
    partner = Partner.objects.create(slug="ovf-part-dep-p", name="ovf-part-dep-p")
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref="ovf-part-dep-t")
    before = _snapshot()

    response = _post_deploy(client, site, overflow)
    _assert_refused(response, before)


def test_overflow_deploy_still_requires_recent_touch(client, monkeypatch):
    """ACCEPTED overflow, no touch → 403; count unchanged.

    Unmarked: C6 RequireRecentTouch, not SCALE-OVERFLOW-SAME-IMAGE text.
    """
    _inject_overflow_deploy(monkeypatch)
    _t1_user(client)
    site, _row = _accepted_overflow("ovf-touch-dep")
    _plant_live_tag(site)
    overflow = _ephemeral_ready(site)
    before = _snapshot()

    response = _post_deploy(client, site, overflow)
    assert response.status_code == 403, response.content
    assert "touch" in response.json()["detail"].lower()
    assert Deployment.objects.count() == before[0]
    assert Finding.objects.count() == before[1]
    assert CheckRun.objects.count() == before[2]


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_evaluate_site_still_does_not_create_a_deployment():
    """evaluate_site does not +1 Deployment; AST bans deploy_overflow_copy.

    What would make this fail: evaluator calling deploy_overflow_copy, or
    dropping deploy_overflow_copy from the shared BANNED_IMPORTS tuple.
    """
    from core.findings import accept_risk
    from scaling.evaluator import evaluate_site

    site = _ready_site("ovf-eval-dep")
    before = Deployment.objects.count()
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    assert row is not None
    accept_risk(row, "cheap+overflow already accepted")
    evaluate_site(site, now=NOW)
    assert Deployment.objects.count() == before
    hits = _ast_hits(AST_PATHS, BANNED_IMPORTS)
    assert hits == [], hits
    assert "deploy_overflow_copy" in BANNED_IMPORTS


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_enroll_overflow_target_still_does_not_create_a_deployment(
    client, monkeypatch,
):
    """ACCEPTED Fake enroll does not +1 Deployment and does not call deploy.

    Do not re-mark 6.7 enroll tests.
    """
    from provision import overflow as enroll_mod

    called = []
    monkeypatch.setattr(
        "deploys.overflow.deploy_overflow_copy",
        lambda *a, **k: called.append((a, k)),
    )
    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-enroll-nodep")
    before = Deployment.objects.count()

    response = _post_overflow(client, site)
    assert response.status_code == 201, response.content
    assert Deployment.objects.count() == before
    assert called == []
    assert [call for call in provider.calls if call[0] == "create_instance"]
    assert "deploy_overflow_copy" not in inspect.getsource(enroll_mod)


def test_idle_registered_machine_refuses_overflow_deploy(client, monkeypatch):
    """ACCEPTED overflow + second READY permanent ram=10 at now → 4xx; no deploy.

    Unmarked extra: C5 idle-pick hit has no named sketch; still refuse.
    """
    _inject_overflow_deploy(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-idle-dep")
    _plant_live_tag(site)
    overflow = _ephemeral_ready(site)
    other = Target.objects.create(
        zone=site.primary_target.zone,
        host="ovf-idle-dep-box.lan",
        ssh_key_ref="ssh-ovf-idle-dep-box",
        status=Target.Status.READY,
        lifecycle=Target.Lifecycle.PERMANENT,
    )
    _plant(other, [timezone.now()], ram=10.0)
    before = _snapshot()

    response = _post_deploy(client, site, overflow)
    _assert_refused(response, before, detail=IDLE_REFUSE)
