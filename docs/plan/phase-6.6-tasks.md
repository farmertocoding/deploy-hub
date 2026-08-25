# Phase 6.6 tasks — Idle registered machine before t3.medium (T1 propose-only)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Overflow Finding body names an idle registered machine at `0` / `own-machine` when one has current headroom; otherwise keeps `0.0416` / `t3.medium`; propose-mode never creates a Target.

**Architecture:** Pure `has_headroom(sample)` in `scaling/pressure.py`; Django SELECT-only `pick_overflow_home(site, *, now)` in `scaling/destination.py` (calls `has_headroom`; never inlines 85); overflow **file** path in `_evaluate_eligible` interpolates the returned tokens. Cheap path unchanged. Beat / CYCLE_LOCK unchanged.

**Tech Stack:** Django, pytest T1 fakes, existing Findings/pager.

**Spec:** `docs/phase-6.6-design-note.md` **r2** (panel §7 is binding). Design panel: do not start implementation until the design panel records MERGE on r2. Do not start a task whose dependencies are open. Do not invent a path, env, Finding fingerprint, action id, CheckRun key, threshold, or gate shape that the design note does not name.

**Branch:** work in place on this workspace (goal harness grades HEAD). Sensitive-path merges to `master` go through the recorded expert-panel vote. Do not push. Do not merge without the panel.

## Global Constraints

- Secrets through the vault. No AWS/DNS/edge token in a Finding, CheckRun, log, task arg, or `AuditEvent.detail`. Cost is `0` (idle) or the public constant `0.0416` / `t3.medium`. Never copy `collect_payload` or raw metrics dumps into Finding/AuditEvent.detail. From a Target row interpolate **only** `host`.
- **Do not invent** `HUB_TEST_CF_TOKEN` / `HUB_TEST_AWS_TOKEN` / `HUB_TEST_PARTNER_TOKEN` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`.
- **`0014` is closed.** No Hub migration. No `ScalePolicy`. No `Site.tier`. No CheckRun.Kind. No new `OperationLock.Kind`. No Finding destination FK.
- Fingerprints unchanged: `scale-cheap-remediation:{site.pk}` then `scale-out-proposal:{site.pk}`.
- `evaluate_site` **must call** `refuse_if_attack(site)` **first**. Catch `AttackRefuse` and `PartnerOverflowRefuse`. Do not reimplement. Do not mock those functions. Do not mock `sustained_pressure`, `evaluate_site`, `has_headroom`, or `pick_overflow_home`.
- Propose-mode **never** provisions. AST-scan `scaling/` **and** `monitor/tasks.py` **and** `monitor/host_metrics.py`. Do not add `scale.approve`. Do not add `scaling.tasks`. Pick is SELECT-only. Do not catch `Exception` in `destination.py` to return miss tokens.
- Reviewer never writes the code they review (D-014).
- Tiers: T1 = fakes. **New Phase 6.6 MUST ids are tier-less.** No `t4`.
- **Gates:** `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. `conformance-6` is `--phase 6 --exclude-tier t2 --exclude-tier t3` and is **not** a `review-round` or `nightly-gates` prereq. Do not waive U1 / PART-K / `failed` / `not-collected`. Do not stub `named-partner.md`.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` in the round they judge except Task 0.
- Copy never says “instance” except `single-instance` and `single-instance-only`. NAV stays six.
- **Markers:** function-level `@pytest.mark.req("<id>")` on `def test_*` only. **No MUST id on a test that does not prove that id’s text.** Schema/persist tests stay unmarked. Do not `@pytest.mark.req("P6-SCALER-DEMO")`. Do not mark idle tests `UX-P6-SINGLE-INSTANCE`. Frontend npm tests do not green registry ids.
- TDD: failing test first. Long "why" HEREDOC commits; no amend.
- Capacity / headroom decision stays separate from I/O. Pick **calls** `has_headroom`.
- Do not edit `evaluate_all` / `_acquire_cycle_lock` / `CYCLE_LOCK*` / `monitor/tasks.py` / `hub/settings/base.py`. Do not import `core.partner_jobs` or `monitor.topology` into `scaling/`.
- Do **not** change assertions on `test_five_hot_mem_minutes_file_proposal_with_cost`, `test_accepted_cheap_unblocks_overflow`, or `test_five_hot_load_minutes_file_proposal`.

Protective cut (**D-101**): MUST = Tasks 0–2.

## Parallel waves

| Shared file | Order |
|---|---|
| registry / DECISIONS / paths / CODEOWNERS / PHASE_6_MUST_IDS | Task 0 |
| `scaling/constants.py` / `scaling/pressure.py` / `scaling/destination.py` / `scaling/evaluator.py` | Task 1 after 0 |
| acceptance + demo | Task 2 after 1 |

---

### Task 0: Registry + custody for idle-first (D-101…D-103)

**Files:** `DECISIONS.md`, `conformance/requirements.yaml`, `conformance/paths.yaml`, `.github/CODEOWNERS`, `tests/test_conformance_gate.py` (`PHASE_6_MUST_IDS` / `allowed_sources`)

**Do not** create a new demo file. Append is Task 2.

- [ ] **Step 1: Write the failing tests**

In `tests/test_conformance_gate.py` (extend the existing due-set test, do not add a weaker d023 duplicate):

```python
PHASE_6_MUST_IDS = {
    # existing eight + cheap two, plus:
    "SCALE-OVERFLOW-IDLE-FIRST",
}
allowed_sources = {
    "phase-6-design-note.md §3",
    "phase-6.5-design-note.md §3",
    "phase-6.6-design-note.md §3",
}

def test_scale_sustained_propose_text_names_idle_and_t3():
    text = _live_registry()["SCALE-SUSTAINED-PROPOSE"]["text"]
    for token in ("idle registered machine", "own-machine", "0.0416", "t3.medium"):
        assert token in text
```

Also assert `scaling/destination.py` is in `conformance/paths.yaml` and `.github/CODEOWNERS`. Those custody asserts stay **unmarked**. Keep existing d023 / nightly assertions. Do not regress `VALID_TIERS`.

- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — copy D-101…D-103 from design note §5. Rewrite `SCALE-SUSTAINED-PROPOSE` `text:` per §3 (idle **and** t3.medium); add `SCALE-OVERFLOW-IDLE-FIRST` `phase: 6`, `verify: test`, no `tier:` key, `source: phase-6.6-design-note.md §3`; compute `text_hash:`. Claim `scaling/destination.py` in **both** paths.yaml and CODEOWNERS. No MUST waiver. Everyday `conformance` stays phase 5.
- [ ] **Step 4: PASS** `pytest tests/test_conformance_gate.py::test_phase_6_due_set_includes_all_section_3_must_ids tests/test_conformance_gate.py::test_scale_sustained_propose_text_names_idle_and_t3 tests/test_d023_actions_not_required.py tests/test_proc_rules.py -q`
- [ ] **Step 5: Commit** with a long "why" HEREDOC. No amend.

---

### Task 1: `has_headroom` + `pick_overflow_home` + overflow body

**Files:** `scaling/constants.py`, `scaling/pressure.py`, `scaling/destination.py` (create), `scaling/evaluator.py` (overflow file path only — do not touch `evaluate_all` / `_acquire_cycle_lock` / `CYCLE_LOCK*`), `tests/test_overflow_destination.py` (create), `tests/test_scale_evaluator.py` (extend CheckRun AST paths only; **do not rewrite** the three named no-second-target tests)

Plant real `HostMetric` rows and real `Target` rows. `scale_ready=True`, `primary_target` set, `exposure=public`, not PartnerSite, unless the test is about that variable. Second Target: same zone (fixture only, not a pick rule), `status=ready`, `lifecycle=permanent`, a distinct `host`. Reuse `_world` / `_ready_site` / `_overflow_after_cheap` / `_plant` from `tests/test_scale_evaluator.py`.

Idle body helper (use in every idle-hit assertion):

```python
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
```

- [ ] **Step 1: Failing tests** in `tests/test_overflow_destination.py`

```python
from django.test import override_settings
from scaling.pressure import has_headroom
from scaling.destination import pick_overflow_home


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
    # MUST use _overflow_after_cheap
    # second READY permanent non-hub ram=10 at now
    # _assert_idle_copy; Target.objects.count() unchanged


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_hot_second_machine_falls_back_to_t3():
    # ram=90 OR load>cores at now → 0.0416 / t3.medium; host not in body


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_stale_second_machine_is_not_idle():
    # latest sample now-121s → t3.medium


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_missing_metrics_is_not_idle():
    # second READY permanent, no HostMetric row → t3.medium


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_pending_error_decommissioned_never_picked():
    # three extra targets with ram=10 at now, statuses pending/error/decommissioned
    # → t3.medium (no leftover idle)


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_ephemeral_never_picked():
    # ephemeral READY ram=10 skipped; leftover third READY permanent picked


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_partner_destination_only_falls_back_to_t3():
    # NO PartnerSite on the overflow site
    # the only non-primary READY permanent headroom Target is in partner.destination_order
    # → 0.0416 / t3.medium; that host NOT in body; count unchanged


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_partner_destination_skipped_picks_leftover():
    # partner dest + leftover third READY permanent; body names leftover.host;
    # does not name partner dest host or ephemeral host


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_primary_target_with_headroom_is_not_picked():
    # call pick_overflow_home(site, now=NOW) with a COLD primary plus a second idle
    # returned host is not site.primary_target.host


@override_settings(HUB_PUBLIC_URL="https://hub.example.test")
@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
def test_hub_host_is_not_picked():
    # READY permanent non-primary non-partner host="hub.example.test" ram=10 at now
    # → 0.0416 / t3.medium; that host not in body
    # when a second non-hub idle exists, pick that host, not the Hub


@pytest.mark.req("SCALE-OVERFLOW-IDLE-FIRST")
@pytest.mark.req("SCALE-PROPOSE-NO-PROVISION")
def test_idle_pick_does_not_create_a_target():
    # idle path: count unchanged; destination.py has no except Exception returning OVERFLOW_*
    # AST still clean
```

Also append `scaling/destination.py` to the CheckRun AST paths in `test_evaluate_scale_proposals_does_not_write_checkrun` (keep that test's markers as-is).

- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — constants from §2; `has_headroom` as C6; `pick_overflow_home` as C5/C5b (SELECT-only, calls `has_headroom`, Hub helper local); overflow file interpolates C7; cheap path does not call pick. No schema. No HTTP. No Beat. No `evaluate_all` edit.
- [ ] **Step 4: PASS** `pytest tests/test_overflow_destination.py tests/test_scale_evaluator.py tests/test_scale_ready_scan.py tests/acceptance/test_phase_6.py -q`
- [ ] **Step 5: Commit** with a long "why" HEREDOC. No amend.

---

### Task 2: Acceptance + demo append

**Files:** `tests/acceptance/test_phase_6.py`, `conformance/demos/phase-6.md`

- [ ] **Step 1: Write** `test_idle_registered_machine_named_when_second_target_has_headroom` in `tests/acceptance/test_phase_6.py`. Append that name to `NAMED`. Docstring transcribes §4 (b). Body imports and **calls** `tests.test_overflow_destination.test_idle_ready_machine_named_in_overflow_body` (do not reimplement). Mark `SCALE-OVERFLOW-IDLE-FIRST` and `SCALE-SUSTAINED-PROPOSE`. Also run `_assert_idle_copy` semantics (propose-mode / no instance / no Approve / no Launch) via that call. Keep `test_scale_ready_quiet_five_hot_mem_files_p2_proposal` as §4 (a) — docstring and calls stay `0.0416` / `t3.medium` with no second Target. Do not mark `P6-SCALER-DEMO`. Do not rewrite F8 seed.

- [ ] **Step 2: RED** (demo sentence / NAMED nodeid missing)
- [ ] **Step 3: Append** `conformance/demos/phase-6.md` with the idle-first clause **and** the new acceptance nodeid. Honest: no VM launched, no ScalePolicy, no DNS join.
- [ ] **Step 4: PASS** acceptance + destination + evaluator. `python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3` — new MUST id verified or skipped-only; no failed / not-collected. U1/PART-K untouched. Uncovered U1 only is allowed (D-081).
- [ ] **Step 5: Commit** with a long "why" HEREDOC. No amend.
