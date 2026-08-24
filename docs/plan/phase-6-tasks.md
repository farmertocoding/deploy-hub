# Phase 6 tasks — Overflow auto-scaling (T1 propose-only)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sustained host pressure files a scale-out proposal with a cost estimate; spikes, gaps, mixed axes, disk-only, attacks, partner overflow, mesh_only, and non-scale-ready sites never propose; propose-mode never provisions.

**Architecture:** HostMetric history from the collector (Hub clock); pure `sustained_pressure(samples, *, now)` separate from I/O; `evaluate_site` calls existing `refuse_if_attack` first then `raise_alert` only to open; scanner `core.scale-ready` + `Site.scale_ready` fail-closed; Sites list-row badge `single-instance-only`.

**Tech Stack:** Django, Celery Beat (`probes`), pytest T1 fakes, existing Findings/pager, React Sites.

**Spec:** `docs/phase-6-design-note.md` **r2** (panel §7 is binding). Design panel r2: Architect/Security/SRE/UX MERGE; QE MERGE-AFTER-FIXES (two named-test nits folded here). Do not start a task whose dependencies are open. Do not start implementation from the design session until the design panel records MERGE on r2. Do not invent a path, env, Finding fingerprint, action id, CheckRun key, threshold, or gate shape that the design note does not name.

**Branch:** cut task branches from `p6-design`. Never implement on `master`. Sensitive-path merges to `master` go through the recorded expert-panel vote.

## Global Constraints

- Secrets through the vault. No AWS/DNS/edge token in a Finding, CheckRun, log, task arg, or `AuditEvent.detail`. Cost is the public constant `0.0416` / `t3.medium`. Never copy `collect_payload` or raw metrics dumps into Finding/AuditEvent.detail.
- **Do not invent** `HUB_TEST_CF_TOKEN` / `HUB_TEST_AWS_TOKEN` / `HUB_TEST_PARTNER_TOKEN` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`.
- **`0013` is closed.** Only Hub migration is Task 1's `0014_phase6.py`. No `ScalePolicy`. No `Site.tier`. No CheckRun.Kind. No new `OperationLock.Kind`.
- Fingerprint **`scale-out-proposal:{site.pk}`** only. Kind already exists in `monitor/alert_rules.py`.
- `evaluate_site` **must call** `refuse_if_attack(site)` **first**. Catch `AttackRefuse` and `PartnerOverflowRefuse`. Do not reimplement. Do not mock those functions.
- Propose-mode **never** provisions. AST-scan `scaling/` **and** `monitor/tasks.py` **and** `monitor/host_metrics.py`. Do not add `scale.approve`. Do not add `scaling.tasks` (`scaling.*` → `control`).
- Reviewer never writes the code they review (D-014).
- Tiers: T1 = fakes. **New Phase 6 MUST ids are tier-less.** No `t4`.
- **Gates:** `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. `conformance-6` is `--phase 6 --exclude-tier t2 --exclude-tier t3` and is **not** a `review-round` or `nightly-gates` prereq. Do not waive U1 / PART-K / `failed` / `not-collected`. Do not stub `named-partner.md` or Task-0 `phase-6.md`.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` in the round they judge except Task 0.
- Copy never says “instance” except `single-instance` and `single-instance-only`. NAV stays six.
- **Markers:** function-level `@pytest.mark.req("<id>")` on `def test_*` only. **No MUST id on a test that does not prove that id’s text.** Schema/persist tests stay unmarked. Do not `@pytest.mark.req("P6-SCALER-DEMO")`. Frontend npm tests do not green registry ids.
- TDD: failing test first. Long "why" HEREDOC commits; no amend.
- Capacity decision stays separate from I/O.

Protective cut (**D-086**): MUST = Tasks 0–6.

## Parallel waves

| Shared file | Order |
|---|---|
| registry / Makefile / DECISIONS / WAIVERS / paths / CODEOWNERS / d023 / nightly makefile test | Task 0 |
| `core/models.py` / `0014_phase6.py` / `monitor/retention.py` | Task 1 after 0 |
| `monitor/collect_once.py` / `monitor/collector.py` / `monitor/host_metrics.py` | Task 2 after 1 |
| `scaling/constants.py` / `scaling/pressure.py` / `scaling/evaluator.py` / `monitor/tasks.py` / Beat | Task 3 after **1+2** |
| `scanner/modules/fallbacks.py` / `FROZEN_CORE_IDS` / `wizard/materialize.py` | Task 4 after **1** |
| `wizard/views.py` / Sites.jsx / simulation-states / seed / generate-client | Task 5 after **1** |
| acceptance + demo | Task 6 after 2–5 |

Independent after Task 1: **Tasks 2, 4, and 5**. Task 3 needs 1+2. Task 4 owns `materialize.py`; Task 5 owns `views.py` + frontend.

---

### Task 0: Unblock `check.py --phase 6` (D-086…D-095)

**Files:** `DECISIONS.md`, `conformance/requirements.yaml`, `Makefile`, `conformance/paths.yaml`, `.github/CODEOWNERS`, `tests/test_d023_actions_not_required.py`, `tests/test_makefile_nightly.py`, `WAIVERS.md` (no new MUST waiver)

**Do not** create `conformance/demos/phase-6.md` in this task.

- [ ] **Step 1: Write the failing tests**

```python
def test_conformance_6_is_phase_6_minus_live_not_a_review_round_prereq():
    ...

def test_conformance_6_is_not_a_nightly_gates_prereq():
    # mirror test_conformance_5_5_is_not_a_review_round_or_nightly_prereq

def test_no_all_tiers_6_target():
    assert "conformance-6-all" not in gates.makefile_targets(REPO)
    recipe = _recipe("conformance-6")
    assert "--exclude-tier t2" in recipe and "--exclude-tier t3" in recipe

def test_phase_6_due_set_includes_all_section_3_must_ids():
    # eight §3 ids at phase: 6, no tier: key; seven verify:test;
    # P6-SCALER-DEMO verify:demo naming conformance/demos/phase-6.md
```

Keep existing d023 assertions. Run `tests/test_mutation_gate.py::test_the_mutated_scope_covers_every_gate_bearing_module` and `test_valid_tiers` if they exist — do not regress `VALID_TIERS`.

- [ ] **Step 2: RED** (no conformance-6)
- [ ] **Step 3: GREEN** — copy D-086…D-095 from design note §5. Add eight §3 ids; compute `text_hash:`. Makefile `conformance-6` + `.PHONY`. Claim `scaling/pressure.py`, `scaling/evaluator.py`, `scaling/constants.py`, `monitor/host_metrics.py` in **both** paths.yaml and CODEOWNERS. No MUST waiver. Everyday `conformance` stays phase 5.
- [ ] **Step 4: PASS** `pytest tests/test_d023_actions_not_required.py tests/test_proc_rules.py tests/test_makefile_nightly.py -q`. Uncovered new ids on `conformance-6` is correct.
- [ ] **Step 5: Commit**

---

### Task 1: HostMetric + Site.scale_ready (`0014_phase6.py`)

**Unmarked** schema/persist-shape tests (they must not carry SCALE-* markers).

- [ ] **Step 1: Failing tests** in `tests/test_host_metric.py` + extend `tests/test_retention.py`

```python
def test_site_scale_ready_defaults_false(): ...
def test_host_metric_stores_ram_disk_load_cores(): ...
@pytest.mark.req("MON-C7-RETENTION")
def test_host_metric_raw_older_than_14d_is_deleted(): ...
```

- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — model as design note §2; `_sweep_host_metric` batched DELETE `ts < now - 14d`. No rollup table. No ScalePolicy. No CheckRun.Kind. No OperationLock.Kind. No data migration.
- [ ] **Step 4: PASS** + `pytest tests/test_retention.py -q`
- [ ] **Step 5: Commit**

---

### Task 2: Persist HostMetric from collector + cores

Unmarked except existing collector reqs if already used.

- [ ] **Step 1: Failing tests** in `tests/test_host_metric_persist.py`

```python
def test_persist_collect_writes_host_metric_from_payload_metrics():
    # ram/cores mapped; ts == Hub `now` kwarg, not payload["ts"]

def test_persist_skips_when_metrics_missing():
    # no row; no invented 0s

def test_persist_coerces_non_finite_and_out_of_range_to_none():
    # mem_pct="hot" / inf / 101 → that axis None (or skip); does not raise

def test_persist_failure_does_not_fail_collect(monkeypatch):
    # persist_sample raises → collect/_persist_collect still returns; collect_payload saved

def test_collect_once_metrics_includes_cores():
    from monitor.collect_once import _metrics
    assert "cores" in _metrics()
```

- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — `persist_sample` as C3/D-094; `_persist_collect(..., *, now=None)` calls it in try/audit **after** Target save; `_metrics` adds cores.
- [ ] **Step 4: PASS** + existing collector tests
- [ ] **Step 5: Commit**

---

### Task 3: Evaluator

**Files:** `scaling/constants.py`, `scaling/pressure.py`, `scaling/evaluator.py`, `monitor/tasks.py`, `hub/settings/base.py` (Beat entry only). Do **not** add `scaling/tasks.py`.

Plant real `HostMetric` rows. `scale_ready=True`, `primary_target` set, `exposure=public`, not PartnerSite, unless the test is about that variable. Do **not** mock `sustained_pressure`, `evaluate_site`, or `refuse_if_attack`. Attack tests: existing `_world` / `_attack_shaped` / `run(site, FakeEdgeProtection())` from `tests/test_attack_playbook.py`. Partner tests: quiet playbook (`refuse_if_attack` on a non-partner control is None).

- [ ] **Step 1: Failing tests** in `tests/test_scale_evaluator.py`

Happy / refuse (markers on the id they prove):

```python
@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_five_hot_mem_minutes_file_proposal_with_cost():
    # 5 distinct minutes, ram=90, disk/load cold
    # fingerprint, TITLE, FIX_ACTION, 0.0416, t3.medium, propose-mode does not launch
    # entity uses domain or name, not pk
    # Target.objects.count() unchanged

@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_five_hot_load_minutes_file_proposal():
    # load=5, cores=4, ram/disk cold

@pytest.mark.req("SCALE-SUSTAINED-PROPOSE")
def test_five_hot_disk_minutes_do_not_propose():
    # disk=90, ram=10, load=0.1, cores=4 → None (disk is not an overflow axis)

@pytest.mark.req("SCALE-SPIKE-NO-PROPOSE")
def test_one_hot_among_five_does_not_propose():
    # four cold ram=10 + newest ram=90

def test_four_of_five_over_one_under_does_not_propose():
    # five distinct in-window minutes, four ram>85 + one under → None
    # unmarked (C11: SCALE-SPIKE-NO-PROPOSE text is 1-of-5 / hole / mixed / stale)
    # Task 6 test_four_of_five_does_not_propose MUST call this proof, not the spike test

@pytest.mark.req("SCALE-SPIKE-NO-PROPOSE")
def test_missing_minute_breaks_streak():
    # 4 hot minutes, a hole > 120s, 1 hot → None

@pytest.mark.req("SCALE-SPIKE-NO-PROPOSE")
def test_mixed_axes_do_not_propose():
    # ram, load, ram, load, ram rotating → None

@pytest.mark.req("SCALE-SPIKE-NO-PROPOSE")
def test_stale_window_does_not_propose():
    # five hot rows older than 6 min → None

@pytest.mark.req("SCALE-NEVER-ATTACK")
def test_attack_engaged_does_not_propose():
    # FakeEdgeProtection + run(); no scale-out-proposal:{pk}

@pytest.mark.req("SCALE-NEVER-ATTACK")
def test_open_proposal_resolves_when_attack_engages():
    # file while quiet, then engage, evaluate_site again → resolved

@pytest.mark.req("SCALE-NEVER-PARTNER")
def test_partner_site_does_not_propose():
    # scale_ready True, primary_target set, quiet playbook, PartnerSite, five hot mem

@pytest.mark.req("SCALE-NEVER-PARTNER")
def test_partner_bind_after_file_resolves_open_proposal():
    ...

@pytest.mark.req("SCALE-PROPOSE-NO-PROVISION")
def test_scaling_and_beat_do_not_import_enroll_or_ec2():
    # AST scaling/ + monitor/tasks.py + monitor/host_metrics.py

@pytest.mark.req("SCALE-READY-PREREQ")
def test_scale_ready_false_five_hot_does_not_propose(): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_mesh_only_five_hot_does_not_propose(): ...
```

Unmarked but required:

```python
def test_cores_none_load_axis_not_over(): ...
def test_cpu_only_does_not_propose(): ...
def test_fewer_than_five_samples_not_sustained(): ...
def test_re_evaluate_while_open_does_not_record_second_push(): ...
def test_streak_break_resolves_open_proposal(): ...
def test_pressure_py_has_no_django_import(): ...
def test_evaluate_site_source_calls_refuse_if_attack(): ...
def test_evaluate_scale_proposals_beat_is_60s_on_probes():
    # key evaluate-scale-proposals; task monitor.tasks.evaluate_scale_proposals
    # schedule 60.0; not under scaling.; CELERY_TASK_ROUTES monitor.* probes
def test_evaluate_scale_proposals_does_not_write_checkrun(): ...
```

- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — constants from §2; `sustained_pressure` as C2; `evaluate_site` as C5–C8; `evaluate_all` per-site isolation; Beat + OperationLock as C7; `raise_alert` only to open.
- [ ] **Step 4: PASS**
- [ ] **Step 5: Commit**

---

### Task 4: `core.scale-ready` + materialize

C13 predicates. Conscious `FROZEN_CORE_IDS` edit (seven → eight always-on ids; `core.symlinked-files` stays conditional). Update seven-id dicts in `tests/test_scanner_django.py` / comments in `tests/test_scanner_core.py`. Reuse `texts`/`paths`. No subprocess. No `core.models` import from scanner.

- [ ] **Step 1: Failing tests** in `tests/test_scale_ready_scan.py`

```python
@pytest.mark.req("SCALE-READY-PREREQ")
def test_sqlite_tree_is_scale_ready_warning_not_blocker(tmp_path): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_clean_tree_is_scale_ready_ok(tmp_path): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_parquet_duckdb_wal_are_warning(tmp_path): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_sqlite_engine_text_is_warning(tmp_path): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_locmem_session_is_warning(tmp_path): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_celery_localhost_broker_is_warning(tmp_path): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_django_media_root_without_object_storage_is_warning(tmp_path): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_absence_of_django_settings_is_not_media_fail(tmp_path): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_materialize_copies_false_on_warning_even_with_confirm_warnings(db): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_materialize_copies_true_on_ok(db): ...

@pytest.mark.req("SCALE-READY-PREREQ")
def test_missing_check_in_report_is_false(db): ...
```

- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — C13; `locked.scale_ready = (check.tier == "ok")`; `update_fields=["scale_ready"]`.
- [ ] **Step 4: PASS** including `tests/test_scanner_core.py`. Update fixture assertions. Re-record `conformance/demos/phase-1/scan-sample-node-site.json` **only if** a test requires byte-identity.
- [ ] **Step 5: Commit**

---

### Task 5: Sites list-row `single-instance-only` + F8

Do **not** alias `single_instance = not scale_ready`. Run `make generate-client` and commit OpenAPI/types/zod. New fields optional.

- [ ] **Step 1: Failing tests**

Pytest (these green UX-P6; `collect_markers` must see them):

```python
@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_project_row_emits_scale_ready_false_without_aliasing_single_instance(auth_client):
    # scale_ready False present; single_instance is not True-because-of-that
    # (omit or false-from-count, never `not scale_ready`)

@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_site_observed_source_paints_single_instance_only_iff_scale_ready_false():
    # grep Sites.jsx: scale_ready === false → single-instance-only
    # SiteObserved used on list rows (SitesView maps it)

@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_f8_required_ids_include_single_instance_only_and_scale_out_proposal():
    # grep REQUIRED_STATE_IDS

@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_nav_stays_six(): ...

@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_scale_out_proposal_markup_has_no_instance_word_or_approve_control():
    # seed/finding copy after stripping allowed tokens; no Approve/Launch ActionButton

@pytest.mark.req("UX-P6-SINGLE-INSTANCE")
def test_f8_single_instance_seed_does_not_retint_to_single_instance_only():
    # grep simulation/seed_v1.json state id=single-instance: still has badge/token
    # single-instance as a full token; doesNotMatch /single-instance-only/
    # do not use prefix includes (substring trap)
```

Frontend `simulation-states.test.ts`: add ids `single-instance-only` and `scale-out-proposal` with renderers; seed + scripted_events; `single-instance` seed `doesNotMatch /single-instance-only/`.

- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — serializer + `project_row_body`; `SiteObserved` on list rows; paint rules C8; F8 seed; `make generate-client`.
- [ ] **Step 4: PASS** pytest + `cd frontend && npm test -- simulation-states`
- [ ] **Step 5: Commit**

---

### Task 6: Acceptance + demo

Pattern: `tests/acceptance/test_phase_4.py`. Module docstring T1 fakes only. `NAMED` tuple. Each `def test_*` transcribes one §4 sentence by **calling** the named proofs (do not reimplement). **Do not** `@pytest.mark.req("P6-SCALER-DEMO")`.

- [ ] **Step 1: Write** `tests/acceptance/test_phase_6.py` with:

```
test_scale_ready_quiet_five_hot_mem_files_p2_proposal
test_four_of_five_does_not_propose
test_one_spike_does_not_propose
test_attack_engaged_does_not_propose
test_partner_site_does_not_propose
test_not_scale_ready_does_not_propose_and_list_paints_single_instance_only
test_nav_stays_six
test_demo_does_not_claim_live_provision_or_auto_or_ami
```

SCALE-* markers only on tests that drive those clauses. Honesty test greps the demo for those nodeids, Fake seams, “no live”, no `HUB_TEST_*`, no Playwright, `conformance-6` minus t2/t3.

- [ ] **Step 2: RED** (demo file missing)
- [ ] **Step 3: Write** `conformance/demos/phase-6.md` describing §4. Honest: no VM launched.
- [ ] **Step 4: PASS** acceptance + evaluator + scale-ready + payload tests. `python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3` — new MUST ids verified or skipped-only; no failed / not-collected. U1/PART-K untouched.
- [ ] **Step 5: Commit**
