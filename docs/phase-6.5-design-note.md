# Phase 6.5 Design Note — Cheap remediations before overflow (T1 propose-only)

**Phase:** 6.5 per deploy-system-plan.md §9.5.3 (post Phase 6 T1 propose-mode)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r1 — cheap remediations first; still never provision.
**Estimate:** hours, not days. Protective cut: **D-097**. Phase 6 T1 MUST is on `master` @ `90acb3a`. Live AWS, auto mode, AMI, ScalePolicy, scale-in, disk-as-overflow, HMAC, U1, Azure, Phase 7 are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No new Hub migration. No `ScalePolicy`. No gunicorn column. No Cache-Control probe table.
**Panel:** §7 is binding. An Implementer who invents a path, env, Finding fingerprint, action id, threshold, or gate shape that §7 does not name is implementing the wrong design.

## 1. What lands this wave

Phase 6 T1 files `scale-out-proposal` on the first sustained streak. §9.5.3 says renting a server is last: ① Cache-Control / edge cache actually working, ② raise Cloudflare cache aggressiveness for anonymous traffic, ③ bump gunicorn workers / container CPU share (`2×CPU+1`). This wave inserts that cheap step **as a Finding**, still propose-only. Nothing launches. Nothing calls Cloudflare cache APIs. Nothing mutates gunicorn.

### 1.1 MUST

1. **Cheap before overflow.** When `evaluate_site` would have filed `scale-out-proposal` (same eligibility, same `sustained_pressure`, `refuse_if_attack` first), file kind **`scale-cheap-remediation`** fingerprint **`scale-cheap-remediation:{site.pk}`** instead, unless a Finding of that fingerprint is already **ACCEPTED**. OPEN/ACKED cheap: return it, do not `raise_alert` again, do not file overflow. ACCEPTED cheap + still sustained + still eligible: file overflow as Phase 6 T1 (same kind/fingerprint/body tokens). ACCEPTED overflow still stays quiet.

2. **Copy.** Title: `Cheap remediations before overflow (propose mode)`. Entity: `site:{domain or name}`. Body names the site, the hot axis, the three §9.5.3 steps (`Cache-Control`, `Cloudflare cache`, `gunicorn` `2×CPU+1`), and `propose-mode does not launch`. **`fix_action` exact:** `Ack is not launch. Apply cache and workers before overflow.` No `\binstance\b`. No Approve/Launch/`Create target`/`enroll`/`instance.create`. Pager link stays `#/findings/{id}`.

3. **Refuse and retract.** `refuse_if_attack` still first. On AttackRefuse / PartnerOverflowRefuse / ineligible / not-sustained: system-resolve OPEN/ACKED **both** `scale-cheap-remediation:{site.pk}` and `scale-out-proposal:{site.pk}` (`source="system"`). Do not file a consolation Finding.

4. **Never provision / never mutate live config.** No Target create. No `enroll_aws_target` / `InstanceCreateView` / `CloudProvider` / boto3. No `EdgeProtection` cache or security-level call from `scaling/`. No gunicorn `--workers` rewrite. AST-scan `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` unchanged from Phase 6. No `scale.approve`. No `scaling.tasks`.

5. **Honesty / gates.** Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. `conformance-6` remains the phase-6 gate and is **not** a review-round prereq. New MUST ids are phase 6, tier-less. Do not waive U1 / PART-K / `failed` / `not-collected`. Do not add `t4`. Do not stub `named-partner.md`. Rewrite `SCALE-SUSTAINED-PROPOSE` `text:` so five hot minutes file cheap first; overflow remains the ACCEPTED-cheap path. Do not mark `P6-SCALER-DEMO` on tests.

6. **F8.** REQUIRED_STATE_IDS gains `scale-cheap-remediation`. Seed a full P2 Finding (title/body/fix_action, topic `findings`); no Approve/Launch. NAV stays six.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| Cheap Finding before overflow; ACCEPTED cheap unblocks overflow | **MUST** |
| Three named steps in body; propose-mode does not launch | **MUST** |
| Retract cheap + overflow on refuse / ineligible / not-sustained | **MUST** |
| Never provision; never CF cache API; never gunicorn mutate | **MUST** |
| Live Cache-Control probe of the origin | **OUT** |
| `EdgeProtection` cache-level change | **OUT** |
| Auto bump workers / container CPU | **OUT** |
| ScalePolicy / auto mode / AMI / scale-in / provision | **OUT** |

## 2. Interfaces that change

**Constants (`scaling/constants.py`) add:**
- `CHEAP_KIND = "scale-cheap-remediation"`
- `CHEAP_TITLE = "Cheap remediations before overflow (propose mode)"`
- `CHEAP_FIX_ACTION = "Ack is not launch. Apply cache and workers before overflow."`

**Python:** `scaling/evaluator.py::evaluate_site` / `_evaluate_eligible` / `_retract` as §1.1. `monitor/alert_rules.py` gains the P2 kind. No Beat change. No HTTP.

## 3. Applicable registry reqs

Task 0 — new MUST ids, phase 6, no `tier:` key. `source: phase-6.5-design-note.md §3`. Rewrite `SCALE-SUSTAINED-PROPOSE` `text:` only (keep id). Compute `text_hash:`.

- `SCALE-SUSTAINED-PROPOSE` — `text:` five consecutive distinct UTC minutes of HostMetric samples in a 300s Hub-clock window over the same axis (mem_pct>85 or load1>cores) file Finding kind scale-cheap-remediation fingerprint scale-cheap-remediation:{site.pk} whose body includes Cache-Control, Cloudflare cache, gunicorn 2×CPU+1, and the sentence propose-mode does not launch; disk-only heat does not file; an ACCEPTED cheap finding plus still-sustained pressure files scale-out-proposal as before.
- `SCALE-CHEAP-BEFORE-OVERFLOW` — `phase: 6`, `verify: test`. `text:` evaluate_site files scale-cheap-remediation before scale-out-proposal; OPEN or ACKED cheap does not file overflow; ACCEPTED cheap unblocks scale-out-proposal; attack or partner refuse system-resolves OPEN or ACKED cheap.
- `SCALE-CHEAP-NO-MUTATE` — `phase: 6`, `verify: test`. `text:` cheap-remediation evaluate_site never creates a Target, never calls EdgeProtection cache or enroll_aws_target, and does not rewrite gunicorn workers.
- `SCALE-NEVER-ATTACK` — `text:` evaluate_site calls refuse_if_attack first; when the attack playbook is engaged no scale-cheap-remediation and no scale-out-proposal is filed and an OPEN or ACKED cheap or overflow Finding for that site is system-resolved.
- `SCALE-NEVER-PARTNER` — `text:` a PartnerSite never receives scale-cheap-remediation or scale-out-proposal even on sustained pressure and a quiet attack playbook; binding PartnerSite after file system-resolves an OPEN cheap or overflow Finding.

Keep `SCALE-SPIKE-NO-PROPOSE`, `SCALE-PROPOSE-NO-PROVISION`, `SCALE-READY-PREREQ`, `UX-P6-SINGLE-INSTANCE`, `P6-SCALER-DEMO` ids. Spike/ready tests stay true (no cheap, no overflow). F8 cheap seed is proven by SCALE-CHEAP-BEFORE-OVERFLOW, not by rewriting UX-P6-SINGLE-INSTANCE.

## 4. Exit demo

Same public scale-ready quiet site, five ram=90 minutes → Findings shows P2 **scale-cheap-remediation** `{pk}`, body contains `Cache-Control`, `Cloudflare cache`, `gunicorn`, `2×CPU+1`, `propose-mode does not launch`; Target count unchanged; no enroll. Accept-risk the cheap row with a reason → re-evaluate files **scale-out-proposal** with `0.0416` / `t3.medium`. Attack engaged: neither kind files; OPEN cheap resolves. Record: append `conformance/demos/phase-6.md` (do not claim a VM, auto, AMI, CF cache API, or gunicorn mutate).

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-097** Protective cut — T1 cheap remediations are a Finding, not a live mutate: Cache-Control / Cloudflare cache / gunicorn 2×CPU+1 named in copy; ACCEPTED cheap unblocks overflow; never provision; never CF cache API; never worker rewrite.
- **D-098** Fingerprint `scale-cheap-remediation:{site.pk}` only for the cheap episode. Kind already-pattern `scale-out-proposal`. Refuse retracts both fingerprints.
- **D-099** `conformance` / `review-round` stay phase 5 minus live. New ids phase 6 tier-less. U1 stays uncovered.

## 6. Protective cut (D-097)

MUST = cheap Finding + ACCEPTED-cheap overflow + retract + F8 seed + registry. Live cache probe / CF API / worker bump / ScalePolicy / auto / AMI / scale-in / provision are **OUT**.

## 7. Closed contract (binding)

**C1 Fingerprints.** `scale-cheap-remediation:{site.pk}` then `scale-out-proposal:{site.pk}`. Always pass `fingerprint=` explicitly.

**C2 Order.** Cheap unless that fingerprint is ACCEPTED. OPEN/ACKED cheap blocks overflow. ACCEPTED cheap does not refresh cheap.

**C3 Refuse.** `refuse_if_attack` first. Retract OPEN/ACKED cheap **and** overflow.

**C4 Never mutate.** No provision, no EdgeProtection cache call, no gunicorn rewrite, no new schema.

**C5 Copy.** Title/fix_action constants. Body has the three named tokens + `propose-mode does not launch`. No Approve/Launch. No `\binstance\b`.

**C6 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Do not mark `P6-SCALER-DEMO`.

**C7 Registry.** Task 0 may rewrite `SCALE-SUSTAINED-PROPOSE` `text:` and add the two new ids. Everyday gates stay phase 5.
