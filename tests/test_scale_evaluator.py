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
    "InstanceCreateView",
    "boto3",
    "CloudProvider",
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


@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_five_hot_mem_minutes_file_proposal_with_cost():
    """Five distinct UTC minutes of ram=90 file a costed propose-mode Finding.

    What would make this fail: last-N without a window, entity keyed on pk,
    missing 0.0416 / t3.medium / propose-mode does not launch, or creating a
    Target as if propose-mode launched.
    """
    from scaling.constants import FIX_ACTION as PINNED_FIX
    from scaling.constants import TITLE as PINNED_TITLE
    from scaling.evaluator import evaluate_site

    site = _ready_site("hot-mem")
    before = Target.objects.count()
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = evaluate_site(site, now=NOW)
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
    from scaling.evaluator import evaluate_site

    site = _ready_site("hot-load")
    _plant(site.primary_target, _minutes(), ram=10.0, disk=10.0, load=5.0, cores=4)
    row = evaluate_site(site, now=NOW)
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
    from scaling.evaluator import evaluate_site
    from test_attack_playbook import _attack_shaped

    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection

    site = _ready_site("atk-engage")
    _plant(site.primary_target, _minutes(), ram=90.0)
    _attack_shaped(site)
    run(site, FakeEdgeProtection())
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


@pytest.mark.req("SCALE-NEVER-ATTACK")
def test_open_proposal_resolves_when_attack_engages():
    """File while quiet, engage the playbook, evaluate_site again → resolved.

    What would make this fail: leaving an OPEN proposal in place after
    AttackRefuse, or filing a consolation Finding.
    """
    from scaling.evaluator import evaluate_site
    from test_attack_playbook import _attack_shaped

    from core.models import AuditEvent
    from monitor.attack_playbook import run
    from providers.fakes import FakeEdgeProtection

    site = _ready_site("atk-retract")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = evaluate_site(site, now=NOW)
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


@pytest.mark.req("SCALE-NEVER-PARTNER")
def test_partner_site_does_not_propose():
    """PartnerSite + quiet playbook + five hot mem must not file.

    What would make this fail: only gating on the attack playbook so partner
    overflow still proposes.
    """
    from scaling.evaluator import evaluate_site

    from core.models import Partner, PartnerSite
    from scaling.attack_gate import refuse_if_attack

    control = _ready_site("part-ctl")
    assert refuse_if_attack(control) is None
    site = _ready_site("part-hot")
    _plant(site.primary_target, _minutes(), ram=90.0)
    partner = Partner.objects.create(slug="part-hot-p", name="part-hot-p")
    PartnerSite.objects.create(partner=partner, site=site, tenant_ref="part-hot-t")
    assert evaluate_site(site, now=NOW) is None
    assert _proposal(site) is None


@pytest.mark.req("SCALE-NEVER-PARTNER")
def test_partner_bind_after_file_resolves_open_proposal():
    """Binding PartnerSite after file system-resolves the OPEN proposal.

    What would make this fail: leaving the proposal OPEN after partner bind,
    or requiring the attack playbook to retract.
    """
    from scaling.evaluator import evaluate_site

    from core.models import AuditEvent, Partner, PartnerSite
    from scaling.attack_gate import refuse_if_attack

    control = _ready_site("bind-ctl")
    assert refuse_if_attack(control) is None
    site = _ready_site("bind-hot")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = evaluate_site(site, now=NOW)
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


@pytest.mark.req("SCALE-PROPOSE-NO-PROVISION")
def test_scaling_and_beat_do_not_import_enroll_or_ec2():
    """AST-scan scaling/ + monitor/tasks.py + monitor/host_metrics.py.

    What would make this fail: importing provision.aws_enroll, providers.ec2,
    enroll_aws_target, InstanceCreateView, boto3, or CloudProvider, or adding
    scaling/tasks.py (scaling.* routes to control).
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
    from scaling.evaluator import evaluate_site
    from test_attack_playbook import _world

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
    from scaling.evaluator import evaluate_site

    from core.models import Site

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
    first = evaluate_site(site, now=NOW)
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
    from scaling.evaluator import evaluate_site

    from core.models import AuditEvent

    site = _ready_site("streak-break")
    _plant(site.primary_target, _minutes(), ram=90.0)
    row = evaluate_site(site, now=NOW)
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

    for path in (
        REPO / "monitor" / "tasks.py",
        REPO / "scaling" / "evaluator.py",
        REPO / "scaling" / "pressure.py",
        REPO / "scaling" / "constants.py",
    ):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "CheckRun":
                pytest.fail(f"{path.relative_to(REPO)} names CheckRun")
            if isinstance(node, ast.Attribute) and node.attr == "CheckRun":
                pytest.fail(f"{path.relative_to(REPO)} attributes CheckRun")
    before = CheckRun.objects.count()
    evaluate_scale_proposals()
    assert CheckRun.objects.count() == before
    src = ast.get_source_segment(
        (REPO / "monitor" / "tasks.py").read_text(encoding="utf-8"),
        next(
            node
            for node in ast.parse(
                (REPO / "monitor" / "tasks.py").read_text(encoding="utf-8")
            ).body
            if isinstance(node, ast.FunctionDef)
            and node.name == "evaluate_scale_proposals"
        ),
    )
    assert src is not None
    assert "evaluate_all()" in src
