# Phase 6.11 Design Note — Daily Beat for `reap_stale_ephemerals` (flag only)

**Phase:** 6.11 per deploy-system-plan.md §9.5.5 (post Phase 6.10 T1 scale-in + callable reaper)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r2 — r1 MERGE (Joseph continue 2026-08-25). Binding §7.
**Estimate:** hours. Protective cut: **D-116**. Phase 6.10 T1 MUST is on `master` @ `31b6f71`. Auto-terminate, cooldown auto, real drain, 30s origin health-pull, Cloudflare Load Balancing, ScalePolicy, auto, AMI, Beat enroll, `scale.approve`, evaluator auto-scale-in, live AWS as a test-plane requirement, HMAC, U1, Azure, Phase 7, and the 6.8 leftover lock-on-seam-refuse are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No `0015`. No `ScalePolicy`. No overflow FK. No `Target.created_at`. No new `CheckRun.Kind` / `SiteInstance` / `DnsRecord` / `OperationLock.Kind` columns. Do not retarget `Site.primary_target`.
**Panel:** §7 is binding.

## 1. What lands this wave

Phase 6.10 ships `monitor/overflow_reaper.py::reap_stale_ephemerals` as a **callable**. Tests plant `AuditEvent.ts` and call it. D-113 left Beat **OUT**, so a Hub that never invokes the function still forgets an ephemeral `aws_ec2` until a human remembers to run it — the "forgotten $80 VM" failure mode is not designed out until the daily job exists. §9.5.5: "Ephemeral targets that somehow outlive their site (Hub crash mid-episode) are caught by a **daily reaper job** that **flags** any `ephemeral` target older than 24h." Flag, not kill. Ack is still not launch. T1 `site.overflow_scale_in` is still the terminate. The evaluator still never terminates.

This wave puts the **existing** function on Celery Beat. It does **not** change the flag body, does **not** auto-terminate, and does **not** fold cooldown auto / drain / 30s health-pull.

### 1.1 MUST

1. **Evaluator / enroll / deploy / join / scale-in stay as 6.10.** `evaluate_site` never creates a Deployment, never joins, never scale-ins, never terminates, never calls `reap_stale_ephemerals`. `evaluate_all` / `evaluate_scale_proposals` stay `evaluate_all()` only. `enroll_overflow_target` / `deploy_overflow_copy` / `join_overflow_traffic` / `scale_in_overflow` do not call the reaper. Do **not** rewrite `SCALE-PROPOSE-NO-PROVISION` / `SCALE-OVERFLOW-T1-ENROLL` / `SCALE-OVERFLOW-SAME-IMAGE` / `SCALE-OVERFLOW-JOIN-TRAFFIC` / `SCALE-OVERFLOW-SCALE-IN` / `SCALE-OVERFLOW-EPHEMERAL-REAPER` `text:`. Do not edit `evaluate_all` / `CYCLE_LOCK*` / `scaling/evaluator.py` product. Do not edit `reap_stale_ephemerals` flag rules (`STALE_S`, birth clock, skip-missing-audit, title / `fix_action` / fingerprint).

2. **AST split (this is the wave's load-bearing edit).** 6.10 C1 banned the **name** `reap_stale_ephemerals` on `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` + `monitor/overflow_reaper.py`. A Beat wrapper in `monitor/tasks.py` **must** name that function, so the 6.10 single list cannot stand. Split:
   - `BANNED_IMPORTS` **drops** `reap_stale_ephemerals`. It still contains the 6.9 list **and** `scale_in_overflow` / `terminate_aws_target` / `boto3` / `CloudProvider`. Scan paths stay `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` + `monitor/overflow_reaper.py`.
   - New `BANNED_REAPER_CALLERS = ("reap_stale_ephemerals",)` scanned **only** on `scaling/` + `monitor/host_metrics.py`. Evaluator / host-metrics still cannot name the reaper.
   - `monitor/tasks.py` MAY import `reap_stale_ephemerals` **only** inside the new wrapper. `evaluate_scale_proposals` (AST of that function, not the whole file) must not name it.
   - `monitor/overflow_reaper.py` still must not import `deploys.overflow` / `terminate_aws_target` / `boto3` / `CloudProvider`. FunctionDef of `reap_stale_ephemerals` is not an `ast.Name` — defining the body stays legal.

3. **Thin Beat wrapper** `monitor/tasks.py::reap_stale_overflow_ephemerals(*, now=None)`:
   - `@shared_task(ignore_result=True)`.
   - Lazy `from monitor.overflow_reaper import reap_stale_ephemerals as body` then `rows = body(now=now)` then `return {"ok": True, "n": len(rows)}`.
   - JSON-safe return only (`ok` / `n`). Do **not** return Finding rows (Celery JSON serializer; `ignore_result=True` is not a license to return models).
   - No secret-shaped kwargs. Beat entry has **no** `kwargs` key.
   - Do **not** write CheckRun (0014 closed; 6.10 already forbade CheckRun on this path). Finding write stays inside `raise_alert` in the body.
   - Do **not** call `scale_in_overflow` / `terminate_aws_target`.
   - Distinct name from the body so the wrapper does not shadow it, and so it is not the weekly drill (`run_reaper_drill` / `drill-reaper-weekly` is the `hub-t3-` test-plane drill — do not conflate).

4. **Beat entry** `ephemeral-overflow-reaper-daily` in `hub/settings/base.py` `CELERY_BEAT_SCHEDULE`:
   - `"task": "monitor.tasks.reap_stale_overflow_ephemerals"` (must equal `reap_stale_overflow_ephemerals.name`).
   - `"schedule": 86400.0` — same shape as `cf-token-scope-daily` / `aws-iam-scope-daily` / `cert-expiry-daily`. §9.5.5 says daily, not a wall-clock hour; do **not** use `crontab`.
   - No `kwargs`. Queue `probes` via existing `CELERY_TASK_ROUTES["monitor.*"]`. Do not add a `scaling.*` task. Do not create `scaling/tasks.py`.
   - Insert next to the other daily audits (after `aws-iam-scope-daily` is fine). Must not equal `evaluate-scale-proposals` or `drill-reaper-weekly`.

5. **Honesty / gates.** Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. New MUST id phase 6, tier-less. Do not waive U1. Do not stub `named-partner.md`. Do not mark `P6-SCALER-DEMO`. Do **not** claim `monitor/tasks.py` or `hub/settings/base.py` in `paths.yaml` (existing comment: do not claim `monitor/tasks.py` wholesale). `monitor/overflow_reaper.py` is already claimed — do not broaden to `monitor/**`.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| Daily Beat `ephemeral-overflow-reaper-daily` (86400 s, queue `probes`) calls `reap_stale_ephemerals` | **MUST** |
| Wrapper JSON-safe `{ok, n}`; no CheckRun; no Beat kwargs | **MUST** |
| Flag body unchanged; 25h still flags, 23h does not; target stays READY | **MUST** |
| Evaluator / `evaluate_scale_proposals` still never call the reaper or terminate | **MUST** |
| Reaper auto-terminate | **OUT** (Ack is not launch; T1 scale-in is the terminate) |
| Cooldown auto scale-in / real drain / 30s health-pull / CF Load Balancing | **OUT** |
| ScalePolicy / auto / AMI / `scale.approve` / evaluator-deploy | **OUT** |
| `Target.created_at` / 0015 / new CheckRun.Kind | **OUT** |
| 6.8 leftover lock-on-seam-refuse | **FOLLOW-UP** |
| U1 named-partner.md, HMAC, Azure, Phase 7 | Unchanged park |

## 2. Interfaces that change

**Python:**
- `monitor/tasks.py` — add `reap_stale_overflow_ephemerals`. Do not change `evaluate_scale_proposals`.
- `hub/settings/base.py` — one `CELERY_BEAT_SCHEDULE` entry.
- `tests/test_scale_evaluator.py` — AST split (`BANNED_IMPORTS` / `BANNED_REAPER_CALLERS` / scan paths).
- `tests/test_overflow_scale_in.py` — Beat proofs; update `test_evaluate_site_still_does_not_terminate` so the reaper name is asserted on evaluator paths, not on the global terminate list.

**Not changed:** `monitor/overflow_reaper.py` product (flag rules, title, `fix_action`, fingerprint). `deploys/overflow.py` scale-in. `scaling/evaluator.py` product. `monitor/alert_rules.py` (kind already exists). ACTION_TIERS / HTTP / generate-client / Findings.jsx / Chrome.jsx / `simulation/seed_v1.json`. No schema.

**Tests:** extend `tests/test_overflow_scale_in.py`; acceptance NAMED in `tests/acceptance/test_phase_6.py`; append `conformance/demos/phase-6.md`. Keep 6.10 NAMED `test_overflow_scale_in_unjoins_terminates_and_reaper_flags` as the scale-in + callable-reaper record (do not rewrite that docstring to claim Beat).

## 3. Applicable registry reqs

Task 0 — one new MUST id, phase 6, no `tier:`. `source: phase-6.11-design-note.md §3`. Do **not** rewrite the 6.6–6.10 overflow `text:`s. Compute `text_hash:` via `--print-text-hashes`. Extend `PHASE_6_MUST_IDS` + `allowed_sources`.

- `SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT` — `phase: 6`, `verify: test`. `text:` Beat ephemeral-overflow-reaper-daily (86400s, queue probes) calls reap_stale_ephemerals; it does not terminate; evaluate_site still never terminates; tests assert the Beat entry and call the task with planted AuditEvent timestamps.

Keep `SCALE-OVERFLOW-EPHEMERAL-REAPER` as the callable-body id (6.10). The new id is the scheduler owner.

## 4. Exit demo

Beat `ephemeral-overflow-reaper-daily` names `monitor.tasks.reap_stale_overflow_ephemerals`, schedule `86400.0`, queue `probes`, no kwargs. Calling the task with an ephemeral READY `aws_ec2` whose `instance.create` AuditEvent is 25h old and is not a site primary files `ephemeral-overflow-orphan:{pk}`; target stays READY (not terminated); no CheckRun row. 23h still does not flag. `evaluate_scale_proposals` does not name the reaper. Record: append `conformance/demos/phase-6.md`. Honest: no live AWS VM, no auto-terminate, no 30s health-pull, no auto, no AMI, no real drain window. Forgotten billing is designed out **as a daily flag**, not as a kill. NAV six. F8 overflow seed stays the no-idle `0.0416` / `t3.medium` case. No Approve or Launch. Ack does not stop billing.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-116** Protective cut — daily Beat calls the 6.10 flag-only `reap_stale_ephemerals`; it does not terminate; evaluator/enroll/deploy/join/scale-in still do not auto-scale-in. Cooldown auto, real drain, 30s health-pull, reaper-terminate, ScalePolicy, leftover lock-on-seam-refuse are later.
- **D-117** Wrapper is `monitor.tasks.reap_stale_overflow_ephemerals` (JSON `{ok, n}`, no CheckRun, no kwargs). Body stays in `monitor/overflow_reaper.py`. AST splits so `scaling/` + `host_metrics.py` cannot name the reaper and the Beat wrapper can. Schedule is `86400.0`, not crontab. Weekly `drill-reaper-weekly` is a different job.
- **D-118** Everyday gates stay phase 5 minus live. New id phase 6 tier-less. U1 stays uncovered. Live AWS remains Joseph; tests plant AuditEvent timestamps.

## 6. Protective cut (D-116)

MUST = Beat schedule + thin JSON-safe wrapper around the existing flag-only function + registry. Auto-terminate / cooldown auto / drain / health-pull / ScalePolicy / auto / AMI / evaluator-scale-in / live AWS / 6.8 leftover lock are **OUT**.

## 7. Closed contract (binding)

**C1 Evaluator.** Never scale-ins or terminates. Never calls `reap_stale_ephemerals`. `evaluate_scale_proposals` body stays `return evaluate_all()`. AST-scan `BANNED_IMPORTS` (6.9 list **plus** `scale_in_overflow` / `terminate_aws_target` / `boto3` / `CloudProvider`, **minus** `reap_stale_ephemerals`) on `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` + `monitor/overflow_reaper.py`. AST-scan `BANNED_REAPER_CALLERS = ("reap_stale_ephemerals",)` on `scaling/` + `monitor/host_metrics.py` only. AST of `evaluate_scale_proposals` (that function, not the file) must not name `reap_stale_ephemerals` / `overflow_reaper`. Reaper file must not import `deploys.overflow`. Do not rewrite 6.6–6.10 overflow `text:`. Do not edit `evaluate_all` / `CYCLE_LOCK*` / `scaling/evaluator.py` product.

**C2 Wrapper.** `reap_stale_overflow_ephemerals(*, now=None)` lazy-imports the body, calls `body(now=now)`, returns `{"ok": True, "n": len(rows)}`. `ignore_result=True`. No CheckRun name in the wrapper. No `kwargs` on the Beat entry. Production Beat does not pass `now`. Tests may pass `now=` on the **body**; the Beat-task test plants timestamps against `timezone.now()` and calls the task with no args (same as `audit_cf_token_scope`).

**C3 Beat.** Key exactly `ephemeral-overflow-reaper-daily`. Task exactly `monitor.tasks.reap_stale_overflow_ephemerals`. Schedule exactly `86400.0` (float-comparable). `CELERY_TASK_ROUTES["monitor.*"]["queue"] == "probes"`. Distinct from `evaluate-scale-proposals` and `drill-reaper-weekly`. No new route. No `scaling/tasks.py`.

**C4 Flag body unchanged.** `STALE_S = 86400`. Title exact `Forgotten ephemeral overflow (past 24 hours)`. `fix_action` exact `Scale in overflow to stop billing.` Fingerprint `ephemeral-overflow-orphan:{target.pk}`. Missing `instance.create` + empty `provider_ref` still skips. 6.10 tests `test_reaper_flags_ephemeral_older_than_24h` / `test_reaper_does_not_terminate` / `test_reaper_skips_missing_birth_audit` stay green and stay marked `SCALE-OVERFLOW-EPHEMERAL-REAPER` only.

**C5 No terminate on the Beat path.** After the task runs on a 25h leftover: target `READY`, not `DECOMMISSIONED`; `terminate_instance` is not called; `scale_in_overflow` is not called. Finding exists. CheckRun count for this path does not grow.

**C6 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Named in `tests/test_overflow_scale_in.py`:
- `test_beat_entry_runs_reaper_daily_on_queue_probes` (`SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT`) — key, task name, `86400.0`, queue `probes`, no `kwargs`; task ≠ `evaluate-scale-proposals` ≠ `drill-reaper-weekly`
- `test_beat_task_flags_and_does_not_terminate` (`SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT`) — plant 25h birth on ephemeral READY non-primary; call `reap_stale_overflow_ephemerals()` with no args; Finding `ephemeral-overflow-orphan:{pk}`; status still READY; return `ok` / `n>=1`; CheckRun count unchanged
- `test_evaluate_scale_proposals_does_not_call_reaper` (`SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT`) — AST of `evaluate_scale_proposals` does not name `reap_stale_ephemerals` / `overflow_reaper`; `_ast_hits` on `scaling/` + `host_metrics.py` for `BANNED_REAPER_CALLERS` is empty
- `test_evaluate_site_still_does_not_terminate` stays marked both 6.10 ids; drop `assert "reap_stale_ephemerals" in BANNED_IMPORTS`; assert the name is in `BANNED_REAPER_CALLERS` and still hits-empty on evaluator paths
Do not mark `P6-SCALER-DEMO`. Do not mark 6.10 callable-body tests with the new id.

Acceptance NAMED `test_ephemeral_reaper_runs_on_daily_beat` **calls** `test_beat_entry_runs_reaper_daily_on_queue_probes` and `test_beat_task_flags_and_does_not_terminate`. Keep `test_overflow_scale_in_unjoins_terminates_and_reaper_flags`. Do not mark the new NAMED `P6-SCALER-DEMO`.

**C7 Registry.** Task 0 adds `SCALE-OVERFLOW-EPHEMERAL-REAPER-BEAT`, extends `PHASE_6_MUST_IDS` + `allowed_sources` with `phase-6.11-design-note.md §3`. Do not rewrite 6.10 `text:`. Do not re-claim `monitor/overflow_reaper.py`. Do not claim `monitor/tasks.py` / `hub/settings/base.py`.

**C8 Module arrows.** `monitor/tasks.py` wrapper → `monitor.overflow_reaper.reap_stale_ephemerals` only. Does **not** import `deploys.overflow` / `terminate_aws_target` / `boto3` / `providers.ec2`. `scaling/` ↛ `monitor.overflow_reaper`. Body still → `monitor.alerts.raise_alert` / `core.models` only. Beat settings ↛ task body (name string only).

**C9 Copy.** No new ACTION_TIERS. No new HTTP. No new F8. NAV six. No Approve/Launch/ActionButton. Reaper operator copy stays the 6.10 strings. Demo may say `daily Beat` / `ephemeral-overflow-reaper-daily`. No `\binstance\b` in new operator copy (demo, Finding, task docstring as operator-facing) except existing `single-instance` / `single-instance-only` / `instance.create` / `instance.terminate` ids. File map does not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`.

**C10 Gate / test-plane.** T1 only. Tests plant `AuditEvent` timestamps the 6.10 way (`create` then `.update(ts=...)`). Do not live-AWS. Do not invent `HUB_TEST_*`. `python conformance/check.py --phase 6 --exclude-tier t2 --exclude-tier t3` verifies the new id; U1 uncovered-only allowed.

## 8. Follow-up only (not this wave)

6.8 leftover: `_resolve_seams` after overflow `begin_deploy` can leave the site deploy lock held on FAILED. Fake-path-safe. **Not** the 6.11 function. Do not fold it into Task 1.

Auto-terminate on the reaper, cooldown auto scale-in, real drain (`DRAIN_S > 0`), 30s origin health-pull remain later. A skipped daily Beat without a CheckRun is **not** a missed-drill this wave (no new `CheckRun.Kind`).
