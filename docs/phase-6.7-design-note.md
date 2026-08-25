# Phase 6.7 Design Note — T1 Fake overflow enroll (propose-gated, still never auto)

**Phase:** 6.7 per deploy-system-plan.md §9.5.4 step 2 (post Phase 6.6 idle-first copy)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r2 — r1 MERGE-AFTER-FIXES folded (Architect AST ban; Security veto missing/RESOLVED/partner + spec-tag pk; QE markers/Fake HTTP inject/acceptance calls; SRE no consolation Finding on gate refuse). Binding §7.
**Estimate:** hours, not days. Protective cut: **D-104**. Phase 6.6 T1 MUST is on `master` @ `5355bce` (pushed). Live AWS as a test-plane requirement, auto mode, AMI, ScalePolicy, scale-in, DNS join, Tunnel replica, deploy-same-image, disk-as-overflow, HMAC, U1, Azure, Phase 7, live cheap mutate are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No `0015`. No `ScalePolicy`. No overflow FK on Target or Finding. No SiteInstance attach (that is deploy, OUT).
**Panel:** §7 is binding. An Implementer who invents a path, env, Finding fingerprint, action id, threshold, or gate shape that §7 does not name is implementing the wrong design.

## 1. What lands this wave

Phase 6.6 names an idle registered machine or quotes `t3.medium`. §9.5.4 step 2 is provision, tagged `lifecycle: ephemeral`. **Ack is still not launch (D-093).** The evaluator still never creates a Target. This wave gates the existing T1 `instance.create` POST: an optional `overflow_site` pk enrolls an ephemeral AWS-shaped Target through `enroll_aws_target` **only when** the overflow Finding is ACCEPTED, idle pick missed, and `refuse_if_attack` is quiet. Tests inject `FakeCloudProvider`. Do not add `scale.approve`. Do not deploy. Do not join DNS.

### 1.1 MUST

1. **Evaluator never provisions.** `evaluate_site` / `pick_overflow_home` / `has_headroom` stay copy. AST-scan `scaling/` **and** `monitor/tasks.py` **and** `monitor/host_metrics.py` still forbids the 6.6 list **and** `enroll_overflow_target` / `provision.overflow`. `SCALE-PROPOSE-NO-PROVISION` `text:` unchanged. No `scaling.tasks`. No Beat enroll.

2. **Overflow enroll is T1 `instance.create`.** Same URL, same `RequireRecentTouch`, same type-the-name (`confirm_name == host`). `InstanceCreateSerializer` gains optional `overflow_site` (integer Site pk, required=False). Absent `overflow_site`: today's enroll unchanged (including default `t3.micro`). Present: call `provision.overflow.enroll_overflow_target` (new). Do **not** add ACTION_TIERS `scale.approve` or `overflow.enroll`. Label stays `Create target`.

3. **Gate (fail-closed).** `enroll_overflow_target(*, site, host, zone, confirm_name, provider=None, make_transport=None, now=None)`:
   - First **site-level** call is `refuse_if_attack(site)` (`PartnerOverflowRefuse` already lives inside it). Catch `AttackRefuse` / `PartnerOverflowRefuse` → `EnrollError`, no Target, **no** `raise_alert` / `_retract` / Finding write / CheckRun.
   - Finding `scale-out-proposal:{site.pk}` must exist and be **ACCEPTED**. Missing / OPEN / ACKED / RESOLVED → `EnrollError` with exact detail `Ack is not launch. Propose-mode does not launch.` Same no-Finding-write rule.
   - `pick_overflow_home(site, now=now or timezone.now())`: if `host_or_none` is not None → `EnrollError` (idle registered machine exists; do not rent). Miss continues. Same no-Finding-write rule.
   - Then `enroll_aws_target(..., instance_type=OVERFLOW_SIZE, provider=..., make_transport=...)`. `OVERFLOW_SIZE` is `t3.medium`. Lifecycle stays the enroll default `ephemeral`. Spec tags **must** include `overflow_site` as the **integer Site pk only** (int or `str(pk)`). Spec / kwargs / tags contain no `collect_payload`, `ssh_key_ref`, `private_key`, `ssh_private_key`, or AWS access-key material. Existing `aws_enroll` create-failure helpers fire only **after** gates pass.
   - Gate `EnrollError` does not write Finding or CheckRun. Do not `except Exception` in `overflow.py` to file. Return the Target. View 201 shape unchanged (`id`, `host`, `kind`). View 400s `confirm_name != host` before this call; overflow tests still pin type-the-name.

4. **Fake in tests; no invented AWS token.** Overflow tests inject `FakeCloudProvider` (and FakeTransport) the same way `tests/test_aws_enroll.py` does. Do not call live `cloud_provider_for` in those tests. Do not invent `HUB_TEST_AWS_TOKEN`. Production overflow enroll reuses `enroll_aws_target` → `cloud_provider_for` (existing wall). Unconfigured AWS still `EnrollError`.

5. **Copy / chrome.** Finding title/`fix_action`/body tokens unchanged (idle-or-t3). No Approve/Launch on the Finding. No new NAV item. No `\binstance\b` in overflow Finding copy (the existing `instance.create` action id and `/api/v1/instance/create/` path stay). F8 overflow seed stays no-idle quote. No new F8 id.

6. **Honesty / gates.** Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. New MUST id phase 6, tier-less. Do not waive U1 / PART-K / `failed` / `not-collected`. Do not add `t4`. Do not stub `named-partner.md`. Do not mark `P6-SCALER-DEMO`. Claim `provision/overflow.py` in paths.yaml **and** CODEOWNERS.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| T1 overflow enroll via existing `instance.create` + `overflow_site` | **MUST** |
| ACCEPTED overflow required; OPEN/ACKED → Ack is not launch | **MUST** |
| Idle pick hit refuses enroll; evaluator still never creates a Target | **MUST** |
| Tests inject FakeCloudProvider; no invented AWS token | **MUST** |
| Deploy same image onto the overflow Target | **OUT** |
| DNS round-robin join / Tunnel replica | **OUT** |
| Scale-in + ephemeral reaper for overflow VMs | **OUT** |
| ScalePolicy / auto / AMI / `scale.approve` / Beat enroll | **OUT** |
| Live AWS as a test-plane requirement | **OUT** (Joseph) |
| SiteInstance attach / overflow_of column | **OUT** |

## 2. Interfaces that change

**HTTP:** `InstanceCreateSerializer.overflow_site` = `IntegerField(required=False)`. POST with it set → `provision.overflow.enroll_overflow_target`. GET cost estimate unchanged.

**Python:**
- `provision/overflow.py::enroll_overflow_target` as §1.1.3. Imports `scaling.destination.pick_overflow_home`, `scaling.attack_gate.refuse_if_attack`, `provision.aws_enroll.enroll_aws_target`. Does not import `intake`. Does not write Findings except via existing enroll failure helpers.
- `core/views.py::InstanceCreateView.post` branches on `overflow_site` after serializer + confirm_name check.
- No Beat change. No evaluator change except tests that already AST-scan `scaling/` (must stay green).

**Constants:** reuse `OVERFLOW_SIZE` / `OVERFLOW_HOURLY_USD` / `FIX_ACTION`. Do not add `scale.approve`.

## 3. Applicable registry reqs

Task 0 — new MUST id, phase 6, no `tier:` key. `source: phase-6.7-design-note.md §3`. Do **not** rewrite `SCALE-PROPOSE-NO-PROVISION` `text:` (evaluator still never creates a Target). Compute `text_hash:` for the new id. Extend `PHASE_6_MUST_IDS` + `allowed_sources`.

- `SCALE-OVERFLOW-T1-ENROLL` — `phase: 6`, `verify: test`. `text:` instance.create with overflow_site enrolls an ephemeral Target only when a Finding scale-out-proposal:{site.pk} is ACCEPTED, pick_overflow_home misses (no idle registered machine), and refuse_if_attack is quiet; OPEN or ACKED overflow refuses with Ack is not launch. Propose-mode does not launch; T1 RequireRecentTouch and type-the-name still apply; evaluate_site still never creates a Target; tests inject FakeCloudProvider.
- Keep `SCALE-SUSTAINED-PROPOSE`, `SCALE-OVERFLOW-IDLE-FIRST`, `SCALE-CHEAP-*`, `SCALE-NEVER-ATTACK`, `SCALE-NEVER-PARTNER`, `SCALE-SPIKE-NO-PROPOSE`, `SCALE-PROPOSE-NO-PROVISION`, `SCALE-READY-PREREQ`, `UX-P6-SINGLE-INSTANCE`, `P6-SCALER-DEMO`. Existing `instance.create` tests stay; do not rewrite them to require `overflow_site`.

## 4. Exit demo

Public scale-ready quiet site, ACCEPTED cheap, five ram=90 minutes, no idle machine → overflow Finding `0.0416` / `t3.medium`. T1 `instance.create` with `overflow_site={pk}`, FakeCloudProvider, touch + type-the-name → Target count +1, `kind=aws_ec2`, `lifecycle=ephemeral`. OPEN overflow + same POST → 4xx, Target count unchanged. Idle registered machine present → 4xx, Target count unchanged. Attack engaged → 4xx. Record: append `conformance/demos/phase-6.md`. Honest: no live AWS VM, no DNS join, no auto, no AMI.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-104** Protective cut — T1 overflow provision is gated `instance.create` (`overflow_site`), not Beat and not `scale.approve`. ACCEPTED overflow unblocks Fake enroll; Ack is not launch; idle pick hit refuses renting; evaluator still never creates a Target; no deploy / DNS / scale-in / ScalePolicy.
- **D-105** Overflow enroll lives in `provision/overflow.py` (calls pick + refuse + `enroll_aws_target`). `scaling/` does not import `provision`. No new ACTION_TIERS id. No schema. Spec tag `overflow_site` is the integer pk only.
- **D-106** Everyday `conformance` / `review-round` stay phase 5 minus live. New id phase 6 tier-less. U1 stays uncovered. Live AWS remains Joseph for the test plane; tests inject FakeCloudProvider.

## 6. Protective cut (D-104)

MUST = T1 overflow enroll gate + idle/attack/OPEN refuse + Fake tests + registry. Deploy / DNS / scale-in / ScalePolicy / auto / AMI / Beat enroll / `scale.approve` / live AWS in CI are **OUT**.

## 7. Closed contract (binding)

**C1 Evaluator.** `evaluate_site` never calls `enroll_aws_target` / `InstanceCreateView` / `enroll_overflow_target`. `SCALE-PROPOSE-NO-PROVISION` holds. AST-scan of `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` forbids the 6.6 list **and** `enroll_overflow_target` / `provision.overflow`. Do not rewrite that id's `text:`.

**C2 HTTP.** Same `POST /api/v1/instance/create/`. Optional `overflow_site`. T1 `RequireRecentTouch` + `confirm_name == host`. No `scale.approve`. No new ACTION_TIERS row.

**C3 Gate order.** First site-level call is `refuse_if_attack(site)`. Then ACCEPTED `scale-out-proposal:{site.pk}` only (missing / OPEN / ACKED / RESOLVED refuse). Then `pick_overflow_home` (hit → refuse rent). Then `enroll_aws_target(..., instance_type=t3.medium)`. OPEN/ACKED/missing/RESOLVED detail is exactly `Ack is not launch. Propose-mode does not launch.` Gate `EnrollError` does not `raise_alert`, `_retract`, write Finding, or write CheckRun.

**C4 Fake / no invented token.** Overflow tests inject `FakeCloudProvider`. Do not invent `HUB_TEST_AWS_TOKEN`. Do not add a second CloudProvider constructor.

**C5 Schema.** `0014` closed. No overflow FK. No SiteInstance write. Spec tags `overflow_site` is the integer Site pk only (int or `str(pk)`). Spec / kwargs / tags contain no `collect_payload`, `ssh_key_ref`, `private_key`, `ssh_private_key`, or AWS access-key material. View never binds `provider` from the request.

**C6 Copy.** Finding chrome unchanged. No Approve/Launch on the Finding. NAV six. No new F8 id. F8 overflow seed stays no-idle `0.0416` / `t3.medium`.

**C7 Beat / lock.** Unchanged: `evaluate-scale-proposals` → `monitor.tasks.evaluate_scale_proposals`, 60 s, `probes`; `CYCLE_LOCK` unchanged; no CheckRun; no `scaling.tasks`. Overflow enroll is request-path only.

**C8 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Do not mark `P6-SCALER-DEMO`. Do not mark existing no-`overflow_site` create tests with `SCALE-OVERFLOW-T1-ENROLL`.

**C9 Registry.** Task 0 adds `SCALE-OVERFLOW-T1-ENROLL`, extends `PHASE_6_MUST_IDS` + `allowed_sources` with `phase-6.7-design-note.md §3`, claims `provision/overflow.py` in paths.yaml and CODEOWNERS. Do not rewrite `SCALE-PROPOSE-NO-PROVISION` `text:`.

**C10 Module arrows.** `provision/overflow.py` → `scaling.destination` / `scaling.attack_gate` / `scaling.constants` (`OVERFLOW_SIZE`, `FIX_ACTION`) / `provision.aws_enroll`. `scaling/` ↛ `provision`. `core/views.py` → `provision.overflow` only on the overflow_site branch. BANNED_IMPORTS on the C1 AST paths include `enroll_overflow_target`.
