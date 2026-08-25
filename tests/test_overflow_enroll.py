"""T1 overflow enroll via instance.create overflow_site (SCALE-OVERFLOW-T1-ENROLL).

ACCEPTED overflow + idle miss + quiet refuse_if_attack enrolls ephemeral via
FakeCloudProvider. OPEN/ACKED/missing/RESOLVED refuse with the exact FIX.
Idle pick hit, attack, and PartnerSite refuse. Evaluator still never creates
a Target. Tests inject Fake; do not call live cloud_provider_for.
"""

from __future__ import annotations

import json

import pytest
from django.utils import timezone
from test_aws_enroll import (
    FRESH,
    HOST,
    RecordingCloud,
    _create_body,
    _t1_user,
    _touch,
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

from core.models import CheckRun, Finding, Target
from core.transport import FakeTransport

pytestmark = pytest.mark.django_db

CREATE_URL = "/api/v1/instance/create/"
FIX = "Ack is not launch. Propose-mode does not launch."
SECRET_MARKERS = (
    "collect_payload",
    "ssh_key_ref",
    "private_key",
    "ssh_private_key",
    "AKIA",
    "aws_secret_access_key",
    "aws_access_key_id",
    "AWS_SECRET_ACCESS_KEY",
    "HUB_TEST_AWS_TOKEN",
)


@pytest.fixture(autouse=True)
def _reset_pager():
    from monitor.pager import reset_pager

    reset_pager()
    yield
    reset_pager()


def _inject_overflow_enroll(monkeypatch):
    """Wrap real enroll_overflow_target; Fake provider/transport, never live AWS."""
    from provision.overflow import enroll_overflow_target as real_enroll

    provider = RecordingCloud()
    transport = FakeTransport(responses=FRESH)

    def patched(**kwargs):
        kwargs.setdefault("provider", provider)
        kwargs.setdefault("make_transport", lambda target: transport)
        return real_enroll(**kwargs)

    monkeypatch.setattr("provision.overflow.enroll_overflow_target", patched)
    return provider, transport


def _snapshot():
    return (
        Target.objects.count(),
        Finding.objects.count(),
        CheckRun.objects.count(),
    )


def _post_overflow(client, site, *, host=HOST, confirm_name=None, **extra):
    body = {
        "host": host,
        "confirm_name": host if confirm_name is None else confirm_name,
        "zone": site.primary_target.zone.slug,
        "overflow_site": site.pk,
    }
    body.update(extra)
    return client.post(
        CREATE_URL,
        data=json.dumps(body),
        content_type="application/json",
    )


def _open_overflow(slug):
    site = _ready_site(slug)
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    assert row is not None
    assert row.fingerprint == f"scale-out-proposal:{site.pk}"
    return site, row


def _accepted_overflow(slug):
    from core.findings import accept_risk

    site, row = _open_overflow(slug)
    if row.state != Finding.State.ACCEPTED:
        accept_risk(row, "overflow enroll test")
    row.refresh_from_db()
    assert row.state == Finding.State.ACCEPTED
    return site, row


def _assert_refused(response, provider, before, *, detail=None):
    assert 400 <= response.status_code < 500, response.content
    if detail is not None:
        assert response.json()["detail"] == detail
    assert Target.objects.count() == before[0]
    assert Finding.objects.count() == before[1]
    assert CheckRun.objects.count() == before[2]
    assert [call for call in provider.calls if call[0] == "create_instance"] == []


def _assert_clean_create(spec, site):
    dumped = json.dumps(spec, default=str)
    for marker in SECRET_MARKERS:
        assert marker not in dumped
    tags = spec.get("tags") or {}
    tag_val = tags.get("overflow_site")
    assert tag_val == site.pk or tag_val == str(site.pk)
    assert spec.get("instance_type") == "t3.medium"
    for marker in SECRET_MARKERS:
        assert marker not in tags
        assert marker not in spec


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_accepted_overflow_t1_create_enrolls_ephemeral_via_fake(client, monkeypatch):
    """ACCEPTED overflow, no idle machine, FakeCloudProvider → 201 ephemeral.

    What would make this fail: OPEN also launching, defaulting to t3.micro,
    omitting the overflow_site pk tag, or copying vault/AWS material into spec.
    """
    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-ok")
    before = Target.objects.count()

    response = _post_overflow(client, site)
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["host"] == HOST
    assert body["kind"] == Target.Kind.AWS_EC2
    assert Target.objects.count() == before + 1
    target = Target.objects.get(pk=body["id"])
    assert target.kind == Target.Kind.AWS_EC2
    assert target.lifecycle == Target.Lifecycle.EPHEMERAL
    creates = [call for call in provider.calls if call[0] == "create_instance"]
    assert creates, "create_instance must run on the ACCEPTED overflow path"
    _assert_clean_create(creates[0][1], site)


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_open_overflow_refuses_with_ack_is_not_launch(client, monkeypatch):
    """OPEN overflow + T1 POST overflow_site → 4xx; FIX; no create_instance.

    What would make this fail: treating OPEN as launch, or filing a consolation
    Finding / CheckRun on the gate refuse.
    """
    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, row = _open_overflow("ovf-open")
    assert row.state == Finding.State.OPEN
    before = _snapshot()

    response = _post_overflow(client, site)
    _assert_refused(response, provider, before, detail=FIX)


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_acked_overflow_refuses_with_ack_is_not_launch(client, monkeypatch):
    """ACKED (not ACCEPTED) → 4xx; FIX; count unchanged.

    What would make this fail: Ack launching, or a consolation Finding on refuse.
    """
    from core.findings import ack

    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, row = _open_overflow("ovf-acked")
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    before = _snapshot()

    response = _post_overflow(client, site)
    _assert_refused(response, provider, before, detail=FIX)


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_idle_registered_machine_refuses_overflow_enroll(client, monkeypatch):
    """ACCEPTED overflow + second READY permanent ram=10 at now → 4xx; no rent.

    What would make this fail: renting t3.medium when pick_overflow_home hits.
    """
    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-idle")
    other = Target.objects.create(
        zone=site.primary_target.zone,
        host="ovf-idle-box.lan",
        ssh_key_ref="ssh-ovf-idle-box",
        status=Target.Status.READY,
        lifecycle=Target.Lifecycle.PERMANENT,
    )
    _plant(other, [timezone.now()], ram=10.0)
    before = _snapshot()

    response = _post_overflow(client, site)
    _assert_refused(response, provider, before)


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_attack_refuses_overflow_enroll(client, monkeypatch):
    """ACCEPTED overflow + attack playbook engaged → 4xx; count unchanged.

    What would make this fail: skipping refuse_if_attack so attack still enrolls.
    """
    from test_attack_playbook import _attack_shaped

    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection

    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-atk")
    _attack_shaped(site)
    run(site, FakeEdgeProtection())
    before = _snapshot()

    response = _post_overflow(client, site)
    _assert_refused(response, provider, before)


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_overflow_enroll_still_requires_recent_touch(client, monkeypatch):
    """ACCEPTED overflow, no touch → 403; count unchanged.

    What would make this fail: overflow_site skipping RequireRecentTouch.
    """
    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    site, _row = _accepted_overflow("ovf-touch")
    before = _snapshot()

    response = _post_overflow(client, site)
    assert response.status_code == 403, response.content
    assert "touch" in response.json()["detail"].lower()
    _assert_refused(response, provider, before)


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_overflow_enroll_still_requires_type_the_name(client, monkeypatch):
    """ACCEPTED overflow, touch, confirm_name != host, overflow_site set → 400.

    What would make this fail: overflow_site skipping type-the-name.
    """
    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-name")
    before = _snapshot()

    response = _post_overflow(client, site, confirm_name="wrong-host")
    assert response.status_code == 400, response.content
    _assert_refused(response, provider, before)


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_missing_overflow_finding_refuses(client, monkeypatch):
    """No scale-out-proposal:{pk} row; T1 POST overflow_site → 4xx; FIX.

    What would make this fail: missing Finding treated as ACCEPTED.
    """
    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site = _ready_site("ovf-miss")
    before = _snapshot()

    response = _post_overflow(client, site)
    _assert_refused(response, provider, before, detail=FIX)


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_resolved_overflow_refuses_with_ack_is_not_launch(client, monkeypatch):
    """RESOLVED row → 4xx; FIX; count unchanged; create_instance not called.

    What would make this fail: a resolved proposal launching on retry.
    """
    from core.findings import resolve

    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, row = _open_overflow("ovf-res")
    resolve(row)
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    before = _snapshot()

    response = _post_overflow(client, site)
    _assert_refused(response, provider, before, detail=FIX)


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
def test_partner_site_refuses_overflow_enroll(client, monkeypatch):
    """PartnerSite bound, ACCEPTED overflow planted, playbook quiet → 4xx.

    What would make this fail: only gating on the playbook so partner still rents.
    """
    from core.models import Partner, PartnerSite

    provider, _transport = _inject_overflow_enroll(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-part")
    partner = Partner.objects.create(slug="ovf-part-p", name="ovf-part-p")
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref="ovf-part-t")
    before = _snapshot()

    response = _post_overflow(client, site)
    _assert_refused(response, provider, before)


@pytest.mark.req("SCALE-OVERFLOW-T1-ENROLL")
@pytest.mark.req("SCALE-PROPOSE-NO-PROVISION")
def test_evaluate_site_still_does_not_create_a_target():
    """AST scaling/ + monitor/tasks.py + monitor/host_metrics.py forbids 6.6 list
    AND enroll_overflow_target / provision.overflow.

    evaluate_site on ACCEPTED cheap+overflow does not +1 Target.
    Do not rewrite SCALE-PROPOSE-NO-PROVISION text.
    """
    from core.findings import accept_risk
    from scaling.evaluator import evaluate_site

    site = _ready_site("ovf-eval")
    before = Target.objects.count()
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    assert row is not None
    accept_risk(row, "cheap+overflow already accepted")
    evaluate_site(site, now=NOW)
    assert Target.objects.count() == before
    hits = _ast_hits(AST_PATHS, BANNED_IMPORTS)
    assert hits == [], hits
    assert "enroll_overflow_target" in BANNED_IMPORTS
    assert "overflow" in BANNED_IMPORTS


def test_create_without_overflow_site_unchanged(client, monkeypatch):
    """Existing instance.create without overflow_site still 201 via Fake.

    Unmarked: do not pin SCALE-OVERFLOW-T1-ENROLL on the no-overflow_site path.
    """
    from provision.aws_enroll import enroll_aws_target as real_enroll

    _t1_user(client)
    _touch(client, monkeypatch)
    provider = RecordingCloud()
    transport = FakeTransport(responses=FRESH)

    def patched(**kwargs):
        kwargs.setdefault("provider", provider)
        kwargs.setdefault("make_transport", lambda target: transport)
        return real_enroll(**kwargs)

    monkeypatch.setattr("provision.aws_enroll.enroll_aws_target", patched)
    body, _zone_row = _create_body()
    assert "overflow_site" not in body
    before = Target.objects.count()
    response = client.post(
        CREATE_URL,
        data=json.dumps(body),
        content_type="application/json",
    )
    assert response.status_code == 201, response.content
    assert Target.objects.count() == before + 1
    target = Target.objects.get(pk=response.json()["id"])
    assert target.kind == Target.Kind.AWS_EC2
    creates = [call for call in provider.calls if call[0] == "create_instance"]
    assert creates
    spec = creates[0][1]
    assert spec.get("instance_type") == "t3.micro"
    assert "overflow_site" not in (spec.get("tags") or {})
    del _zone_row
