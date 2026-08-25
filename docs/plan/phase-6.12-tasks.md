# Phase 6.12 tasks — Overflow seam-refuse releases deploy locks

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** After overflow `begin_deploy` holds site + overflow-target deploy locks, `execute` that raises `DeploySeamRefused` from `_resolve_seams` marks FAILED and releases those locks; `evaluate_site` still never creates a Deployment.

**Architecture:** One-line-plus in `execute`'s existing `except DeploySeamRefused`: `release_deploy_locks(deployment)` after FAILED. QUEUED primary path is a no-op release.

**Tech Stack:** Django, pytest T1, existing overflow deploy helpers.

**Spec:** `docs/phase-6.12-design-note.md` **r1**. §7 is binding. Do not invent a path/env/fingerprint/action/gate that §7 does not name.

**Branch:** work in place. Expert team may commit.

## Global Constraints

- Secrets through the vault. No AWS keys in Finding, AuditEvent.detail, task kwargs.
- **Do not invent** `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.
- **`0014` is closed.** No `Target.created_at`. No new `CheckRun.Kind`. No overflow FK.
- `evaluate_site` never creates a Deployment. Do not add `scale.approve`. No new ACTION_TIERS. No new HTTP.
- Reviewer never writes the code they review (D-014).
- New MUST id phase 6, tier-less. Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. Do not waive U1.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` except Task 0.
- Copy never says “instance” except `single-instance` / `single-instance-only` / existing `instance.create` / `instance.terminate` ids.
- Markers: function-level `@pytest.mark.req` on `def test_*` only. Do not mark `P6-SCALER-DEMO`. Do not mark 6.8–6.11 tests with the new id except the explicit call-through.
- TDD: failing test first. Long why HEREDOC. No amend.
- Do not edit `evaluate_all` / `CYCLE_LOCK*` / `scaling/evaluator.py` product. Do not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`.
- Do not claim `deploys/pipeline.py` in `paths.yaml`. Do not re-claim `deploys/overflow.py`.

Protective cut (**D-119**): MUST = Tasks 0–2.

## Parallel waves

| Shared file | Order |
|---|---|
| registry / DECISIONS / PHASE_6_MUST_IDS | Task 0 |
| `deploys/pipeline.py` execute + overflow deploy tests | Task 1 after 0 |
| acceptance + demo | Task 2 after 1 |

---

### Task 0: Registry + custody (D-119…D-121)

**Files:** `DECISIONS.md`, `conformance/requirements.yaml`, `tests/test_conformance_gate.py`

- [ ] **Step 1: Write the failing test** — `PHASE_6_MUST_IDS` += `SCALE-OVERFLOW-LOCK-ON-SEAM-REFUSE`; `allowed_sources` += `phase-6.12-design-note.md §3`. Do not rewrite 6.6–6.11 overflow `text:`. Do not claim `deploys/pipeline.py`.
- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — copy D-119…D-121. Add the id `phase: 6`, `verify: test`, no `tier:`; `text_hash` via `--print-text-hashes`.
- [ ] **Step 4: PASS** `pytest tests/test_conformance_gate.py::test_phase_6_due_set_includes_all_section_3_must_ids tests/test_d023_actions_not_required.py tests/test_proc_rules.py -q`
- [ ] **Step 5: Commit** long why HEREDOC. No amend.

---

### Task 1: Release locks on overflow seam-refuse

**Files:** `deploys/pipeline.py`; `tests/test_overflow_deploy.py`

- [ ] **Step 1: Failing tests** in `tests/test_overflow_deploy.py` as design-note §7 C5.
- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — `execute` `except DeploySeamRefused`: FAILED, `release_deploy_locks`, re-raise.
- [ ] **Step 4: PASS** overflow deploy + deploy seams + scale evaluator.
- [ ] **Step 5: Commit** long why HEREDOC. No amend.

---

### Task 2: Acceptance + demo append

**Files:** `tests/acceptance/test_phase_6.py`, `conformance/demos/phase-6.md`

- [ ] **Step 1:** NAMED `test_overflow_seam_refuse_releases_deploy_locks` calls the Task 1 lock test. Append the name to `NAMED`.
- [ ] **Step 2: RED**
- [ ] **Step 3: Append** demo section. Honesty: no live AWS, no live Cloudflare, no auto.
- [ ] **Step 4: PASS** acceptance + overflow deploy. `python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3` — new id verified; U1 uncovered-only allowed.
- [ ] **Step 5: Commit** long why HEREDOC. No amend.
