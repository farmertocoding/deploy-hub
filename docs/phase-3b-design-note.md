# Phase 3b Design Note — Adopt + first-run bind

**Phase:** 3b per §I (addendum 2026-07-30, D-032/D-044) · gate float **`3.5`** (same half-step rule as 2.5)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-23 · **Seat:** Grok 4.6
**Estimate:** ~1 wk incl. review. Protective cut: **D-047**. Phase 3 MUST + leftovers are on `master` (`898a0f2`).
**Branch:** these two docs land on **`p3b-design`**; Implementers cut task branches from it. Never implement on `master`. Sensitive-path merges go through the recorded panel vote.
**Closed schema wave:** `0009_phase3.py` stays closed. 3b adds **one** migration, `0010_phase3b.py`, on **`Site` only** — no new tables.

## 1. What lands this phase

Phase 3 shipped DNS/TLS, Findings, and Settings-connect, then cut adopt because §1.12 had five holes. Architect panel I1 left a second hole: connect creates `DnsAccount`/`DnsZone` and vaults a DNS token, but never binds `Site.dns_zone` and never plants `origin_ca_key_ref`. Fail-closed is the honest interim. 3b finishes the operator path that makes a public site deployable, then adopts a live compose stack without taking it down.

### 1.1 MUST

1. **Settings-bind + Origin-CA plant (Architect I1).** Public Site create/save **binds `Site.dns_zone`**. One connected zone → auto-bind; several → picker; none → refuse and file `site-dns-unbound:{pk}` on `findings`. **No Origin-CA paste** (12b stays DNS-token only). Plant is a Hub-local file read: request body carries a **path** under `/var/lib/deploy-hub/` or `/etc/deploy-hub/` (0600, Hub-readable); the view vaults the bytes and sets `DnsAccount.origin_ca_key_ref`. Key bytes never enter the browser, the connect form, Findings, or any `deploys/` payload. Until planted, `resolve_production_seams` still refuses. Test-plane plant stays `HUB_TEST_ORIGIN_CA_KEY` in `tests/harness/cf_zone.py`. Do not invent `HUB_TEST_CF_TOKEN`. Do not add a product env for the Origin-CA key.
2. **§F3 first-run checklist owns Home** until applicable items are done: ① enroll first target · ② connect Cloudflare (skip when the first site is `mesh_only`, review3 §M4) · ②b plant Origin-CA (skip for mesh-only / unproxied-until-refused; required before the first proxied public deploy) · ③ add a project (the POST that binds `dns_zone`). After that, Home is today's map + fleet.
3. **Adopt-existing-site**, with §1.12 closed as follows.

**(a) Compose-as-unit vs V5 — V5 compression, one Site.** A compose stack is not a new multi-container Site. Classify into the existing manifest: one **service** container + optional **static_route** + optional **jobs** (worker / beat / scheduler / one-shot migrate, same image or `jobs_image`) + optional Hub-provisioned cache. Site-owned edge is `Site.edge_owner`, not a second Site. Two unrelated public services that cannot compress → Finding, refuse, split into two Projects. Matches `WIZ-V5-ONE-MANIFEST` and Task 15's `classify_services()`.

**(b) Compose source — the §A4 clone (or `Project.local_path`).** `read_compose` uses `yaml.safe_load` on the Project tree and **executes nothing** (M1). Filename order: `docker-compose.prod.yml`, `compose.prod.yaml`, `docker-compose.yml`, `compose.yaml`. Operator paste is refused (no field). A live-host compose file, if present, is **`Transport.get` observation only** — a drift Finding against the git compose **blocks the flip**; it is never the plan source. `deploys/` still never constructs a Cloudflare client.

**(c) Temp subdomain — site's own `DnsZone`; adopt_flow + Beat clean up.** Name `{slug}-adopt-{8hex}.{DnsZone.name}` (8hex from the adopt `CheckRun`). Same `proxied` as the Site. Desired state is a `DnsRecord` row. No dedicated adoption zone (that would be a second token; Settings-connect is one-zone). Mesh-only adopt has no temp name. Cleanup owner is **`deploys/adopt_flow.py::cleanup`**: on cancel, on successful flip (delete the temp name, not prod), and on Beat `adopt-temp-reaper` when a `CheckRun(kind=adopt)` still names a temp older than **24 h from first upsert**. Failed cleanup files `adopt-temp-orphan:{site_pk}:{name}` (P2) on `findings`. This 24 h is an abandon TTL, **not** a Hub-down and not a REL-P2 claim.

**(d) DB/volume — point-in-place; never a silent strand (§N6).** Register every compose named volume onto existing `SiteVolume`. A compose `db`/`postgres` service is a **connection pointer** (vault the live `DATABASE_URL`); do **not** start a second Postgres on the same data dir and do **not** call the Hub DB provisioner as a silent default. App volumes may be mounted by the verify container while the old stack is up (T2 plan text says so). Flip **refuses** if any named volume is unmapped. Decommission stops old containers and **never** `docker volume rm` a registered name (Task 15's confirmation test). Move-to-new-cluster is Phase 4 backup/restore. Two writers on one Postgres data dir is forbidden.

**(e) Caddy ownership — `Site.edge_owner ∈ {host_caddy, site_caddy}`, default `host_caddy`.** `adoption_plan` writes it once from classification (caddy/nginx/traefik publishing 80/443 → `site_caddy`). Ambiguous → Finding blocks until the operator PATCHes the field **once** (T2). Not a per-run prompt. Fresh Hub sites stay `host_caddy`. `host_caddy`: ignore the compose edge service, keep `ensure_route`. `site_caddy`: do not PUT a colliding host-Caddy route for that domain.

### 1.2 MUST vs 3b-later

| Item | Line |
|---|---|
| Settings-bind + Origin-CA plant (I1) | **MUST** |
| §F3 checklist owns Home | **MUST** |
| Adopt (a)–(e), retire `PROV-J7` + `PROV-E6-ADOPT-TEMP-SUBDOMAIN` | **MUST** |
| Hub-central DNS-01 (`TLS-B2-HUB-DNS01-UNPROXIED`) | **3b-later / stay phase 4.** Unproxied refusal stays. The Phase-3 SEC-B2 waiver line that says “built in Phase 3b” is wrong; Task 0 corrects it to phase 4. |
| App-log viewer §E3 | **3b-later** (own `site.{id}.applog` authz; no registry id today) |
| Scheduled-jobs UI §E8/`jobs_image` §N7 | **3b-later** (arbitrary-command surface; V3 tiers exist, the UI does not) |
| Backup/restore operator surface §E5 | **stay Phase 4** |
| LE-staging credentialed run | **leftover, not 3b MUST.** Do not invent `HUB_TEST_CF_TOKEN`. |
| 24 h Hub-down | **not this phase.** D-042 stays. |

## 2. Interfaces / tables that change

**Migration `0010_phase3b.py` (Site only):** `Site.edge_owner` (`host_caddy` \| `site_caddy`, default `host_caddy`). No new models. Adopt progress lives on `CheckRun.Kind.ADOPT` (Python choices; CharField, no migration) + `CheckRun.results` (`schema_version`, `temp_name`, `stage`, `started_at`) + existing `DnsRecord` / `SiteVolume` / `BackupUnit` / `Finding`.

**Interfaces:** `POST /api/v1/projects/` creates Project+Site and binds `dns_zone` (public). `POST /api/v1/dns-accounts/{id}/origin-ca-plant/` (path only). `provision/adopt.py`: `read_compose`, `classify_services`, `adoption_plan` (Findings + one manifest + volumes + `edge_owner`). `provision/service.py`: occupied host is “stack we can adopt” → plan, not only refuse. `deploys/adopt_flow.py`: temp DNS via `desired["dns"]` from `dns_provider_for` → verify (HTTP 200 + site healthz) → flip prod name → decommission old path → `cleanup`. Flip refuses unless verify recorded success for this image tag. Beat `adopt-temp-reaper`. Home checklist snapshot on the existing shell events client; topic remains **`findings`**. `deploys/` never imports `providers.cloudflare`. `HUB_TEST_ZONE_SLUGS` is the allowlist; `HUB_TEST_DNS_ZONE` stays retired.

`check.py --phase 3.5`; `make conformance-3.5`; review-round stays `--phase 3 --exclude-tier t2 --exclude-tier t3` (Phase 3 MUST does not grow).

## 3. Applicable registry reqs

**Already due, waived until 3b tests:** `PROV-J7-COMPOSE-AWARE-ADOPT`, `PROV-E6-ADOPT-TEMP-SUBDOMAIN` — **bump to `phase: 3.5`** (D-020 phase-bump) and retire the waiver lines when the marked tests pass.

**New (Task 0):** `DNS-SITE-ZONE-BIND` · `TLS-B2-ORIGIN-CA-PLANT` · `UX-F3-FIRST-RUN-CHECKLIST` · `P3B-ADOPT-DEMO` (`verify: demo`).

**Not due:** `TLS-B2-HUB-DNS01-UNPROXIED` (phase 4) · `SEC-F5-T1-HARDWARE-TOUCH` (phase 4) · LE-staging credentialed body · REL-P2 24 h.

## 4. Exit demo

Connect Cloudflare (existing 12b) → plant Origin-CA from a Hub-local file → add a public project (Site.dns_zone bound, no unbound Finding) → §F3 card leaves Home → enroll/use a target that is occupied → fresh-host guard offers adopt, not only refuse → plan classifies the three fixture stacks (web+worker+beat+migrate; web+site-Caddy; web only) → temp `{slug}-adopt-{8hex}` upserts in the site's `DnsZone` → verify 200 → flip prod name → old path decommissioned, registered volumes still present → cancel/abandon deletes the temp name (flow + 24 h reaper) → a compose with two public services refuses with a Finding. Record: `conformance/demos/phase-3.5.md`. `make review-round` twice clean (still Phase 3 minus live tiers). `make conformance-3.5` is the 3b gate; live tiers stay skipped-only + dated waiver, never a T1-sibling green. No 24 h Hub-down. No invented test-zone token.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

Not open `DECISION:` blockers. Irreversible/spend: adopt flip writes the operator's own `DnsZone` (T2, Hub-side adapter); test plane stays `purpose=test` + `HUB_TEST_ZONE_SLUGS`. Origin-CA plant reads a file the operator placed on the Hub. No new Cloudflare spend.

- **D-047** Protective cut — §1.2. MUST = bind + plant + F3 + adopt (a)–(e). App-log, jobs UI, DNS-01, backup UI, LE-staging, 24 h Hub-down are out.
- **D-048** V5 compression for adopt: one Site; no multi-container Site model.
- **D-049** Compose source is the §A4 clone / `local_path`. Paste refused. Live compose is observe-and-diff only.
- **D-050** Temp name lives in `Site.dns_zone`. Cleanup = `adopt_flow.cleanup` + Beat `adopt-temp-reaper` (24 h abandon TTL). No adoption zone.
- **D-051** Adopted data is point-in-place (`SiteVolume` + existing `DATABASE_URL`). Unmapped volume blocks flip. No silent second DB. No `docker volume rm` of a registered name.
- **D-052** `Site.edge_owner` is the per-site Caddy record. Written by the plan or one T2 PATCH, never a per-run prompt.

## 6. Out of scope (explicitly)

App-log viewer · scheduled-jobs UI + `jobs_image` run-in-own-image · Hub-central DNS-01 · backup/restore UI · LE-staging credentialed run · 24 h Hub-down · WebAuthn / T1 hardware · attack playbook / `EdgeProtection` · vault Settings screen (Phase 4; plant is the one Origin-CA write) · AWS/Azure · partner intake · D-012.

**May slip without failing the MUST demo:** simulation-seed completeness beyond the adopt/checklist states · phone-width polish on the new cards. **Not** slip-able: bind, plant, F3, classify/plan, temp subdomain, verify-before-flip, abandon cleanup, volume register-and-refuse.

**MUST:** Task 0 gate · `0010` `edge_owner` · bind + file-plant · F3 Home card · compose plan + occupied-host adopt pointer · adopt flow + reaper · retire the two adopt waivers · demo record.
