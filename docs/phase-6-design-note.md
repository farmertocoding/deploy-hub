# Phase 6 Design Note — Overflow auto-scaling (T1 propose-only)

**Phase:** 6 per §I / deploy-system-plan.md §9.5 (post-v1, gated on scale-ready; propose-mode first)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-24 · **Seat:** Grok 4.6
**Revision:** r2 — design panel MERGE-AFTER-FIXES (Architect + Security + QE + SRE + UX). Required fixes folded: same-axis in-window streak (not last-N); disk axis **out** of overflow (Security, not waivable); no `raise_alert` refresh of OPEN/ACKED/ACCEPTED; system-resolve OPEN/ACKED on ineligible or Attack/Partner refuse; `mesh_only` ineligible; Hub-clock `HostMetric.ts` + persist isolation; `fix_action` pinned; `single_instance` not aliased to `not scale_ready`; F8 `single-instance-only` + list-row badge; C13 scale-ready predicates; Beat skip-if-running + per-site isolation + no CheckRun + no `scaling.tasks`. §7 is binding.
**Estimate:** days, not weeks. Protective cut: **D-086**. Phase 5.5 T1 MUST is on `master` @ `39ead14`. Live AWS/KMS/S3/intake/CF, U1 named partner, HMAC enablement, MCP, Azure, auto-mode provision, AMI bake are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET` tokens. Do not stub `named-partner.md`.**
**Branch:** these two docs land on **`p6-design`**; Implementers cut task branches from it. Never implement on `master`. Sensitive-path merges go through the recorded panel vote.
**Closed schema wave:** `0013_phase55.py` stays closed. Phase 6 adds **one** Hub migration, `0014_phase6.py`: `HostMetric` + `Site.scale_ready`. No `ScalePolicy` table. No `Site.tier`. No `Site.partner_id`. No `Target.tier`. **Task 1 is the only `core/models.py` writer this phase.** Later tasks do not edit it. Do not add `OperationLock.Kind`. Do not backfill `scale_ready` from old scan JSON.
**Panel:** §7 is binding. An Implementer who invents a path, env, Finding fingerprint, action id, threshold, or gate shape that §7 does not name is implementing the wrong design.

## 1. What lands this phase

Phase 5.5 finished T1 Fake partner intake. Phase 6 is the §9.5 promise **cut to propose-mode**: sustained host pressure becomes a Finding with a cost estimate. Nothing launches. Attack-shaped load never scales. Partner overflow never scales. Sites that fail scale-ready are single-instance-only and ineligible.

The full §9.5 playbook (cheap remediations, provision ephemeral, DNS round-robin, Tunnel replica, scale-in, AMI bake, `ScalePolicy` table, auto mode) is **later**. Addendum §I: "Gated on having scale-ready sites; propose-mode first." This wave is that first.

### 1.1 MUST

1. **HostMetric persistence.** Collector already writes `{load1, mem_pct, disk_pct}` into `Target.collect_payload`. That is a latest sample, not a history. Sustained 5-minute detection needs rows. `HostMetric(target, ts, cpu, ram, disk, load, cores)`: `cpu` nullable unused this wave; `ram`/`disk`/`load` are `mem_pct`/`disk_pct`/`load1`; `cores` from `os.cpu_count()` in `monitor/collect_once.py::_metrics`. `HostMetric.ts` is the **Hub** persist clock (`now or timezone.now()`), never `payload["ts"]`. Persist after `_persist_collect` writes `collect_payload`; a persist failure **audits and must not raise** out of `collect()` (traffic ingest + `run_for_target` still run). Coerce finite floats; ram/disk outside `[0, 100]` or non-finite → store None for that axis; cores None unless a positive int; skip insert when `metrics` missing or not a dict (no invented numbers). Retention: raw DELETE after 14 d; hourly rollup 1 y stays **pinned**, the rollup table is **not** this wave.

2. **Capacity decision is a pure function**, separate from I/O. `scaling/pressure.py::sustained_pressure(samples, *, now) -> bool`. No Django, no I/O. `samples` is a sequence of mappings with keys `ram`, `disk`, `load`, `cores`, `ts` (None allowed). Overload = **sustained same-axis** pressure, never a spike and never last-N-ignoring-gaps:
   - Filter to Hub `ts` in `[now - WINDOW_S, now]` (`WINDOW_S = 300`).
   - Bucket by UTC minute; one sample per minute (latest in that minute).
   - Need **5 consecutive distinct UTC minutes** (`CONSECUTIVE_MINUTES = 5`); a missing minute breaks the streak.
   - Newest bucket is within `MAX_SAMPLE_GAP_S = 120` of `now`.
   - **Same axis** is over on all five: `ram > 85` **or** (`cores >= 1` and `load > cores`). Mixed-axis (mem then load then mem) is **not** sustained. `disk` is **not** an overflow axis (host-health / existing `resource-pressure`; Security: disk fill is an L5 bypass). `cpu` is not an axis. `None` is not over.
   - Fewer than 5, a hole, a retry cluster that does not yield 5 distinct minutes, a stale newest row, or a TypeError-prone null → `False`.

3. **Propose-only emission.** When `sustained_pressure` is true for a site's `primary_target` **and** the site is eligible, file via existing `monitor.alerts.raise_alert` kind **`scale-out-proposal`** (row already in `monitor/alert_rules.py`) **only to open an episode**. Fingerprint **`scale-out-proposal:{site.pk}`**. If a row is already OPEN, ACKED, or ACCEPTED for that fingerprint, **return it and do not call `raise_alert`** (no `after_raise` / `_record_push`; P2 is once per episode). ACCEPTED stays quiet (F2: operator declined overflow). Title: `Scale-out proposal awaiting approval (propose mode)`. Entity: `site:{site.domain or site.name}` (not pk). Body names the site, the hot axis, `0.0416`, `t3.medium`, and the sentence `propose-mode does not launch`. No `\binstance\b`. **`fix_action` exact:** `Ack is not launch. Propose-mode does not launch.` Do not name `instance.create`, enroll, `/api/v1/instance/create/`, Approve, or Launch in title/body/fix_action/pager. Pager `click_url` stays `{HUB_PUBLIC_URL}/#/findings/{id}` — that **is** the protocol “approve action link”. Ack is not launch. No `scale.approve` POST. No `ActionButton` / T1 overlay on this Finding. No call to `InstanceCreateView`, `provision.aws_enroll.enroll_aws_target`, or any `CloudProvider` create.

4. **Attack gate and partner overflow.** Every `evaluate_site` **must call** `scaling.attack_gate.refuse_if_attack(site)` **first** (SEC-L5-NEVER-SCALE-ATTACK, D-057), not only on the file path. Catch `AttackRefuse` and `PartnerOverflowRefuse`: **system-resolve** any OPEN or ACKED `scale-out-proposal:{site.pk}` (`source="system"`); do **not** file; no consolation Finding. Do not reimplement the refuse. Evaluator Beat stays **separate** from `collect_all` (a failed SSH collect must still evaluate). Same-tick race is at most one minute; the next evaluate retracts. Do not fold evaluate into `collect_all`. Do not add `scaling.tasks` (`scaling.*` already routes to `control`).

5. **Scale-ready prerequisite (§9.5.6).** Scanner `common_checks` always emits `core.scale-ready` (warning, never blocker — "marked, not blocked"). Predicates = C13. `Site.scale_ready` default **False** (fail-closed). Missing check or any non-`ok` tier → False. `confirm_warnings` does not set True. No `deployhub.yaml` downgrade for this id. `wizard.materialize` sets `locked.scale_ready = (check.tier == "ok")` on the `select_for_update` row (`update_fields=["scale_ready"]`). Scanner does not import `core.models`. Reuse `common_checks` `texts`/`paths` (no second walk; no escaped-symlink reads beyond the existing refusal). No subprocess. Do not supersede `node-ts.local-state`.

6. **Sites chrome.** `SiteSummarySerializer` / `project_row_body` **always emit** `scale_ready` (bool) on live rows. Do **not** set `single_instance = not scale_ready`. `single_instance` keeps its F8 meaning (observed one-copy); omit on live rows this wave. Fields `required=False` so older sim rows parse. Paint: `scale_ready === false` → **`single-instance-only`** (omitted/undefined does **not** paint). `single_instance || instances === 1` → **`single-instance`**. Both badges only when both facts are true. Render `SiteObserved` on Sites **list rows** (next to PartnerBadge / ManifestLine), not detail-only. NAV stays six. Copy never says "instance" except those two tokens. F8: required states **`single-instance-only`** (seed `{scale_ready: false}`, no `single_instance: true` unless both badges intended; `must_render: ["single-instance-only"]`; existing `single-instance` seed `doesNotMatch /single-instance-only/`) **and** **`scale-out-proposal`** (full P2 Finding: protocol title, body tokens, pinned `fix_action`, topic `findings`; no Approve/Launch/`Create target` control; no `$0.05`). Do not backfill every `sim.js` site as `scale_ready: false`.

7. **Honesty / gates.** Task 0 does **not** bump everyday `conformance` / `review-round` off `--phase 5 --exclude-tier t2 --exclude-tier t3`. `conformance-6` is `--phase 6 --exclude-tier t2 --exclude-tier t3` and is **not** a `review-round` or `nightly-gates` prereq. Two consecutive clean `make review-round` rounds close a *phase*, not each merge. Do not waive U1 / PART-K / `failed` / `not-collected`. Do not add `t4`. Do not add all-tiers 6. Do not stub `conformance/demos/phase-6.md` in Task 0.

8. **Beat brakes.** `evaluate-scale-proposals` → `monitor.tasks.evaluate_scale_proposals`, 60.0, queue `probes` (existing `monitor.*` route). Skip-if-running: `OperationLock` kind=`collect`, object_id=`evaluate-scale-proposals`, stale takeover 300 s (probe_uptime pattern). `evaluate_all` isolates per site (try/audit/continue). Any exception other than the two named refuses → return None, do not file. **No CheckRun** read or write. AST-scan `scaling/` **and** `monitor/tasks.py` **and** `monitor/host_metrics.py` for `provision.aws_enroll`, `providers.ec2`, `enroll_aws_target`, `InstanceCreateView`, `boto3`, `CloudProvider`.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| HostMetric persist + Hub ts + 14 d raw DELETE + collector isolation | **MUST** |
| Pure `sustained_pressure` + 5 consecutive distinct minutes, same-axis mem **or** load | **MUST** |
| Finding `scale-out-proposal` + cost + pinned `fix_action`; no re-page; retract | **MUST** |
| Call `refuse_if_attack` first (attack + partner); resolve OPEN/ACKED on refuse | **MUST** |
| `core.scale-ready` warning + `Site.scale_ready` fail-closed + list-row badge | **MUST** |
| Standing pin: scaler never provisions; AST includes Beat/persist modules | **MUST** |
| F8 `single-instance-only` + `scale-out-proposal` | **MUST** |
| `0014_phase6.py`; `conformance-6` minus live; everyday gates stay phase 5 | **MUST** |
| Disk as overflow-proposal axis | **OUT** (host-health; existing resource-pressure) |
| `ScalePolicy` table / per-site thresholds / auto mode | **OUT** |
| Cheap remediations (cache, gunicorn workers) | **OUT** |
| Provision ephemeral / DNS join / Tunnel replica / AMI bake | **OUT** |
| Scale-in + ephemeral reaper for overflow VMs | **OUT** |
| Hourly HostMetric rollup table | **OUT** |
| CPU axis / `/proc/stat` | **OUT** |
| `scale.approve` POST that launches | **OUT** |
| Live AWS pricing API | **OUT** (`0.0416` / `t3.medium`) |
| HMAC / MCP / U1 / Azure / Phase 7 | **OUT** / Joseph / later |

## 2. Interfaces / tables that change

**Migration `0014_phase6.py` (Hub) — Task 1 owns this file and `core/models.py` for the whole phase:**
- `HostMetric`: FK `Target` (`related_name="host_metrics"`, `on_delete=CASCADE`); `ts` DateTimeField `db_index=True`; `cpu` FloatField `null=True`; `ram` FloatField `null=True`; `disk` FloatField `null=True`; `load` FloatField `null=True`; `cores` PositiveIntegerField `null=True`. Index `(target, -ts)`. No unique-on-ts. No `granularity` column.
- `Site.scale_ready`: BooleanField default `False`. No data migration backfill.
- No `ScalePolicy`. No CheckRun Kind. No new `OperationLock.Kind`.
- No `Site.tier`. No `Site.partner_id`. No `Target.tier`.

**Constants (`scaling/constants.py`):**
- `MEM_PCT_THRESHOLD = 85.0`
- `CONSECUTIVE_MINUTES = 5`
- `WINDOW_S = 300`
- `MAX_SAMPLE_GAP_S = 120`
- `OVERFLOW_HOURLY_USD = "0.0416"`
- `OVERFLOW_SIZE = "t3.medium"`
- `PROPOSE_MODE = "propose"`
- `FIX_ACTION = "Ack is not launch. Propose-mode does not launch."`
- `TITLE = "Scale-out proposal awaiting approval (propose mode)"`

**Python (files and signatures — do not invent others):**
- `monitor/host_metrics.py::persist_sample(target, payload, *, now)` — I/O only; Hub `ts`; coerce; never raise to caller of `_persist_collect`.
- `scaling/pressure.py::sustained_pressure(samples, *, now) -> bool`
- `scaling/evaluator.py::evaluate_site(site, *, now=None) -> Finding | None`
- `scaling/evaluator.py::evaluate_all(*, now=None)`
- `monitor/collect_once.py::_metrics` adds `"cores": os.cpu_count()`
- `monitor/collector.py::_persist_collect(target, payload, *, now=None)` calls `persist_sample` in try/audit
- `monitor/retention.py::_sweep_host_metric` batched DELETE `ts < now - 14d` (no hourly grain)
- `monitor/tasks.py::evaluate_scale_proposals` Beat; body is `evaluate_all()` only
- `scanner/modules/fallbacks.py::_check_scale_ready` + `common_checks` list
- `wizard/materialize.py` writes `Site.scale_ready`
- `wizard/views.py` serializer + `project_row_body`; `make generate-client` for OpenAPI
- `frontend/src/screens/Sites.jsx` `SiteObserved` on list rows as §1.1.6

**HTTP:** none new.

**Gates:** `make conformance` and `make review-round` stay phase 5 minus live. `make conformance-6` = `--phase 6 --exclude-tier t2 --exclude-tier t3`, **not** a `review-round` or `nightly-gates` prereq. No `t4`. No all-tiers 6.

## 3. Applicable registry reqs

**Task 0 — new MUST ids, phase 6, no `tier:` key.** Copy these fields; do not invent. `source: phase-6-design-note.md §3`. `text_hash:` computed by Task 0. Do not change existing `text:` / `text_hash:`. Do not bump PART-K / U1.

- `SCALE-SUSTAINED-PROPOSE` — `phase: 6`, `verify: test`. `text:` five consecutive distinct UTC minutes of HostMetric samples in a 300s Hub-clock window over the same axis (mem_pct>85 or load1>cores) file Finding kind scale-out-proposal fingerprint scale-out-proposal:{site.pk} whose body includes the cost estimate and the sentence propose-mode does not launch; disk-only heat does not file.
- `SCALE-SPIKE-NO-PROPOSE` — `phase: 6`, `verify: test`. `text:` a single sample over threshold among five, a missing minute, mixed axes, or samples older than the window do not file scale-out-proposal.
- `SCALE-NEVER-ATTACK` — `phase: 6`, `verify: test`. `text:` evaluate_site calls refuse_if_attack first; when the attack playbook is engaged no scale-out-proposal is filed and an OPEN or ACKED proposal for that site is system-resolved.
- `SCALE-NEVER-PARTNER` — `phase: 6`, `verify: test`. `text:` a PartnerSite never receives scale-out-proposal even on sustained pressure and a quiet attack playbook; binding PartnerSite after file system-resolves an OPEN proposal.
- `SCALE-PROPOSE-NO-PROVISION` — `phase: 6`, `verify: test`. `text:` propose-mode evaluate_site never creates a Target, never calls enroll_aws_target or InstanceCreateView, and scaling/ plus monitor/tasks.py plus monitor/host_metrics.py do not import provision.aws_enroll or providers.ec2.
- `SCALE-READY-PREREQ` — `phase: 6`, `verify: test`. `text:` core.scale-ready is warning not blocker; Site.scale_ready defaults False; missing check or warning is False even if confirm_warnings; a failing or mesh_only site is ineligible; a passing public site can be proposed.
- `UX-P6-SINGLE-INSTANCE` — `phase: 6`, `verify: test`. `text:` Sites payload emits scale_ready and does not alias single_instance to not scale_ready; SiteObserved paints single-instance-only iff scale_ready is false and is shown on list rows; F8 REQUIRED_STATE_IDS includes single-instance-only and scale-out-proposal; NAV stays six; copy never says instance except single-instance and single-instance-only; the proposal Finding has no Approve or Launch control.
- `P6-SCALER-DEMO` — `phase: 6`, `verify: demo`, `demo: conformance/demos/phase-6.md`. `text:` demo record names the MUST path in design note §4; no live provision, no auto mode, no AMI, no ScalePolicy table.

**Waivers:** Task 0 waives **nothing that is MUST**. `failed` / `not-collected` are unwaiable.

## 4. Exit demo

A public scale-ready site (`core.scale-ready` ok, `Site.scale_ready=True`, not `mesh_only`), quiet attack playbook, not a PartnerSite, five HostMetric rows `ram=90` one distinct UTC minute apart inside the 300s window → Findings inbox shows P2 **scale-out-proposal** fingerprint `scale-out-proposal:{pk}`, body contains `0.0416`, `t3.medium`, and `propose-mode does not launch`; `fix_action` is the C8 sentence; Target count unchanged; no `enroll_aws_target` call. Re-evaluate while OPEN does not add a push-log event. Four of five over + one under → no Finding. One spike → no Finding. Disk-only five hot minutes → no Finding. Same pressure while attack playbook is engaged → no `scale-out-proposal` (attack Finding may exist); an already-OPEN proposal is resolved. Same pressure on a PartnerSite → no proposal. A site with `scale_ready=False` and five hot mem samples → no proposal; Sites **list** paints **single-instance-only**. `mesh_only` + five hot mem → no proposal. NAV is still six.

Record: `conformance/demos/phase-6.md`. Does **not** claim a VM launched, auto mode, AMI, live AWS, or U1. Everyday `make review-round` (phase 5) may go green while phase-6 ids are uncovered. Two consecutive clean **`make conformance-6`** rounds close the phase. T1 task merges may proceed on panel MERGE + `make review-round` green.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-086** Protective cut — T1 propose-only overflow: HostMetric history, sustained-pressure evaluator, scale-out-proposal Finding with cost estimate, attack+partner refuse + retract, scale-ready check + single-instance-only marking; never provision; no ScalePolicy table; no auto/AMI/cheap-remediation/scale-in; disk is not an overflow axis; `conformance-6` is the phase gate and is not a review-round or nightly-gates prereq; everyday `conformance`/`review-round` stay phase 5 minus live.
- **D-087** One Hub wave `0014_phase6.py`: `HostMetric` + `Site.scale_ready` (default False); `0013` stays closed; Task 1 is the only `core/models.py` writer. No `ScalePolicy`. No `Site.tier`. No CheckRun.Kind. No new OperationLock.Kind.
- **D-088** Thresholds are constants: same-axis `ram > 85` or (`cores >= 1` and `load > cores`); 5 consecutive distinct UTC minutes in a 300s Hub-clock window; newest within 120s; spike / hole / mixed-axis / stale / disk-only = not sustained; cpu axis out; disk overflow-axis out.
- **D-089** Fingerprint `scale-out-proposal:{site.pk}`; `evaluate_site` calls `refuse_if_attack` first; catch `AttackRefuse` and `PartnerOverflowRefuse`; system-resolve OPEN/ACKED on refuse or ineligibility; do not reimplement; do not re-`raise_alert` while OPEN/ACKED/ACCEPTED.
- **D-090** `core.scale-ready` is warning not blocker; Site.scale_ready fail-closed default False; missing/warning/confirm_warnings → False; materialize copies from the report; `mesh_only` ineligible; ineligible sites do not get a proposal Finding.
- **D-091** `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. `conformance-6` is `--phase 6 --exclude-tier t2 --exclude-tier t3` and is not a `review-round` or `nightly-gates` prereq. No `t4`. No all-tiers 6. New MUST ids are tier-less.
- **D-092** Cost estimate is `OVERFLOW_HOURLY_USD="0.0416"` / `OVERFLOW_SIZE="t3.medium"`; no live AWS pricing; body must include both plus `propose-mode does not launch`.
- **D-093** No `scale.approve` POST. Pager link to the Finding is the approve-action link. Ack is not launch. `fix_action` is exactly `Ack is not launch. Propose-mode does not launch.` `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` must not import `provision.aws_enroll` or `providers.ec2`.
- **D-094** `persist_sample` is called from `_persist_collect` after the Target save, in try/audit (must not fail collect); `cores` from `os.cpu_count()` in `_metrics`; `cpu` column exists nullable and is unused; `ts` is Hub `now`; coerce finite in-range floats.
- **D-095** HostMetric raw 14 d DELETE lands with the table; hourly rollup 1 y stays a pinned horizon without a rollup table this wave.

## 6. Protective cut (D-086)

MUST = Tasks 0–6. Auto-mode / AMI / ScalePolicy / cheap remediations / scale-in / disk-as-overflow are **OUT**, not slipped. First Joseph interrupt that would grow the MUST line = live provision.

## 7. Closed contract (binding)

**C1 Fingerprints.** `scale-out-proposal:{site.pk}` only. Do not invent `scale-propose:`. Attack/partner refuses do not file a second scale fingerprint. Default `raise_alert` fingerprint `{kind}:{entity}` would be wrong if entity is the domain — always pass `fingerprint=` explicitly.

**C2 Streak.** `sustained_pressure(samples, *, now) -> bool`. Mappings keys `ram, disk, load, cores, ts`. Window `[now-300s, now]`, 5 consecutive distinct UTC minutes, newest ≤ 120s from `now`, **same axis** (`ram > 85` or load>cores with `cores >= 1`). Disk is stored but is **not** an overflow axis. None/missing is not over. Last-N-without-window is illegal.

**C3 HostMetric.** Columns `target, ts, cpu, ram, disk, load, cores`. `ts` = Hub persist clock. `ram`=`mem_pct`, `disk`=`disk_pct`, `load`=`load1`. Coercion as §1.1.1.

**C4 Never provision.** `evaluate_site` / `evaluate_all` / `sustained_pressure` / `persist_sample` / `evaluate_scale_proposals` never create a Target, never call enroll, never import ec2/aws_enroll/boto3/CloudProvider/InstanceCreateView.

**C5 Refuse.** `refuse_if_attack(site)` is called first on every `evaluate_site`. Partner overflow is already inside it. On either named refuse: resolve OPEN/ACKED proposal; do not file.

**C6 Eligibility.** `primary_target_id` set **and** `scale_ready is True` **and** `exposure != mesh_only` **and** refuse does not raise. Else None (and retract if OPEN/ACKED).

**C7 Beat / pager.** `evaluate-scale-proposals` → `monitor.tasks.evaluate_scale_proposals`, 60 s, queue `probes`. No `scaling.tasks`. No CheckRun. Skip-if-running OperationLock kind=`collect` object_id=`evaluate-scale-proposals` stale 300 s. Per-site try/audit/continue. `raise_alert` only to open; no refresh of OPEN/ACKED/ACCEPTED; resolve OPEN/ACKED when not sustained or ineligible.

**C8 Copy.** Title = `TITLE` constant. Entity = `site:{domain or name}`. Body contains cost constants + `propose-mode does not launch` + site name + hot axis. `fix_action` = `FIX_ACTION` constant. Badge `single-instance-only` iff `scale_ready === false`. `single-instance` iff F8 one-copy. Never alias `single_instance = not scale_ready`. Never "instance" except those two tokens. No Approve/Launch/`Create target` control on the Finding. "approve action link" = `#/findings/{id}`.

**C9 Isolation.** No `Site.tier`. Partner sites refuse via C5.

**C10 Sensitive custody (Task 0 claims before code exists).** `scaling/pressure.py`, `scaling/evaluator.py`, `scaling/constants.py`, `monitor/host_metrics.py`. `scanner/modules/fallbacks.py` and `wizard/materialize.py` already listed. Do not claim `monitor/tasks.py` wholesale. Do not broaden to `scaling/**` or `frontend/**`.

**C11 Markers.** Function-level `@pytest.mark.req("<id>")` on `def test_*` only. No MUST id on skip-unless, live tests, or tests that do not prove that id’s text. Schema/persist tests stay unmarked. `P6-SCALER-DEMO` is `verify: demo` of the file — **do not** `@pytest.mark.req("P6-SCALER-DEMO")`. Frontend npm tests do not green registry ids; UX-P6 needs pytest greps `collect_markers` can see.

**C12 Registry.** Do not edit `conformance/requirements.yaml` in the round it judges except Task 0. Do not stub the demo file in Task 0.

**C13 Scale-ready predicates.** `_check_scale_ready` is always in `common_checks` (warning | ok). Fail (warning) on any of: files `*.sqlite3` / `*.sqlite3-wal` / files named `*-wal` / `*.parquet` / `*.duckdb`; settings/text with sqlite `ENGINE` or sqlite `DATABASE_URL`; `SESSION_ENGINE` locmem; Celery imported or required **and** a broker URL containing `localhost` or `127.0.0.1`; **Django-only media:** `MEDIA_ROOT` / `DEFAULT_FILE_STORAGE` / `STORAGES` without django-storages / `STORAGES` / S3-shaped setting. Absence of Django settings is not a media fail. Empty tree → `ok`. Reuse `texts`/`paths`. No schema bump. No 0014 backfill. Missing id → `scale_ready=False`.
