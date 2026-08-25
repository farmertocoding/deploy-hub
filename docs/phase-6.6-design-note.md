# Phase 6.6 Design Note — Idle registered machine before t3.medium (T1 propose-only)

**Phase:** 6.6 per deploy-system-plan.md §9.5.4 step 1 (post Phase 6.5 cheap-then-overflow)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r2 — r1 MERGE-AFTER-FIXES folded (Architect C6; Security veto Hub-host + partner miss-path; QE proofs/NAMED/due-set; SRE SELECT-only + Beat restated; UX C7 idle TDD). Binding §7.
**Estimate:** hours, not days. Protective cut: **D-101**. Phase 6.5 T1 MUST is on `master` @ `5392d57`. Live AWS, auto mode, AMI, ScalePolicy, scale-in, provision, DNS join, Tunnel replica, disk-as-overflow, HMAC, U1, Azure, Phase 7, live Cache-Control / CF cache API / gunicorn mutate are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No new Hub migration. No `ScalePolicy`. No gunicorn column. No destination FK on Finding.
**Panel:** §7 is binding. An Implementer who invents a path, env, Finding fingerprint, action id, threshold, or gate shape that §7 does not name is implementing the wrong design.

## 1. What lands this wave

Phase 6.5 files `scale-cheap-remediation` first; ACCEPTED cheap unblocks `scale-out-proposal` whose body always names `0.0416` / `t3.medium`. §9.5.4 step 1 says renting is last among destinations too: an idle second computer of yours is checked first because it is free. This wave inserts that pick **into the overflow Finding body**. Nothing launches. No Target is created. No `ScalePolicy` table.

### 1.1 MUST

1. **Idle before cloud quote.** When `evaluate_site` files `scale-out-proposal` (same eligibility, same `sustained_pressure`, `refuse_if_attack` first, ACCEPTED cheap), call `pick_overflow_home(site, *, now)` **only on that file path** and write the returned tokens into the body. Fingerprint stays `scale-out-proposal:{site.pk}`. Title and `fix_action` stay the Phase 6 constants. OPEN/ACKED/ACCEPTED overflow still does not re-`raise_alert`. Cheap path does not call pick.

2. **Pick rule (fail-closed, SELECT-only).** Eligible overflow home = a `Target` that is all of: `status=ready`, `lifecycle=permanent`, `pk != site.primary_target_id`, not a partner destination, not the Hub host, and **current headroom**. Partner destination: `target.pk == int(x)` for any `x` in **any** `Partner.destination_order` (skip values that raise `TypeError`/`ValueError`). Hub host: `(target.host or "").casefold()` equals `(urlparse(settings.HUB_PUBLIC_URL).hostname or "").casefold()` when that hostname is non-empty; empty `HUB_PUBLIC_URL` → no extra skip. Duplicate the four-line hostname helper in `scaling/destination.py`; do **not** import `core.partner_jobs` or `monitor.topology` into `scaling/`. Current headroom = the latest `HostMetric` for that target with Hub `ts` in `[now - MAX_SAMPLE_GAP_S, now]` mapped to `{ram, load, cores}` and **`has_headroom` returns True**. Missing row, stale row, or `has_headroom` False → skip that target. Among remaining, pick **lowest pk**. Do not inspect `SiteInstance`. Do not pick `ephemeral` / `pending` / `error` / `decommissioned`.

3. **Copy.** Idle hit interpolates **only** `target.host` from the Target row. Body keeps the Phase 6 estimate sentence with swapped tokens: `Overflow estimate 0 USD/hour on own-machine`, plus `idle registered machine` and that host, plus `propose-mode does not launch`. No-idle miss: keep the Phase 6 body (`Overflow estimate 0.0416 USD/hour on t3.medium. propose-mode does not launch.`). **`fix_action` unchanged:** `Ack is not launch. Propose-mode does not launch.` Title unchanged. No `\binstance\b`. No Approve/Launch/`Create target`/`enroll`/`instance.create`. Entity stays `site:{domain or name}`. Do not write `ssh_key_ref` / `host_key_fingerprint` / `provider_ref` / `collect_payload` / destination_order pks into the Finding.

4. **Refuse and retract.** Unchanged from 6.5: `refuse_if_attack` first; AttackRefuse / PartnerOverflowRefuse / ineligible / not-sustained system-resolves OPEN/ACKED **both** fingerprints. Do not file a consolation Finding. A PartnerSite still never receives overflow (the pick never runs).

5. **Never provision / never mutate.** `pick_overflow_home` is a **read-only SELECT** of `Target` + the latest in-window `HostMetric`. No `save` / `create` / `update` / `delete` / `select_for_update`. No `OperationLock`. No `CheckRun` / `AuditEvent` / `Finding` write. No `collect_payload`. No Target create. No `enroll_aws_target` / `InstanceCreateView` / `CloudProvider` / boto3. AST-scan `scaling/` **and** `monitor/tasks.py` **and** `monitor/host_metrics.py`. No `scale.approve`. No `scaling.tasks`. Do not catch `Exception` inside pick to synthesize miss tokens — let it reach `evaluate_site`'s existing `except Exception: return None` (do not file). Do not call pick from `evaluate_all`.

6. **Honesty / gates.** Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. `conformance-6` remains the phase-6 gate and is **not** a review-round prereq. New MUST ids are phase 6, tier-less. Do not waive U1 / PART-K / `failed` / `not-collected`. Do not add `t4`. Do not stub `named-partner.md`. Rewrite `SCALE-SUSTAINED-PROPOSE` overflow sentence so ACCEPTED-cheap overflow names idle-or-t3.medium. Do not mark `P6-SCALER-DEMO` on tests. F8 `scale-out-proposal` seed stays the no-idle `0.0416` / `t3.medium` case. No new F8 id.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| Overflow body names idle registered machine (0 / own-machine) when one exists | **MUST** |
| Else keep 0.0416 / t3.medium | **MUST** |
| Partner destination / Hub host / ephemeral / stale metrics never picked | **MUST** |
| Never provision; SELECT-only pick; no ScalePolicy; no schema | **MUST** |
| Create ephemeral Target / enroll AWS / deploy same image | **OUT** |
| DNS round-robin join / Tunnel replica | **OUT** |
| Scale-in + ephemeral reaper | **OUT** |
| ScalePolicy table / auto mode / AMI / live AWS pricing | **OUT** |
| Live cheap mutate (Cache-Control / CF cache / gunicorn) | **OUT** |

## 2. Interfaces that change

**Constants (`scaling/constants.py`) add:**
- `IDLE_COST_USD = "0"`
- `IDLE_SIZE = "own-machine"`

**Python:**
- `scaling/pressure.py::has_headroom(sample) -> bool` — pure, no Django. True iff `sample` is a mapping **and** `ram` is a number `<= 85` **and** `load` is a number **and** load is not over (`cores` missing/None or `cores < 1` or `load <= cores`). Non-mapping / `None` ram / `None` load → False. Disk is not an axis.
- `scaling/destination.py::pick_overflow_home(site, *, now) -> tuple[str | None, str, str]` — `(host_or_none, cost, size)`. Django **SELECT only**. Loads latest in-window HostMetric, maps `{ram, load, cores}`, **calls** `has_headroom` (does not inline 85/cores). Idle hit: `(target.host, IDLE_COST_USD, IDLE_SIZE)`. Miss: `(None, OVERFLOW_HOURLY_USD, OVERFLOW_SIZE)`. No `except Exception` that returns miss tokens.
- `scaling/evaluator.py` overflow **file** path inside `_evaluate_eligible` calls `pick_overflow_home` with the same `clock` and interpolates the returned tokens into `Overflow estimate {cost} USD/hour on {size}`. Cheap path, existing-overflow return, and `evaluate_all` do not call pick. Do not edit `evaluate_all` / `_acquire_cycle_lock` / `CYCLE_LOCK*` / `monitor/tasks.py` / `hub/settings/base.py`.

No HTTP. No Beat change. No serializer change. No F8 new state.

## 3. Applicable registry reqs

Task 0 — new MUST id, phase 6, no `tier:` key. `source: phase-6.6-design-note.md §3`. Rewrite `SCALE-SUSTAINED-PROPOSE` `text:` only (keep id). Compute `text_hash:`. Extend `PHASE_6_MUST_IDS` and `allowed_sources`.

- `SCALE-SUSTAINED-PROPOSE` — `text:` five consecutive distinct UTC minutes of HostMetric samples in a 300s Hub-clock window over the same axis (mem_pct>85 or load1>cores) file Finding kind scale-cheap-remediation fingerprint scale-cheap-remediation:{site.pk} whose body includes Cache-Control, Cloudflare cache, gunicorn 2×CPU+1, and the sentence propose-mode does not launch; disk-only heat does not file; an ACCEPTED cheap finding plus still-sustained pressure files scale-out-proposal whose body names idle registered machine, 0, and own-machine when a READY permanent non-primary non-partner-destination non-hub-host Target has current headroom, otherwise 0.0416 and t3.medium.
- `SCALE-OVERFLOW-IDLE-FIRST` — `phase: 6`, `verify: test`. `text:` evaluate_site overflow body prefers a READY permanent non-primary Target with current headroom (latest HostMetric within 120s, ram not >85 and load not >cores) at 0 USD/hour on own-machine over t3.medium; ephemeral, pending, error, decommissioned, partner destination_order, hub host matching HUB_PUBLIC_URL hostname, stale or missing metrics, and the site's primary_target are never picked; propose-mode still does not create a Target.
- Keep `SCALE-CHEAP-BEFORE-OVERFLOW`, `SCALE-CHEAP-NO-MUTATE`, `SCALE-NEVER-ATTACK`, `SCALE-NEVER-PARTNER`, `SCALE-SPIKE-NO-PROPOSE`, `SCALE-PROPOSE-NO-PROVISION`, `SCALE-READY-PREREQ`, `UX-P6-SINGLE-INSTANCE`, `P6-SCALER-DEMO`. Spike/ready/cheap tests stay true. Do not rewrite `test_five_hot_mem_minutes_file_proposal_with_cost`, `test_accepted_cheap_unblocks_overflow`, or `test_five_hot_load_minutes_file_proposal`. `SCALE-PROPOSE-NO-PROVISION` AST list already covers `scaling/` so `destination.py` is in the scan.

## 4. Exit demo

Same public scale-ready quiet site, five ram=90 minutes, ACCEPTED cheap → overflow. (a) No other ready Target with headroom → body contains `0.0416` / `t3.medium`; Target count unchanged. (b) A second READY permanent non-hub Target with a latest ram=10 sample at `now` → body contains `idle registered machine`, that host, `0`, `own-machine`, `propose-mode does not launch`; Target count unchanged; no enroll. Attack engaged: neither kind files. Record: append `conformance/demos/phase-6.md` (do not claim a VM, auto, AMI, DNS join, or ScalePolicy).

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-101** Protective cut — T1 overflow destination pick is copy, not provision: idle registered READY permanent non-primary non-partner non-hub Target with current headroom is named at `0` / `own-machine`; else `0.0416` / `t3.medium`; never create a Target; no ScalePolicy.
- **D-102** Current headroom is `has_headroom` on the latest HostMetric within `MAX_SAMPLE_GAP_S`: mapping + numeric ram `<= 85` + numeric load + load not over; `None` ram or `None` load is False. Pick SELECT-only, calls `has_headroom`, lowest pk. Hub host and partner `destination_order` (int-coerced) never picked. Pick exceptions raise through (do not file).
- **D-103** `conformance` / `review-round` stay phase 5 minus live. New id phase 6 tier-less. U1 stays uncovered. F8 overflow seed stays the no-idle quote. Beat / CYCLE_LOCK / no-CheckRun stay Phase 6 values.

## 6. Protective cut (D-101)

MUST = idle-or-t3 body on overflow + pick exclusions (partner dest, Hub host, ephemeral, stale) + never provision + registry. Create Target / enroll / deploy / DNS join / scale-in / ScalePolicy / auto / AMI / cheap mutate are **OUT**.

## 7. Closed contract (binding)

**C1 Fingerprints.** Unchanged: `scale-cheap-remediation:{site.pk}` then `scale-out-proposal:{site.pk}`. Always pass `fingerprint=` explicitly.

**C2 Order.** Unchanged: cheap unless that fingerprint is ACCEPTED. Pick runs **only** on the overflow **file** path inside `_evaluate_eligible`. Do not call pick from `evaluate_all`, the cheap path, or the existing-overflow return.

**C3 Refuse.** Unchanged: `refuse_if_attack` first. Retract OPEN/ACKED cheap **and** overflow.

**C4 Never mutate.** No provision, no EdgeProtection cache call, no gunicorn rewrite, no new schema, no ScalePolicy, no Finding destination FK. Pick is SELECT-only (C5).

**C5 Pick.** Eligible = READY + permanent + not primary + not partner-destination (`pk == int(x)` on any `Partner.destination_order`, skip bad coerce) + not Hub host (C5b) + current headroom. Lowest pk. Miss → `(None, "0.0416", "t3.medium")`. Hit → `(host, "0", "own-machine")`. SELECT `Target` and that row’s latest in-window `HostMetric`; map `{ram, load, cores}`; **call** `has_headroom`. No write, no `select_for_update`, no lock, no `collect_payload`. Do not catch `Exception` to synthesize miss tokens. Do not inspect `SiteInstance`. Do not add a zone filter.

**C5b Hub host.** Ineligible when `HUB_PUBLIC_URL` hostname is non-empty and equals `target.host` casefold. Helper lives in `scaling/destination.py` (urlparse, same four lines as `monitor.topology._hub_hostname`). Empty hostname → no extra skip. Do not import `core.partner_jobs`. Do not add `Target.is_hub`.

**C6 Headroom.** `has_headroom(sample)` is pure, no Django; True iff `sample` is a mapping **and** `ram` is a number `<= 85` **and** `load` is a number **and** load is not over (`cores` missing/None or `cores < 1` or `load <= cores`). Non-mapping / `None` ram / `None` load → False. Stale or missing HostMetric (latest `ts` not in `[now - MAX_SAMPLE_GAP_S, now]`, or no row) → pick skips that target. Disk is not an axis.

**C7 Copy.** Idle body: `Overflow estimate 0 USD/hour on own-machine` plus `idle registered machine` plus **only** `target.host` plus `propose-mode does not launch`. Miss body: `Overflow estimate 0.0416 USD/hour on t3.medium. propose-mode does not launch.` Title/`fix_action` unchanged. No Approve/Launch. No `\binstance\b`. From the Target row interpolate **only** `host`.

**C8 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Do not mark `P6-SCALER-DEMO`. Do not mark `has_headroom` unit tests. Idle `SCALE-SUSTAINED-PROPOSE` mark must use `_overflow_after_cheap`.

**C9 Registry.** Task 0 rewrites `SCALE-SUSTAINED-PROPOSE` `text:`, adds `SCALE-OVERFLOW-IDLE-FIRST`, extends `PHASE_6_MUST_IDS` + `allowed_sources` with `phase-6.6-design-note.md §3`. Everyday gates stay phase 5. Claim `scaling/destination.py` in paths.yaml **and** CODEOWNERS. Pin `SCALE-SUSTAINED-PROPOSE` `text:` contains `idle registered machine`, `own-machine`, `0.0416`, **and** `t3.medium`.

**C10 F8.** Existing `scale-out-proposal` seed stays no-idle `0.0416` / `t3.medium`. No new REQUIRED_STATE_ID. Do not rewrite `simulation/seed_v1.json` overflow or cheap seeds.

**C11 Beat / lock / CheckRun.** Unchanged from Phase 6: `evaluate-scale-proposals` → `monitor.tasks.evaluate_scale_proposals`, 60 s, queue `probes`; no `scaling.tasks`; `CYCLE_LOCK` stays `("target", "evaluate-scale-proposals", "collect")` stale 300 s; no CheckRun read or write. Do not edit `evaluate_all` / `_acquire_cycle_lock` / `CYCLE_LOCK*` / `monitor/tasks.py` / `hub/settings/base.py`. Extend `test_evaluate_scale_proposals_does_not_write_checkrun` AST paths to include `scaling/destination.py`.
