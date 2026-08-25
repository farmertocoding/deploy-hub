# Phase 6.12 Design Note — Overflow seam-refuse releases deploy locks

**Phase:** 6.12 per the 6.8 leftover recorded in `docs/phase-6.9-design-note.md` §8 (post Phase 6.11 daily Beat reaper)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r1 — leftover lock-on-seam-refuse only. Binding §7.
**Estimate:** hours. Protective cut: **D-119**. Phase 6.11 T1 MUST is on `master` @ `2b0c8df`. Auto-terminate, cooldown auto, real drain, 30s origin health-pull, Cloudflare Load Balancing, ScalePolicy, auto, AMI, Beat enroll, `scale.approve`, evaluator auto-scale-in, live AWS as a test-plane requirement, HMAC, U1, Azure, and Phase 7 are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No `0015`. No `ScalePolicy`. No overflow FK. No `Target.created_at`. No new `CheckRun.Kind` / `SiteInstance` / `DnsRecord` / `OperationLock.Kind` columns. Do not retarget `Site.primary_target`.
**Panel:** §7 is binding. Expert team continue (Joseph delegated commit/merge/push for this leftover).

## 1. What lands this wave

`deploy_overflow_copy` calls `begin_deploy` **before** `execute`. `begin_deploy` acquires site + overflow-target `kind=deploy` locks and sets RUNNING. `execute` then calls `_resolve_seams`. When both `dns` and `cert_issuer` are unset, that takes the production factory and can raise `DeploySeamRefused`. Today's handler sets FAILED and re-raises **before** the `finally` that `release_deploy_locks`. Heartbeat sweep only RUNNING deployments, so a FAILED holder is **not** swept. The site lock sticks; 6.9 join then 4xx `could not acquire deploy lock`. Fake-path overflow injects `dns=`, so T1 never hits this. Production `OverflowDeployView` does not inject `dns=`.

This wave releases those locks on the seam-refuse path. It does **not** auto-join, auto-scale-in, auto-terminate, or fold cooldown / drain / health-pull.

### 1.1 MUST

1. **Evaluator / enroll / deploy / join / scale-in / Beat stay as 6.11.** `evaluate_site` never creates a Deployment, never joins, never scale-ins, never terminates, never calls `reap_stale_ephemerals`. Do **not** rewrite 6.6–6.11 overflow `text:`. Do not edit `evaluate_all` / `CYCLE_LOCK*` / `scaling/evaluator.py` product. Do not edit `reap_stale_ephemerals` flag rules. Do not edit Beat key `ephemeral-overflow-reaper-daily`.

2. **`execute` releases locks on `DeploySeamRefused`.** After setting FAILED, call `release_deploy_locks(deployment)` then re-raise. Safe when no locks exist (QUEUED primary path: release is a no-op). Do not move `_resolve_seams` after `begin_deploy` for the primary path — overflow already began. Do not teach heartbeat sweep to reap FAILED holders (that would widen C1 of the heartbeat module).

3. **Proof is Fake-path-safe.** Force `_resolve_seams` to raise after overflow `begin_deploy` (call `deploy_overflow_copy` with `transport=` injected and **no** `dns=` / `cert_issuer=`, on a site whose DnsAccount has no token refs). Assert: `DeploySeamRefused` raised; deployment FAILED; no `OperationLock` with `kind=deploy` and `holder=str(deployment.pk)`; a later site `kind=deploy` acquire for join succeeds. Do not live-DNS. Do not live-AWS.

4. **Honesty / gates.** Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. New MUST id phase 6, tier-less. Do not waive U1. Do not stub `named-partner.md`. Do not mark `P6-SCALER-DEMO`. Do **not** claim `deploys/pipeline.py` in `paths.yaml` (existing file; do not broaden `deploys/**`). Do not re-claim `deploys/overflow.py`.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| `execute` releases deploy locks on `DeploySeamRefused` after overflow `begin_deploy` | **MUST** |
| FAILED holder is not left for heartbeat sweep to miss | **MUST** |
| Evaluator still never creates a Deployment | **MUST** |
| Reaper auto-terminate / cooldown auto / real drain / 30s health-pull / CF LB | **OUT** |
| ScalePolicy / auto / AMI / `scale.approve` / evaluator-deploy | **OUT** |
| U1 named-partner.md, HMAC, Azure, Phase 7 | Unchanged park |

## 2. Interfaces that change

**Python:**
- `deploys/pipeline.py::execute` — `DeploySeamRefused` handler also `release_deploy_locks`.
- `tests/test_overflow_deploy.py` — seam-refuse-after-begin proofs.
- Acceptance NAMED in `tests/acceptance/test_phase_6.py`; append `conformance/demos/phase-6.md`.

**Not changed:** `deploys/overflow.py` product gates. `deploys/seams.py` refuse body. ACTION_TIERS / HTTP / generate-client / Findings.jsx / Chrome.jsx / `simulation/seed_v1.json`. No schema. Beat / evaluator / reaper body.

## 3. Applicable registry reqs

Task 0 — one new MUST id, phase 6, no `tier:`. `source: phase-6.12-design-note.md §3`. Do **not** rewrite the 6.6–6.11 overflow `text:`s. Compute `text_hash:` via `--print-text-hashes`. Extend `PHASE_6_MUST_IDS` + `allowed_sources`.

- `SCALE-OVERFLOW-LOCK-ON-SEAM-REFUSE` — `phase: 6`, `verify: test`. `text:` After overflow begin_deploy holds site and overflow-target deploy locks, execute that raises DeploySeamRefused from _resolve_seams marks FAILED and releases those locks; a FAILED holder is not left for heartbeat sweep to miss; evaluate_site still never creates a Deployment.

## 4. Exit demo

ACCEPTED overflow, enrolled ephemeral READY target, prior succeeded `image_tag`, `PipelineTransport`, **no** `dns=` / `cert_issuer=`, DnsAccount without token refs → `deploy_overflow_copy` raises `DeploySeamRefused`; the overflow Deployment is FAILED; no `OperationLock` remains with `holder=<that deployment pk>`; a subsequent site deploy-lock acquire succeeds. `evaluate_site` still does not create a Deployment. Record: append `conformance/demos/phase-6.md`. Honest: no live AWS VM, no live Cloudflare, no auto-terminate, no 30s health-pull, no auto, no AMI, no real drain window. NAV six. F8 overflow seed stays the no-idle `0.0416` / `t3.medium` case. No Approve or Launch.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-119** Protective cut — overflow seam-refuse after `begin_deploy` releases site + overflow-target deploy locks; evaluator/enroll/deploy/join/scale-in/Beat stay as 6.11. Cooldown auto, real drain, 30s health-pull, reaper-terminate, ScalePolicy remain later.
- **D-120** Fix lives in `execute`'s `DeploySeamRefused` handler (`release_deploy_locks` after FAILED). Do not widen heartbeat sweep to FAILED holders. QUEUED primary seam-refuse stays a no-op release.
- **D-121** Everyday gates stay phase 5 minus live. New id phase 6 tier-less. U1 stays uncovered. Do not claim `deploys/pipeline.py`.

## 6. Protective cut (D-119)

MUST = lock release on overflow seam-refuse + registry. Auto-terminate / cooldown auto / drain / health-pull / ScalePolicy / auto / AMI / evaluator-scale-in / live AWS / Phase 7 are **OUT**.

## 7. Closed contract (binding)

**C1 Evaluator.** Never creates a Deployment. AST-scan of `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` still forbids the 6.11 lists. Do not rewrite 6.6–6.11 overflow `text:`. Do not edit `evaluate_all` / `CYCLE_LOCK*` / `scaling/evaluator.py` product.

**C2 Release on refuse.** `execute`'s `except DeploySeamRefused` sets FAILED, `release_deploy_locks(deployment)`, then re-raises. `release_deploy_locks` already drops every `kind=deploy` row with `holder=str(deployment.pk)`. Do not add a second lock table. Do not change `begin_deploy` acquire order.

**C3 Proof.** `deploy_overflow_copy(site, overflow, transport=PipelineTransport())` with **no** `dns=` / `cert_issuer=` on a site whose DnsAccount has empty `dns_token_ref` and `origin_ca_key_ref`. Raises `DeploySeamRefused`. Deployment FAILED. `OperationLock.objects.filter(kind=deploy, holder=str(pk))` is empty. A later `locks.acquire("site", site.pk, "deploy", "overflow-join-probe")` succeeds (then release that probe holder). Existing `test_execute_without_refs_refuses_and_does_not_fake` stays green (QUEUED, no leftover locks).

**C4 No new HTTP / ACTION_TIERS.** View still does not inject `dns=`. This wave does not add a serializer field. Fake-path HTTP inject (`dns=FakeDnsProvider()`) stays; it is not this proof.

**C5 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Named in `tests/test_overflow_deploy.py`:
- `test_overflow_seam_refuse_after_begin_deploy_releases_locks` (`SCALE-OVERFLOW-LOCK-ON-SEAM-REFUSE`)
- `test_evaluate_site_still_does_not_create_a_deployment` stays marked `SCALE-OVERFLOW-SAME-IMAGE` only; add `test_evaluate_site_still_does_not_create_a_deployment_on_lock_wave` marked with the new id that **calls** that existing function
Do not mark `P6-SCALER-DEMO`. Do not mark 6.8–6.11 tests with the new id except the explicit call-through.

Acceptance NAMED `test_overflow_seam_refuse_releases_deploy_locks` **calls** `test_overflow_seam_refuse_after_begin_deploy_releases_locks`. Do not mark the new NAMED `P6-SCALER-DEMO`.

**C6 Registry.** Task 0 adds `SCALE-OVERFLOW-LOCK-ON-SEAM-REFUSE`, extends `PHASE_6_MUST_IDS` + `allowed_sources` with `phase-6.12-design-note.md §3`. Do not rewrite 6.11 `text:`. Do not claim `deploys/pipeline.py`. Do not re-claim `deploys/overflow.py`.

**C7 Module arrows.** `deploys/pipeline.py` already imports `DeploySeamRefused` and `release_deploy_locks`. No new import. `scaling/` ↛ `deploys`.

**C8 Copy.** No new ACTION_TIERS. No new F8. NAV six. No Approve/Launch/ActionButton. No `\binstance\b` in new operator copy (demo, 4xx blobs) except existing `single-instance` / `single-instance-only` / `instance.create` / `instance.terminate` ids. File map does not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`.

**C9 Gate / test-plane.** T1 only. Do not live-AWS. Do not invent `HUB_TEST_*`. `python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3` verifies the new id; U1 uncovered-only allowed.

## 8. Follow-up only (not this wave)

Auto-terminate on the reaper, cooldown auto scale-in, real drain (`DRAIN_S > 0`), 30s origin health-pull remain later. Phase 7 polish remains later.
