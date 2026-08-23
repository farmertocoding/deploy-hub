# Phase 5.5 Design Note — Partner Deploy REST (T1 Fake intake)

**Phase:** 5.5 per §I / addendum §K (Azure is Phase 7 / V11; scaler is Phase 6 gated)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-24 · **Seat:** Grok 4.6
**Revision:** r2 — design panel MERGE-AFTER-FIXES (Architect + Security + QE + SRE + UX). Required fixes: `conformance`/`review-round` stay phase 5 minus live; `conformance-5.5` is the phase gate (U1 due there only); CustomHostname on `dns_provider_for`; no `Site.partner_id`/`Target.tier`; C12 aggregate fingerprints; M2 outbox-only; webhook re-resolve; claim `core/partner_templates.py` (+ `core/partner_jobs.py`); fail-closed intake stub; 201 returns minted `hubk_*`/`whsec_` once; empty `INTAKE_URL` does not flood CheckRun; Q9 quota vector; Create partner never Connected; destination-rank + kill-switch chrome; F8 `REQUIRED_STATE_IDS`; `UX-P55-PARTNERS` text covers those chrome clauses. §7 remains binding.
**Estimate:** 2–4 wk T1. Protective cut: **D-075**. Phase 5 MUST is on `master` @ `4f30c7a`. DNS-01 stays the Phase 4 slip. Live AWS stays Joseph. **Do not invent `HUB_TEST_CF_TOKEN`, `HUB_TEST_AWS_TOKEN`, or `HUB_TEST_PARTNER_TOKEN`. Do not invent a named partner.**
**Branch:** these two docs land on **`p55-design`**; Implementers cut task branches from it. Never implement on `master`. Sensitive-path merges go through the recorded panel vote.
**Closed schema wave:** `0012_phase5.py` stays closed. Phase 5.5 adds **one** Hub migration, `0013_phase55.py`: `Partner`, `PartnerSite`, Hub replay-nonce table, Hub idempotency-key store, `AuditEvent.partner` nullable FK (replaces `partner_id_stub`). No `Site.tier`. No `Site.partner_id`. No `Target.tier`. No `NetworkZone.kind`. **Task 1 is the only `core/models.py` writer this phase.** Later tasks do not edit it.
**Panel:** §7 is binding. An Implementer who invents a path, env, Finding fingerprint, action id, or gate shape that §7 does not name is implementing the wrong design.

## 1. What lands this phase

Phase 5 finished the AWS adapters. Phase 5.5 is the §K promise: **public intake, private Hub, one-way pull** — REST-only, T1 Fake. U1’s named committed partner is the **exit / live-surface** gate, not a start freeze. MCP stays cut from v1.

### 1.1 MUST

1. **Partner Intake** as its own tiny process under `intake/**` (already sensitive). Not a Django app, not `INSTALLED_APPS`, not Hub `urlpatterns`. Credential-free: public keys + quota counters + job outbox. No vault/KEK/Hub Postgres/SSH/Celery broker/cloud SDK. Public listener = the six K3 routes under `/partner/v1/…` only. Outbox is mesh-only (`/internal/outbox`). Fake intake is the T1 default. Hub product code (`monitor/`, `core/`, `hub/`, `deploys/`) must not `import intake`; `intake_client_for` speaks HTTP or an injected `FakeIntakeClient`. T1 tests may import `intake`.
2. **Hub Beat poll** of the intake outbox every **10 s** (5–15 band) on queue `probes`. Per-tick batch cap 20 + 0–2 s jitter. `intake_client_for` is fail-closed. Empty `INTAKE_URL` → poll no-op / SKIPPED, **does not insert a CheckRun every 10 s** (upsert-at-most-one or skip persist), never a T1-sibling green, never P1. N=3 consecutive failures → P2 `hub-outbox-poll-failing`. Intake unreachable > 5 min → P1 `partner-intake-unreachable`.
3. **Hub-authoritative Ed25519.** Intake verifies cheaply; Hub re-verifies against the Partner pubkey slots, 5-minute window, Postgres nonce cache, Stripe-style Idempotency-Key 24 h. One shared `conformance/fixtures/partner-signature-vectors.json` consumed by **both** verifiers (valid / expired / replayed / mutated-body / idempotency / **quota-exceeded**). Replay rejected at Hub even when Fake intake forwards (M5 / PART-K2). Hub refuse wins on quota.
4. **Six K3 endpoints on the intake**, never Hub `/api/partner/*`. Extend the M2 standing test to also 404 Hub `/api/partner/*` and `/mcp`.
5. **Isolation without `Site.tier`:** `Partner` + `PartnerSite` FK + dedicated destination Targets. No `Site.partner_id`. No `Target.tier` (partner-tier iff pk ∈ some `destination_order`). Partner-tier **targets** (copy may say that); never Hub host; never co-host with non-partner sites; Tunnel required for own-server partner destinations; overflow refuse; scheduled-job commands prohibited (V3).
6. **Templates:** one digest-pinned Hub-built fixture image (T1 Fake registry / docker load). Partner Dockerfile / build / git-as-source / unconstrained image **refuse**. Not `catalog/` host-hardening.
7. **K6 standing tests:** partner router maps to no `ACTION_TIERS` T1/T2 internal id; Hub replay reject even if intake forwards; cross-partner IDOR 404; Hub re-enforces finite quotas. PART-K1/K2/K6 **verified, not waived**; `text:` / `text_hash:` untouched.
8. **Standard Webhooks** exact, Hub egress only, §B10 HTTPS allowlist, T1 fake sink, `whsec_` vaulted Hub-side (shown once on mint 201). Intake never holds webhook secrets. **Re-resolve at every delivery** (do not inherit git’s clone TOCTOU exception).
9. **Fake CustomHostname** TXT-before-serve as a capability on the object `dns_provider_for` (or the injected Fake) returns. Helpers must not construct a Cloudflare client. Unverified hostname is never a Caddy route. Live CF-for-SaaS / paid edge = Joseph. No new ACME / DNS-01.
10. **M2 git-webhook** as a **second outbox type on the same Hub poller** (MUST — Phase 2 already promised this transport). Not a Hub inbound route. Not a 7th public intake route. No GitHub/webhook HTTP listener. No webhook secret on intake. T1 Fake **plants** `{type: "git-push", git_url, ref, sha}`; Hub re-validates via `validate_git_url`.
11. **Operator surface without a 7th NAV item.** Settings **Partners** tab (peer of Cloudflare/AWS, after AWS) is **Create partner**, not Connect. Sites/Findings filter. Copy: partner site / partner-tier target, never “instance.” Fake / empty `INTAKE_URL` / post-create never paints `Connected`. No `connect_partner` checklist item.
12. **T1 kill switches.** `partner.create` T1 (201 **returns** `hubk_live_` / `hubk_test_` / `whsec_` once — Enroll once-panel; GET never; AuditEvent/logs never). `partner.suspend` T1. `partner.api_kill_switch` T1 (enable is T1, not a toggle). `partner.site_takedown` T2 on site detail. `partner.destination_rank` T2 (own-server confirm is the K5 honesty sentence once). Global flag **default OFF**. K6 “no T1/T2” is the **partner router**, not the operator surface. Reaper: T1 Fake plant of orphaned partner sites (distinct from Multipass prefix and AWS `purpose=test`). O1: partner-site hard-down P2 via Partner FK fingerprint `site-down:{name}`; N≥2 → P1 fingerprint `partner-aggregate-down:{partner.pk}`; partner-tier host down reuses `host-down:{host}`. Prod host-down **must not** use `partner-aggregate-down`. SLA copy = response-time, not uptime / 99.9%.
13. **U2 numeric floors** (Hub-authoritative). See §7 C11. Unbounded `max_sites` is out. Fleet cap stays under the 30-node map bar. Partner sites refuse overflow scale.
14. **Honesty / gates:** Task 0 does **not** bump PART-K off 5.5 and does not waive them. `conformance` and `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. `conformance-5.5` is `--phase 5.5 --exclude-tier t2 --exclude-tier t3` and is **not** a `review-round` or `nightly-gates` prereq. `conformance-5` stays phase 5 minus live. `conformance-3` stays all-tiers 3. No `t4`. No all-tiers 5.5. `PART-U1-NAMED-PARTNER` is `verify: demo` of a Joseph-named artifact, due at `--phase 5.5` only; missing `named-partner.md` = uncovered on `conformance-5.5`, **not** on everyday `conformance`/`review-round`. T1 task merges do not wait on Joseph. Two consecutive clean **`conformance-5.5`** rounds wait on the interrupt. Do not stub that file. Do not waive U1 / PART-K / `failed` / `not-collected`.

### 1.2 MUST vs later

| Item | Line |
|---|---|
| T1 Fake intake process + six K3 endpoints + import wall | **MUST** |
| Hub 10 s poll + re-verify + replay/idempotency in Postgres | **MUST** |
| Shared signature-vector file vs both verifiers (incl. quota-exceeded) | **MUST** |
| Partner / PartnerSite isolation; no `Site.tier` / `Site.partner_id` / `Target.tier` | **MUST** |
| Template-only refuse; K6 + V3 standing tests | **MUST** |
| Standard Webhooks T1 fake sink + re-resolve; Fake CustomHostname on `dns_provider_for` | **MUST** |
| M2 git-webhook second outbox type on the same poller (not a public route) | **MUST** |
| Settings Partners tab + F8 + T1 kill-switch chrome + reaper orphan + O1 P2 | **MUST** |
| U2 finite quota defaults + fleet cap | **MUST** |
| `0013_phase55.py`; PART-K stay 5.5; `conformance-5.5` minus live (U1 due there) | **MUST** |
| HMAC/bearer compatibility fallback | **named first slip.** Evaluation, not enablement. Do not build until a named partner cannot sign. |
| Named committed partner (U1) | **Joseph interrupt / exit gate** (`PART-U1-NAMED-PARTNER`) |
| Live intake VM / `api.partners.<domain>` / live CF-for-SaaS / paid edge / dedicated partner cloud targets | **Joseph interrupt** |
| MCP adapter | **OUT** (not a slip) |
| Azure, scaler loop, DNS-01, N1 redo, 7th NAV, Hub `/api/partner/*`, `Site.tier`, invented token envs, `t4`, all-tiers 5.5, Workers intake, billing-grade metering | **OUT** |

## 2. Interfaces / tables that change

**Migration `0013_phase55.py` (Hub) — Task 1 owns this file and `core/models.py` for the whole phase:**
- `Partner`: `slug` (unique, max 64), `name`, `pubkey_current` + `pubkey_previous` (TextField; two Ed25519 slots), `max_sites` default **5**, `deploys_per_day` default **50**, `domains` default **5**, `destination_order` JSONField default `[]` (ordered Target pks), `suspended` default False, `webhook_url` blank, `created_at`.
- `PartnerSite`: FK `Partner` + OneToOne `Site`; `tenant_ref`; unique `(partner, tenant_ref)`. Querysets always filter on Partner.
- `PartnerReplayNonce`: FK Partner + `nonce` + `seen_at`; unique `(partner, nonce)`.
- `PartnerIdempotencyKey`: FK Partner + `key` + `params_hash` (64 hex) + `status_code` + `response` JSON + `created_at`; unique `(partner, key)`. 24 h TTL.
- `AuditEvent.partner` nullable FK (`SET_NULL`); **remove** `partner_id_stub`.
- Python-only `CheckRun.Kind`: `PARTNER_REAPER = "partner_reaper"`, `INTAKE_POLL = "intake_poll"`. Do not AlterField CheckRun.
- No `Site.tier`. No `Site.partner_id`. No `Target.tier`. No `NetworkZone.kind`. No PartnerTemplate table (fixture module, not `catalog/`). Destination order is Partner config, not a NAV console.
- `Secret.Kind.WEBHOOK_SECRET = "webhook_secret"` (Python-only on `vault/models.py`; if makemigrations emits AlterField, fold it into `vault/migrations/0003_phase55.py` — not a second Hub core wave). `owner_type="partner"`, `owner_id=str(partner.pk)`. HMAC kind waits on the slip. The Ed25519 **private** key is never vaulted and never stored as a Partner column (public slots only).

**ACTION_TIERS:** `partner.create` T1, `partner.suspend` T1, `partner.api_kill_switch` T1, `partner.site_takedown` T2, `partner.destination_rank` T2. Labels say “partner”, never “instance”. Global `PARTNER_API_ENABLED` **default OFF**.

**HTTP — intake (not Hub):** see §7 C3. Hub has **zero** partner inbound.

**HTTP — Hub operator (tailnet, not the partner API):**
- `POST /api/v1/partners/` — `core/partner_views.py` included from `core/zone_urls.py` (same `api/v1/` include as AWS connect). **Not** `core/urls.py` (`/api/auth/`). 201 **returns** `hubk_*` + `whsec_` once.
- `POST /api/v1/partners/<int:pk>/suspend/` — `hub/urls.py` beside other T1 routes.
- `POST /api/v1/partner-api/kill-switch/` — `hub/urls.py`.
- `POST /api/v1/sites/<int:pk>/takedown/` — `hub/urls.py` (T2).
- `POST /api/v1/partners/<int:pk>/destination-rank/` — `hub/urls.py` / `core/partner_views.py` (T2).

**Gates:** `make conformance` and `make review-round` stay `python conformance/check.py --phase 5 --exclude-tier t2 --exclude-tier t3`. `make conformance-5.5` = `--phase 5.5 --exclude-tier t2 --exclude-tier t3` and is **not** a `review-round` or `nightly-gates` prereq. `conformance-5` stays phase 5 minus live. `conformance-3` stays all-tiers Phase 3. No `t4`. No all-tiers 5.5.

## 3. Applicable registry reqs

**Task 0 — PART-K stay `phase: 5.5` and become due at `--phase 5.5` (`conformance-5.5`), not on everyday `conformance`. `text:` / `text_hash:` untouched:** `PART-K1-ZERO-INBOUND-HUB` · `PART-K2-REPLAY-AT-HUB` · `PART-K6-NO-INTERNAL-ACTIONS`.

**New (Task 0).** Copy these fields; do not invent. MUST ids have **no `tier:` key**. `source: phase-5.5-design-note.md §3`. SCAN-M4: do not hang full-text §K3/§K4/§K5/§K7 (live CF-for-SaaS, HMAC enablement, MCP, paid edge) on T1 Fake tests. `text_hash:` is computed by Task 0 (`conformance/check.py --print-text-hashes`), not invented here.

- `PART-INTAKE-PROCESS` — `phase: 5.5`, `verify: test`. `text:` `intake/**` is a separate process, not `INSTALLED_APPS`; credential-free import wall (no vault/core/deploys/Celery/cloud SDKs); public listener is the six K3 routes only; outbox is mesh-only; Hub product code does not import `intake`.
- `PART-K3-ENDPOINTS` — `phase: 5.5`, `verify: test`. `text:` six K3 endpoints live on the intake under `/partner/v1/…`; Hub urlpatterns contain neither `/api/partner` nor `/mcp`.
- `PART-HUB-POLL` — `phase: 5.5`, `verify: test`. `text:` Beat polls the outbox every 10 s on `probes`; `intake_client_for` is fail-closed; empty `INTAKE_URL` is SKIPPED/no-op and does not insert a CheckRun every 10 s; N=3 failures file `hub-outbox-poll-failing`; unreachable >5 min files `partner-intake-unreachable`.
- `PART-Q9-SHARED-VECTORS` — `phase: 5.5`, `verify: test`. `text:` one shared signature-vector file drives valid/expired/replayed/mutated-body plus idempotency and quota cases against both the intake verifier and the Hub re-verifier; Hub refuse wins on quota-exceeded.
- `PART-ISOLATION` — `phase: 5.5`, `verify: test`. `text:` isolation is `Partner` + `PartnerSite` + dedicated destination Targets; no `Site.tier`; no `Site.partner_id`; no `Target.tier`; Hub host and non-partner co-host refuse; partner overflow refuses.
- `PART-TEMPLATES` — `phase: 5.5`, `verify: test`. `text:` v1 deploys one digest-pinned fixture template image only; partner Dockerfile, build step, git-as-source, and unconstrained image refuse.
- `PART-WEBHOOKS` — `phase: 5.5`, `verify: test`. `text:` Standard Webhooks exact; Hub egress only through `validate_webhook_url`; re-resolve at every delivery (no git clone-TOCTOU exception); T1 fake sink; `whsec_` vaulted Hub-side, never on intake, never in AuditEvent.detail.
- `PART-CUSTOM-HOSTNAME` — `phase: 5.5`, `verify: test`. `text:` Fake CustomHostname TXT-before-serve as a capability on the object `dns_provider_for` returns; helpers do not construct a Cloudflare client; unverified hostname is never served; no new ACME or DNS-01.
- `PART-KILL-SWITCH` — `phase: 5.5`, `verify: test`. `text:` `partner.create`/`partner.suspend`/`partner.api_kill_switch` are T1; `partner.site_takedown` is T2; enable is T1 not a toggle; global flag default OFF; Fake Transport stop+detach+revoke; reaper plants orphaned partner sites.
- `PART-M2-GIT-WEBHOOK` — `phase: 5.5`, `verify: test`. `text:` git-webhook is a second outbox type on the same Hub poller, Fake-planted, not a public intake or Hub route; no webhook secret on intake; Hub re-validates via `validate_git_url`.
- `PART-U2-QUOTAS` — `phase: 5.5`, `verify: test`. `text:` Hub enforces `max_sites=5`, `deploys_per_day=50`, `domains=5`, fleet cap 12; intake copies are edge-only; unbounded max_sites is out.
- `UX-P55-PARTNERS` — `phase: 5.5`, `verify: test`. `text:` Settings Partners tab after AWS is Create partner not Connect; POST 201 returns `hubk_*` + `whsec_` once (Enroll once-panel) and GET never; Fake / empty `INTAKE_URL` / post-create never Connected; destination-order T2 honesty on the tab (K5 abuse/IP-reputation sentence once for own-server); kill-switch overlays (enable is T1 not a toggle; suspend names stop/detach/revoke; takedown T2 on site detail); F8 partner-intake-empty/error/degraded plus kill/rank overlays and PartnerSite seed (never `Site.tier=partner`); Sites All/Mine/Partner + partner badge (symbol + words); hide adopt and job-create on partner site detail; copy never says instance except `single-instance` and never 99.9% SLA; NAV stays six.
- `P55-PARTNER-DEMO` — `phase: 5.5`, `verify: demo`, `demo: conformance/demos/phase-5.5.md`. `text:` demo record names the MUST path in design note §4; no named partner, no live intake, no HMAC enablement, no MCP.
- `PART-U1-NAMED-PARTNER` — `phase: 5.5`, `verify: demo`, `demo: conformance/demos/named-partner.md`. `text:` a named committed partner exists as a Joseph-filled artifact; missing file is uncovered; T1 fixture slugs are not this proof.

**Tiered, not review-round MUST** (Task 0 registers; `--exclude-tier` drops them from `conformance-5.5`). T1 Fake tests do **not** mark these ids (D-024). Skip-unless the existing test-plane wall (`HUB_TEST_MODE` + `HUB_TEST_ZONE_SLUGS`). Do not invent `HUB_TEST_CF_TOKEN`. Do not waive.

- `PART-Q9-T2-CONTAINER` — `phase: 5.5`, `verify: test`, `tier: t2`. `text:` intake container + Hub poller: signed job becomes a Deployment; tamper audits; replay rejected at Hub even when forwarded.
- `PART-Q9-T3-LIVE-PATH` — `phase: 5.5`, `verify: test`, `tier: t3`. `text:` nightly live partner-path (named partner + test-zone template deploy + live webhook + live kill switch) runs only behind the existing test-plane wall; absent config is skipped-only.

**Waivers:** Task 0 waives **nothing that is MUST**. Do not retire `TLS-B2-HUB-DNS01-UNPROXIED`, `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`, `HARNESS-T3-LE-STAGING`, `DNS-CF-T3-LIVE`, or `REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven`. Do not waive PART-K1/K2/K6 or PART-U1. Do not register a live-intake MUST id. `failed` / `not-collected` are unwaiable. HMAC writeup is not a due id.

## 4. Exit demo

Settings Partners tab: empty tab is one sentence + T1 **Create partner** (not Connect); Fake / empty `INTAKE_URL` / post-create never paints `Connected` (name the Fake). T1 `partner.create` requires WebAuthn touch + type-the-name (confirm = slug), mints Ed25519, **201 returns** `hubk_test_` + `whsec_` **once** (Enroll once-panel: copy + “I saved them”; closing loses them); GET / list / AuditEvent / Finding / CheckRun / log never echo them; private key is not a Partner column and is not vaulted; AWS connect still never echoes pasted IAM keys. Global partner-API flag is OFF until T1 `partner.api_kill_switch` enables it (same id, label “Enable partner API”, type `partner-api` — never a toggle) → signed `POST /partner/v1/sites` on the **intake** (in-process Fake) with Idempotency-Key lands in the mesh outbox; Hub Beat (10 s, `probes`) pulls, **re-verifies** Ed25519 from the shared vector file (including quota-exceeded), rejects expired / mutated-body / replay **even when the Fake intake forwards**, stores first response 24 h, mismatch 422 → validated job becomes an ordinary Deployment on a dedicated destination Target via `PartnerSite` (no `Site.tier` / `Site.partner_id` / `Target.tier`); partner Dockerfile / git-source / unconstrained image refuses; partner A 404s on B’s ids; Hub host and non-partner co-host refuse; overflow scale refuses; scheduled-job create on that site refuses → Settings Partners ranker: empty `destination_order` is visible and create-site refuses; default dedicated cloud first; ranking `kind=ssh` is T2 `POST /api/v1/partners/<pk>/destination-rank/` with ConfirmDialog `summary` = the K5 honesty sentence once (“abuse takedowns and IP-reputation damage land on hardware and residential/office connections you cannot dispose of”) then the save proceeds; own-server without tunnel refuses as a Finding, not a nag → Fake CustomHostname (capability on the `dns_provider_for` object) is not served until TXT verifies; Standard Webhooks Hub-egress re-resolves at every delivery, signs vs a reference verifier against a Fake sink; `whsec_` is vault-only → T1 `partner.suspend` overlay names stop containers / detach routes / revoke the Hub-side key; per-site takedown is T2 on partner site detail (`{domain} route → 410`) → 410; reaper weekly drill plants an orphaned partner site and writes `CheckRun.Kind.PARTNER_REAPER`; Multipass and AWS purpose=test reapers stay → partner-site hard-down is P2 fingerprint `site-down:{name}` (Partner FK); N≥2 is P1 fingerprint `partner-aggregate-down:{partner.pk}`; partner-tier host down reuses `host-down:{host}`; prod host-down is not `partner-aggregate-down` → git-webhook outbox type on the **same** poller is Fake-planted `{type: "git-push"}` with zero Hub/intake inbound listener → quotas: fifth site over `max_sites=5` refuses; fleet cap 12 refuses; empty `INTAKE_URL` SKIPPED not P1 and does not grow CheckRun every 10 s → NAV is still six; F8 partner-intake-empty/error/degraded plus kill/rank overlays render (`REQUIRED_STATE_IDS`); Sites All/Mine/Partner + `partner` badge (symbol + words); hide adopt and job-create; copy never says “instance” except `single-instance`; SLA is response-time, never 99.9%.

Record: `conformance/demos/phase-5.5.md`. Does **not** claim U1 named partner or live intake. `PART-U1-NAMED-PARTNER` stays uncovered until Joseph writes `conformance/demos/named-partner.md`. Everyday `make review-round` (phase 5) may go green while U1 is uncovered. Two consecutive clean **`make conformance-5.5`** rounds wait on that interrupt; T1 task merges may proceed. `make conformance-5.5` is the phase gate and **excludes t2/t3**. Live intake / CF-for-SaaS stay skipped-only, never a T1-sibling green. No invented token env. No paid edge.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

Not open `DECISION:` blockers. Irreversible/spend: named partner, live intake VM / `api.partners.<domain>`, live Cloudflare-for-SaaS, any paid edge, dedicated partner cloud targets are Joseph interrupts. MUST does not enable them.

- **D-075** Protective cut — T1 Fake-intake REST, Hub poll + re-verify + replay/idempotency, six K3 endpoints on intake, Partner/PartnerSite isolation, Standard Webhooks Hub-egress Fake sink, Fake CustomHostname TXT-before-serve, M2 git-webhook on the same poller, Settings Partners tab, T1 kill switches, U2 finite quotas, PART-K verified; live VM/CF-SaaS/named partner/paid edge Joseph; MCP/Azure/scaler/DNS-01/N1/7th NAV/`Site.tier`/Hub inbound out; HMAC is first slip.
- **D-076** One Hub wave `0013_phase55.py`: `Partner`, `PartnerSite`, Hub replay-nonce table, Hub idempotency store; `AuditEvent.partner` real FK replaces `partner_id_stub`; `0012` stays closed; Task 1 is the only `core/models.py` writer. No `Site.partner_id`. No `Target.tier`.
- **D-077** `intake/` is a separate process, not `INSTALLED_APPS`; import rule: intake never imports `vault` / `core` models / `deploys` / Celery / cloud SDKs; Hub product modules never `import intake`; Hub never mounts intake URLs; Fake intake is the T1 default; two verifiers, one shared vector file; `intake_client_for` speaks HTTP or an injected `FakeIntakeClient`.
- **D-078** Isolation is Partner + PartnerSite + dedicated destination Targets (a Target in any Partner `destination_order` hosts only `PartnerSite` rows); no `Site.tier` (D-053 stands); no `Site.partner_id`; no `Target.tier`.
- **D-079** `custom_hostname` is a `DnsProvider.capabilities()` flag on the object `dns_provider_for` (or the injected Fake) returns; create/status/TXT live on that object; `providers/custom_hostname.py` is helpers only (no vault token load, no `api_request`, no Cloudflare HTTP client). Route 53 and Fake-without-the-flag omit the capability. `EdgeProtection` stays CF-only. Live CF-for-SaaS is Joseph. Partner-base domain never hosts Joseph prod sites. No new ACME / DNS-01.
- **D-080** `conformance` / `review-round` stay `--phase 5 --exclude-tier t2 --exclude-tier t3`. `conformance-5.5` is `--phase 5.5 --exclude-tier t2 --exclude-tier t3` and is the Phase 5.5 exit gate (`PART-U1-NAMED-PARTNER` due there only). `conformance-5` stays phase 5 minus live. `conformance-3` stays all-tiers 3. `nightly-gates` still uses `conformance-3`. `conformance-5.5` is not a `review-round` or `nightly-gates` prereq. No `t4`. No all-tiers 5.5. New MUST ids are tier-less. Q9 T2/T3 ids carry `tier:` so exclude-tier drops them. This overrides the scope-panel Gates row for everyday `conformance` only, so U1 cannot hostage T1 merges.
- **D-081** U1 “named, committed partner” is a Joseph interrupt / live-exit gate, **not** a freeze on T1 implementation; do not invent a partner name; T1 may use an in-test fixture slug only; `PART-U1-NAMED-PARTNER` missing file = uncovered on `conformance-5.5`, not on `conformance`/`review-round`.
- **D-082** ACTION_TIERS: `partner.create` / `partner.suspend` / `partner.api_kill_switch` T1; `partner.site_takedown` / `partner.destination_rank` T2. Settings tab `{id: "partners", label: "Partners"}` after AWS is **Create partner**, not Connect. NAV stays six. No `connect_partner`. K6 “no T1/T2” is the partner router only. Global `HUB_PARTNER_API_ENABLED` → `PARTNER_API_ENABLED` default `False`. Enable is T1 (type `partner-api`), not a toggle. POST `partner.create` 201 **returns** `hubk_*` + `whsec_` once; GET never.
- **D-083** Ed25519 default; Hub re-verifies against Partner pubkey slots; 5-minute window; Hub nonce cache (10 min TTL); Stripe-style Idempotency-Key 24 h. Shared `conformance/fixtures/partner-signature-vectors.json` (incl. quota-exceeded; Hub refuse wins). HMAC/bearer is evaluation-only this wave. Partner columns store public keys only; the private key is never vaulted.
- **D-084** U2 numbers: Partner defaults `max_sites=5`, `deploys_per_day=50`, `domains=5`; `HUB_PARTNER_FLEET_MAX_SITES` → `PARTNER_FLEET_MAX_SITES` default `12`; rate floors 60 req/min general, deploy-create 3/min + 100/day per site; Hub-authoritative; quota-abuse files `budget-cap-hit` fingerprint `budget-cap-hit:partner`; unbounded `max_sites` is out.
- **D-085** M2 git-webhook is MUST as a second **outbox type** on the same poller (Fake-plant `{type: "git-push"}`; Hub re-validates via `validate_git_url`). No GitHub/webhook HTTP listener on intake or Hub. No webhook secret on intake. MCP is OUT, not a slip. Named first slip = HMAC/bearer writeup.

## 6. Out of scope (explicitly)

MCP adapter · Azure adapter · overflow scaler (the refuse gate stays; partner overflow also refuses) · Hub-central DNS-01 · restore UI · Router Advisor · 7th NAV item · Partners/Intake/Webhooks/Catalog consoles · N1 recreate redo · 3b adopt redo · `NetworkZone.kind` · `Site.tier` · `Site.partner_id` · `Target.tier` · HMAC **enablement** · live intake VM / `api.partners.<domain>` · live Cloudflare-for-SaaS · any paid edge · dedicated live partner cloud targets · Cloudflare Workers intake · billing-grade metering · inventing a partner name · inventing `HUB_TEST_CF_TOKEN` / `HUB_TEST_AWS_TOKEN` / `HUB_TEST_PARTNER_TOKEN` / `HUB_WEBHOOK_SECRET` · Hub inbound `/api/partner/*` or `/mcp` · a GitHub/webhook HTTP listener on intake · `t4` · all-tiers 5.5 · a 4th F6 phone screen · `connect_partner` checklist · UI copy that calls a partner site an “instance” · painting `Connected` on Fake / empty `INTAKE_URL` / post-create · a CheckRun insert every 10 s for unconfigured intake.

**May slip without failing the MUST demo:** HMAC/bearer writeup (first) · 90-day dual-key rotation playbook (instant Hub revoke stays MUST) · lookalike-brand denylist polish (partner-base ≠ Joseph prod is MUST) · L5 Under-Attack on a live intake hostname · U2 full §12.5 prose beyond the numeric defaults · Q9 T2 container · Q9 T3 live path. **Not** slip-able: T1 Fake intake, Hub poll + re-verify + replay/idempotency, six K3 endpoints on intake, Partner/PartnerSite isolation, template-only refuse, K6/V3 tests, Standard Webhooks Fake sink + re-resolve, Fake CustomHostname on `dns_provider_for`, M2 git-webhook outbox type, Settings Partners tab + F8 + kill/rank chrome, T1 kill switches + reaper orphan + O1 P2, U2 numbers, `0013`, PART-K verified, `conformance-5.5` minus live tiers.

## 7. Closed answers (panel — do not reopen)

### C1 — Protective cut / U1 / slips

MUST is T1 Fake Partner Intake + Hub poll + Hub-authoritative Ed25519 re-verify + Postgres replay/idempotency + six K3 REST endpoints on **intake** + Partner/PartnerSite isolation (no `Site.tier`) + K6 tests + Standard Webhooks T1 fake sink + Fake CustomHostname TXT-before-serve + M2 git-webhook as second outbox type + Settings Partners tab + T1 kill switches + PART-K1/K2/K6 verified + `conformance-5.5` minus live + `PART-U1-NAMED-PARTNER` `verify: demo` (file missing = uncovered on `conformance-5.5`; Joseph names it later).

U1 is the **exit** gate, not a start block. Implement T1 Fake now. Never skip-unless U1, never invent a partner, never T1-sibling-green live intake. Everyday `conformance` / `review-round` stay phase 5 so T1 merges are not red on U1. Two consecutive clean **`conformance-5.5`** rounds wait on the Joseph interrupt. Do not stub `named-partner.md`. Do not waive U1 / PART-K / `failed` / `not-collected`.

Named first slip = HMAC/bearer (K2 fallback; do not build until a named partner cannot sign). MCP is **OUT** (U1 cut from v1, not a slip). M2 git-webhook outbox is **MUST**.

Joseph: named partner, live intake VM / `api.partners.<domain>`, live CF-for-SaaS, paid edge, dedicated partner cloud targets.

### C2 — Schema

`0013` = Partner + PartnerSite + `PartnerReplayNonce` + `PartnerIdempotencyKey` + `AuditEvent.partner` FK (drop `partner_id_stub`). CheckRun kinds `partner_reaper` and `intake_poll` are Python-only. `0012` closed. Task 1 is the only `core/models.py` writer. No `Site.tier`. No `Site.partner_id`. No `Target.tier`. No `NetworkZone.kind`. Public keys live on Partner (not vault). `whsec_` is `Secret.Kind.WEBHOOK_SECRET`. The Ed25519 private key is never vaulted as the public column. HMAC vault kind waits on the slip. Templates are `core/partner_templates.py` (one digest-pinned fixture), not a Hub table and not `AppliedCatalogEntry`.

A Target is partner-tier iff its pk appears in any Partner `destination_order`. That Target may host only `PartnerSite` rows, never the Hub host, never a non-partner Site.

### C3 — Intake HTTP / process / import wall

Intake is a **stdlib WSGI** process (`intake/app.py` callable `application`; `intake/__main__.py` entry). No Django, no DRF, no Flask/FastAPI/Starlette. `cryptography` (Ed25519) is allowed on intake; vault/KEK/Django/Celery/boto3/azure/cloudflare are not.

**Public routes (six K3 families under `/partner/v1/`):**
- `POST /partner/v1/sites`
- `POST /partner/v1/sites/{id}/deployments`
- `GET /partner/v1/deployments/{id}`
- `POST /partner/v1/sites/{id}/domains`
- `GET /partner/v1/domains/{hostname}`
- idempotent `DELETE /partner/v1/sites/{id}` and `DELETE /partner/v1/sites/{id}/domains/{hostname}` (absent = 204)

**Mesh-only (not on the public listener):** `GET /internal/outbox`, `POST /internal/ack`. T1 standing test: a public client cannot hit `/internal/*`. Git-push is **not** a 7th public route.

Hub urlpatterns gain **zero** `/partner/`, `/api/partner/`, or `/mcp` routes. Extend `tests/test_git_poller.py` needles/paths: `/api/partner`, `/api/partner/`, `/api/partner/v1/sites`, `/partner/v1/sites`, `/mcp`, `/mcp/`.

Standing import test: `intake/` does not import `vault`, `core`, `deploys`, `celery`, `hub`, `django`, `boto3`, `botocore`, `azure`, `cloudflare`. Hub product modules (`monitor/`, `core/`, `hub/`, `deploys/`) never `import intake`. Hub never includes intake URLs. Intake is not in `INSTALLED_APPS`. T1 tests may import `intake`.

Task 2 verify stub is **fail-closed**: missing/invalid signature → 401/403, never 201/202. 201/202 tests sign with a fixture key.

### C4 — Auth / vectors / replay / idempotency

Ed25519. Canonical string: `{method}\n{path}\n{hex(sha256(body))}\n{timestamp}\n{nonce}`. Headers: `X-Partner-Timestamp` (unix seconds), `X-Partner-Nonce`, `X-Partner-Key-Id`, `X-Partner-Signature` (base64). `Idempotency-Key` as Stripe: first response stored 24 h keyed by `(partner, key)` + `params_hash`; replay returns it verbatim; param mismatch = 422.

5-minute timestamp window (Hub authoritative). Nonce cache TTL **10 minutes**. Two pubkey slots per Partner (current + previous). Key material **shown once** with `hubk_live_` / `hubk_test_` prefixes: POST `partner.create` **201 returns** `hubk_*` + `whsec_` once (Enroll once-panel). GET / list never echo private material. AuditEvent / Finding / CheckRun / log / task arg never contain `hubk_`, `whsec_`, PEM, or raw key bytes. Hub stores **public** keys only on Partner columns; `vault.put` is `WEBHOOK_SECRET` only (never the Ed25519 private key). Instant Hub revocation is MUST (drop the slot / `suspended=True`). 90-day rotate playbook may slip. AWS connect still never echoes pasted IAM keys.

Shared file: `conformance/fixtures/partner-signature-vectors.json`. Cases: valid, expired, replayed, mutated-body, idempotency match, idempotency mismatch, quota exceeded. `intake/verify.py` and `core/partner_verify.py` both consume it and must not share implementation. Both load the quota-exceeded vector; Hub refuse wins (intake “allow” cannot override).

HMAC/bearer is **not built**. Task 10 is a writeup only (`docs/hmac-bearer-evaluation.md`). If it ever lands later, secret + verify are Hub-side only.

### C5 — Isolation / templates / destination / V3

No `Site.tier`. No `Site.partner_id`. No `Target.tier`. Partner-ness = `PartnerSite` membership. Hub re-validator (intake is untrusted) refuses: Hub host (topology r1 hostname), Target that already hosts a non-`PartnerSite`, Target not in this Partner’s `destination_order`, overflow auto-scale, scheduled-job create/edit on a `PartnerSite` (V3), partner Dockerfile / `jobs_image` / git URL / unconstrained image.

Templates: one fixture under `images/partner-t1-static/` + digest file `conformance/fixtures/partner-t1-template.digest`. T1 ships via docker load / Fake registry. Wildcard `*.apps.<partner-base>` is a DB row + Caddy route, zero DNS, never ACME.

Destination order lives on Settings Partners. Default rank: dedicated cloud targets first. Empty `destination_order` → create-site refuses (tab copy says so). Ranking an own-server (`kind=ssh`) target is T2 `partner.destination_rank` via `POST /api/v1/partners/<int:pk>/destination-rank/`; confirm `summary` is the K5 honesty sentence **once** (“abuse takedowns and IP-reputation damage land on hardware and residential/office connections you cannot dispose of”) and then the save proceeds. Honesty sentence only when the save includes `kind=ssh`. Own-server partner destinations refuse unless Fake `collect_payload["tunnel"] is True` (Finding, not a nag). Partner-base domain ≠ any non-partner Site domain. Task 7 owns the ranker chrome.

`scaling/attack_gate.py` stays. Partner overflow also refuses (even when the playbook is not engaged).

### C6 — Poller / Beat / env / M2

Env: `HUB_INTAKE_URL` → `INTAKE_URL` default `""`. `HUB_PARTNER_API_ENABLED` → `PARTNER_API_ENABLED` default `False`. `HUB_PARTNER_FLEET_MAX_SITES` → `PARTNER_FLEET_MAX_SITES` default `12`. **Do not invent `HUB_TEST_CF_TOKEN` / `HUB_TEST_AWS_TOKEN` / `HUB_TEST_PARTNER_TOKEN` / `HUB_WEBHOOK_SECRET` / `HUB_INTAKE_HMAC`.**

Beat: `poll-intake-outbox` → `monitor.tasks.poll_intake_outbox` (body in `monitor/intake_poll.py`), `schedule: 10.0`, queue `probes` (existing `monitor.*` route). Per-tick batch cap **20**. Task applies 0–2 s jitter. Constructor `intake_client_for()` fail-closed; tests inject `FakeIntakeClient`. Empty `INTAKE_URL` → no-op, SKIPPED, do not file P1, **do not insert a new CheckRun per 10 s tick** (return without write, or upsert at most one latest `intake_poll` row). Do not add `INTAKE_POLL` / `intake_poll` to `DRILL_PERIODS`. Configured success/failure may persist on **transition**, not every 10 s.

N=3 consecutive poll failures → P2 fingerprint `hub-outbox-poll-failing`. Last successful intake probe > 5 min ago → P1 fingerprint `partner-intake-unreachable`. Unconfigured is not unreachable. Pass `fingerprint=` explicitly for those two global pins.

M2 git-webhook: outbox item `{type: "git-push", git_url, ref, sha}` on the **same** poller. T1 Fake **plants** it (untrusted hint). `git_url` through existing `validate_git_url`. Hub turns it into the existing git-poll enqueue. Partner jobs are `{type: "partner-job", ...}`. No Hub inbound. No GitHub/Gitea/webhook HTTP listener on intake or Hub. Public intake listener stays the six K3 families. No webhook secret / `HUB_WEBHOOK_SECRET` / `GITHUB_WEBHOOK` / HMAC on intake.

### C7 — Webhooks / CustomHostname

`validate_webhook_url` in `core/validators.py`: HTTPS-only (no ssh), ports `{None, 443}`, then the same B10 address checks as git (loopback / link-local / private / reserved / multicast / unspecified / CGNAT / `.local` suffixes refuse). Delivery is Hub egress only (`core/partner_webhooks.py`). **Re-resolve and re-run B10 on every send** (any blocked address → do not POST). Do not inherit git’s “Hub never clones” TOCTOU exception (`core/validators.py` documents that the clone runs on the build target). Redirects off, or `Location` re-validated through the same checks. T1 test: URL accepted when public; later resolve returns link-local/loopback/private/CGNAT → zero mutating call.

Standard Webhooks exact: `webhook-id` / `webhook-timestamp` / `webhook-signature`, HMAC-SHA256 over `id.timestamp.payload`, `whsec_` prefix, dual-secret rotation slots later. T1 Fake sink + reference verifier library (unit, no live POST). Retry ~5× over 24 h; sustained failure disables delivery and files existing kind `hub-egress-degraded` with entity `partner:{pk}` (default fingerprint `hub-egress-degraded:partner:{pk}`). `whsec_` never on intake, never in Finding / CheckRun / log / task arg / `AuditEvent.detail`.

CustomHostname: capability `"custom_hostname"` on the object `dns_provider_for` (or the injected Fake) returns. create/status/TXT live on that object. `providers/custom_hostname.py` is helpers only — no vault token load, no `api_request`, no Cloudflare HTTP client. Task 6 AST-scans the analog of `test_dns_provider_for_is_the_only_construction_path`. Route 53 and Fake-without-the-flag omit the capability. `EdgeProtection` stays CF-only. Serve nothing until verified. Live SaaS API and fallback-origin ADR stay Joseph. No new ACME / DNS-01.

### C8 — T1 ids / UX / F8 / HTTP operator

ACTION_TIERS:

| id | tier | label | confirm_name |
|---|---|---|---|
| `partner.create` | T1 | Create partner | intended slug |
| `partner.suspend` | T1 | Suspend partner | partner slug |
| `partner.api_kill_switch` | T1 | Disable partner API | `partner-api` |
| `partner.site_takedown` | T2 | Take down site | site domain |
| `partner.destination_rank` | T2 | Rank partner destination | target host |

T1 = WebAuthn touch + type-the-name; TOTP does not write `hardware_touch_at`. Overlay for suspend names stop containers / detach routes / revoke key (`T1Overlay` may take optional `summary` of T2 shape; partner T1 omits cost; other T1 ids omit summary). CSAM/phishing auto-suspend has no overlay; files a Finding after. Enabling the API (flag currently OFF) uses the same `partner.api_kill_switch` id with label “Enable partner API” when the flag is off — still T1, never a Settings checkbox/toggle.

Settings tabs gain `{id: "partners", label: "Partners"}` **after AWS**: `security`, `cloudflare`, `aws`, `partners`, `developer`, `vault`. The tab is **Create partner** (mint), not AWS/CF **Connect** (paste). `INTAKE_URL` is env, not a Settings token paste. Empty tab = one sentence + the T1 Create partner button. After 201 and while Fake / empty `INTAKE_URL`, still never `\bConnected\b`; name the Fake. Intake unreachable = P1 Finding `partner-intake-unreachable` **plus** Settings error/degraded with last-confirmed `data as of HH:MM:SS`. NAV stays the six. Do not add `connect_partner` to `checklist.ITEM_IDS`. Do not add a 4th F6 phone screen.

F8 `REQUIRED_STATE_IDS` += `partner-intake-empty`, `partner-intake-error`, `partner-intake-degraded`, kill-switch overlay, destination-order confirm, PartnerSite-bound site (filter + `partner` badge). Seed a PartnerSite-bound site — **never** `tier: partner` on Site, never a committed-partner name. Plus Finding `partner-intake-unreachable`. Hide adopt and job-create on partner site detail. `?sim=` mounts Shell. Badge = symbol + words (`SiteObserved` is the peer).

Copy: “partner site”, “partner-tier target”, “Intake”, “Suspend partner”, “Take down site”. `doesNotMatch /\binstance\b/i` except the existing `single-instance` token. SLA is response-time, not 99.9% (`doesNotMatch /99\.9%|uptime SLA/i` on Settings Partners).

Pinned operator paths: `POST /api/v1/partners/`, `POST /api/v1/partners/<int:pk>/suspend/`, `POST /api/v1/partner-api/kill-switch/`, `POST /api/v1/sites/<int:pk>/takedown/`, `POST /api/v1/partners/<int:pk>/destination-rank/`. `core/urls.py` is `/api/auth/` — do not hang them there.

Minted partner material: 201 **returns** `hubk_*` + `whsec_` once. GET never. AWS connect still never echoes pasted IAM keys.

### C9 — Kill switches / reaper / O1

Global flag default **OFF**. Per-partner suspend: Fake Transport stop containers + detach routes + Hub-side key revoke (`pubkey_*` cleared / `suspended=True`). Per-site takedown on partner site detail → 410. Auto-trigger files P1 fingerprint `partner-kill-switch:{partner.pk}`. Task 7 wires Settings.jsx / Sites.jsx / Tiers.jsx / F8: suspend overlay names stop/detach/revoke; enable is T1 not a toggle; takedown T2 on site detail; F8 those overlays.

Reaper: `monitor/partner_reaper.py` (no boto3, no Multipass). T1 Fake plant of orphaned partner sites (Partner gone / kill-switched / quota-expired) → containers gone + routes detached. Weekly drill analog writes `CheckRun.Kind.PARTNER_REAPER`. Leave `monitor/reaper.py` Multipass `hub-t3-` prefix-only. Leave `monitor/cloud_reaper.py` AWS `purpose=test`. Do not claim `HARNESS-REAPER-TEST-PLANE` covers partner. Do not fold partner reaper into `drill-reaper-weekly` / `DRILL_PERIODS[REAPER]`.

O1 classifier: `monitor/antinoise.py` `_env_role_label` / `_file_open` must **not** map every `host-down:` / `zone-down:` to `partner-aggregate-down`. Partner-ness = `PartnerSite` exists (or Target pk in a Partner `destination_order` for host-down). Do not add a `tier` column to make `_env_role_label` work.

- Partner-site hard-down = kind `partner-site-hard-down` P2, fingerprint **`site-down:{name}`** (the site probe fp; classifier reads Partner FK). Not a new color-only status.
- Partner-tier **host** down = kind `partner-aggregate-down` P1, fingerprint **`host-down:{host}`** (reuse that host-down probe fp).
- N≥2 partner sites down = kind `partner-aggregate-down` P1, fingerprint **`partner-aggregate-down:{partner.pk}`** (pass `fingerprint=` explicitly). Do not escalate by `classify(partner-site-hard-down, aggregate=True)` alone.
- Prod `host-down:` / `zone-down:` **must not** use `partner-aggregate-down` (stay the prod classifier).

Intake as Target: live VM enroll is Joseph. T1 Fake probe is enough. `ufw-posture-intake` / `profile="intake"` stay for the later VM.

### C10 — Gates / env names / Q9 T2 T3

Keep `make conformance` and `review-round` at `--phase 5 --exclude-tier t2 --exclude-tier t3`. Add `conformance-5.5` as `--phase 5.5 --exclude-tier t2 --exclude-tier t3` (`.PHONY`; **not** a `review-round` or `nightly-gates` prereq). Leave `conformance-5` as today’s phase-5 recipe. Leave `conformance-4` / `conformance-3.5` minus-live and `conformance-3` all-tiers 3. `nightly-gates` still uses `conformance-3`. No all-tiers 5.5. No `t4` in `VALID_TIERS`. New MUST ids have **no `tier:` key**. Do not stub `conformance/demos/phase-5.5.md` or `conformance/demos/named-partner.md` in Task 0 (missing = uncovered). Do not edit `REVIEW_CHECKLIST.md` in the judging round. Registry edits are Task 0.

`PART-U1-NAMED-PARTNER` is due at `--phase 5.5` only. Missing `named-partner.md` = uncovered on `conformance-5.5`, not on everyday `conformance`/`review-round`. T1 task merges do not wait on Joseph. Two consecutive clean **`conformance-5.5`** rounds wait on the interrupt. Do not stub. Do not waive U1 / PART-K / `failed` / `not-collected`.

Task 0 tests must **not** pin `conformance` at 5.5. Keep the current phase-5 pin on `conformance`. Named tests: `test_review_round_conformance_is_still_phase_5_minus_live_tiers`; `test_conformance_5_5_is_phase_5_5_minus_live_tiers`; `test_conformance_5_5_is_not_a_review_round_or_nightly_prereq`.

Q9 T2/T3 stay skip-unless the existing test-plane wall. T1 Fake tests do not mark those ids. PART-K become due at `--phase 5.5` and must go `verified` by passed T1 tests, not `WAIVERS.md`.

Pinned names: `HUB_INTAKE_URL`, `HUB_PARTNER_API_ENABLED`, `HUB_PARTNER_FLEET_MAX_SITES`. No invented token env.

### C11 — Quotas (U2 — numbers)

Start from K3’s Netlify-proven floors, then cap the fleet under D-041’s 30-node map bar (zone/host/container/hub/edge nodes). Abuse-grade only; billing-grade OUT.

| Knob | Default | Enforced where |
|---|---|---|
| `Partner.max_sites` | **5** | Hub create-site; intake edge copy |
| `Partner.deploys_per_day` | **50** | Hub deploy-create |
| `Partner.domains` | **5** | Hub add-domain |
| `PARTNER_FLEET_MAX_SITES` | **12** | Hub create-site (all partners) |
| General rate | **60 req/min** / key | both; Hub authoritative |
| Deploy-create rate | **3/min + 100/day per site** | both; Hub authoritative |

Headers `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset`. Fifth site over `max_sites` refuses. Thirteenth fleet partner site refuses. Quota-abuse trip files existing P1 `budget-cap-hit` fingerprint `budget-cap-hit:partner` (refs, never secrets). Intake saying “allow” cannot override Hub.

### C12 — Finding kinds / fingerprints

Register **new** kinds in `monitor/alert_rules.py` **before** first `raise_alert`. Existing partner kinds stay; do not re-register. Tokens / `whsec_` / private keys never in title/body/detail. Kind and fingerprint are **different strings** except the two global pins below (pass `fingerprint=` explicitly; do not use raise_alert default `{kind}:{entity}` for those two). Task lists quote the **fingerprint** column, not the kind.

| kind | sev | fingerprint |
|---|---|---|
| `partner-intake-unreachable` | p1 (exists) | `partner-intake-unreachable` |
| `hub-outbox-poll-failing` | p2 (exists) | `hub-outbox-poll-failing` |
| `partner-kill-switch` | p1 (exists) | `partner-kill-switch:{partner.pk}` |
| `partner-replay` | p2 (**new**) | `partner-replay:{partner.pk}` |
| `budget-cap-hit` | p1 (exists) | `budget-cap-hit:partner` |
| `partner-site-hard-down` | p2 (exists) | `site-down:{name}` (reuse the **site** probe fp; classifier reads Partner FK) |
| `partner-aggregate-down` | p1 (exists) | N≥2 partner sites: `partner-aggregate-down:{partner.pk}`; partner-tier host down: reuse `host-down:{host}`. **Not** every `host-down:` / `zone-down:`. Prod host-down stays the prod classifier. |
| `hub-egress-degraded` | p2 (exists) | `hub-egress-degraded:partner:{pk}` (webhook disable) |

### Already correct (keep)

D-053 / D-054 / D-057 / D-059 / D-060 / D-064 / D-065…D-074. `0009`/`0010`/`0011`/`0012` closed. `findings` is the canonical topic. Triple key for test-plane DNS. `deploys/` never imports `providers.cloudflare` or boto3. Secrets through the vault. Reversible-by-default. `scaling/attack_gate.py` stays. `ssh.rotate` stays T1. FakeCloudProvider / FakeDnsProvider remain what tests inject. `providers/**` and `intake/**` already sensitive-path. PART-K `text:` / `text_hash:` / `phase: 5.5` already correct. `dns_provider_for` / `edge_protection_for` remain the only construction paths (D-033/D-034/D-057).

### Sensitive-path additions (Task 0 claims before the first line of code)

`intake/**` already listed. Also claim: `monitor/intake_poll.py` · `core/partner_webhooks.py` · `providers/custom_hostname.py` · `core/partner_views.py` · `monitor/partner_reaper.py` · `core/partner_verify.py` · **`core/partner_templates.py`** · **`core/partner_jobs.py`** (claim before it exists; Task 4 may materialize there or stay in already-claimed `monitor/intake_poll.py` / `core/partner_verify.py`). `providers/**`, `core/actions.py`, `core/validators.py` (ordinary; webhook URL helper lands there), `monitor/alert_rules.py`, `monitor/reaper.py`, `monitor/cloud_reaper.py`, `scaling/attack_gate.py` already listed. Do not fold Partners create into unclaimed `core/zone_views.py`. Do not broaden to `deploys/**` or `frontend/**` wholesale — Settings Partners and Sites filter land in existing claimed / ordinary UI files as the tasks name them.
