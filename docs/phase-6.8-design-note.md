# Phase 6.8 Design Note — Deploy live image onto overflow target (T1 Fake, skip DNS)

**Phase:** 6.8 per deploy-system-plan.md §9.5.4 step 3 (post Phase 6.7 T1 Fake enroll)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r2 — r1 MERGE-AFTER-FIXES folded (Architect SHIP pin + lock/heartbeat; Security veto refuse proofs + no-delay-to-primary; QE markers/inject; SRE site+overflow locks; UX copy C11). Binding §7.
**Estimate:** hours-to-a-day. Protective cut: **D-107**. Phase 6.7 T1 MUST is on `master` @ `f8c5d14` (pushed). DNS join, Tunnel replica, scale-in, ScalePolicy, auto, AMI, Beat enroll, `scale.approve`, live AWS as a test-plane requirement, HMAC, U1, Azure, Phase 7, live cheap mutate are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No `0015`. No `ScalePolicy`. No overflow FK. SiteInstance already exists — create a row, do not add columns. Do not retarget `Site.primary_target`.
**Panel:** §7 is binding.

## 1. What lands this wave

Phase 6.7 enrolls an ephemeral Target. §9.5.4 step 3 deploys the site's **current live image tag** (no rebuild) via the pipeline, skipping DNS (join is later). **Ack is still not launch.** The evaluator still never creates a Target or a Deployment. This wave adds `deploys/overflow.py::deploy_overflow_copy` and a T1 POST that runs it.

### 1.1 MUST

1. **Evaluator / enroll stay copy+enroll.** `evaluate_site` never creates a Deployment. `enroll_overflow_target` does not call deploy (6.7 tests stay green). AST-scan `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` still forbids the 6.7 list (`enroll_overflow_target` / `provision.overflow` included). Do not rewrite `SCALE-PROPOSE-NO-PROVISION` `text:`.

2. **`deploy_overflow_copy(site, target, *, transport, dns=None, sleep=None, cert_issuer=None)`** in `deploys/overflow.py`:
   - First site-level call: `refuse_if_attack(site)`. Attack/partner → `OverflowDeployError`, no Deployment, no Finding/CheckRun write.
   - Finding `scale-out-proposal:{site.pk}` must be **ACCEPTED**. Missing / OPEN / ACKED / RESOLVED → `OverflowDeployError` with exact `Ack is not launch. Propose-mode does not launch.`
   - `target` must be `kind=aws_ec2`, `lifecycle=ephemeral`, `status=ready`, `pk != site.primary_target_id`. Else refuse, no Deployment.
   - `pick_overflow_home` hit → refuse (idle exists; do not deploy to a rented box). Miss continues.
   - Require a succeeded Deployment on `site` with a stored `image_tag` artifact (live pin). If none → refuse.
   - Create Deployment on the current Manifest (same version; do **not** bump). `persist_steps`. Mark **BUILD** and **DNS** `SKIPPED`. Do **not** skip SHIP.
   - `begin_deploy(deployment, target=target)` still acquires **site** `kind=deploy` (serializes vs primary deploy). Overflow acquires **that** target `kind=deploy`, **not** `site.primary_target`. `_write_heartbeat` / `touch_heartbeat` heartbeats the held pair (site pk + overflow target pk), not hardcoded `site.primary_target_id`. Do not change `Site.primary_target`. Do not add `Deployment.target`. Do **not** `run_deploy.delay` (worker `execute(pk)` would `_default_transport` onto primary).
   - Call `execute(deployment.pk, transport=transport, dns=dns, sleep=sleep, cert_issuer=cert_issuer)` in-process with the overflow transport. `_assemble_desired`: if BUILD is SKIPPED, pin `image_tag` from `_pin_from_succeeded_history` even when SHIP is pending. `ensure_ship` uses `_desired_image_tag(desired)` (not `image_tag(git_sha, body)`). Do not docker build.
   - On SUCCEEDED: `SiteInstance.objects.create(site=site, target=target, desired_image_tag=pinned, desired_state=RUNNING, observed_state=RUNNING, internal_port=…)` using the same port as the desired dict (20000 default). Unique (target, port) is free on a new host.
   - Tests inject `PipelineTransport` (never live SSH). Do not invent `HUB_TEST_AWS_TOKEN`.

3. **T1 HTTP.** `POST /api/v1/sites/{pk}/overflow-deploy/` `OverflowDeployView`: `RequireRecentTouch`; serializer `{target: int, confirm_name: str}` with `confirm_name == target.host`. ACTION_TIERS new row `{id: "site.overflow_deploy", tier: "T1", label: "Deploy overflow copy"}`. `T1_HTTP["site.overflow_deploy"] = "/api/v1/sites/{pk}/overflow-deploy/"`. `make generate-client` (action_tiers.js). View loads site, target; calls `deploy_overflow_copy`. 201 `{deployment: id, target: id}`. 4xx on `OverflowDeployError`. Do not add `scale.approve`.

4. **No DNS join.** DNS step SKIPPED. `ensure_dns` is not called. FakeDnsProvider in tests must not receive `upsert_record` for this deploy.

5. **Honesty / gates.** Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. New MUST id phase 6, tier-less. Do not waive U1. Do not stub `named-partner.md`. Do not mark `P6-SCALER-DEMO`. Claim `deploys/overflow.py` in paths.yaml **and** CODEOWNERS.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| Same-image overflow deploy; BUILD skipped; live tag pinned | **MUST** |
| SHIP + start/health/route/smoke/cutover on overflow Target | **MUST** |
| DNS step skipped; primary_target unchanged | **MUST** |
| SiteInstance row on success | **MUST** |
| T1 POST + ACTION_TIERS `site.overflow_deploy` | **MUST** |
| DNS round-robin join / Tunnel replica | **OUT** |
| Scale-in / reaper / ScalePolicy / auto / AMI | **OUT** |
| Evaluator auto-deploy / `scale.approve` / Beat enroll | **OUT** |

## 2. Interfaces that change

**Python:**
- `deploys/overflow.py::deploy_overflow_copy` + `OverflowDeployError`.
- `deploys/pipeline.py::begin_deploy(deployment, *, target=None)` — default `site.primary_target`; overflow passes the ephemeral Target. Heartbeat/lock that pk.
- `deploys/pipeline.py::_assemble_desired` — if BUILD is SKIPPED, pin `image_tag` from `_pin_from_succeeded_history` even when SHIP is not skipped.
- `core/views.py::OverflowDeployView` + serializer.
- `hub/urls.py` path.
- `core/actions.py` ACTION_TIERS row; generate-client.
- `tests/test_webauthn_t1.py` `T1_HTTP` entry.

**Not changed:** `provision/overflow.py` enroll body (no deploy call). `scaling/evaluator.py` product.

## 3. Applicable registry reqs

Task 0 — new MUST id, phase 6, no `tier:`. `source: phase-6.8-design-note.md §3`. Do **not** rewrite `SCALE-PROPOSE-NO-PROVISION` or `SCALE-OVERFLOW-T1-ENROLL` `text:`. Extend `PHASE_6_MUST_IDS` + `allowed_sources`.

- `SCALE-OVERFLOW-SAME-IMAGE` — `phase: 6`, `verify: test`. `text:` deploy_overflow_copy onto an ephemeral overflow Target pins the site's last succeeded image_tag, skips BUILD and DNS, runs SHIP, does not change Site.primary_target, and creates a SiteInstance; OPEN or ACKED overflow refuses with Ack is not launch; evaluate_site still never creates a Deployment; tests inject PipelineTransport.

## 4. Exit demo

ACCEPTED overflow, enrolled ephemeral READY target, a prior succeeded deploy with image_tag artifact, PipelineTransport → Deployment SUCCEEDED; BUILD and DNS SKIPPED; SHIP not skipped; `primary_target` unchanged; SiteInstance exists; no DNS upsert. OPEN overflow → 4xx, no Deployment. Record: append `conformance/demos/phase-6.md`. Honest: no live AWS VM, no DNS join, no auto, no AMI.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-107** Protective cut — T1 same-image overflow deploy: pin live tag, skip BUILD and DNS, run SHIP on the ephemeral Target, lock that Target, do not retarget primary. Evaluator/enroll do not auto-deploy. Join DNS is 6.9.
- **D-108** ACTION_TIERS `site.overflow_deploy` T1. Confirm is type-the-host. PipelineTransport in tests. No overflow FK.
- **D-109** Everyday gates stay phase 5 minus live. New id phase 6 tier-less. U1 stays uncovered.

## 6. Protective cut (D-107)

MUST = pin+skip-BUILD+skip-DNS+SHIP-on-overflow-target+SiteInstance+T1 HTTP. DNS join / scale-in / ScalePolicy / auto / AMI / evaluator-deploy / live AWS CI are **OUT**.

## 7. Closed contract (binding)

**C1 Evaluator.** Never creates a Deployment. AST-scan of `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` still forbids the 6.7 list **and** `deploy_overflow_copy`. `enroll_overflow_target` does not call `deploy_overflow_copy` and does not +1 Deployment. Do not rewrite `SCALE-PROPOSE-NO-PROVISION` `text:`.

**C2 Pin.** BUILD SKIPPED ⇒ `_assemble_desired` sets `image_tag` from last succeeded artifact even if SHIP is pending. `ensure_ship` uses `_desired_image_tag(desired)`. Plant a stored tag ≠ `image_tag(current git_sha, body)` and assert SHIP uses the stored artifact. No docker build in `mutating_calls`. Do not bump Manifest.

**C3 Skip DNS.** DNS step SKIPPED. No `upsert_record`.

**C4 Target.** `begin_deploy(deployment, *, target=None)` default `primary_target`. Overflow: still site `kind=deploy` lock; target lock + heartbeat are the overflow pk, **not** `primary_target`. This deployment does not hold a deploy lock on `primary_target`. `execute` uses the injected overflow transport; never `_default_transport(site)`; never `run_deploy.delay`. Do not assign `Site.primary_target`. No `Deployment.target` column.

**C5 Gate.** First site-level call is `refuse_if_attack(site)`. Then ACCEPTED `scale-out-proposal:{pk}` only (missing / OPEN / ACKED / RESOLVED refuse). Then ephemeral READY non-primary; idle pick miss. Gate `OverflowDeployError` does not `raise_alert`, `_retract`, write Finding, or write CheckRun. OPEN/ACKED/missing/RESOLVED detail is exact `FIX_ACTION`. Catch `AttackRefuse` / `PartnerOverflowRefuse` → `OverflowDeployError`.

**C6 HTTP.** T1 `site.overflow_deploy`, label exactly `Deploy overflow copy`. RequireRecentTouch + `confirm_name == target.host`. Serializer `{target: int, confirm_name: str}` only — view never binds `transport` / `provider` / `image_tag` / `ssh_key_ref` from the request. HTTP inject: wrap `deploys.overflow.deploy_overflow_copy` with `kwargs.setdefault("transport", PipelineTransport())` and `dns=FakeDnsProvider()`; patch the module attribute the view calls. generate-client.

**C7 SiteInstance.** One row on SUCCEEDED. No new columns.

**C8 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. `SCALE-OVERFLOW-SAME-IMAGE` only on tests that prove that id's text. Do not mark `P6-SCALER-DEMO`. Do not mark 6.7 enroll tests or `test_env_lifecycle.py` with the new id. Do not mark RequireRecentTouch-only tests with the new id. Evaluate-site Deployment-count test carries `SCALE-OVERFLOW-SAME-IMAGE` (not `SCALE-PROPOSE-NO-PROVISION`).

**C9 Registry.** Task 0 adds `SCALE-OVERFLOW-SAME-IMAGE`, claims `deploys/overflow.py`.

**C10 Module arrows.** `deploys/overflow.py` → `deploys.pipeline` / `scaling.attack_gate` / `scaling.destination` / `scaling.constants`. `scaling/` ↛ `deploys`. View → `deploys.overflow` only.

**C11 Copy.** ACTION_TIERS label exactly `Deploy overflow copy`. Finding chrome unchanged (no Approve / Launch / `Deploy overflow copy` / `Create target` / ActionButton on the Finding or F8 overflow renderer). NAV six. No new F8 id. F8 `scale-out-proposal` seed stays no-idle `0.0416` / `t3.medium`. No `\binstance\b` in new operator copy (label, OverflowDeployError details, demo, 4xx blobs) except existing `single-instance` / `single-instance-only` and existing `instance.create` / `instance.terminate` ids. File map does not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`.
