"""Phase 6 evaluator: sustained propose, spike/attack/partner refuse, never provision.

Plant real HostMetric rows. Do not mock sustained_pressure, evaluate_site, or
refuse_if_attack. Markers only on tests that prove that id's text (C11).
"""
from __future__ import annotations

import ast
import pathlib
import re
from datetime import UTC, datetime, timedelta

import pytest
from django.conf import settings

from core.models import Finding, HostMetric, Target

pytestmark = pytest.mark.django_db

REPO = pathlib.Path(__file__).resolve().parent.parent
NOW = datetime(2026, 8, 24, 12, 10, 30, tzinfo=UTC)
TITLE = "Scale-out proposal awaiting approval (propose mode)"
FIX_ACTION = "Ack is not launch. Propose-mode does not launch."
BANNED_IMPORTS = (
    "aws_enroll",
    "ec2",
    "enroll_aws_target",
    "enroll_overflow_target",
    "overflow",
    "InstanceCreateView",
    "boto3",
    "CloudProvider",
    "EdgeProtection",
    "purge_cache",
    "set_security_level",
)
AST_PATHS = (
    REPO / "scaling",
    REPO / "monitor" / "tasks.py",
    REPO / "monitor" / "host_metrics.py",
)


@pytest.fixture(autouse=True)
def _reset_pager():
    from monitor.pager import reset_pager

    reset_pager()
    yield
    reset_pager()


def _ready_site(slug):
    from test_attack_playbook import _world

    site = _world(slug)
    site.scale_ready = True
    site.save(update_fields=["scale_ready"])
    return site


def _fp(site):
    return f"scale-out-proposal:{site.pk}"


def _cheap_fp(site):
    return f"scale-cheap-remediation:{site.pk}"


def _cheap(site):
    return Finding.objects.filter(fingerprint=_cheap_fp(site)).first()


def _overflow_after_cheap(site, *, now=NOW):
    """Accept the cheap Finding so evaluate_site may file overflow."""
    from core.findings import accept_risk
    from scaling.evaluator import evaluate_site

    cheap = evaluate_site(site, now=now)
    assert cheap is not None
    assert cheap.fingerprint == _cheap_fp(site)
    if cheap.state != Finding.State.ACCEPTED:
        accept_risk(cheap, "cheap remediations already applied")
    return evaluate_site(site, now=now)


def _minutes(now=NOW, n=5):
    return [now - timedelta(minutes=n - 1 - i) for i in range(n)]


def _plant(target, timestamps, **fields):
    payload = {
        "cpu": None,
        "ram": 10.0,
        "disk": 10.0,
        "load": 0.1,
        "cores": 4,
    }
    payload.update(fields)
    for ts in timestamps:
        HostMetric.objects.create(target=target, ts=ts, **payload)


def _plant_series(target, timestamps, series):
    for ts, fields in zip(timestamps, series, strict=True):
        _plant(target, [ts], **fields)


def _proposal(site):
    return Finding.objects.filter(fingerprint=_fp(site)).first()


def _push_count():
    from core.models import AlertState
    from monitor.antinoise import PUSH_LOG_FP

    log = AlertState.objects.filter(fingerprint=PUSH_LOG_FP).first()
    if log is None:
        return 0
    return len(log.transitions or [])


def _ast_hits(paths, names):
    hits = []
    files = []
    for path in paths:
        if path.is_dir():
            files.extend(sorted(path.rglob("*.py")))
        elif path.is_file():
            files.append(path)
    for py in files:
        try:
            tree = ast.parse(py.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        rel = py.relative_to(REPO)
        for node in ast.walk(tree):
            found = set()
            if isinstance(node, ast.Import):
                for alias in node.names:
                    found.update(alias.name.split("."))
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    found.update(node.module.split("."))
                for alias in node.names:
                    found.update(alias.name.split("."))
            elif isinstance(node, ast.Name):
                found.add(node.id)
            elif isinstance(node, ast.Attribute):
                found.add(node.attr)
            banned = found & set(names)
            if banned:
                hits.append(f"{rel}:{node.lineno}:{sorted(banned)}")
    return hits


def _evaluate_site_fn():
    src = (REPO / "scaling" / "evaluator.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == "evaluate_site":
            return node
    return None


def _unwrap(stmts):
    stmts = list(stmts)
    if (
        stmts
        and isinstance(stmts[0], ast.Expr)
        and isinstance(stmts[0].value, ast.Constant)
    ):
        stmts = stmts[1:]
    return stmts


def _call_name(call):
    if isinstance(call.func, ast.Name):
        return call.func.id
    if isinstance(call.func, ast.Attribute):
        return call.func.attr
    return None


CHEAP_TITLE = "Cheap remediations before overflow (propose mode)"
CHEAP_FIX_ACTION = "Ack is not launch. Apply cache and workers before overflow."


@pytest.mark.req("SCALE-CHEAP-BEFORE-OVERFLOW")
@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_five_hot_mem_minutes_file_cheap_before_overflow():
    """Five ram=90 minutes file cheap remediations, not overflow.

    What would make this fail: skipping §9.5.3 so the first streak still
    opens scale-out-proposal:{pk} and rents a server in copy.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("cheap-mem")
    before = Target.objects.count()
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = evaluate_site(site, now=NOW)
    assert row is not None
    assert row.fingerprint == _cheap_fp(site)
    assert row.entity == f"site:{site.domain}"
    assert row.title == CHEAP_TITLE
    assert row.fix_action == CHEAP_FIX_ACTION
    assert "Cache-Control" in row.body
    assert "Cloudflare cache" in row.body
    assert "gunicorn" in row.body
    assert "2×CPU+1" in row.body or "2xCPU+1" in row.body
    assert "propose-mode does not launch" in row.body
    assert site.name in row.body
    assert "ram" in row.body
    blob = f"{row.title} {row.body} {row.fix_action}"
    assert re.search(r"\binstance\b", blob) is None
    assert "Approve" not in blob
    assert "Launch" not in blob
    assert "enroll" not in blob
    assert _proposal(site) is None
    assert Target.objects.count() == before


@pytest.mark.req("SCALE-CHEAP-BEFORE-OVERFLOW")
def test_open_cheap_does_not_file_overflow():
    """OPEN cheap blocks scale-out-proposal on the next evaluate.

    What would make this fail: filing overflow while cheap is still OPEN.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("cheap-open")
    _plant(site.primary_target, _minutes(), ram=90.0)
    first = evaluate_site(site, now=NOW)
    assert first is not None
    assert first.fingerprint == _cheap_fp(site)
    second = evaluate_site(site, now=NOW)
    assert second is not None
    assert second.pk == first.pk
    assert second.state == Finding.State.OPEN
    assert _proposal(site) is None


@pytest.mark.req("SCALE-CHEAP-BEFORE-OVERFLOW")
def test_acked_cheap_does_not_file_overflow():
    """ACKED cheap still blocks overflow.

    What would make this fail: treating Ack as skip-cheap so overflow files.
    """
    from core.findings import ack
    from scaling.evaluator import evaluate_site

    site = _ready_site("cheap-acked")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = evaluate_site(site, now=NOW)
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    again = evaluate_site(site, now=NOW)
    assert again is not None
    assert again.pk == row.pk
    assert _proposal(site) is None


@pytest.mark.req("SCALE-CHEAP-BEFORE-OVERFLOW")
@pytest.mark.req("SCALE-NEVER-ATTACK")
def test_open_cheap_resolves_when_attack_engages():
    """OPEN cheap system-resolves when the attack playbook engages."""
    from test_attack_playbook import _attack_shaped

    from core.models import AuditEvent
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection
    from scaling.evaluator import evaluate_site

    site = _ready_site("cheap-atk")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = evaluate_site(site, now=NOW)
    assert row.fingerprint == _cheap_fp(site)
    _attack_shaped(site)
    run(site, FakeEdgeProtection())
    assert evaluate_site(site, now=NOW) is None
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert AuditEvent.objects.filter(
        action="finding_resolved",
        source="system",
        object_id=str(row.pk),
    ).exists()
    assert _proposal(site) is None


@pytest.mark.req("SCALE-CHEAP-BEFORE-OVERFLOW")
@pytest.mark.req("SCALE-NEVER-PARTNER")
def test_partner_bind_resolves_open_cheap():
    """Binding PartnerSite system-resolves OPEN cheap; no overflow."""
    from core.models import AuditEvent, Partner, PartnerSite
    from scaling.evaluator import evaluate_site

    site = _ready_site("cheap-part")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = evaluate_site(site, now=NOW)
    partner = Partner.objects.create(slug="cheap-part-p", name="cheap-part-p")
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref="cheap-part-t")
    assert evaluate_site(site, now=NOW) is None
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert AuditEvent.objects.filter(
        action="finding_resolved",
        source="system",
        object_id=str(row.pk),
    ).exists()
    assert _proposal(site) is None


@pytest.mark.req("SCALE-CHEAP-BEFORE-OVERFLOW")
def test_partner_bind_resolves_acked_cheap():
    """Binding PartnerSite system-resolves ACKED cheap; no overflow.

    Marked SCALE-CHEAP-BEFORE-OVERFLOW only (that id's text is OPEN or ACKED
    cheap). Unmarked for SCALE-NEVER-PARTNER: that id's retract sentence is
    OPEN-only (C11 / D-096).
    """
    from core.findings import ack
    from core.models import AuditEvent, Partner, PartnerSite
    from scaling.evaluator import evaluate_site

    site = _ready_site("cheap-acked-part")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = evaluate_site(site, now=NOW)
    assert row is not None
    assert row.fingerprint == _cheap_fp(site)
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    partner = Partner.objects.create(
        slug="cheap-acked-part-p", name="cheap-acked-part-p",
    )
    PartnerSite.objects.create(
        partner=partner, site=site, tenant_ref="cheap-acked-part-t",
    )
    assert evaluate_site(site, now=NOW) is None
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert AuditEvent.objects.filter(
        action="finding_resolved",
        source="system",
        object_id=str(row.pk),
    ).exists()
    assert _proposal(site) is None
    assert Finding.objects.filter(fingerprint=_cheap_fp(site)).count() == 1


@pytest.mark.req("SCALE-CHEAP-BEFORE-OVERFLOW")
@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_accepted_cheap_unblocks_overflow():
    """ACCEPTED cheap + still-sustained files the costed overflow Finding.

    What would make this fail: ACCEPTED cheap staying a dead-end, or filing
    overflow without the operator skipping cheap remediations.
    """
    from core.findings import accept_risk
    from scaling.constants import FIX_ACTION as PINNED_FIX
    from scaling.constants import TITLE as PINNED_TITLE
    from scaling.evaluator import evaluate_site

    site = _ready_site("cheap-ack")
    before = Target.objects.count()
    _plant(site.primary_target, _minutes(), ram=90.0)
    cheap = evaluate_site(site, now=NOW)
    assert cheap is not None
    assert cheap.fingerprint == _cheap_fp(site)
    accept_risk(cheap, "cache and workers already applied")
    cheap.refresh_from_db()
    assert cheap.state == Finding.State.ACCEPTED
    row = evaluate_site(site, now=NOW)
    assert row is not None
    assert row.fingerprint == _fp(site)
    assert row.title == TITLE == PINNED_TITLE
    assert row.fix_action == FIX_ACTION == PINNED_FIX
    assert "0.0416" in row.body
    assert "t3.medium" in row.body
    assert "propose-mode does not launch" in row.body
    assert Target.objects.count() == before


@pytest.mark.req("SCALE-CHEAP-NO-MUTATE")
def test_cheap_path_does_not_call_edge_cache_or_enroll():
    """Cheap evaluate never mutates Cloudflare cache or gunicorn or enrolls.

    What would make this fail: scaling.evaluator importing EdgeProtection
    cache helpers or rewriting workers while proposing cheap steps.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("cheap-nomut")
    before = Target.objects.count()
    _plant(site.primary_target, _minutes(), ram=90.0)
    evaluate_site(site, now=NOW)
    src = (REPO / "scaling" / "evaluator.py").read_text(encoding="utf-8")
    assert "set_security_level" not in src
    assert "purge_cache" not in src
    assert "gunicorn" not in src or "2×CPU+1" in src or "2xCPU+1" in src
    assert "--workers" not in src
    hits = _ast_hits(AST_PATHS, BANNED_IMPORTS)
    assert hits == [], hits
    assert Target.objects.count() == before
    assert not (REPO / "scaling" / "tasks.py").exists()


@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_five_hot_mem_minutes_file_proposal_with_cost():
    """Five distinct UTC minutes of ram=90 file a costed propose-mode Finding.

    What would make this fail: last-N without a window, entity keyed on pk,
    missing 0.0416 / t3.medium / propose-mode does not launch, or creating a
    Target as if propose-mode launched.
    """
    from scaling.constants import FIX_ACTION as PINNED_FIX
    from scaling.constants import TITLE as PINNED_TITLE

    site = _ready_site("hot-mem")
    before = Target.objects.count()
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    assert row is not None
    assert row.fingerprint == _fp(site)
    assert row.entity == f"site:{site.domain}"
    assert str(site.pk) not in row.entity
    assert row.title == TITLE == PINNED_TITLE
    assert row.fix_action == FIX_ACTION == PINNED_FIX
    assert "0.0416" in row.body
    assert "t3.medium" in row.body
    assert "propose-mode does not launch" in row.body
    assert site.name in row.body
    assert "ram" in row.body
    blob = f"{row.title} {row.body} {row.fix_action}"
    assert re.search(r"\binstance\b", blob) is None
    assert "Approve" not in blob
    assert "Launch" not in blob
    assert "enroll" not in blob
    assert "instance.create" not in blob
    assert row.source_engine == "scaling.evaluator"
    assert row.severity == Finding.Severity.P2
    assert row.state == Finding.State.OPEN
    assert Target.objects.count() == before


@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_five_hot_load_minutes_file_proposal():
    """Same-axis load>cores for five consecutive minutes files the proposal.

    What would make this fail: requiring ram heat, ignoring cores, or treating
    load=5 with cores=4 as cold.
    """

    site = _ready_site("hot-load")
    _plant(site.primary_target, _minutes(), ram=10.0, disk=10.0, load=5.0, cores=4)
    row = _overflow_after_cheap(site)
    assert row is not None
    assert row.fingerprint == _fp(site)
    assert "load" in row.body
    assert "0.0416" in row.body
    assert "t3.medium" in row.body
    assert "propose-mode does not launch" in row.body


@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_five_hot_disk_minutes_do_not_propose():
    """Disk is not an overflow axis: five hot disk minutes must not file.

    What would make this fail: treating disk>85 as sustained overflow so a
    host-health fill becomes a scale-out proposal.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("hot-disk")
    _plant(
        site.primary_target,
        _minutes(),
        ram=10.0,
        disk=90.0,
        load=0.1,
        cores=4,
    )
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


@pytest.mark.req("SCALE-SPIKE-NO-PROPOSE")
def test_one_hot_among_five_does_not_propose():
    """A single newest ram=90 among four cold minutes is a spike, not a streak.

    What would make this fail: last-N or any-over-threshold filing on one hot
    sample.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("spike-one")
    series = (
        [{"ram": 10.0}] * 4
        + [{"ram": 90.0}]
    )
    _plant_series(site.primary_target, _minutes(), series)
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


def test_four_of_five_over_one_under_does_not_propose():
    """Five in-window minutes with four ram>85 and one under must not file.

    Unmarked: SCALE-SPIKE-NO-PROPOSE text is 1-of-5 / hole / mixed / stale.
    Task 6 must call this proof, not the spike test.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("four-of-five")
    series = (
        [{"ram": 10.0}]
        + [{"ram": 90.0}] * 4
    )
    _plant_series(site.primary_target, _minutes(), series)
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


@pytest.mark.req("SCALE-SPIKE-NO-PROPOSE")
def test_missing_minute_breaks_streak():
    """Four hot minutes, a hole > 120s, then one hot must not file.

    What would make this fail: last-N ignoring a missing UTC minute, so a
    retry cluster or a collector gap still looks sustained.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("hole")
    stamps = [
        NOW - timedelta(minutes=5),
        NOW - timedelta(minutes=4),
        NOW - timedelta(minutes=3),
        NOW - timedelta(minutes=2),
        NOW,
    ]
    assert (stamps[-1] - stamps[-2]) >= timedelta(seconds=120)
    _plant(site.primary_target, stamps, ram=90.0)
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


@pytest.mark.req("SCALE-SPIKE-NO-PROPOSE")
def test_mixed_axes_do_not_propose():
    """Rotating ram/load/ram/load/ram is not the same axis for five minutes.

    What would make this fail: OR-ing axes per minute so mixed heat files.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("mixed-axes")
    series = [
        {"ram": 90.0, "load": 0.1, "cores": 4},
        {"ram": 10.0, "load": 5.0, "cores": 4},
        {"ram": 90.0, "load": 0.1, "cores": 4},
        {"ram": 10.0, "load": 5.0, "cores": 4},
        {"ram": 90.0, "load": 0.1, "cores": 4},
    ]
    _plant_series(site.primary_target, _minutes(), series)
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


@pytest.mark.req("SCALE-SPIKE-NO-PROPOSE")
def test_stale_window_does_not_propose():
    """Five hot rows older than 6 minutes are outside the 300s window.

    What would make this fail: last-N of stored history with no Hub-clock
    window, so a dead collector keeps proposing forever.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("stale")
    stamps = [NOW - timedelta(minutes=12 - i) for i in range(5)]
    assert all(NOW - ts > timedelta(minutes=6) for ts in stamps)
    _plant(site.primary_target, stamps, ram=90.0)
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


@pytest.mark.req("SCALE-NEVER-ATTACK")
def test_attack_engaged_does_not_propose():
    """FakeEdgeProtection + run() must not file scale-out-proposal:{pk}.

    What would make this fail: skipping refuse_if_attack so attack-shaped
    load still opens a proposal.
    """
    from test_attack_playbook import _attack_shaped

    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection
    from scaling.evaluator import evaluate_site

    site = _ready_site("atk-engage")
    _plant(site.primary_target, _minutes(), ram=90.0)
    _attack_shaped(site)
    run(site, FakeEdgeProtection())
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None
    assert _cheap(site) is None


@pytest.mark.req("SCALE-NEVER-ATTACK")
def test_open_proposal_resolves_when_attack_engages():
    """File while quiet, engage the playbook, evaluate_site again → resolved.

    What would make this fail: leaving an OPEN proposal in place after
    AttackRefuse, or filing a consolation Finding.
    """
    from test_attack_playbook import _attack_shaped

    from core.models import AuditEvent
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection
    from scaling.evaluator import evaluate_site

    site = _ready_site("atk-retract")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    assert row is not None
    assert row.state == Finding.State.OPEN
    _attack_shaped(site)
    run(site, FakeEdgeProtection())
    assert evaluate_site(site, now=NOW) is None
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert AuditEvent.objects.filter(
        action="finding_resolved",
        source="system",
        object_id=str(row.pk),
    ).exists()
    assert Finding.objects.filter(fingerprint=_fp(site)).count() == 1


@pytest.mark.req("SCALE-NEVER-ATTACK")
def test_acked_proposal_resolves_when_attack_engages():
    """File while quiet, ack, engage the playbook, evaluate_site → resolved.

    What would make this fail: `_retract` handling OPEN only so an ACKED
    proposal stays in the inbox after AttackRefuse (SCALE-NEVER-ATTACK text
    is OPEN or ACKED).
    """
    from test_attack_playbook import _attack_shaped

    from core.findings import ack
    from core.models import AuditEvent
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection
    from scaling.evaluator import evaluate_site

    site = _ready_site("atk-acked")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    assert row is not None
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    _attack_shaped(site)
    run(site, FakeEdgeProtection())
    assert evaluate_site(site, now=NOW) is None
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert AuditEvent.objects.filter(
        action="finding_resolved",
        source="system",
        object_id=str(row.pk),
    ).exists()
    assert Finding.objects.filter(fingerprint=_fp(site)).count() == 1


@pytest.mark.req("SCALE-NEVER-ATTACK")
@pytest.mark.req("SCALE-CHEAP-BEFORE-OVERFLOW")
def test_acked_cheap_resolves_when_attack_engages():
    """ACKED cheap system-resolves when the attack playbook engages.

    What would make this fail: `_retract` resolving ACKED only for overflow
    and OPEN-only for cheap, so an ACKED cheap Finding stays in the inbox
    (SCALE-NEVER-ATTACK / SCALE-CHEAP-BEFORE-OVERFLOW text is OPEN or ACKED).
    """
    from test_attack_playbook import _attack_shaped

    from core.findings import ack
    from core.models import AuditEvent
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection
    from scaling.evaluator import evaluate_site

    site = _ready_site("cheap-acked-atk")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = evaluate_site(site, now=NOW)
    assert row is not None
    assert row.fingerprint == _cheap_fp(site)
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    _attack_shaped(site)
    run(site, FakeEdgeProtection())
    assert evaluate_site(site, now=NOW) is None
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert AuditEvent.objects.filter(
        action="finding_resolved",
        source="system",
        object_id=str(row.pk),
    ).exists()
    assert _proposal(site) is None
    assert Finding.objects.filter(fingerprint=_cheap_fp(site)).count() == 1
    assert Finding.objects.filter(
        fingerprint=_cheap_fp(site),
        state=Finding.State.OPEN,
    ).count() == 0
    assert Finding.objects.filter(
        fingerprint=_fp(site),
        state=Finding.State.OPEN,
    ).count() == 0


@pytest.mark.req("SCALE-NEVER-PARTNER")
def test_partner_site_does_not_propose():
    """PartnerSite + quiet playbook + five hot mem must not file.

    What would make this fail: only gating on the attack playbook so partner
    overflow still proposes.
    """
    from core.models import Partner, PartnerSite
    from scaling.attack_gate import refuse_if_attack
    from scaling.evaluator import evaluate_site

    control = _ready_site("part-ctl")
    assert refuse_if_attack(control) is None
    site = _ready_site("part-hot")
    _plant(site.primary_target, _minutes(), ram=90.0)
    partner = Partner.objects.create(slug="part-hot-p", name="part-hot-p")
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref="part-hot-t")
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None
    assert _cheap(site) is None


@pytest.mark.req("SCALE-NEVER-PARTNER")
def test_partner_bind_after_file_resolves_open_proposal():
    """Binding PartnerSite after file system-resolves the OPEN proposal.

    What would make this fail: leaving the proposal OPEN after partner bind,
    or requiring the attack playbook to retract.
    """
    from core.models import AuditEvent, Partner, PartnerSite
    from scaling.attack_gate import refuse_if_attack
    from scaling.evaluator import evaluate_site

    control = _ready_site("bind-ctl")
    assert refuse_if_attack(control) is None
    site = _ready_site("bind-hot")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    assert row is not None
    partner = Partner.objects.create(slug="bind-hot-p", name="bind-hot-p")
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref="bind-hot-t")
    assert evaluate_site(site, now=NOW) is None
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert AuditEvent.objects.filter(
        action="finding_resolved",
        source="system",
        object_id=str(row.pk),
    ).exists()


def test_partner_bind_after_file_resolves_acked_proposal():
    """Binding PartnerSite after ack system-resolves the ACKED proposal.

    Unmarked: SCALE-NEVER-PARTNER text is OPEN-only (C11 / D-096). C5 still
    retracts ACKED on PartnerOverflowRefuse.
    """
    from core.findings import ack
    from core.models import AuditEvent, Partner, PartnerSite
    from scaling.attack_gate import refuse_if_attack
    from scaling.evaluator import evaluate_site

    control = _ready_site("bind-acked-ctl")
    assert refuse_if_attack(control) is None
    site = _ready_site("bind-acked")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    assert row is not None
    ack(row)
    row.refresh_from_db()
    assert row.state == Finding.State.ACKED
    partner = Partner.objects.create(slug="bind-acked-p", name="bind-acked-p")
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref="bind-acked-t")
    assert evaluate_site(site, now=NOW) is None
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert AuditEvent.objects.filter(
        action="finding_resolved",
        source="system",
        object_id=str(row.pk),
    ).exists()


@pytest.mark.req("SCALE-PROPOSE-NO-PROVISION")
def test_scaling_and_beat_do_not_import_enroll_or_ec2():
    """AST-scan scaling/ + monitor/tasks.py + monitor/host_metrics.py.

    What would make this fail: importing provision.aws_enroll, providers.ec2,
    enroll_aws_target, enroll_overflow_target, provision.overflow,
    InstanceCreateView, boto3, or CloudProvider, or adding scaling/tasks.py
    (scaling.* routes to control).
    """
    assert (REPO / "scaling" / "evaluator.py").is_file()
    assert (REPO / "scaling" / "pressure.py").is_file()
    assert (REPO / "scaling" / "constants.py").is_file()
    assert not (REPO / "scaling" / "tasks.py").exists()
    hits = _ast_hits(AST_PATHS, BANNED_IMPORTS)
    assert hits == [], hits


@pytest.mark.req("SCALE-READY-PREREQ")
def test_scale_ready_false_five_hot_does_not_propose():
    """Fail-closed: scale_ready False is ineligible even with five hot mem.

    What would make this fail: omitting the scale_ready gate so every public
    site with a primary_target can be proposed.
    """
    from test_attack_playbook import _world

    from scaling.evaluator import evaluate_site

    site = _world("not-ready")
    assert site.scale_ready is False
    _plant(site.primary_target, _minutes(), ram=90.0)
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


@pytest.mark.req("SCALE-READY-PREREQ")
def test_mesh_only_five_hot_does_not_propose():
    """mesh_only is ineligible even when scale_ready and five minutes are hot.

    What would make this fail: treating mesh_only like public overflow.
    """
    from core.models import Site
    from scaling.evaluator import evaluate_site

    site = _ready_site("mesh-hot")
    site.exposure = Site.Exposure.MESH_ONLY
    site.save(update_fields=["exposure"])
    _plant(site.primary_target, _minutes(), ram=90.0)
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


def test_cores_none_load_axis_not_over():
    """cores None is not load>cores; five such minutes must not propose.

    What would make this fail: `load > cores` unguarded so None TypeErrors or
    compares as hot.
    """
    from scaling.evaluator import evaluate_site
    from scaling.pressure import sustained_pressure

    site = _ready_site("cores-none")
    _plant(
        site.primary_target,
        _minutes(),
        ram=10.0,
        disk=10.0,
        load=5.0,
        cores=None,
    )
    samples = [
        {"ram": 10.0, "disk": 10.0, "load": 5.0, "cores": None, "ts": ts}
        for ts in _minutes()
    ]
    assert sustained_pressure(samples, now=NOW) is False
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


def test_cpu_only_does_not_propose():
    """cpu is not an overflow axis.

    What would make this fail: treating HostMetric.cpu as sustained pressure.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("cpu-only")
    _plant(
        site.primary_target,
        _minutes(),
        cpu=99.0,
        ram=10.0,
        disk=10.0,
        load=0.1,
        cores=4,
    )
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


def test_fewer_than_five_samples_not_sustained():
    """Four hot minutes are not five consecutive distinct UTC minutes.

    What would make this fail: a threshold of 4 or last-N on a short window.
    """
    from scaling.evaluator import evaluate_site
    from scaling.pressure import sustained_pressure

    site = _ready_site("four-hot")
    stamps = _minutes(n=4)
    _plant(site.primary_target, stamps, ram=90.0)
    samples = [
        {"ram": 90.0, "disk": 10.0, "load": 0.1, "cores": 4, "ts": ts}
        for ts in stamps
    ]
    assert sustained_pressure(samples, now=NOW) is False
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


def test_re_evaluate_while_open_does_not_record_second_push():
    """OPEN already: return the row; do not raise_alert / _record_push again.

    What would make this fail: refreshing an OPEN episode every Beat tick so
    P2 pages once a minute.
    """
    from scaling.evaluator import evaluate_site

    site = _ready_site("re-open")
    _plant(site.primary_target, _minutes(), ram=90.0)
    first = _overflow_after_cheap(site)
    assert first is not None
    n = _push_count()
    assert n >= 1
    second = evaluate_site(site, now=NOW)
    assert second is not None
    assert second.pk == first.pk
    assert second.state == Finding.State.OPEN
    assert _push_count() == n
    assert Finding.objects.filter(fingerprint=_fp(site)).count() == 1


def test_streak_break_resolves_open_proposal():
    """A cold newest minute after an OPEN proposal system-resolves it.

    What would make this fail: leaving OPEN forever once filed, with no close
    path when pressure is no longer sustained.
    """
    from core.models import AuditEvent
    from scaling.evaluator import evaluate_site

    site = _ready_site("streak-break")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = _overflow_after_cheap(site)
    assert row is not None
    later = NOW + timedelta(minutes=1)
    _plant(site.primary_target, [later], ram=10.0)
    assert evaluate_site(site, now=later) is None
    row.refresh_from_db()
    assert row.state == Finding.State.RESOLVED
    assert AuditEvent.objects.filter(
        action="finding_resolved",
        source="system",
        object_id=str(row.pk),
    ).exists()


def test_pressure_py_has_no_django_import():
    """sustained_pressure is a pure function: scaling/pressure.py has no Django.

    What would make this fail: importing django so a capacity decision pulls
    the ORM into the streak math.
    """
    path = REPO / "scaling" / "pressure.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        modules = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.append(node.module)
        assert all(m.split(".")[0] != "django" for m in modules), modules


def test_evaluate_site_source_calls_refuse_if_attack():
    """evaluate_site must call refuse_if_attack first, not only on the file path.

    What would make this fail: gating attack after raise_alert, or catching a
    boolean instead of the named refuse.
    """
    func = _evaluate_site_fn()
    assert func is not None
    stmts = _unwrap(func.body)
    assert stmts, "evaluate_site has no body"
    first = stmts[0]
    if isinstance(first, ast.Try):
        inner = _unwrap(first.body)[0]
    else:
        inner = first
    call = None
    if isinstance(inner, ast.Expr) and isinstance(inner.value, ast.Call):
        call = inner.value
    elif isinstance(inner, ast.Assign) and isinstance(inner.value, ast.Call):
        call = inner.value
    assert call is not None
    assert _call_name(call) == "refuse_if_attack"


def test_evaluate_scale_proposals_beat_is_60s_on_probes():
    """Beat key evaluate-scale-proposals → monitor.tasks, 60s, queue probes.

    What would make this fail: a scaling.tasks entry (control queue), a
    schedule other than 60s, or folding evaluate into collect_all.
    """
    from monitor import tasks as monitor_tasks

    beat = settings.CELERY_BEAT_SCHEDULE
    assert "evaluate-scale-proposals" in beat
    entry = beat["evaluate-scale-proposals"]
    assert entry["task"] == "monitor.tasks.evaluate_scale_proposals"
    assert entry["task"] == monitor_tasks.evaluate_scale_proposals.name
    assert float(entry["schedule"]) == 60.0
    assert not entry["task"].startswith("scaling.")
    assert "scaling.tasks" not in entry["task"]
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "probes"
    assert settings.CELERY_TASK_ROUTES["scaling.*"]["queue"] == "control"
    assert not (REPO / "scaling" / "tasks.py").exists()
    assert beat["evaluate-scale-proposals"]["task"] != beat["collect-all-targets"]["task"]


def test_evaluate_scale_proposals_does_not_write_checkrun():
    """No CheckRun read or write on the evaluator Beat path.

    What would make this fail: a per-tick CheckRun flood from
    evaluate_scale_proposals / evaluate_all / evaluate_site.
    """
    from core.models import CheckRun
    from monitor.tasks import evaluate_scale_proposals

    tasks_src = (REPO / "monitor" / "tasks.py").read_text(encoding="utf-8")
    task_fn = next(
        node
        for node in ast.parse(tasks_src).body
        if isinstance(node, ast.FunctionDef)
        and node.name == "evaluate_scale_proposals"
    )
    scoped = [task_fn]
    for path in (
        REPO / "scaling" / "evaluator.py",
        REPO / "scaling" / "pressure.py",
        REPO / "scaling" / "constants.py",
        REPO / "scaling" / "destination.py",
    ):
        scoped.append(ast.parse(path.read_text(encoding="utf-8")))
    for tree in scoped:
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "CheckRun":
                pytest.fail("evaluator path names CheckRun")
            if isinstance(node, ast.Attribute) and node.attr == "CheckRun":
                pytest.fail("evaluator path attributes CheckRun")
    before = CheckRun.objects.count()
    evaluate_scale_proposals()
    assert CheckRun.objects.count() == before
    src = ast.get_source_segment(tasks_src, task_fn)
    assert src is not None
    assert "evaluate_all()" in src
