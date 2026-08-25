# Phase 6.11 tasks — Daily Beat for `reap_stale_ephemerals` (flag only)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Beat `ephemeral-overflow-reaper-daily` (86400 s, queue `probes`) calls `reap_stale_ephemerals`; it flags 24h leftovers and does not terminate; `evaluate_site` still never terminates.

**Architecture:** Thin `monitor/tasks.py::reap_stale_overflow_ephemerals` lazy-imports the 6.10 body and returns JSON `{ok, n}`. One `CELERY_BEAT_SCHEDULE` entry. AST splits so `scaling/` + `host_metrics.py` cannot name the reaper and the Beat wrapper can.

**Tech Stack:** Django, Celery Beat, pytest T1 planted `AuditEvent` timestamps.

**Spec:** `docs/phase-6.11-design-note.md` **r2**. §7 is binding. Do not invent a path/env/fingerprint/action/gate that §7 does not name.

**Branch:** work in place. Do not push. Do not merge without the panel.

## Global Constraints

- Secrets through the vault. No AWS keys in Finding, AuditEvent.detail, task kwargs, or the wrapper return.
- **Do not invent** `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.
- **`0014` is closed.** No `Target.created_at`. No new `CheckRun.Kind`. No overflow FK.
- `evaluate_site` never terminates and never calls the reaper. `evaluate_scale_proposals` stays `evaluate_all()` only.
- Do not add `scale.approve`. No new ACTION_TIERS. No new HTTP.
- Do not change `reap_stale_ephemerals` flag rules, title, `fix_action`, or fingerprint.
- Reviewer never writes the code they review (D-014).
- New MUST id phase 6, tier-less. Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. Do not waive U1.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` except Task 0.
- Copy never says “instance” except `single-instance` / `single-instance-only` / existing `instance.create` / `instance.terminate` ids.
- Markers: function-level `@pytest.mark.req` on `def test_*` only. Do not mark `P6-SCALER-DEMO`. Do not mark 6.10 callable-body tests with the new id.
- TDD: failing test first. Long why HEREDOC. No amend.
- Do not edit `evaluate_all` / `CYCLE_LOCK*` / `scaling/evaluator.py` product. Do not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`. Do not fold the 6.8 leftover. Do not conflate with `drill-reaper-weekly`.
- Do not claim `monitor/tasks.py` or `hub/settings/base.py` in `paths.yaml`.

Protective cut (**D-116**): MUST = Tasks 0–2.

## Parallel waves

| Shared file | Order |
|---|---|
| registry / DECISIONS / PHASE_6_MUST_IDS | Task 0 |
| `monitor/tasks.py` wrapper + `hub/settings/base.py` Beat + AST split + Beat tests | Task 1 after 0 |
| acceptance + demo | Task 2 after 1 |

---

### Task 0: Registry + custody (D-116…D-118)

**Files:** `DECISIONS.md`, `conformance/requirements.yaml`, `tests/test_conformance_gate.py`

**Interfaces:**
- Consumes: 6.10 ids already in `PHASE_6_MUST_IDS`
- Produces: `SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT` at phase 6, `verify: test`, no `tier:`; `allowed_sources` includes `phase-6.11-design-note.md §3`; D-116…D-118 rows

- [ ] **Step 1: Write the failing test** — `PHASE_6_MUST_IDS` += `SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT`; `allowed_sources` += `phase-6.11-design-note.md §3`. Do not rewrite `SCALE-OVERFLOW-EPHEMERAL-REAPER` or any 6.6–6.10 overflow `text:`. Do not re-claim `monitor/overflow_reaper.py`. Do not claim `monitor/tasks.py`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_conformance_gate.py::test_phase_6_due_set_includes_all_section_3_must_ids -q`
Expected: FAIL — new id missing from the registry and/or source not in `allowed_sources`.

- [ ] **Step 3: Write minimal implementation**

Copy D-116…D-118 into `DECISIONS.md` (verbatim from design-note §5).

Add to `conformance/requirements.yaml` after the 6.10 block:

```yaml
  # Phase 6.11 (docs/phase-6.11-design-note.md §3, Task 0 / D-116…D-118).
  # New MUST id is tier-less (no `tier:` key). Do not rewrite
  # SCALE-OVERFLOW-EPHEMERAL-REAPER text:. Everyday conformance stays phase 5.
  - id: SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT
    phase: 6
    verify: test
    source: phase-6.11-design-note.md §3
    text_hash: sha256:COMPUTE_VIA_PRINT_TEXT_HASHES
    text: >
      Beat ephemeral-overflow-reaper-daily (86400s, queue probes) calls reap_stale_ephemerals; it does not terminate; evaluate_site still never terminates; tests assert the Beat entry and call the task with planted AuditEvent timestamps.
```

Pin `text_hash` with:

```bash
python conformance/check.py --print-text-hashes
```

Use the hash that command prints for this id. Do not invent one.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_conformance_gate.py::test_phase_6_due_set_includes_all_section_3_must_ids tests/test_d023_actions_not_required.py tests/test_proc_rules.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add DECISIONS.md conformance/requirements.yaml tests/test_conformance_gate.py docs/phase-6.11-design-note.md docs/plan/phase-6.11-tasks.md
git commit -m "$(cat <<'EOF'
A 24h ephemeral leftover is only flagged when a test calls the reaper, so a running Hub still forgets billing.

§9.5.5's daily job was the named 6.10 slip (D-113). Registry id SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT owns the Beat entry; the 6.10 body id stays the callable. D-116…D-118.
EOF
)"
```

No amend.

---

### Task 1: Beat wrapper + schedule + AST split

**Files:**
- Modify: `monitor/tasks.py` (append wrapper only; do not change `evaluate_scale_proposals`)
- Modify: `hub/settings/base.py` (`CELERY_BEAT_SCHEDULE` one entry)
- Modify: `tests/test_scale_evaluator.py` (`BANNED_IMPORTS` drops `reap_stale_ephemerals`; add `BANNED_REAPER_CALLERS` + evaluator-only scan paths)
- Modify: `tests/test_overflow_scale_in.py` (C6 tests; update `test_evaluate_site_still_does_not_terminate`)
- Do not edit: `monitor/overflow_reaper.py` product, `deploys/overflow.py`, `scaling/evaluator.py`, `Findings.jsx`, `Chrome.jsx`, `simulation/seed_v1.json`

**Interfaces:**
- Consumes: `monitor.overflow_reaper.reap_stale_ephemerals(*, now=None) -> list[Finding]`
- Produces: `monitor.tasks.reap_stale_overflow_ephemerals(*, now=None) -> dict` with keys `ok` (True) and `n` (int); Beat key `ephemeral-overflow-reaper-daily`

Reuse `_ready_scale` / `_birth` / `_ephemeral_ready` from `tests/test_overflow_scale_in.py`.

- [ ] **Step 1: Write the failing tests** in `tests/test_overflow_scale_in.py`

```python
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
    assert settings.CELERY_TASK_ROUTES["monitor.*"]["queue"] == "probes"
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
    import pathlib

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
```

Update `test_evaluate_site_still_does_not_terminate`: drop `assert "reap_stale_ephemerals" in BANNED_IMPORTS`. Assert `"reap_stale_ephemerals" in BANNED_REAPER_CALLERS` and `_ast_hits(EVALUATOR_REAPER_AST_PATHS, BANNED_REAPER_CALLERS) == []`. Keep `"scale_in_overflow" in BANNED_IMPORTS` and `"terminate_aws_target" in BANNED_IMPORTS`.

In `tests/test_scale_evaluator.py`:

```python
BANNED_IMPORTS = (
    "aws_enroll",
    "ec2",
    "enroll_aws_target",
    "enroll_overflow_target",
    "overflow",
    "deploy_overflow_copy",
    "join_overflow_traffic",
    "scale_in_overflow",
    # reap_stale_ephemerals lives in BANNED_REAPER_CALLERS (6.11): the Beat
    # wrapper in monitor/tasks.py must name it; evaluator still must not.
    "terminate_aws_target",
    "InstanceCreateView",
    "boto3",
    "CloudProvider",
    "EdgeProtection",
    "purge_cache",
    "set_security_level",
)
BANNED_REAPER_CALLERS = ("reap_stale_ephemerals",)
AST_PATHS = (
    REPO / "scaling",
    REPO / "monitor" / "tasks.py",
    REPO / "monitor" / "host_metrics.py",
    REPO / "monitor" / "overflow_reaper.py",
)
EVALUATOR_REAPER_AST_PATHS = (
    REPO / "scaling",
    REPO / "monitor" / "host_metrics.py",
)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_overflow_scale_in.py::test_beat_entry_runs_reaper_daily_on_queue_probes tests/test_overflow_scale_in.py::test_beat_task_flags_and_does_not_terminate tests/test_overflow_scale_in.py::test_evaluate_scale_proposals_does_not_call_reaper -q`
Expected: FAIL — missing Beat key / missing wrapper / `BANNED_REAPER_CALLERS` not defined.

- [ ] **Step 3: Write minimal implementation**

`monitor/tasks.py` — append after `evaluate_scale_proposals`:

```python
@shared_task(ignore_result=True)
def reap_stale_overflow_ephemerals(*, now=None):
    """Beat `ephemeral-overflow-reaper-daily`. Flag only; never terminate."""
    from monitor.overflow_reaper import reap_stale_ephemerals as body

    rows = body(now=now)
    return {"ok": True, "n": len(rows)}
```

`hub/settings/base.py` — in `CELERY_BEAT_SCHEDULE`, after `aws-iam-scope-daily`:

```python
    "ephemeral-overflow-reaper-daily": {
        "task": "monitor.tasks.reap_stale_overflow_ephemerals",
        "schedule": 86400.0,
    },
```

Do not change `reap_stale_ephemerals` in `monitor/overflow_reaper.py`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_overflow_scale_in.py tests/test_scale_evaluator.py tests/test_overflow_join.py tests/test_overflow_deploy.py tests/test_drills.py::test_beat_schedule_lists_three_drills tests/test_cf_token_audit.py::test_beat_entry_runs_the_audit_daily_on_queue_probes -q`
Expected: PASS. 6.10 reaper body tests stay green. Weekly drill Beat still present. Daily CF audit still present.

- [ ] **Step 5: Commit**

```bash
git add monitor/tasks.py hub/settings/base.py tests/test_scale_evaluator.py tests/test_overflow_scale_in.py
git commit -m "$(cat <<'EOF'
A running Hub never invoked reap_stale_ephemerals, so a 24h ephemeral leftover stayed unflagged.

Daily Beat ephemeral-overflow-reaper-daily (86400s, probes) calls the 6.10 flag-only body and returns JSON {ok, n}. It does not terminate. Evaluator AST still cannot name the reaper.
EOF
)"
```

No amend.

---

### Task 2: Acceptance + demo append

**Files:** `tests/acceptance/test_phase_6.py`, `conformance/demos/phase-6.md`

**Interfaces:**
- Consumes: Task 1 named tests
- Produces: NAMED `test_ephemeral_reaper_runs_on_daily_beat`; demo section for 6.11

- [ ] **Step 1: Write the failing NAMED test**

Append `"test_ephemeral_reaper_runs_on_daily_beat"` to `NAMED`. Add:

```python
@pytest.mark.django_db
@pytest.mark.req("SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT")
def test_ephemeral_reaper_runs_on_daily_beat():
    """Daily Beat ephemeral-overflow-reaper-daily names the wrapper,
    86400s, queue probes, no kwargs. Task flags a 25h leftover;
    target stays READY; no CheckRun. Honest: no live AWS VM, no
    auto-terminate, no 30s health-pull, no auto, no AMI, no real
    drain window.

    Transcribes tests/test_overflow_scale_in.py::
    test_beat_entry_runs_reaper_daily_on_queue_probes and
    ::test_beat_task_flags_and_does_not_terminate.
    """
    from test_overflow_scale_in import (
        test_beat_entry_runs_reaper_daily_on_queue_probes,
        test_beat_task_flags_and_does_not_terminate,
    )

    test_beat_entry_runs_reaper_daily_on_queue_probes()
    test_beat_task_flags_and_does_not_terminate()
```

Keep `test_overflow_scale_in_unjoins_terminates_and_reaper_flags`. Do not rewrite its docstring to claim Beat (it transcribes 6.10). Do not mark `P6-SCALER-DEMO`.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/acceptance/test_phase_6.py::test_demo_does_not_claim_live_provision_or_auto_or_ami tests/acceptance/test_phase_6.py::test_ephemeral_reaper_runs_on_daily_beat -q`
Expected: FAIL on demo nodeid / 6.11 section missing (NAMED body may already pass if Task 1 is in).

- [ ] **Step 3: Append the demo**

Append a `### Daily ephemeral reaper Beat (§4, Phase 6.11)` section to `conformance/demos/phase-6.md`:

Beat `ephemeral-overflow-reaper-daily` names
`monitor.tasks.reap_stale_overflow_ephemerals`, schedule 86400.0,
queue `probes`, no kwargs. Calling the task with an ephemeral READY
aws_ec2, birth 25h ago, not primary → Finding
`ephemeral-overflow-orphan:{pk}`; target still READY (not terminated);
no CheckRun. (`test_ephemeral_reaper_runs_on_daily_beat` calls the
Task 1 proofs; it does not reimplement them.) Honest: no live AWS VM,
no auto-terminate, no 30s health-pull, no auto, no AMI, no real drain
window. Forgotten billing is designed out as a daily flag, not as a
kill. NAV six. F8 overflow seed stays the no-idle `0.0416` /
`t3.medium` case. No Approve or Launch. Ack does not stop billing.

Leave the 6.10 section's "no Beat reaper" sentence — that is the 6.10
record. Do **not** rewrite the outstanding bullet "a Beat reaper that
auto-terminates" — auto-terminate is still OUT.

If the NAMED-in-demo assertion requires the new nodeid in the demo
file, name `test_ephemeral_reaper_runs_on_daily_beat` there.

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/acceptance/test_phase_6.py tests/test_overflow_scale_in.py -q`
Then: `python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3`
Expected: new id verified; U1 uncovered-only allowed.

- [ ] **Step 5: Commit**

```bash
git add tests/acceptance/test_phase_6.py conformance/demos/phase-6.md
git commit -m "$(cat <<'EOF'
§4 daily Beat reaper had no acceptance nodeid or demo sentence, so NAMED still described only the callable flag.

test_ephemeral_reaper_runs_on_daily_beat calls the Task 1 Beat proofs. Honest: flag only, no auto-terminate, no live AWS.
EOF
)"
```

No amend.
