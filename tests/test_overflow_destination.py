"""Phase 6.6 idle-first overflow destination (C5/C5b/C6/C7).

Plant real HostMetric and Target rows. Do not mock sustained_pressure,
evaluate_site, refuse_if_attack, has_headroom, or pick_overflow_home.
"""
from __future__ import annotations

import ast
import re
from datetime import timedelta

import pytest
from django.test import override_settings
from test_scale_evaluator import (
    AST_PATHS,
    BANNED_IMPORTS,
    FIX_ACTION,
    NOW,
    REPO,
    TITLE,
    _ast_hits,
    _minutes,
    _overflow_after_cheap,
    _plant,
    _ready_site,
)

from core.models import Partner, Target
from scaling.destination import pick_overflow_home
from scaling.pressure import has_headroom

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_pager():
    from monitor.pager import reset_pager

    reset_pager()
    yield
    reset_pager()


def _assert_idle_copy(row, host):
    blob = f"{row.title}\n{row.body}\n{row.fix_action}"
    assert row.title == TITLE
    assert row.fix_action == FIX_ACTION
    assert "idle registered machine" in row.body
    assert host in row.body
    assert "Overflow estimate 0 USD/hour on own-machine" in row.body
    assert "propose-mode does not launch" in row.body
    assert "t3.medium" not in row.body and "0.0416" not in row.body
    assert re.search(r"\binstance\b", blob) is None
    assert re.search(r"\bApprove\b", blob) is None
    assert re.search(r"\bLaunch\b", blob) is None
    assert "Create target" not in blob


def _assert_t3_copy(row, *hosts):
    assert "0.0416" in row.body
    assert "t3.medium" in row.body
    assert "propose-mode does not launch" in row.body
    assert "idle registered machine" not in row.body
    for host in hosts:
        assert host not in row.body


def _extra_target(
    site,
    host,
    *,
    status=Target.Status.READY,
    lifecycle=Target.Lifecycle.PERMANENT,
):
    return Target.objects.create(
        zone=site.primary_target.zone,
        host=host,
        ssh_key_ref=f"ssh-{host}",
        status=status,
        lifecycle=lifecycle,
    )


def test_has_headroom_false_on_none_or_hot():
    assert has_headroom({"ram": 10.0, "load": 0.1, "cores": 4}) is True
    assert has_headroom({"ram": 85.0, "load": 0.1, "cores": 4}) is True
    assert has_headroom({"ram": None, "load": 0.1, "cores": 4}) is False
    assert has_headroom({"ram": 10.0, "load": None, "cores": 4}) is False
    assert has_headroom({"ram": 10.0, "load": None, "cores": None}) is False
    assert has_headroom({"ram": 90.0, "load": 0.1, "cores": 4}) is False
    assert has_headroom({"ram": 10.0, "load": 9.0, "cores": 4}) is False


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_idle_ready_machine_named_in_overflow_body():
    """ACCEPTED cheap overflow names the idle registered machine, not t3.medium.

    What would make this fail: always interpolating 0.0416 / t3.medium when a
    READY permanent non-primary non-hub Target has current headroom.
    """
    site = _ready_site("idle-ready")
    other = _extra_target(site, "idle-ready-box.lan")
    _plant(site.primary_target, _minutes(), ram=90.0)
    _plant(other, [NOW], ram=10.0)
    before = Target.objects.count()
    row = _overflow_after_cheap(site)
    assert row is not None
    _assert_idle_copy(row, other.host)
    assert Target.objects.count() == before


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_hot_second_machine_falls_back_to_t3():
    """ram=90 or load>cores at now is not headroom; overflow keeps t3.medium.

    What would make this fail: treating a hot second machine as idle so the
    body names that host at 0 / own-machine.
    """
    ram_site = _ready_site("hot-ram-2nd")
    ram_other = _extra_target(ram_site, "hot-ram-2nd.lan")
    _plant(ram_site.primary_target, _minutes(), ram=90.0)
    _plant(ram_other, [NOW], ram=90.0)
    ram_row = _overflow_after_cheap(ram_site)
    _assert_t3_copy(ram_row, ram_other.host)

    load_site = _ready_site("hot-load-2nd")
    load_other = _extra_target(load_site, "hot-load-2nd.lan")
    _plant(load_site.primary_target, _minutes(), ram=90.0)
    _plant(load_other, [NOW], ram=10.0, load=9.0, cores=4)
    load_row = _overflow_after_cheap(load_site)
    _assert_t3_copy(load_row, load_other.host)


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_stale_second_machine_is_not_idle():
    """Latest sample now-121s is outside MAX_SAMPLE_GAP_S; keep t3.medium.

    What would make this fail: treating a stale HostMetric as current headroom.
    """
    site = _ready_site("stale-2nd")
    other = _extra_target(site, "stale-2nd.lan")
    _plant(site.primary_target, _minutes(), ram=90.0)
    _plant(other, [NOW - timedelta(seconds=121)], ram=10.0)
    row = _overflow_after_cheap(site)
    _assert_t3_copy(row, other.host)


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_missing_metrics_is_not_idle():
    """READY permanent with no HostMetric row is not idle.

    What would make this fail: missing samples counting as headroom.
    """
    site = _ready_site("miss-metric")
    other = _extra_target(site, "miss-metric.lan")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    _assert_t3_copy(row, other.host)


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_pending_error_decommissioned_never_picked():
    """pending / error / decommissioned extras with ram=10 are not leftover idle.

    What would make this fail: skipping the READY gate so a pending box is named.
    """
    site = _ready_site("pend-err")
    pending = _extra_target(site, "pend-err-pending.lan", status=Target.Status.PENDING)
    error = _extra_target(site, "pend-err-error.lan", status=Target.Status.ERROR)
    decom = _extra_target(
        site, "pend-err-decom.lan", status=Target.Status.DECOMMISSIONED,
    )
    _plant(site.primary_target, _minutes(), ram=90.0)
    _plant(pending, [NOW], ram=10.0)
    _plant(error, [NOW], ram=10.0)
    _plant(decom, [NOW], ram=10.0)
    row = _overflow_after_cheap(site)
    _assert_t3_copy(row, pending.host, error.host, decom.host)


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_ephemeral_never_picked():
    """READY ephemeral ram=10 is skipped; leftover READY permanent is named.

    What would make this fail: picking ephemeral because it is READY and idle.
    """
    site = _ready_site("eph-skip")
    eph = _extra_target(
        site,
        "eph-skip-eph.lan",
        lifecycle=Target.Lifecycle.EPHEMERAL,
    )
    leftover = _extra_target(site, "eph-skip-left.lan")
    _plant(site.primary_target, _minutes(), ram=90.0)
    _plant(eph, [NOW], ram=10.0)
    _plant(leftover, [NOW], ram=10.0)
    before = Target.objects.count()
    row = _overflow_after_cheap(site)
    _assert_idle_copy(row, leftover.host)
    assert eph.host not in row.body
    assert Target.objects.count() == before


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_partner_destination_only_falls_back_to_t3():
    """Partner destination_order is never overflow home, even with no PartnerSite.

    What would make this fail: picking a destination_order Target because the
    overflow site itself is not a PartnerSite.
    """
    site = _ready_site("part-only")
    dest = _extra_target(site, "part-only-dest.lan")
    Partner.objects.create(
        slug="part-only-p",
        name="part-only-p",
        destination_order=[dest.pk],
    )
    _plant(site.primary_target, _minutes(), ram=90.0)
    _plant(dest, [NOW], ram=10.0)
    before = Target.objects.count()
    row = _overflow_after_cheap(site)
    _assert_t3_copy(row, dest.host)
    assert Target.objects.count() == before


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_partner_destination_skipped_picks_leftover():
    """Skip partner dest and ephemeral; name the leftover READY permanent host.

    What would make this fail: naming the partner dest or the ephemeral box.
    """
    site = _ready_site("part-left")
    dest = _extra_target(site, "part-left-dest.lan")
    eph = _extra_target(
        site,
        "part-left-eph.lan",
        lifecycle=Target.Lifecycle.EPHEMERAL,
    )
    leftover = _extra_target(site, "part-left-box.lan")
    Partner.objects.create(
        slug="part-left-p",
        name="part-left-p",
        destination_order=[dest.pk],
    )
    _plant(site.primary_target, _minutes(), ram=90.0)
    _plant(dest, [NOW], ram=10.0)
    _plant(eph, [NOW], ram=10.0)
    _plant(leftover, [NOW], ram=10.0)
    row = _overflow_after_cheap(site)
    _assert_idle_copy(row, leftover.host)
    assert dest.host not in row.body
    assert eph.host not in row.body


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_primary_target_with_headroom_is_not_picked():
    """Cold primary plus a second idle: pick returns the second host, not primary.

    What would make this fail: treating the site's primary_target as overflow home.
    """
    site = _ready_site("cold-prim")
    _plant(site.primary_target, [NOW], ram=10.0)
    other = _extra_target(site, "cold-prim-idle.lan")
    _plant(other, [NOW], ram=10.0)
    host, cost, size = pick_overflow_home(site, now=NOW)
    assert host == other.host
    assert host != site.primary_target.host
    assert cost == "0"
    assert size == "own-machine"


@override_settings(HUB_PUBLIC_URL="https://hub.example.test")
@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_hub_host_is_not_picked():
    """Hub hostname is never overflow home; a leftover non-hub idle is.

    What would make this fail: naming hub.example.test because it is READY
    permanent with ram=10, or picking Hub over a later leftover.
    """
    hub_only = _ready_site("hub-only")
    hub = _extra_target(hub_only, "hub.example.test")
    _plant(hub_only.primary_target, _minutes(), ram=90.0)
    _plant(hub, [NOW], ram=10.0)
    hub_row = _overflow_after_cheap(hub_only)
    _assert_t3_copy(hub_row, hub.host)

    leftover_site = _ready_site("hub-left")
    hub2 = _extra_target(leftover_site, "hub.example.test")
    leftover = _extra_target(leftover_site, "hub-left-box.lan")
    _plant(leftover_site.primary_target, _minutes(), ram=90.0)
    _plant(hub2, [NOW], ram=10.0)
    _plant(leftover, [NOW], ram=10.0)
    left_row = _overflow_after_cheap(leftover_site)
    _assert_idle_copy(left_row, leftover.host)
    assert "hub.example.test" not in left_row.body


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
@pytest.mark.req("SCALE-PROPOSE-NO-PROVISION")
def test_idle_pick_does_not_create_a_target():
    """Idle path is copy only: no new Target, no except-Exception miss, AST clean.

    What would make this fail: pick creating a Target, swallowing Exception into
    0.0416 / t3.medium, or the overflow file path importing enroll/ec2.
    """
    site = _ready_site("idle-noprov")
    other = _extra_target(site, "idle-noprov-box.lan")
    _plant(site.primary_target, _minutes(), ram=90.0)
    _plant(other, [NOW], ram=10.0)
    before = Target.objects.count()
    row = _overflow_after_cheap(site)
    _assert_idle_copy(row, other.host)
    assert Target.objects.count() == before

    dest = REPO / "scaling" / "destination.py"
    src = dest.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        if node.type is None:
            pytest.fail("destination.py has a bare except")
        if isinstance(node.type, ast.Name) and node.type.id == "Exception":
            for stmt in ast.walk(node):
                if not isinstance(stmt, ast.Return):
                    continue
                dumped = ast.dump(stmt)
                assert "OVERFLOW" not in dumped
                assert "0.0416" not in dumped
                assert "t3.medium" not in dumped
            pytest.fail("destination.py catches Exception")
    writes = {"save", "create", "update", "delete", "select_for_update"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in writes:
            pytest.fail(f"destination.py mutates via .{node.attr}")
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            names = []
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif node.module:
                names = [node.module]
            joined = " ".join(names)
            assert "partner_jobs" not in joined
            assert "monitor.topology" not in joined
            assert joined != "topology"
    pick_fn = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "pick_overflow_home"
    )
    pick_names = {n.id for n in ast.walk(pick_fn) if isinstance(n, ast.Name)}
    assert "has_headroom" in pick_names
    assert "85" not in src
    assert "MEM_PCT_THRESHOLD" not in src
    hits = _ast_hits(AST_PATHS, BANNED_IMPORTS)
    assert hits == [], hits

    ev_src = (REPO / "scaling" / "evaluator.py").read_text(encoding="utf-8")
    ev_tree = ast.parse(ev_src)

    def _fn(name):
        return next(
            node
            for node in ev_tree.body
            if isinstance(node, ast.FunctionDef) and node.name == name
        )

    def _mentions_pick(fn):
        for node in ast.walk(fn):
            if isinstance(node, ast.Name) and node.id == "pick_overflow_home":
                return True
            if isinstance(node, ast.Attribute) and node.attr == "pick_overflow_home":
                return True
        return False

    assert _mentions_pick(_fn("_evaluate_eligible"))
    assert not _mentions_pick(_fn("_file_cheap"))
    assert not _mentions_pick(_fn("evaluate_all"))
    assert not _mentions_pick(_fn("_acquire_cycle_lock"))


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_idle_pick_does_not_name_another_workspace_host():
    """Idle home is workspace-scoped. Tenant B must not see tenant A's hostname.

    What would make this fail: pick_overflow_home walking every READY permanent
    Target, so B's scale-out-proposal body names A's host and B cannot rent.
    """
    from core.models import NetworkZone, Workspace

    other = Workspace.objects.create(name="Other overflow", slug="ovf-other-ws")
    other_zone = NetworkZone.objects.create(
        workspace=other, name="ovf-other-net", slug="ovf-other-net",
    )
    idle = Target.objects.create(
        zone=other_zone,
        host="idle-other-ws.lan",
        ssh_key_ref="ssh-idle-other-ws",
        status=Target.Status.READY,
        lifecycle=Target.Lifecycle.PERMANENT,
    )
    _plant(idle, [NOW], ram=10.0)
    site = _ready_site("ovf-ws-b")
    _plant(site.primary_target, _minutes(), ram=90.0)
    host, _cost, _size = pick_overflow_home(site, now=NOW)
    assert host != idle.host
    row = _overflow_after_cheap(site)
    assert idle.host not in row.body
