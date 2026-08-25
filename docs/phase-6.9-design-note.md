# Phase 6.9 Design Note — Join overflow traffic (T1 Fake DNS round-robin; tunnel replica sibling)

**Phase:** 6.9 per deploy-system-plan.md §9.5.4 step 4 (post Phase 6.8 same-image deploy, DNS SKIPPED)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-25 · **Seat:** Grok 4.6
**Revision:** r2 — r1 MERGE-AFTER-FIXES folded (Architect dns_set-before-dump + prod `dns_provider_for`; Security veto Hub-vaulted tunnel JWT + refuse-before-Transport + proxied honesty + tunnel-wins; QE named tests + NAMED calls; SRE lock `finally` + mesh_only in C5 + leftover recovery; UX MERGE). Binding §7.
**Estimate:** hours-to-a-day. Protective cut: **D-110**. Phase 6.8 T1 MUST is on `master` @ `50ea444` (pushed). Scale-in, ephemeral reaper, ScalePolicy, auto, AMI, Beat enroll, `scale.approve`, evaluator auto-deploy, 30s origin health-pull, Cloudflare Load Balancing, live AWS as a test-plane requirement, HMAC, U1, Azure, Phase 7, live cheap mutate, and the 6.8 leftover lock-on-seam-refuse are **not this wave**. **Do not invent `HUB_TEST_*` / `HUB_INTAKE_HMAC` / `HUB_WEBHOOK_SECRET`. Do not stub `named-partner.md`.**
**Closed schema:** `0014_phase6.py` stays closed. No `0015`. No `ScalePolicy`. No overflow FK. No new `SiteInstance` / `DnsRecord` / `OperationLock.Kind` columns. Do not retarget `Site.primary_target`. Do not add `Deployment.target`. Do not un-skip the 6.8 Deployment DNS step.
**Panel:** §7 is binding.

## 1. What lands this wave

Phase 6.8 ships a bit-identical copy onto the enrolled ephemeral and creates a `SiteInstance`. DNS was SKIPPED; `primary_target` stayed put; the copy is not live traffic. §9.5.4 step 4 joins that copy: add the overflow origin's A record **next to** the primary behind Cloudflare's proxy (round-robin). Tunnel-mode home sites get the same effect with a second `cloudflared` replica on the new host **instead of** an A record. **Tunnel-mode wins:** `kind=ssh` and `collect_payload.tunnel is True` never upserts an origin A (even if `Target.host` parses as IPv4). Proxied public origin-A sites that are **not** tunnel-mode take DNS. **Ack is still not launch.** The evaluator still never joins traffic. This wave adds `deploys/overflow.py::join_overflow_traffic` and a T1 POST that runs it.

### 1.1 MUST

1. **Evaluator / enroll / deploy stay copy+enroll+ship.** `evaluate_site` never creates a Deployment and never calls `join_overflow_traffic` / `upsert_record`. `enroll_overflow_target` does not join. `deploy_overflow_copy` still skips DNS (6.8 tests stay green). AST-scan `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` still forbids the 6.8 list **and** `join_overflow_traffic`. Do not rewrite `SCALE-PROPOSE-NO-PROVISION` / `SCALE-OVERFLOW-T1-ENROLL` / `SCALE-OVERFLOW-SAME-IMAGE` `text:`.

2. **`join_overflow_traffic(site, target, *, dns=None, replica=None, transport=None)`** in `deploys/overflow.py`:
   - First site-level call: `refuse_if_attack(site)`. Attack/partner → `OverflowDeployError`, no DNS write, no replica call, no Finding/CheckRun write.
   - Finding `scale-out-proposal:{site.pk}` must be **ACCEPTED**. Missing / OPEN / ACKED / RESOLVED → `OverflowDeployError` with exact `Ack is not launch. Propose-mode does not launch.`
   - `site.exposure == mesh_only` → refuse **before** acquire / replica / `ensure_dns` (ensure_dns would skip and look like success).
   - `target` must be `kind=aws_ec2`, `lifecycle=ephemeral`, `status=ready`, `pk != site.primary_target_id`. Else refuse.
   - A `SiteInstance` for `(site, target)` with `observed_state=RUNNING` must exist (the 6.8 copy). Else refuse `overflow copy is not running`.
   - Do **not** call `pick_overflow_home` (the box is already rented; an idle machine appearing later must not block joining it).
   - Do not create a Deployment. Do not bump Manifest. Do not assign `Site.primary_target`. Do not change `SiteInstance` rows.
   - Acquire site `kind=deploy` lock (holder exactly `overflow-join:{site.pk}`) for the join body; `finally` releases **that** holder (never `holder=None`). Do **not** acquire a target deploy lock on `primary_target` or the overflow pk. If the site lock cannot be taken → `OverflowDeployError("could not acquire deploy lock")` — fail-loud, no silent retry; operator retries after the in-flight deploy ends.
   - **Tunnel sibling (wins):** when primary is tunnel-mode home (`kind=ssh` and `collect_payload.tunnel is True`), call the replica seam **instead of** `upsert_record`. Do not add an A record. `replica` defaults to `_start_cloudflared_replica`. **B5 pin (Security, not waivable):** this wave does **not** create a Hub vault home for tunnel JWTs. `_start_cloudflared_replica` raises immediately with exact `tunnel replica is not configured`. It does **not** call `vault.service.get`, does **not** construct Transport, does **not** `run`/`put`, does **not** SSH-read the primary, does **not** `cloudflared service install`. Tests inject `replica=` (recording callable) for the happy tunnel path and never create a tunnel Secret. View never binds `replica`. Token never appears in Transport argv, `PipelineTransport.calls`, SSH transcripts, put bodies, Celery kwargs, 4xx or 201 bodies, `OverflowDeployError`, `AuditEvent.detail`, Finding, or CheckRun. Do not invent `HUB_TEST_CF_TOKEN`. Replica wiring for a later wave is a new per-target tunnel on the overflow host, or a scoped Cloudflare Tunnel API — not Hub-copy of the primary JWT.
   - **DNS join (not tunnel-mode):** when tunnel-mode does not apply and `site.exposure == public` and both `site.primary_target.host` and `target.host` are **joinable IPv4** (stdlib `ipaddress.IPv4Address`; reject RFC1918 `10/8` `172.16/12` `192.168/16`, CGNAT `100.64/10`, loopback, link-local, multicast, unspecified; **allow** documentation TEST-NET `192.0.2.0/24` `198.51.100.0/24` `203.0.113.0/24` and other globally-routed unicast — do **not** use `IPv4Address.is_private` / `is_global` as the allow, because this interpreter treats TEST-NET-3 as `is_private`), call `deploys.steps.ensure_dns` with a non-pipeline desired: `dns_values=[primary_ipv4, overflow_ipv4]` (primary first), `dns_proxied=site.proxied`, `dns_zone=site.dns_zone`, `domain=site.domain`, `site=site`. Pass `dns_proxied` **before** any `_desired_dns_records` / `dns_set` snapshot. Injected `dns` is required in tests (`FakeDnsProvider`). When `dns is None` (production T1 POST): `providers.registry.dns_provider_for(site.dns_zone)` — never `_default_dns()` / Fake, never import `providers.cloudflare`. Catch `ScopeError` / missing `dns_zone` → `OverflowDeployError`; join itself does not `raise_alert`. Do not call `CloudProvider.get_instance`. Do not live-DNS-resolve a hostname. If the two IPv4s are equal → refuse `overflow origin IPv4 matches primary`.
   - Else → refuse `overflow join needs origin IPv4s or a tunnel-mode home`.
   - On DNS success: `DnsRecord` for `(site, name=site.domain, rtype=A)` stores **all** values, comma-joined (`_persist_dns_rows` writes `",".join(rec["values"])` — single-value rows stay a single address, existing `== "198.51.100.1"` pins keep).
   - Return a small dict the view serializes. DNS: `{target, joined: "dns", name, values}`. Tunnel: `{target, joined: "tunnel"}`.

3. **Join survives the next primary deploy.** `_assemble_desired` sets `desired["dns_proxied"] = site.proxied`. If the site's A `DnsRecord.value` is a comma-separated list of two or more joinable IPv4s, set `desired["dns_values"]` to that list **before** computing `desired["dns_set"]`. A multi-IPv4 `DnsRecord` **wins over** a stale single-A `dns_set` (including rollback artifacts): after arts load, rewrite `dns_set` from `_desired_dns_records(desired)` when the joined list is in play. `ensure_dns` prefers `dns_set` overlay — promoting only `dns_values` after the dump (or leaving rollback `dns_set`) would upsert `[primary]` only; Cloudflare `upsert_record` then DELETEs `current[len(values):]`. 6.8 overflow deploys still skip the DNS **step**; they do not upsert.

4. **T1 HTTP.** `POST /api/v1/sites/{pk}/overflow-join/` `OverflowJoinView`: `RequireRecentTouch`; serializer `{target: int, confirm_name: str}` with `confirm_name == target.host`. ACTION_TIERS new row `{id: "site.overflow_join", tier: "T1", label: "Join overflow traffic"}`. `T1_HTTP["site.overflow_join"] = "/api/v1/sites/{pk}/overflow-join/"`. `make generate-client`. View loads site, target; calls `core.overflow_deploys.join` (D4 port). 201 on success. 4xx on `OverflowDeployError`. Do not add `scale.approve`. Do not reuse T2 `dns.change`. View never binds `transport` / `dns` / `replica` / `provider` / `token` / `image_tag` / `ssh_key_ref` from the request.

5. **Port.** `core.overflow_deploys.register_join` + `join()` on a **second** slot `_join` (do not reuse `_impl`). Wired from `deploys.apps.DeploysConfig.ready()` via `overflow_join_thunk` (look-up-at-call-time so HTTP inject patches `deploys.overflow.join_overflow_traffic`). Core `views.py` / `overflow_deploys.py` still do not import `deploys`. Reuse `OverflowDeployError`. Unwired `join()` fails loud naming `DeploysConfig.ready()`.

6. **Honesty / gates.** Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. New MUST id phase 6, tier-less. Do not waive U1. Do not stub `named-partner.md`. Do not mark `P6-SCALER-DEMO`. `deploys/overflow.py` is already claimed in paths.yaml **and** CODEOWNERS — do not broaden to `deploys/**`.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| T1 join: overflow A next to primary (FakeDns, round-robin, `proxied=site.proxied`) | **MUST** |
| Tunnel-mode home sibling: injected replica, no A record; default replica refuse-closed; no Hub-vaulted JWT | **MUST** |
| Join persists comma-joined DnsRecord; `_assemble_desired` rewrites `dns_values` **and** `dns_set` so later ensure_dns cannot drop overflow | **MUST** |
| OPEN/ACKED refuse with Ack is not launch; evaluator still never joins | **MUST** |
| 30s origin health-check that pulls a dead origin from DNS | **OUT** |
| Cloudflare Load Balancing (paid) | **OUT** |
| Scale-in + ephemeral reaper (§9.5.5) | **OUT** (needs a joined origin to drain) |
| ScalePolicy / auto / AMI bake | **OUT** |
| Evaluator auto-deploy / Beat enroll / `scale.approve` | **OUT** (Ack is not launch, D-093) |
| Live AWS / live Cloudflare as a test-plane requirement | **OUT** (Joseph) |
| AAAA / IPv6 join | **OUT** |
| Hub-copy of the primary tunnel JWT onto the overflow host | **OUT** (B5; Security) |
| 6.8 leftover: `_resolve_seams` after overflow `begin_deploy` can leave the site deploy lock held on FAILED | **FOLLOW-UP** (real, Fake-path-safe; not this wave's function) |
| U1 named-partner.md, HMAC, Azure, Phase 7 | Unchanged park |

## 2. Interfaces that change

**Python:**
- `deploys/overflow.py::join_overflow_traffic` + `overflow_join_thunk` + `_start_cloudflared_replica` (refuse-closed) + `_joinable_ipv4`.
- `deploys/steps.py::_persist_dns_rows` — persist `",".join(values)` (single-value unchanged).
- `deploys/pipeline.py::_assemble_desired` — `dns_proxied=site.proxied`; multi-IPv4 `DnsRecord` wins `dns_values` **and** `dns_set` (including over rollback overlay).
- `core/overflow_deploys.py::register_join` / `join` (`_join` slot).
- `core/views.py::OverflowJoinView` + serializers.
- `hub/urls.py` path.
- `core/actions.py` ACTION_TIERS row; generate-client.
- `tests/test_webauthn_t1.py` `T1_HTTP` entry.
- `deploys/apps.py` wires `register_join`.

**Tests:** `tests/test_overflow_join.py`; acceptance NAMED in `tests/acceptance/test_phase_6.py`; append `conformance/demos/phase-6.md` (rewrite the live "No DNS join" header — it becomes false).

**Not changed:** `deploy_overflow_copy` skip-DNS body. `provision/overflow.py` enroll body. `scaling/evaluator.py` product. `providers/cloudflare.py` (already multi-value upserts). `vault/service.py` (no tunnel-token `get` caller). No schema.

## 3. Applicable registry reqs

Task 0 — new MUST id, phase 6, no `tier:`. `source: phase-6.9-design-note.md §3`. Do **not** rewrite `SCALE-PROPOSE-NO-PROVISION` / `SCALE-OVERFLOW-T1-ENROLL` / `SCALE-OVERFLOW-SAME-IMAGE` `text:`. Compute `text_hash:` for the new id. Extend `PHASE_6_MUST_IDS` + `allowed_sources`.

- `SCALE-OVERFLOW-JOIN-TRAFFIC` — `phase: 6`, `verify: test`. `text:` join_overflow_traffic on a public site with joinable IPv4 origins upserts the overflow A next to the primary (round-robin, proxied) without changing Site.primary_target; tunnel-mode home sites add a cloudflared replica on the overflow host instead of an A record; OPEN or ACKED overflow refuses with Ack is not launch; evaluate_site still never joins traffic; tests inject FakeDnsProvider.

## 4. Exit demo

ACCEPTED overflow, RUNNING SiteInstance on an ephemeral overflow Target, primary and overflow hosts are TEST-NET-3 IPv4s, FakeDnsProvider → 201 `joined=dns`; upsert_record values are `[primary_ipv4, overflow_ipv4]` with `proxied=True` on a default site; `primary_target` unchanged; no new Deployment; later `_assemble_desired` `dns_values` **and** `dns_set` keep both. OPEN overflow → 4xx, no upsert. Tunnel-mode home primary (`kind=ssh`, `collect_payload.tunnel true`) + injected replica → 201 `joined=tunnel`; no upsert_record. Record: append `conformance/demos/phase-6.md`; rewrite the header so it no longer says "No DNS join." Honest: no live Cloudflare zone, no live AWS VM, no 30s health-pull, no auto, no AMI, no Hub-vaulted tunnel JWT.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

- **D-110** Protective cut — T1 join overflow traffic: DNS A next to primary for joinable-IPv4 public origins that are not tunnel-mode; tunnel replica sibling when primary is tunnel-mode (injected seam; default refuse-closed; no Hub-vaulted JWT, B5). Do not retarget primary; evaluator/enroll/deploy do not auto-join. Scale-in, 30s health-pull, ScalePolicy, auto, AMI, leftover lock-on-seam-refuse are later.
- **D-111** ACTION_TIERS `site.overflow_join` T1. Confirm is type-the-host. FakeDnsProvider + injected replica in tests. No overflow FK. Join is not a Deployment. DnsRecord.value comma-joins multiple A values; `_assemble_desired` rewrites `dns_set` so the next primary `ensure_dns` cannot drop the overflow origin.
- **D-112** Everyday gates stay phase 5 minus live. New id phase 6 tier-less. U1 stays uncovered. Live Cloudflare remains Joseph for the test plane; tests inject FakeDnsProvider.

## 6. Protective cut (D-110)

MUST = T1 join DNS round-robin for joinable-IPv4 public origins + tunnel replica sibling (inject / refuse-closed) + persist both IPs so later ensure_dns cannot drop overflow + registry. 30s health-pull / CF LB / scale-in / ScalePolicy / auto / AMI / evaluator-join / live CF in CI / Hub-vaulted JWT / 6.8 leftover lock are **OUT**.

## 7. Closed contract (binding)

**C1 Evaluator.** Never joins traffic. AST-scan of `scaling/` + `monitor/tasks.py` + `monitor/host_metrics.py` still forbids the 6.8 list **and** `join_overflow_traffic`. `enroll_overflow_target` does not call `join_overflow_traffic`. `deploy_overflow_copy` still skips DNS and does not `upsert_record`. Do not rewrite `SCALE-PROPOSE-NO-PROVISION` / `SCALE-OVERFLOW-T1-ENROLL` / `SCALE-OVERFLOW-SAME-IMAGE` `text:`. `evaluate_site` does not +1 DnsRecord upsert and does not call replica.

**C2 Tunnel wins; DNS is origin-A.** Primary `kind=ssh` and `collect_payload.tunnel is True` → replica path, **no** `upsert_record` (even if host is IPv4). Else public + both hosts joinable IPv4 → `ensure_dns` with `dns_values=[primary, overflow]` (primary first), `dns_proxied=site.proxied`. Default `_ready_site` is `{slug}.lan` (not IPv4): the DNS happy test **plants** TEST-NET-3 on both hosts. Pin `proxied=True` on the default site (catches `upsert_record`'s `proxied=False` default) **and** a `site.proxied=False` FakeDns case that upserts `proxied=False` (do not claim orange-cloud). No `CloudProvider.get_instance`. No hostname DNS lookup. Equal IPv4s refuse. RFC1918 / CGNAT / loopback / link-local refuse the DNS path.

**C3 Tunnel sibling (B5).** Happy tests inject `replica=` and never create a tunnel Secret. Default `_start_cloudflared_replica` raises exact `tunnel replica is not configured` **before** any Transport construct/`run`/`put` and **never** calls `vault.service.get`. 201 `joined=tunnel`. Token never in Transport argv, `PipelineTransport.calls`, SSH transcripts, put bodies, Celery kwargs, 4xx or 201 bodies, OverflowDeployError, AuditEvent.detail, Finding, or CheckRun. Do not invent `HUB_TEST_CF_TOKEN`. Do not SSH-cat the primary. Do not edit `providers/cloudflare.py`.

**C4 Survive ensure_dns.** `_persist_dns_rows` writes `",".join(rec["values"])`. `_assemble_desired` sets `dns_proxied=site.proxied` and, when the A `DnsRecord.value` is a comma-separated multi-IPv4 list, sets `dns_values` to that list **before** baking `dns_set`; a joined list **wins over** rollback `dns_set`. C4's subsequent `ensure_dns` uses that **assembled** desired (not a hand-built dict). A subsequent `ensure_dns` against FakeDns that already holds both values records **no** upsert. Single-value persist stays a single address (adopt `== "198.51.100.1"` stays green).

**C5 Gate.** First site-level call is `refuse_if_attack(site)`. Then ACCEPTED `scale-out-proposal:{pk}` only. Then **`mesh_only` refuse** (before acquire / replica / `ensure_dns`). Then ephemeral READY non-primary. Then RUNNING SiteInstance. Do not call `pick_overflow_home`. Gate `OverflowDeployError` does not `raise_alert`, `_retract`, write Finding, or write CheckRun. OPEN/ACKED/missing/RESOLVED detail is exact `FIX_ACTION`. Catch `AttackRefuse` / `PartnerOverflowRefuse` → `OverflowDeployError`. No Deployment on the gate path **or** the success path.

**C6 HTTP.** T1 `site.overflow_join`, label exactly `Join overflow traffic`. RequireRecentTouch + `confirm_name == target.host`. Serializer `{target: int, confirm_name: str}` only. HTTP inject: wrap `deploys.overflow.join_overflow_traffic` with `kwargs.setdefault("dns", FakeDnsProvider())`; tunnel happy tests also `setdefault("replica", recording)`. Patch the module attribute the thunk calls. generate-client. Do not add `scale.approve`. Do not reuse `dns.change`.

**C7 Locks.** Site `kind=deploy` holder `overflow-join:{site.pk}` during the join body; `finally` releases that holder. Overflow target and `primary_target` have **no** deploy lock from this join. Do not `run_deploy.delay`. Do not assign `Site.primary_target`. No new Deployment. Lock-busy is fail-loud (`could not acquire deploy lock`).

**C8 Markers.** Function-level `@pytest.mark.req` on `def test_*` only. `SCALE-OVERFLOW-JOIN-TRAFFIC` only on tests that prove that id's text. Named in `tests/test_overflow_join.py`:
- `test_overflow_join_upserts_a_next_to_primary` (marked)
- `test_tunnel_mode_home_joins_via_replica_not_a` (marked)
- `test_open_overflow_refuses_join_with_ack_is_not_launch` (marked)
- `test_acked_overflow_refuses_join_with_ack_is_not_launch` (marked)
- `test_evaluate_site_still_does_not_join_traffic` (marked)
- `test_overflow_join_still_requires_recent_touch` (**unmarked**)
Do not mark `P6-SCALER-DEMO`. Do not mark 6.7/6.8 enroll/deploy tests with the new id.

**C9 Registry.** Task 0 adds `SCALE-OVERFLOW-JOIN-TRAFFIC`. Do not re-claim `deploys/overflow.py`. Do not broaden `deploys/**`.

**C10 Module arrows.** `deploys/overflow.py` → `deploys.steps` / `providers.registry` (prod `dns_provider_for` only) / `scaling.attack_gate` / `scaling.constants` / `core.locks`. Does **not** import `deploys.pipeline`, `providers.cloudflare`, or `vault.service`. `scaling/` ↛ `deploys`. View → `core.overflow_deploys` only. Second port slot `_join` via `register_join`; do not reuse `_impl`.

**C11 Copy.** ACTION_TIERS label exactly `Join overflow traffic`. Finding chrome unchanged (no Approve / Launch / `Join overflow traffic` / `Create target` / ActionButton on the Finding or F8 overflow renderer). NAV six. No new F8 id. F8 `scale-out-proposal` seed stays no-idle `0.0416` / `t3.medium`. No `\binstance\b` in new operator copy (label, OverflowDeployError details, demo, 4xx blobs) except existing `single-instance` / `single-instance-only` and existing `instance.create` / `instance.terminate` ids. File map does not edit `Findings.jsx` / `Chrome.jsx` / `simulation/seed_v1.json`. Refuse strings: `FIX_ACTION`, `overflow copy is not running`, `could not acquire deploy lock`, `overflow origin IPv4 matches primary`, `overflow join needs origin IPv4s or a tunnel-mode home`, `tunnel replica is not configured`.

## 8. Follow-up only (not this wave)

If `deploy_overflow_copy` has already `begin_deploy`'d (site+overflow target locks held, status=RUNNING) and `execute` then raises `DeploySeamRefused` from `_resolve_seams`, `execute` sets FAILED and re-raises **before** the `finally` that `release_deploy_locks`. The site deploy lock can stick. Heartbeat sweep only RUNNING deployments, so a FAILED holder is **not** swept. Recovery: delete the FAILED row's `OperationLock` (`kind=deploy`, `holder=<that deployment pk>`). Fake-path overflow injects `dns=`, so `_resolve_seams` does not take the production factory and this does not fail T1. Production `OverflowDeployView` does not inject `dns=`, so a live overflow seam-refuse can leave `holder=str(deployment.pk)` on site+overflow target; 6.9 join then 4xx `could not acquire deploy lock`. Real, Fake-path-safe (force `_resolve_seams` to raise after begin_deploy, assert locks released). **Not** the 6.9 function. Do not fold it into Task 1.
