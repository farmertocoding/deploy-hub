"""T1 join overflow traffic (SCALE-OVERFLOW-JOIN-TRAFFIC).

ACCEPTED overflow + RUNNING SiteInstance + joinable IPv4 origins upserts
the overflow A next to the primary. Tunnel-mode home uses an injected
replica instead of an A record. OPEN/ACKED refuse with the exact FIX.
Evaluator still never joins. Tests inject FakeDnsProvider.
"""

from __future__ import annotations

import inspect
import json
import re

import pytest
from django.utils import timezone
from test_aws_enroll import _t1_user, _touch
from test_overflow_deploy import (
    PINNED_TAG,
    _ephemeral_ready,
    _plant_live_tag,
    _snapshot,
)
from test_overflow_enroll import _accepted_overflow, _open_overflow
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

from core.models import CheckRun, DnsRecord, Finding, Site, SiteInstance, Target
from deploys.models import Deployment
from providers.fakes import FakeDnsProvider

pytestmark = pytest.mark.django_db

JOIN_URL = "/api/v1/sites/{pk}/overflow-join/"
FIX = "Ack is not launch. Propose-mode does not launch."
TUNNEL_UNCONFIGURED = "tunnel replica is not configured"
PRIMARY_IP = "203.0.113.10"
OVERFLOW_IP = "203.0.113.20"
INSTANCE_WORD = re.compile(r"\binstance\b")


@pytest.fixture(autouse=True)
def _reset_pager():
    from monitor.pager import reset_pager

    reset_pager()
    yield
    reset_pager()


def _inject_overflow_join(monkeypatch, *, replica=None):
    """Wrap real join_overflow_traffic; FakeDns, never live Cloudflare."""
    from deploys.overflow import join_overflow_traffic as real

    dns = FakeDnsProvider()

    def patched(site, target, **kwargs):
        kwargs.setdefault("dns", dns)
        if replica is not None:
            kwargs.setdefault("replica", replica)
        return real(site, target, **kwargs)

    monkeypatch.setattr("deploys.overflow.join_overflow_traffic", patched)
    return dns


def _running_copy(site, target):
    return SiteInstance.objects.create(
        site=site,
        target=target,
        desired_image_tag=PINNED_TAG,
        desired_state=SiteInstance.DesiredState.RUNNING,
        observed_state=SiteInstance.ObservedState.RUNNING,
        internal_port=20000,
    )


def _plant_ipv4s(site, overflow, *, primary=PRIMARY_IP, extra=OVERFLOW_IP):
    row = site.primary_target
    row.host = primary
    row.save(update_fields=["host"])
    overflow.host = extra
    overflow.save(update_fields=["host"])


def _post_join(client, site, target, *, confirm_name=None):
    body = {
        "target": target.pk,
        "confirm_name": target.host if confirm_name is None else confirm_name,
    }
    return client.post(
        JOIN_URL.format(pk=site.pk),
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


def _ready_join(slug):
    site, _row = _accepted_overflow(slug)
    overflow = _ephemeral_ready(site, host=f"{slug}-ovf.lan")
    _plant_ipv4s(site, overflow)
    _running_copy(site, overflow)
    return site, overflow


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_overflow_join_upserts_a_next_to_primary(client, monkeypatch):
    """ACCEPTED, RUNNING SiteInstance, TEST-NET-3 IPv4s → 201 joined=dns.

    FakeDns upsert values are both IPv4s, proxied=True; primary_target
    unchanged; no new Deployment; DnsRecord comma-joined; assembled
    dns_values AND dns_set keep both.

    What would make this fail: replacing the primary A, skipping upsert,
    retargeting primary, creating a Deployment, or baking a single-A dns_set.
    """
    from core.actions import ACTION_TIERS
    from core.views import OverflowJoinSerializer, OverflowJoinView
    from deploys.pipeline import _assemble_desired
    from deploys.testing import PipelineTransport

    dns = _inject_overflow_join(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, overflow = _ready_join("ovf-join-dns")
    primary_id = site.primary_target_id
    before_dep = Deployment.objects.count()

    response = _post_join(client, site, overflow)
    assert response.status_code == 201, response.content
    body = response.json()
    assert body["joined"] == "dns"
    assert body["target"] == overflow.pk
    assert body["name"] == site.domain
    assert body["values"] == [PRIMARY_IP, OVERFLOW_IP]
    assert Deployment.objects.count() == before_dep

    site.refresh_from_db()
    assert site.primary_target_id == primary_id

    upserts = [c for c in dns.calls if c[0] == "upsert_record"]
    assert upserts, dns.calls
    hit = upserts[-1]
    assert hit[2] == site.domain
    assert hit[3] == "A"
    assert hit[4] == [PRIMARY_IP, OVERFLOW_IP]
    assert hit[5] is True

    rec = DnsRecord.objects.get(site=site, name=site.domain, rtype="A")
    assert rec.value == f"{PRIMARY_IP},{OVERFLOW_IP}"

    planted, _tag, _computed = _plant_live_tag(site)
    desired = _assemble_desired(
        planted, transport=PipelineTransport(), dns=FakeDnsProvider(),
        sleep=lambda _s: None,
    )
    assert desired["dns_values"] == [PRIMARY_IP, OVERFLOW_IP]
    assert desired["dns_proxied"] is True
    dumped = json.loads(desired["dns_set"])
    assert dumped[0]["values"] == [PRIMARY_IP, OVERFLOW_IP]
    assert dumped[0]["proxied"] is True

    row = next(r for r in ACTION_TIERS if r["id"] == "site.overflow_join")
    assert row == {
        "id": "site.overflow_join",
        "tier": "T1",
        "label": "Join overflow traffic",
    }
    assert INSTANCE_WORD.search(row["label"]) is None
    assert set(OverflowJoinSerializer().get_fields()) == {"target", "confirm_name"}
    view_src = inspect.getsource(OverflowJoinView)
    assert "ssh_key_ref" not in view_src
    assert "image_tag" not in view_src
    assert "provider" not in view_src
    assert "replica" not in view_src
    assert "token" not in view_src
    from deploys import overflow as overflow_mod

    src = inspect.getsource(overflow_mod)
    assert "run_deploy.delay" not in src
    assert "vault.service.get" not in src
    assert "providers.cloudflare" not in src


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_tunnel_mode_home_joins_via_replica_not_a(client, monkeypatch):
    """kind=ssh + collect_payload.tunnel True → 201 joined=tunnel; no A.

    What would make this fail: upserting an origin A for a tunnel home, or
    skipping the replica seam.
    """
    calls = []

    def recording(site, target, transport=None):
        calls.append((site.pk, target.pk, transport))

    dns = _inject_overflow_join(monkeypatch, replica=recording)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-join-tun")
    overflow = _ephemeral_ready(site, host="ovf-join-tun-ovf.lan")
    _running_copy(site, overflow)
    primary = site.primary_target
    primary.kind = Target.Kind.SSH
    primary.collect_payload = {"tunnel": True}
    primary.save(update_fields=["kind", "collect_payload"])

    response = _post_join(client, site, overflow)
    assert response.status_code == 201, response.content
    assert response.json() == {"target": overflow.pk, "joined": "tunnel"}
    assert calls == [(site.pk, overflow.pk, None)]
    assert not any(c[0] == "upsert_record" for c in dns.calls)


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_open_overflow_refuses_join_with_ack_is_not_launch(client, monkeypatch):
    """OPEN → 4xx; FIX exact; no upsert; Finding/CheckRun unchanged.

    What would make this fail: treating OPEN as launch, or a consolation
    Finding / CheckRun / Approve / Launch / instance word on the 4xx blob.
    """
    dns = _inject_overflow_join(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, row = _open_overflow("ovf-join-open")
    assert row.state == Finding.State.OPEN
    overflow = _ephemeral_ready(site)
    _plant_ipv4s(site, overflow)
    _running_copy(site, overflow)
    before = _snapshot()

    response = _post_join(client, site, overflow)
    _assert_refused(response, before, detail=FIX)
    assert not any(c[0] == "upsert_record" for c in dns.calls)


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_acked_overflow_refuses_join_with_ack_is_not_launch(client, monkeypatch):
    """ACKED (not ACCEPTED) → 4xx; FIX; no upsert.

    What would make this fail: Ack joining traffic.
    """
    from core.findings import ack

    dns = _inject_overflow_join(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, row = _open_overflow("ovf-join-acked")
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    overflow = _ephemeral_ready(site)
    _plant_ipv4s(site, overflow)
    _running_copy(site, overflow)
    before = _snapshot()

    response = _post_join(client, site, overflow)
    _assert_refused(response, before, detail=FIX)
    assert not any(c[0] == "upsert_record" for c in dns.calls)


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_evaluate_site_still_does_not_join_traffic():
    """evaluate_site does not upsert DNS; AST bans join_overflow_traffic.

    What would make this fail: evaluator calling join_overflow_traffic, or
    dropping join_overflow_traffic from the shared BANNED_IMPORTS tuple.
    """
    from core.findings import accept_risk
    from scaling.evaluator import evaluate_site

    site = _ready_site("ovf-eval-join")
    before = DnsRecord.objects.count()
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    assert row is not None
    accept_risk(row, "cheap+overflow already accepted")
    evaluate_site(site, now=NOW)
    assert DnsRecord.objects.count() == before
    hits = _ast_hits(AST_PATHS, BANNED_IMPORTS)
    assert hits == [], hits
    assert "join_overflow_traffic" in BANNED_IMPORTS


def test_overflow_join_still_requires_recent_touch(client, monkeypatch):
    """ACCEPTED overflow, no touch → 403; no upsert.

    Unmarked: C6 RequireRecentTouch, not SCALE-OVERFLOW-JOIN-TRAFFIC text.
    """
    dns = _inject_overflow_join(monkeypatch)
    _t1_user(client)
    site, overflow = _ready_join("ovf-join-touch")
    before = _snapshot()

    response = _post_join(client, site, overflow)
    assert response.status_code == 403, response.content
    assert "touch" in response.json()["detail"].lower()
    assert Deployment.objects.count() == before[0]
    assert Finding.objects.count() == before[1]
    assert CheckRun.objects.count() == before[2]
    assert not any(c[0] == "upsert_record" for c in dns.calls)


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_unproxied_join_upserts_grey_cloud(client, monkeypatch):
    """site.proxied=False → upsert proxied=False; do not claim orange-cloud."""
    dns = _inject_overflow_join(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, overflow = _ready_join("ovf-join-grey")
    site.proxied = False
    site.save(update_fields=["proxied"])

    response = _post_join(client, site, overflow)
    assert response.status_code == 201, response.content
    upserts = [c for c in dns.calls if c[0] == "upsert_record"]
    assert upserts[-1][5] is False


@pytest.mark.req("SCALE-OVERFLOW-JOIN-TRAFFIC")
def test_default_replica_refuses_without_transport(client, monkeypatch):
    """Tunnel-mode, no injected replica → exact refuse; no Transport, no upsert."""
    dns = _inject_overflow_join(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, _row = _accepted_overflow("ovf-join-norep")
    overflow = _ephemeral_ready(site, host="ovf-join-norep-ovf.lan")
    _running_copy(site, overflow)
    primary = site.primary_target
    primary.kind = Target.Kind.SSH
    primary.collect_payload = {"tunnel": True}
    primary.save(update_fields=["kind", "collect_payload"])
    before = _snapshot()

    response = _post_join(client, site, overflow)
    _assert_refused(response, before, detail=TUNNEL_UNCONFIGURED)
    assert not any(c[0] == "upsert_record" for c in dns.calls)
    blob = response.content.decode()
    assert "eyJ" not in blob
    assert "token" not in blob.lower()


def test_overflow_join_view_does_not_import_deploys():
    """ARCH-D4: OverflowJoinView uses the core port; core never imports deploys."""
    import pathlib

    repo = pathlib.Path(__file__).resolve().parent.parent
    banned = re.compile(r"^\s*(?:from|import)\s+deploys\b", re.M)
    for rel in ("core/views.py", "core/overflow_deploys.py"):
        src = (repo / rel).read_text(encoding="utf-8")
        assert banned.search(src) is None, rel


def test_overflow_join_port_unwired_fails_loud(monkeypatch):
    """Unwired overflow join port raises RuntimeError naming DeploysConfig.ready()."""
    from django.apps import apps as django_apps

    import core.overflow_deploys as port

    monkeypatch.setattr(port, "_join", None)
    with pytest.raises(RuntimeError, match="DeploysConfig.ready"):
        port.join(None, None)
    django_apps.get_app_config("deploys").ready()
    assert port._join is not None


def test_mesh_only_refuses_join(client, monkeypatch):
    """mesh_only ACCEPTED overflow → 4xx before ensure_dns skip-success."""
    dns = _inject_overflow_join(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, overflow = _ready_join("ovf-join-mesh")
    site.exposure = Site.Exposure.MESH_ONLY
    site.dns_zone = None
    site.save(update_fields=["exposure", "dns_zone"])
    before = _snapshot()

    response = _post_join(client, site, overflow)
    _assert_refused(response, before)
    assert not any(c[0] == "upsert_record" for c in dns.calls)


def test_idle_registered_machine_does_not_block_join(client, monkeypatch):
    """Already-rented overflow still joins when an idle machine exists."""
    dns = _inject_overflow_join(monkeypatch)
    _t1_user(client)
    _touch(client, monkeypatch)
    site, overflow = _ready_join("ovf-join-idle")
    other = Target.objects.create(
        zone=site.primary_target.zone,
        host="ovf-join-idle-box.lan",
        ssh_key_ref="ssh-ovf-join-idle-box",
        status=Target.Status.READY,
        lifecycle=Target.Lifecycle.PERMANENT,
    )
    _plant(other, [timezone.now()], ram=10.0)

    response = _post_join(client, site, overflow)
    assert response.status_code == 201, response.content
    assert any(c[0] == "upsert_record" for c in dns.calls)
