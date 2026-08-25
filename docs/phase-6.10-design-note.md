# Phase 6.10 Design Note — Scale-in overflow + ephemeral reaper (T1 Fake)

**Phase:** 6.10 per deploy-system-plan.md §9.5.5 (post Phase 6.9 join traffic)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r2 — r1 MERGE-AFTER-FIXES folded (Architect C4 1-IPv4 / dual-lock / reaper AST / orphan playbook; Security partner-first no refuse_if_attack / unjoin-before-DECOMMISSIONED-skip / RecordingCloud audit; QE NAMED calls / AuditEvent.update(ts) / tunnel test; SRE unjoin-fail-aborts-terminate / get_instance None / honest not-designed-out; UX 4xx pins + Ack-does-not-stop-billing). Binding §7.
**Estimate:** hours-to-a-day. Protective cut: **D-113**. Phase 6.9 T1 MUST is on `master` @ `974f3d0`. ScalePolicy, auto, AMI, Beat enroll, `scale.approve`, evaluator auto-deploy / auto-scale-in, 30s origin health-pull, Cloudflare Load Balancing, live AWS as a test-plane requirement, HMAC, U1, Azure, Phase 7, live drain window, Hub-vaulted tunnel JWT, and the 6.8 leftover lock-on-seam-refuse are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No `0015`. No `ScalePolicy`. No overflow FK. No `Target.created_at` (age the reaper from `AuditEvent` `instance.create`). No new `SiteInstance` / `DnsRecord` / `OperationLock.Kind` / `CheckRun.Kind` columns. Do not retarget `Site.primary_target`.
**Panel:** §7 is binding.

## 1. What lands this wave

Phase 6.9 joins the overflow origin (or a tunnel replica sibling). §9.5.5 is the matching teardown: remove the overflow origin from DNS → stop the copy → **terminate the cloud target and its disk** → verify via the CloudProvider port that it is gone. Ephemeral targets that outlive the episode are **flagged** (Finding), not auto-killed — Ack is still not launch. The evaluator still never terminates. This wave adds `deploys/overflow.py::scale_in_overflow` (T1 POST) and `monitor/overflow_reaper.py::reap_stale_ephemerals` (callable; no Beat).

### 1.1 MUST

1. **Evaluator / enroll / deploy / join stay copy+enroll+ship+join.** `evaluate_site` never creates a Deployment, never joins, never scale-ins, never terminates. `enroll_overflow_target` / `deploy_overflow_copy` / `join_overflow_traffic` do not call scale-in. AST-scan `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` still forbids the 6.9 list **and** `scale_in_overflow` / `reap_stale_ephemerals` / `terminate_aws_target`. Do not rewrite `SCALE-PROPOSE-NO-PROVISION` / `SCALE-OVERFLOW-T1-ENROLL` / `SCALE-OVERFLOW-SAME-IMAGE` / `SCALE-OVERFLOW-JOIN-TRAFFIC` `text:`. Do not edit `evaluate_all` / `CYCLE_LOCK*` / `monitor/tasks.py` / `hub/settings/base.py` / `scaling/evaluator.py` product. No Beat schedule.

2. **`scale_in_overflow(site, target, *, dns=None, provider=None, transport=None, replica=None, sleep=None)`** in `deploys/overflow.py`:
   - First site-level call is **`refuse_if_partner_overflow(site)` only**. Do **not** call `refuse_if_attack` (AttackRefuse would short-circuit the partner check). Partner → `OverflowDeployError` with the refuse string, no DNS write, no terminate. Attack engaged does **not** block.
   - `mesh_only` may still scale-in. Do not call `ensure_dns` on mesh_only.
   - `target` must be `kind=aws_ec2`, `lifecycle=ephemeral`, `pk != site.primary_target_id`. Else refuse exact `overflow target must be an ephemeral aws_ec2 that is not the site primary`.
   - Missing SiteInstance is **not** a refuse (enroll-only leftover still bills). If a row exists in any observed_state, still scale-in.
   - Do **not** require ACCEPTED `scale-out-proposal:{pk}`. Do **not** call `pick_overflow_home`.
   - Do not create a Deployment. Do not bump Manifest. Do not assign `Site.primary_target`.
   - Acquire **site then overflow-target** `kind=deploy` (holder exactly `overflow-scale-in:{site.pk}`). Do **not** lock `primary_target`. If target lock misses, release the site holder then raise `could not acquire deploy lock`. Nested `finally` releases only holders taken (`holder=` always). Do not steal a leftover `holder=<deployment pk>`.
   - **Unjoin always runs first** (even if the target is already DECOMMISSIONED — `instance.terminate` can leave a dead A). Not tunnel-mode: if the site A comma-split values contain `target.host.strip()`, `ensure_dns` with remainder (joinable IPv4s, primary first), `dns_proxied=site.proxied`. Production `dns is None` → `dns_provider_for(site.dns_zone)`. If `ensure_dns` fails → `OverflowDeployError("could not unjoin overflow origin")` and **do not terminate**. Skip `ensure_dns` only when the overflow address is already absent or mesh_only. Do not invent `[primary]` if remainder is empty and primary is unparseable — refuse, do not terminate.
   - **Tunnel sibling:** tunnel-mode home → no A upsert. Call injected `replica`; default is a **no-op lambda** (do not reuse `_start_cloudflared_replica`, do not raise, do not `vault.service.get`, do not Transport). Then still terminate.
   - **Drain:** default no-op (`DRAIN_S = 0`). No docker stop.
   - **Terminate** unless already DECOMMISSIONED: `terminate_aws_target(target, provider=provider)`. Tests inject `RecordingCloud`. After success `get_instance(provider_ref) is None`. Wrap `TerminateError` as `OverflowDeployError("overflow terminate failed")` — never `str(exc)` (those strings contain `instance.terminate`). On terminate fail: status ERROR, row kept, SiteInstance not ABSENT, A already primary-only.
   - If a SiteInstance row exists: `desired_state=ABSENT`, `observed_state=ABSENT`. Do not delete it.
   - OPEN/ACKED/ACCEPTED `scale-out-proposal:{site.pk}`: `resolve(..., source="system")`.
   - Return `{target, unjoined: "dns"|"tunnel"|"none"}`.
   - After success the view `audit("site.overflow_scale_in", source="api", actor=request.user, obj=site, severity="security")` with no extra kwargs.

3. **Survive ensure_dns after unjoin.** `_joined_dns_values`: **delete** the `"," not in rec.value` short-circuit **and** the `len(parts) < 2` check. Split on comma even when there is no comma. A single joinable IPv4 **is** in play. Empty/missing/non-IPv4 still uses the manifest. After scale-in `_assemble_desired` `dns_values` **and** `dns_set` are `[primary]`, never `127.0.0.1`, never the overflow IP. 6.9 two-value and adopt `== "198.51.100.1"` stay green.

4. **T1 HTTP.** `POST /api/v1/sites/{pk}/overflow-scale-in/` `OverflowScaleInView`: `RequireRecentTouch`; serializer `{target: int, confirm_name: str}` with `confirm_name == target.host`. ACTION_TIERS new row `{id: "site.overflow_scale_in", tier: "T1", label: "Scale in overflow"}`. `T1_HTTP["site.overflow_scale_in"] = "/api/v1/sites/{pk}/overflow-scale-in/"`. `make generate-client`. View loads site, target; calls `core.overflow_deploys.scale_in`. 200 on success. 4xx on `OverflowDeployError`. Do not add `scale.approve`. Do not reuse `instance.terminate` as the playbook (that path does not unjoin DNS). View never binds `transport` / `dns` / `replica` / `provider` / `token` / `image_tag` / `ssh_key_ref` from the request.

5. **Port.** `core.overflow_deploys.register_scale_in` + `scale_in()` on a **third** slot `_scale_in` (do not reuse `_impl` / `_join`). Wired from `deploys.apps.DeploysConfig.ready()` via `overflow_scale_in_thunk`. Core still does not import `deploys`. Reuse `OverflowDeployError`. Unwired `scale_in()` fails loud naming `DeploysConfig.ready()`.

6. **`reap_stale_ephemerals(*, now=None)`** in `monitor/overflow_reaper.py`:
   - `now` default `timezone.now()`. `STALE_S = 86400`.
   - For each `Target` with `kind=aws_ec2`, `lifecycle=ephemeral`, `status` in `{ready, error}` (not DECOMMISSIONED), that is **not** `primary_target` of any Site:
     - Birth = oldest `AuditEvent` with `action="instance.create"`, `object_type="Target"`, `object_id=str(target.pk)`. Tests: `create` then `.update(ts=...)` (`auto_now_add` ignores `ts=` on create). **Missing audit → skip** unless `provider_ref` is set (enroll-then-fail leftovers still flag). Fixtures without `provider_ref` skip.
     - If `now - birth.ts >= STALE_S`: file via `raise_alert` kind **`ephemeral-overflow-orphan`** fingerprint **`ephemeral-overflow-orphan:{target.pk}`**. If a row is already OPEN/ACKED/ACCEPTED, return it and do not `raise_alert` again.
     - **Do not terminate. Do not call `scale_in_overflow`. Do not call `terminate_aws_target`.** Flag only.
   - Title exact: `Forgotten ephemeral overflow (past 24 hours)`. Entity: `target:{host}` (not pk). **`fix_action` exact:** `Scale in overflow to stop billing.` Body names the host, `24 hours`, `propose-mode does not launch`, and **Ack does not stop billing**. If a SiteInstance exists, body also names that site domain so the T1 is findable. No `\binstance\b`. No Approve/Launch.
   - No CheckRun write. No Beat. Tests call the function with a planted `AuditEvent.ts`.
   - Task 0 adds the kind to `monitor/alert_rules.py` P2 (same shape as `scale-cheap-remediation`). Claim `monitor/overflow_reaper.py` in paths.yaml **and** CODEOWNERS.

7. **Honesty / gates.** Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. New MUST ids phase 6, tier-less. Do not waive U1. Do not stub `named-partner.md`. Do not mark `P6-SCALER-DEMO`.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| T1 scale-in: unjoin overflow A (or skip if already gone) + terminate Fake + SiteInstance ABSENT | **MUST** |
| Tunnel scale-in: no A upsert; replica unjoin inject/no-op; still terminate | **MUST** |
| After unjoin, DnsRecord is primary-only; assemble promotes 1+ IPv4s so next ensure_dns keeps it | **MUST** |
| Reaper flags ephemeral aws_ec2 READY/ERROR older than 24h (AuditEvent birth); does not terminate | **MUST** |
| Attack does not block scale-in; partner overflow still refuses | **MUST** |
| 30–60 min cooldown auto scale-in | **OUT** |
| Real drain grace period (`DRAIN_S > 0`) | **OUT** |
| 30s origin health-pull / CF Load Balancing | **OUT** |
| Reaper auto-terminate | **OUT** (Ack is not launch; T1 scale-in is the terminate) |
| Beat schedule for the reaper | **OUT** |
| ScalePolicy / auto / AMI / `scale.approve` / evaluator-deploy | **OUT** |
| Live AWS / live Cloudflare as a test-plane requirement | **OUT** (Joseph) |
| `Target.created_at` / 0015 | **OUT** |
| 6.8 leftover lock-on-seam-refuse | **FOLLOW-UP** |
| U1 named-partner.md, HMAC, Azure, Phase 7 | Unchanged park |

## 2. Interfaces that change

**Python:**
- `deploys/overflow.py::scale_in_overflow` + `overflow_scale_in_thunk`.
- `deploys/pipeline.py::_joined_dns_values` — 1+ joinable IPv4s, not only 2+.
- `core/overflow_deploys.py::register_scale_in` / `scale_in`.
- `core/views.py::OverflowScaleInView` + serializers.
- `hub/urls.py` path.
- `core/actions.py` ACTION_TIERS row; generate-client.
- `tests/test_webauthn_t1.py` `T1_HTTP` entry.
- `deploys/apps.py` wires `register_scale_in`.
- **Create** `monitor/overflow_reaper.py`.
- `monitor/alert_rules.py` new P2 kind `ephemeral-overflow-orphan`.

**Tests:** `tests/test_overflow_scale_in.py`; acceptance NAMED in `tests/acceptance/test_phase_6.py`; append `conformance/demos/phase-6.md`.

**Not changed:** join/deploy/enroll bodies except `_joined_dns_values`. `scaling/evaluator.py` product. `providers/cloudflare.py`. `provision/aws_enroll.py` terminate body (call it). `monitor/tasks.py` / Beat. No schema.

## 3. Applicable registry reqs

Task 0 — two new MUST ids, phase 6, no `tier:`. `source: phase-6.10-design-note.md §3`. Do **not** rewrite the 6.6–6.9 overflow `text:`s. Compute `text_hash:`. Extend `PHASE_6_MUST_IDS` + `allowed_sources`.

- `SCALE-OVERFLOW-SCALE-IN` — `phase: 6`, `verify: test`. `text:` scale_in_overflow on an ephemeral overflow Target unjoins that origin from DNS (or skips if already unjoined), does not change Site.primary_target, terminates via CloudProvider (absent equals success), and marks a SiteInstance absent when one exists; tunnel-mode home sites skip the A record and still terminate; partner overflow refuses; attack does not block scale-in; evaluate_site still never terminates; tests inject FakeDnsProvider and FakeCloudProvider.
- `SCALE-OVERFLOW-EPHEMERAL-REAPER` — `phase: 6`, `verify: test`. `text:` reap_stale_ephemerals flags an ephemeral aws_ec2 that is not a site primary when its instance.create AuditEvent is older than 24 hours; it does not terminate; missing birth audit is skipped; evaluate_site still never terminates; tests plant AuditEvent timestamps.

## 4. Exit demo

ACCEPTED overflow, RUNNING SiteInstance, joined TEST-NET-3 pair, FakeDns + FakeCloudProvider → T1 scale-in 200; DnsRecord is primary-only; `terminate_instance` called; target DECOMMISSIONED; SiteInstance ABSENT; `primary_target` unchanged; overflow Finding system-resolved. PartnerSite → 4xx, no terminate. Attack engaged → scale-in still 200. Reaper: ephemeral READY, birth 25h ago, not primary → Finding `ephemeral-overflow-orphan:{pk}`; target still READY (not terminated). Birth 23h ago → no Finding. Record: append `conformance/demos/phase-6.md`. Honest: no live AWS VM, no 30s health-pull, no auto, no AMI, no Beat reaper, no real drain window.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-113** Protective cut — T1 scale-in unjoins then terminates via FakeCloudProvider; reaper flags 24h ephemeral leftovers and does not terminate; evaluator/enroll/deploy/join do not auto-scale-in. This wave does **not** design out forgotten billing (no Beat). Cooldown auto, real drain, 30s health-pull, Beat, ScalePolicy, leftover lock-on-seam-refuse are later.
- **D-114** ACTION_TIERS `site.overflow_scale_in` T1. Confirm is type-the-host. FakeDns + FakeCloudProvider in tests. No overflow FK. Attack does not block scale-in; partner overflow still refuses. Birth clock is `AuditEvent` `instance.create`, not a new `Target.created_at`.
- **D-115** Everyday gates stay phase 5 minus live. New ids phase 6 tier-less. U1 stays uncovered. Live AWS remains Joseph; tests inject FakeCloudProvider.

## 6. Protective cut (D-113)

MUST = T1 unjoin+terminate + 24h flag-only reaper + registry. Cooldown auto / drain window / health-pull / reaper-terminate / Beat / ScalePolicy / auto / AMI / evaluator-scale-in / live AWS / 6.8 leftover lock are **OUT**.

## 7. Closed contract (binding)

**C1 Evaluator.** Never scale-ins or terminates. AST-scan of `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` **and** `monitor/overflow_reaper.py` forbids the 6.9 list **and** `scale_in_overflow` / `reap_stale_ephemerals` / `terminate_aws_target` / `boto3` / `CloudProvider`. `BANNED_IMPORTS` gains those names. Reaper file must not import `deploys.overflow`. Do not rewrite 6.6–6.9 overflow `text:`. Do not edit Beat / `monitor/tasks.py` product.

**C2 Unjoin then terminate.** Unjoin (or skip-if-gone) **always** before terminate, including DECOMMISSIONED leftovers. FakeDns last upsert values are `[primary]` only when the overflow address was present. Then RecordingCloud `terminate_instance(provider_ref)`; `get_instance(provider_ref) is None`; Target row still exists, `DECOMMISSIONED`. SiteInstance ABSENT/ABSENT if a row existed. `primary_target` unchanged. No new Deployment. `ensure_dns` failure → no `terminate_instance` in calls. mesh_only skips `ensure_dns`, still terminates.

**C3 Tunnel sibling.** Tunnel-mode home: no `upsert_record`. Injected `replica` is called; default is a no-op lambda (not `_start_cloudflared_replica`). Token never in vault.get, Transport, 4xx, OverflowDeployError, AuditEvent.detail, Finding, CheckRun. 200 `unjoined=tunnel`. Do not invent `HUB_TEST_CF_TOKEN`.

**C4 Survive ensure_dns after unjoin.** `_joined_dns_values` has **no** comma short-circuit and **no** `len < 2`. One joinable IPv4 is in play. After unjoin `_assemble_desired` keeps `[primary]` in `dns_values` and `dns_set`. Never `127.0.0.1`. Never re-add overflow. Adopt `== "198.51.100.1"` stays.

**C5 Gate.** First call `refuse_if_partner_overflow` only. Partner+attack combined still 4xx. Attack alone does not block. No ACCEPTED requirement. No `pick_overflow_home`. Missing SiteInstance still unjoins+terminates. `OverflowDeployError` details: `could not acquire deploy lock`, `could not unjoin overflow origin`, `overflow terminate failed`, `overflow target must be an ephemeral aws_ec2 that is not the site primary`. Never `str(TerminateError)` (contains `instance.terminate`). 4xx detail is that public string only. Gate does not write CheckRun.

**C6 HTTP.** T1 `site.overflow_scale_in`, label exactly `Scale in overflow`. RequireRecentTouch + `confirm_name == target.host`. Serializer `{target: int, confirm_name: str}` only. HTTP inject: wrap with `kwargs.setdefault("dns", FakeDnsProvider())` and `setdefault("provider", RecordingCloud())` (from `test_aws_terminate`); plant `target.provider_ref` on that cloud. Patch `deploys.overflow.scale_in_overflow`. generate-client. After 200, view audits `site.overflow_scale_in` with empty detail. Do not add `scale.approve`. Do not reuse `instance.terminate` as this playbook. Append-only in `core/views.py`.

**C7 Locks.** Acquire site then overflow-target, holder `overflow-scale-in:{site.pk}`. Target-miss releases site then raises. Nested finally releases only taken holders. `primary_target` has no deploy lock from this call. Do not `run_deploy.delay`. Do not `holder=None`.

**C8 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. Named in `tests/test_overflow_scale_in.py`:
- `test_overflow_scale_in_unjoins_and_terminates` (`SCALE-OVERFLOW-SCALE-IN`) — joined TEST-NET-3 pair, RecordingCloud `provider_ref`, 200, upsert `[primary]`, `terminate_instance` in calls, `get_instance` is None, DECOMMISSIONED, SiteInstance ABSENT, `primary_target` unchanged, `_assemble_desired` `[primary]`
- `test_tunnel_mode_home_scale_in_skips_a_still_terminates` (`SCALE-OVERFLOW-SCALE-IN`)
- `test_attack_does_not_block_overflow_scale_in` (`SCALE-OVERFLOW-SCALE-IN`)
- `test_partner_site_refuses_overflow_scale_in` (`SCALE-OVERFLOW-SCALE-IN`) including PartnerSite+engaged playbook
- `test_evaluate_site_still_does_not_terminate` (both ids)
- `test_reaper_flags_ephemeral_older_than_24h` (`SCALE-OVERFLOW-EPHEMERAL-REAPER`) — `AuditEvent.objects.create` then `.update(ts=now-25h)`; 23h does not flag
- `test_reaper_does_not_terminate` (`SCALE-OVERFLOW-EPHEMERAL-REAPER`)
- `test_reaper_skips_missing_birth_audit` (`SCALE-OVERFLOW-EPHEMERAL-REAPER`)
- `test_overflow_scale_in_still_requires_recent_touch` (**unmarked**)
- `test_overflow_scale_in_view_does_not_import_deploys` (**unmarked** D4)
Acceptance NAMED `test_overflow_scale_in_unjoins_terminates_and_reaper_flags` **calls** `test_overflow_scale_in_unjoins_and_terminates` and `test_reaper_flags_ephemeral_older_than_24h`. Do not mark `P6-SCALER-DEMO`.

**C9 Registry.** Task 0 adds both ids, the alert-rules row, and claims `monitor/overflow_reaper.py` in paths.yaml **and** CODEOWNERS.

**C10 Module arrows.** `deploys/overflow.py` → `deploys.steps` / `providers.registry` / `provision.aws_enroll.terminate_aws_target` / `scaling.attack_gate.refuse_if_partner_overflow` / `core.locks` / `core.findings`. Does **not** import `boto3`, `vault.service`, `providers.ec2`, `providers.cloudflare`, `deploys.pipeline`. `monitor/overflow_reaper.py` → `monitor.alerts.raise_alert` / `core.models`. Does **not** import `deploys.overflow` / `terminate_aws_target`. `scaling/` ↛ `deploys` / `monitor.overflow_reaper`. View → `core.overflow_deploys` only. Third port slot `_scale_in`.

**C11 Copy.** Label exactly `Scale in overflow`. Reaper title exact `Forgotten ephemeral overflow (past 24 hours)`. Reaper `fix_action` exact `Scale in overflow to stop billing.` Body names host, `24 hours`, `propose-mode does not launch`, and that **Ack does not stop billing**. No Approve/Launch/ActionButton. NAV six. No new F8. No `\binstance\b` in new operator copy (label, OverflowDeployError details, demo, 4xx, reaper title/body/fix_action) except existing `single-instance` / `single-instance-only` / `instance.create` / `instance.terminate` ids. File map does not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`. Pinned 4xx: `could not acquire deploy lock`, `could not unjoin overflow origin`, `overflow terminate failed`, `overflow target must be an ephemeral aws_ec2 that is not the site primary`.

## 8. Follow-up only (not this wave)

6.8 leftover: `_resolve_seams` after overflow `begin_deploy` can leave the site deploy lock held on FAILED. Fake-path-safe. **Not** the 6.10 function. Do not fold it into Task 1.
