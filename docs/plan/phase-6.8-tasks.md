# Phase 6.8 tasks — Deploy live image onto overflow target (T1 Fake, skip DNS)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `deploy_overflow_copy` pins the last succeeded `image_tag`, skips BUILD and DNS, ships onto the ephemeral overflow Target, does not retarget `primary_target`, creates a SiteInstance; OPEN/ACKED refuse with Ack is not launch.

**Architecture:** `deploys/overflow.py` owns the gate + enqueue. `begin_deploy(..., target=)` locks the overflow Target. `_assemble_desired` pins live tag when BUILD is SKIPPED even if SHIP is pending. T1 POST `/api/v1/sites/{pk}/overflow-deploy/`. Tests inject `PipelineTransport`.

**Spec:** `docs/phase-6.8-design-note.md` **r2**. Do not start implementation until design panel MERGE on r2. Do not invent a path/env/fingerprint/action/gate that §7 does not name.

**Branch:** work in place. Do not push. Do not merge without the panel.

## Global Constraints

- Secrets through the vault. No `collect_payload` / SSH private keys / AWS keys in Finding, AuditEvent.detail, task kwargs, or artifacts.
- **Do not invent** `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.
- **`0014` is closed.** No overflow FK. Do not assign `Site.primary_target`.
- `evaluate_site` never creates a Deployment. `enroll_overflow_target` does not call deploy. AST 6.7 banned list unchanged.
- Do not add `scale.approve`. New ACTION_TIERS id is exactly `site.overflow_deploy` T1.
- Overflow deploy tests inject `PipelineTransport`. Do not live-SSH.
- `refuse_if_attack` first. Do not mock `refuse_if_attack`, `pick_overflow_home`, `evaluate_site`.
- Reviewer never writes the code they review (D-014).
- New MUST ids phase 6, tier-less. Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. Do not waive U1.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` except Task 0.
- Copy never says “instance” except `single-instance` / `single-instance-only` in Finding/UI. ACTION_TIERS label is `Deploy overflow copy`.
- Markers: function-level `@pytest.mark.req` on `def test_*` only. Do not mark `P6-SCALER-DEMO`. Do not mark 6.7 enroll tests with `SCALE-OVERFLOW-SAME-IMAGE`.
- TDD: failing test first. Long why HEREDOC. No amend.
- Do not edit `evaluate_all` / `CYCLE_LOCK*` / `monitor/tasks.py` / `hub/settings/base.py` / `scaling/evaluator.py` product.

Protective cut (**D-107**): MUST = Tasks 0–2.

## Parallel waves

| Shared file | Order |
|---|---|
| registry / DECISIONS / paths / CODEOWNERS / PHASE_6_MUST_IDS | Task 0 |
| `deploys/overflow.py` / `deploys/pipeline.py` begin_deploy + _assemble_desired / views / urls / ACTION_TIERS / T1_HTTP / generate-client | Task 1 after 0 |
| acceptance + demo | Task 2 after 1 |

---

### Task 0: Registry + custody (D-107…D-109)

**Files:** `DECISIONS.md`, `conformance/requirements.yaml`, `conformance/paths.yaml`, `.github/CODEOWNERS`, `tests/test_conformance_gate.py`

- [ ] **Step 1: Failing tests** — `PHASE_6_MUST_IDS` += `SCALE-OVERFLOW-SAME-IMAGE`; `allowed_sources` += `phase-6.8-design-note.md §3`; unmarked custody `deploys/overflow.py` in paths.yaml and CODEOWNERS. Do not rewrite `SCALE-PROPOSE-NO-PROVISION` or `SCALE-OVERFLOW-T1-ENROLL` text.
- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — copy D-107…D-109. Add the id `phase: 6`, `verify: test`, no `tier:`; `text_hash` via `--print-text-hashes`. Claim the path in **both** files.
- [ ] **Step 4: PASS** `pytest tests/test_conformance_gate.py::test_phase_6_due_set_includes_all_section_3_must_ids tests/test_d023_actions_not_required.py tests/test_proc_rules.py -q`
- [ ] **Step 5: Commit** long why HEREDOC. No amend.

---

### Task 1: `deploy_overflow_copy` + T1 HTTP + pin when BUILD skipped

**Files:** create `deploys/overflow.py`; modify `deploys/pipeline.py` (`begin_deploy`, `_assemble_desired`, heartbeat); `deploys/steps.py` (`ensure_ship` uses `_desired_image_tag`); `core/views.py` OverflowDeployView; `hub/urls.py`; `core/actions.py`; `tests/test_webauthn_t1.py` T1_HTTP; `frontend/src/api/action_tiers.js` via `make generate-client` (or `scripts_dev/generate_actions.py`); tests in `tests/test_overflow_deploy.py`. Do not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`.

Reuse `_ready_site` / `_overflow_after_cheap` / `_plant` / enroll helpers. Plant a succeeded Deployment with `image_tag` artifact and SKIPPED-or-SUCCEEDED BUILD on the **primary**. Overflow target: enroll via Fake (or construct READY ephemeral aws_ec2 Target). Inject `PipelineTransport`.

- [ ] **Step 1: Failing tests** in `tests/test_overflow_deploy.py`

```python
@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_overflow_deploy_pins_live_tag_skips_build_and_dns():
    # ACCEPTED overflow, ephemeral READY target, prior succeeded image_tag
    # PipelineTransport; BUILD SKIPPED; DNS SKIPPED; SHIP not skipped
    # deployment SUCCEEDED; primary_target unchanged; SiteInstance exists
    # no docker build in mutating_calls; FakeDns no upsert_record


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_open_overflow_refuses_deploy_with_ack_is_not_launch():
    # OPEN → 4xx; FIX exact; no Deployment; Finding/CheckRun unchanged; no \binstance\b / Approve / Launch


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_acked_overflow_refuses_deploy_with_ack_is_not_launch(): ...


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_missing_overflow_finding_refuses_deploy(): ...


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_resolved_overflow_refuses_deploy_with_ack_is_not_launch(): ...


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_attack_refuses_overflow_deploy(): ...


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_partner_site_refuses_overflow_deploy(): ...


def test_overflow_deploy_still_requires_recent_touch():
    # unmarked (C6 not SCALE-OVERFLOW-SAME-IMAGE text); T1 POST no touch → 403


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_evaluate_site_still_does_not_create_a_deployment():
    # evaluate_site does not +1 Deployment; AST bans deploy_overflow_copy


@pytest.mark.req("SCALE-OVERFLOW-SAME-IMAGE")
def test_enroll_overflow_target_still_does_not_create_a_deployment():
    # ACCEPTED Fake enroll does not +1 Deployment and does not call deploy_overflow_copy
    # Do not re-mark 6.7 enroll tests
```

HTTP inject (every overflow POST including refuse): wrap real `deploy_overflow_copy` with `kwargs.setdefault("transport", PipelineTransport())` and `dns=FakeDnsProvider()`; patch `deploys.overflow.deploy_overflow_copy`. Happy path: stored `image_tag` ≠ computed tag; SHIP uses stored; site deploy lock held; overflow target lock held; `primary_target` has **no** deploy lock from this deployment; ACTION_TIERS row id/tier/label exact. Do not `run_deploy.delay`. Do not call `_default_transport`.

- [ ] **Step 2: RED**
- [ ] **Step 3: GREEN** — C1–C7, C10. generate-client. No schema. enroll_overflow_target unchanged.
- [ ] **Step 4: PASS** `pytest tests/test_overflow_deploy.py tests/test_overflow_enroll.py tests/test_env_lifecycle.py tests/test_scale_evaluator.py tests/test_webauthn_t1.py::test_t1_action_ids_are_require_recent_touch_or_404 -q`
- [ ] **Step 5: Commit** long why HEREDOC. No amend.

---

### Task 2: Acceptance + demo append

**Files:** `tests/acceptance/test_phase_6.py`, `conformance/demos/phase-6.md`

- [ ] **Step 1:** NAMED `test_overflow_deploy_pins_live_image_skips_dns`. Docstring transcribes §4. Body `from test_overflow_deploy import ...` and **calls** `test_overflow_deploy_pins_live_tag_skips_build_and_dns` and `test_open_overflow_refuses_deploy_with_ack_is_not_launch`. Mark `SCALE-OVERFLOW-SAME-IMAGE`. Do not mark `P6-SCALER-DEMO`. Keep 6.6/6.7 NAMED tests.
- [ ] **Step 2: RED** (demo nodeid missing)
- [ ] **Step 3: Append** demo: same-image overflow deploy, BUILD+DNS skipped, no DNS join, no live AWS VM, no auto, no AMI. Honesty: NAV six, F8 overflow seed unchanged, no Approve/Launch on the Finding.
- [ ] **Step 4: PASS** acceptance + overflow deploy + enroll. `python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3` — new id verified; U1 uncovered-only allowed.
- [ ] **Step 5: Commit** long why HEREDOC. No amend.
