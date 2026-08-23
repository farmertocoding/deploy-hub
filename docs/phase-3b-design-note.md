# Phase 3b Design Note — Adopt + first-run bind

**Phase:** 3b per §I (addendum 2026-07-30, D-032/D-044) · gate float **`3.5`** (same half-step rule as 2.5)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-23 · **Seat:** Grok 4.6
**Estimate:** ~1 wk incl. review. Protective cut: **D-047**. Phase 3 MUST + leftovers landed on `master` at `898a0f2`; master has since moved. **Do not merge master into `p3b-design` for this wave.**
**Branch:** these two docs land on **`p3b-design`**; Implementers cut task branches from it. Never implement on `master`. Sensitive-path merges go through the recorded panel vote.
**Closed schema wave:** `0009_phase3.py` stays closed. 3b adds **one** migration, `0010_phase3b.py`, on **`Site` only** — `Site.edge_owner` only. No new tables. Do not add a Site FK to `CheckRun`. Do not add `Site.tier`.
**Panel:** Architect `285f8f94` · Security `7feafebe` · QE `2b0a7f89`. §7 is binding. An Implementer who invents a path, env, Finding fingerprint, or gate shape that §7 does not name is implementing the wrong design.

## 1. What lands this phase

Phase 3 shipped DNS/TLS, Findings, and Settings-connect, then cut adopt because §1.12 had five holes. Architect panel I1 left a second hole: connect creates `DnsAccount`/`DnsZone` and vaults a DNS token, but never binds `Site.dns_zone` and never plants `origin_ca_key_ref`. Fail-closed is the honest interim. 3b finishes the operator path that makes a public site deployable, then adopts a live compose stack without taking it down.

### 1.1 MUST

1. **Settings-bind + Origin-CA plant (Architect I1).** `POST /api/v1/projects/` creates Project+Site in one transaction (body in §7 I-target). Public Site create **binds `Site.dns_zone` to one matching-purpose eligible zone** (§7 I-purpose). One eligible zone → auto-bind; several eligible → body `dns_zone` required; zero eligible → **409, no Project, no Site, no Finding**. `site-dns-unbound:{pk}` is **illegal**: `site_public_requires_dns_zone` forbids an unbound public Site, so there is no `pk` to hang a Finding on. Mesh-only may omit the FK. **No Origin-CA paste** (12b stays DNS-token only). Plant is a Hub-local file read: body `{path}` only, and `path` must resolve inside an Origin-CA **subdir** (§7 S1) — not `/etc/deploy-hub/` or `/var/lib/deploy-hub/` wholesale. Vault with the shape `origin_cert_issuer_for` already loads (§7 I-plant). Key bytes never enter the browser, the connect form, Findings, Manifest, CheckRun, or any `deploys/` payload. Until planted, `resolve_production_seams` still refuses. Test-plane plant stays `HUB_TEST_ORIGIN_CA_KEY` in `tests/harness/cf_zone.py`. Do not invent `HUB_TEST_CF_TOKEN`. Do not add a product env for the Origin-CA key.
2. **§F3 first-run checklist owns Home** until applicable items are done: ① enroll first target · ② connect Cloudflare (skip when the first site is `mesh_only`, review3 §M4) · ②b plant Origin-CA (skip for mesh-only / unproxied-until-refused; required before the first proxied public deploy) · ③ add a project (the POST that binds `dns_zone` and `primary_target`). After that, Home is today's map + fleet.
3. **Adopt-existing-site**, with §1.12 closed as follows.

**(a) Compose-as-unit vs V5 — V5 compression, one Site.** A compose stack is not a new multi-container Site. Classify into the existing manifest: one **service** container + optional **static_route** + optional **jobs** (worker / beat / scheduler / one-shot migrate, same image or `jobs_image`) + optional cache. Site-owned edge is `Site.edge_owner`, not a second Site. Two unrelated public services that cannot compress → Finding, refuse, split into two Projects. Matches `WIZ-V5-ONE-MANIFEST` and Task 15's `classify_services()`. On **adopt**, a classified cache/redis is a **pointer** (same rule as db in (d)), not a Hub-provisioned cache. Hub-provisioned cache stays the fresh-site path.

**(b) Compose source — the §A4 clone (or `Project.local_path`).** `read_compose` uses `yaml.safe_load` on the Project tree and **executes nothing** (M1). Filename order: `docker-compose.prod.yml`, `compose.prod.yaml`, `docker-compose.yml`, `compose.yaml`. Operator paste is refused (no field). Live-host compose is **not** discovered. `live_compose_path` is an explicit `adopt_flow` argument (§7 I-live). Unset → no drift check. No disk walk. `/srv/sites/{slug}` is the post-Hub layout, not a default compose path. When the argument is set, `Transport.get` that path only, diff against the git compose, and **block the flip** on drift. `deploys/` still never constructs a Cloudflare client.

**(c) Temp subdomain — site's own `DnsZone`; adopt_flow + Beat clean up.** Name `{slug}-adopt-{8hex}.{DnsZone.name}`. **8hex = `secrets.token_hex(4)`**, stored in `CheckRun.results["temp_name"]` at first upsert and reused after (I-run). Same `proxied` as the Site. Desired state is a `DnsRecord` row. No dedicated adoption zone. **Mesh-only adopt has no temp DNS**; verify over mesh seams (`resolve_production_seams` returns `(None, None)`; probe healthz via `Transport` on the adopted container); decommission still runs. Cleanup owner is **`deploys/adopt_flow.py::cleanup`**: on cancel, on successful flip (delete the temp name, not prod), and on Beat `adopt-temp-reaper` when a `CheckRun(kind=adopt)` still names a temp older than **24 h from `results.started_at`**. Failed cleanup files `adopt-temp-orphan:{site_pk}:{name}` (P2) on `findings`. This 24 h is an abandon TTL, **not** a Hub-down and not a REL-P2 claim. Reaper reconstructs the provider via `dns_provider_for(site.dns_zone)` / seams using `results["site_id"]`. **Never persist a token for the reaper** (S4).

**(d) DB/volume — point-in-place; never a silent strand (§N6).** Register every compose named volume onto existing `SiteVolume`. A compose `db`/`postgres` service is a **connection pointer**: obtain `DATABASE_URL` in this order — git/local compose `environment` / `env_file` on the classified db service → else `docker inspect` on the classified db container (else the classified web container) — then `vault.put(kind=Secret.Kind.DATABASE_URL, owner_type="site", owner_id=str(site.pk))`. Deploy injects it **only** through existing `_env_mapping_for_deploy`. Never Manifest.body, never `CheckRun.results`, never a Finding title/body/fix_action, never the `findings` websocket. Missing → Finding `adopt-db-url-missing:{site_pk}` whose copy names the miss, **not** the URL, and **never** `ensure_site_db`. Do **not** start a second Postgres on the same data dir. Classified cache/redis uses the same obtain order and never-provision rule; persist through the existing env-bundle path (no new `Secret.Kind`); missing → `adopt-cache-url-missing:{site_pk}` with no URL in the copy. App volumes may be mounted by the verify container while the old stack is up. Flip **refuses** if any named volume is unmapped. Decommission stops old containers and **never** `docker volume rm` a registered name. Move-to-new-cluster is Phase 4 backup/restore. Two writers on one Postgres data dir is forbidden.

**(e) Caddy ownership — `Site.edge_owner ∈ {host_caddy, site_caddy}`, default `host_caddy`.** `adoption_plan` writes it once from classification (image is caddy/nginx/traefik **and** it publishes 80/443 → `site_caddy`). **Ambiguous** = a 80/443 publisher whose image is not caddy/nginx/traefik, **or** two different edge images. Ambiguous → Finding blocks until the operator `PATCH /api/v1/sites/{id}/` with body `{edge_owner}` **only** (must not accept or clear `dns_zone`). Not a per-run prompt. Fresh Hub sites stay `host_caddy`. `host_caddy`: ignore the compose edge service, keep `ensure_route`. `site_caddy`: do not PUT a colliding host-Caddy route for that domain.

**MUST start** is `deploys/adopt_flow.py` with `desired` using the same keys `_assemble_desired` already publishes. `desired["dns"]` comes from `dns_provider_for(site.dns_zone)` (None for mesh_only, same as `resolve_production_seams`). Task 8 HTTP start may slip. Adopt uses `Site.primary_target`. Adopt **refuses** without a target.

### 1.2 MUST vs 3b-later

| Item | Line |
|---|---|
| Settings-bind + Origin-CA plant (I1) | **MUST** |
| §F3 checklist owns Home | **MUST** |
| Adopt (a)–(e), retire `PROV-J7` + `PROV-E6-ADOPT-TEMP-SUBDOMAIN` | **MUST** (T1 fakes; no live CF token) |
| Hub-central DNS-01 (`TLS-B2-HUB-DNS01-UNPROXIED`) | **stay phase 4.** Unproxied refusal stays. Task 0 retcons `deploys/certs.py` and the ACME-scan docstring from “Phase 3b” to **phase 4**. Do not mark full-text `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`. |
| App-log viewer §E3 | **3b-later** (own `site.{id}.applog` authz; no registry id today) |
| Scheduled-jobs UI §E8/`jobs_image` §N7 | **3b-later** (arbitrary-command surface; V3 tiers exist, the UI does not) |
| Backup/restore operator surface §E5 | **stay Phase 4** |
| LE-staging credentialed run | **leftover, not 3b MUST.** Leftover Task 8 owns that line if credentials exist. 3b does not freeze or retire `HARNESS-T3-LE-STAGING`. Do not invent `HUB_TEST_CF_TOKEN`. |
| 24 h Hub-down | **not this phase.** D-042 stays. |

## 2. Interfaces / tables that change

**Migration `0010_phase3b.py` (Site only):** `Site.edge_owner` (`host_caddy` \| `site_caddy`, default `host_caddy`). No new models. No `CheckRun` column. No `Site.tier`. Adopt progress lives on `CheckRun.Kind.ADOPT` (Python choices; CharField, no migration) + `CheckRun.results` **closed schema** `{schema_version, site_id, temp_name, stage, started_at}` (S2) + existing `DnsRecord` / `SiteVolume` / `BackupUnit` / `Finding`. `CheckRun` has no Site FK; `site_id` lives in `results`.

**Interfaces:**
- `POST /api/v1/projects/` — body `name` + (`git_url`/`git_ref` \| `local_path`) + `domain`/`exposure`/`proxied` + optional `dns_zone`/`primary_target` (§7 I-target / I-purpose).
- `POST /api/v1/dns-accounts/{id}/origin-ca-plant/` — `{path}` only; S1 + I-plant.
- `PATCH /api/v1/sites/{id}/` — `{edge_owner}` only; must not clear `dns_zone`.
- `provision/adopt.py`: `read_compose`, `classify_services`, `adoption_plan` (Findings + one manifest + volumes + `edge_owner`).
- `provision/service.py`: occupied host is “stack we can adopt” → plan, not only refuse.
- `deploys/adopt_flow.py`: MUST start. `desired["dns"]` from `dns_provider_for`. Temp DNS (public) → verify → flip prod name → decommission → `cleanup`. Mesh-only: no temp DNS, verify over mesh seams, decommission still runs. Flip refuses unless verify recorded success for this image tag. `live_compose_path` explicit or skip drift.
- Beat `adopt-temp-reaper` reconstructs via `dns_provider_for(site.dns_zone)` / seams. No stored token.
- Home checklist snapshot on the existing shell events client; topic remains **`findings`**.
- `deploys/` never imports `providers.cloudflare`.
- `HUB_TEST_ZONE_SLUGS` is the allowlist; `HUB_TEST_DNS_ZONE` stays retired.

**Gates:** `make conformance-3.5` is `python conformance/check.py --phase 3.5 --exclude-tier t2 --exclude-tier t3` (same shape as `conformance` / review-round). Do **not** add an all-tiers 3.5 gate. Leave `conformance-3` as **all-tiers Phase 3** (nightly). Do **not** claim `conformance-3` excludes live tiers. `make review-round` stays `--phase 3 --exclude-tier t2 --exclude-tier t3` via the existing `conformance` target. Phase 3 MUST does not grow.

## 3. Applicable registry reqs

**Already due, waived until 3b tests:** `PROV-J7-COMPOSE-AWARE-ADOPT`, `PROV-E6-ADOPT-TEMP-SUBDOMAIN` — **bump to `phase: 3.5`** (D-020 phase-bump) and retire the waiver lines when the marked **T1** tests pass. No live CF token required.

**New (Task 0), tier-less (no `tier:` key; T1-verifiable):** `DNS-SITE-ZONE-BIND` · `TLS-B2-ORIGIN-CA-PLANT` · `UX-F3-FIRST-RUN-CHECKLIST` · `P3B-ADOPT-DEMO` (`verify: demo`). A mistaken `tier: t2|t3` on these ids cannot verify on this host.

**Not due:** `TLS-B2-HUB-DNS01-UNPROXIED` (phase 4) · `SEC-F5-T1-HARDWARE-TOUCH` (phase 4) · LE-staging credentialed body · REL-P2 24 h.

## 4. Exit demo

Connect Cloudflare (existing 12b) → plant Origin-CA from a Hub-local file under an Origin-CA subdir → `POST /api/v1/projects/` binds `Site.dns_zone` (eligible purpose) and `primary_target` (no unbound Finding, because no unbound public Site exists) → §F3 card leaves Home → enroll/use a target that is occupied → fresh-host guard offers adopt, not only refuse → plan classifies the three fixture stacks (web+worker+beat+migrate; web+site-Caddy; web only) → **MUST start** `adopt_flow` with `desired["dns"]` from `dns_provider_for` → public: temp `{slug}-adopt-{8hex}` upserts in the site's `DnsZone`; mesh-only: no temp name, verify over mesh seams → live site stays up until flip → verify succeeds → flip prod name → old path decommissioned, registered volumes still present (never `docker volume rm`) → cancel/abandon deletes the temp name (flow + 24 h reaper) → a compose with two public services refuses with a Finding. Record: `conformance/demos/phase-3.5.md`. `make review-round` twice clean (Phase 3 minus live tiers). `make conformance-3.5` is the 3b gate and **excludes t2/t3**. `conformance-3` remains the all-tiers Phase 3 nightly gate. Live 3.5 tiers stay skipped-only + dated waiver, never a T1-sibling green. No 24 h Hub-down. No invented test-zone token. Task 8 HTTP start may slip; the MUST demo does not wait on it.

## 5. Decisions (closed — Task 0 copies to DECISIONS.md)

Not open `DECISION:` blockers. Irreversible/spend: adopt flip writes the operator's own `DnsZone` (T2, Hub-side adapter); test plane stays `purpose=test` + `HUB_TEST_ZONE_SLUGS`. Origin-CA plant reads a file the operator placed on the Hub. No new Cloudflare spend.

- **D-047** Protective cut — §1.2. MUST = bind + plant + F3 + adopt (a)–(e). App-log, jobs UI, DNS-01, backup UI, LE-staging, 24 h Hub-down are out. MUST start is `adopt_flow` + `desired["dns"]` from `dns_provider_for`. Task 8 HTTP may slip.
- **D-048** V5 compression for adopt: one Site; no multi-container Site model.
- **D-049** Compose source is the §A4 clone / `local_path`. Paste refused. `live_compose_path` is an explicit adopt-flow argument; unset → no drift check; no disk walk; `/srv/sites/{slug}` is not a default.
- **D-050** Temp name lives in `Site.dns_zone`. 8hex = `secrets.token_hex(4)` in `CheckRun.results.temp_name` at first upsert. `results` closed schema includes `site_id`. Cleanup = `adopt_flow.cleanup` + Beat `adopt-temp-reaper` (24 h from `results.started_at`). Reaper reconstructs via `dns_provider_for(site.dns_zone)` / seams; never stores a token. No adoption zone. Mesh-only: no temp DNS.
- **D-051** Adopted data is point-in-place. Obtain `DATABASE_URL` from compose `environment`/`env_file` else `docker inspect` (db, else web) → `vault.put(kind=DATABASE_URL, owner_type=site, owner_id=site.pk)` → `_env_mapping_for_deploy` only. Missing → Finding, never `ensure_site_db`. Cache/redis = same pointer rule. Unmapped volume blocks flip. Never `docker volume rm` a registered name.
- **D-052** `Site.edge_owner` is the per-site Caddy record. Written by the plan or one `PATCH /api/v1/sites/{id}/` `{edge_owner}` only (must not clear `dns_zone`). Ambiguous = 80/443 whose image is not caddy/nginx/traefik, or two different edge images. Never a per-run prompt.
- **D-053** Public bind uses matching-purpose eligible zones (`purpose=prod`; `purpose=test` only under `HUB_TEST_MODE` + name on `HUB_TEST_ZONE_SLUGS`). Site has no tier. Zero eligible → 409 and zero rows (no `site-dns-unbound`). Project create binds `primary_target` (one enrolled Target → auto; else body). Adopt refuses without a target. Plant vault shape = `API_TOKEN` / `owner_type=dns_account` / `owner_id=ref`. Plant roots = Origin-CA subdirs only. New 3.5 req ids are tier-less. `conformance-3.5` excludes t2/t3; `conformance-3` stays all-tiers Phase 3.

## 6. Out of scope (explicitly)

App-log viewer · scheduled-jobs UI + `jobs_image` run-in-own-image · Hub-central DNS-01 · backup/restore UI · LE-staging credentialed run · 24 h Hub-down · WebAuthn / T1 hardware · attack playbook / `EdgeProtection` · vault Settings screen (Phase 4; plant is the one Origin-CA write) · AWS/Azure · partner intake · D-012 · merging master for leftover hash pins.

**May slip without failing the MUST demo:** Task 8 HTTP start / Sites adopt UI · simulation-seed completeness beyond the adopt/checklist states · phone-width polish on the new cards. **Not** slip-able: bind, plant, F3, classify/plan, `adopt_flow` + `desired["dns"]` from `dns_provider_for`, temp subdomain (public), mesh-only verify-without-temp, verify-before-flip, live-stays-up-until-flip, abandon cleanup, volume register-and-never-`docker volume rm`.

**MUST:** Task 0 gate · `0010` `edge_owner` · bind + file-plant · F3 Home card · compose plan + occupied-host adopt pointer · adopt flow + reaper · retire the two adopt waivers on T1 fakes · demo record.

## 7. Closed answers (panel — do not reopen)

### C1 — zero zones (Architect `285f8f94`)

Public Site create with zero eligible zones is **HTTP 409**. Create **zero** Project rows, **zero** Site rows, **zero** Findings. `site-dns-unbound:{pk}` is illegal. Delete any test named `test_public_site_create_with_no_zone_files_unbound_finding_and_409`. The replacement asserts 409 and `Site.objects.count()` / `Finding.objects.count()` unchanged.

### I-purpose

Eligible zone =
- `DnsZone.purpose == prod`, **or**
- `DnsZone.purpose == test` **and** `settings.HUB_TEST_MODE` **and** `DnsZone.name` is on `settings.HUB_TEST_ZONE_SLUGS`.

Match `DnsZone.name`, not a slug field (DnsZone has none). Site has **no** tier field; do not add one. “One connected zone → auto-bind” means **exactly one eligible zone**. A `purpose=test` zone is never eligible outside that triple key. A requested `dns_zone` that is not eligible → 409, zero rows, zero Findings.

### I-dburl / S3 / cache

Obtain order (adopt, classified db/postgres):
1. Project-tree compose service `environment` / `env_file` for `DATABASE_URL`.
2. Else `Transport` `docker inspect` on the classified db container; if none, the classified web container.

Then `vault.put(kind=Secret.Kind.DATABASE_URL, owner_type="site", owner_id=str(site.pk))`. The only deploy read path is existing `_env_mapping_for_deploy`. Never Manifest, never CheckRun, never Finding copy, never the `findings` websocket. Missing → `adopt-db-url-missing:{site_pk}`, never `ensure_site_db`. Cache/redis: same obtain order and never-start-a-second-one rule; persist via existing `Secret.Kind.ENV_BUNDLE` (no new Kind); missing classified-cache URL → `adopt-cache-url-missing:{site_pk}` with no URL in the copy.

### I-live

`adopt_flow(..., live_compose_path=None)`. Unset → skip drift. Set → `Transport.get` that path only. No walk of `/srv/sites/{slug}` or any other default. That prefix is post-Hub (certs, etc.), not a compose root.

### I-run / S2

`CheckRun` has no Site FK. Do not add one. For `kind=adopt`, `results` is exactly:

```
{"schema_version": 1, "site_id": <int>, "temp_name": <str>, "stage": <str>, "started_at": <iso8601>}
```

No other keys. `temp_name` for public = `{slug}-adopt-{secrets.token_hex(4)}.{zone.name}` written at first upsert; mesh-only = `""`. `started_at` is first-upsert time (reaper TTL). Stages the flow writes: `temp_dns` (public only) · `verify` · `flip` · `decommission` · `cleanup`. Adopt Findings use existing `finding()` / `finding_event` fields; those strings must not contain a compose `DATABASE_URL`.

### I-plant / S1 / S5

`vault.put(kind=Secret.Kind.API_TOKEN, owner_type="dns_account", owner_id=ref)` then `DnsAccount.origin_ca_key_ref = ref`. Reuse an existing ref if set; otherwise mint `uuid.uuid4().hex` (same as Settings-connect). This is the row `origin_cert_issuer_for` / `_load_origin_ca_key` already loads.

Allowlisted plant roots **only**:
- `/etc/deploy-hub/origin-ca/`
- `/var/lib/deploy-hub/origin-ca/`

Not `/etc/deploy-hub/` or `/var/lib/deploy-hub/` wholesale. Read:
1. `p = Path(path)`; `resolved = p.resolve(strict=True)` (missing → 400).
2. `resolved` must be under one allowlisted root (prefix check on the resolved path).
3. `p.is_symlink()` is refuse; `resolved` must be a regular file; `st_mode & 0o777 == 0o600`.
4. Deny if `resolved` equals `Path(settings.VAULT_KEYFILE).resolve()` (default `/etc/deploy-hub/vault.key`).

Named tests: 0644 refuse, symlink refuse, `VAULT_KEYFILE` refuse.

### I-edge

`PATCH /api/v1/sites/{id}/` serializer fields = `{edge_owner}` only. A PATCH must not clear `dns_zone`. Ambiguous = 80/443 whose image is not `caddy` / `nginx` / `traefik`, or two different edge images.

### I-target

`POST /api/v1/projects/` body = `name` + (`git_url` + optional `git_ref` default `main` **xor** `local_path`) + `domain` / `exposure` / `proxied` + optional `dns_zone` / `primary_target`. Public requires non-blank `domain`. One transaction: failure creates neither Project nor Site.

`primary_target`: enrolled = a `Target` row exists. Exactly one → auto-bind. Several → body `primary_target` required (existing Target pk). Zero → 409, zero rows. Adopt reads `site.primary_target` and **refuses** if null. No implicit host.

409 = fleet-state refuse (zero/several eligible zones without a legal `dns_zone`; zero/several Targets without a legal `primary_target`; requested zone not eligible). 400 = malformed body.

### I-mesh adopt

No temp DNS, `results.temp_name == ""`, `desired["dns"] is None`, verify healthz over `Transport` (mesh seams), decommission still runs, reaper still calls `cleanup`.

### M1

The Task 6 volume test asserts decommission **never** issues `docker volume rm` for a registered name. It is not a “without confirmation” test.

### S4 / S6 / exfil

Reaper: load `Site` from `results["site_id"]`, then `dns_provider_for(site.dns_zone)` / `resolve_production_seams`. Never persist a token on the CheckRun or elsewhere for the reaper. Task 0 retcons `deploys/certs.py` (`UnproxiedCertUnsupported` docstring + unproxied `fix_action`) and `tests/test_no_token_exfiltration.py::test_no_acme_dns_challenge_block_is_ever_generated` from “Phase 3b” to **phase 4**. Do not mark full-text `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`. Extend `test_no_token_exfiltration.py` over adopt `put`/`run`. Do not invent `HUB_TEST_CF_TOKEN`.

### QE gates / I2–I4 / Task 9

- `conformance-3.5` = `--phase 3.5 --exclude-tier t2 --exclude-tier t3`. Not all-tiers.
- `conformance-3` = `--phase 3` all-tiers (nightly). Do not claim it excludes live tiers.
- `conformance` / `review-round` stay Phase 3 minus live tiers.
- Task 0 must **not** say “keep the LE-staging waiver.” Leftover Task 8 owns that line. 3b neither freezes nor retires it. Do not retire REL-P2 24 h.
- Named test: several eligible zones → body `dns_zone` required (I2).
- Named test: live site stays up until flip (I3, E6 never-take-down).
- New 3b ids are tier-less (I4).
- Task 9 retires `PROV-J7` / `PROV-E6-ADOPT-TEMP-SUBDOMAIN` with T1 fakes. Do not require a live CF token.

### Already correct (keep)

D-047 cut: DNS-01 phase 4, app-log/jobs UI out, no 24 h Hub-down, no invented `HUB_TEST_CF_TOKEN`. `0009` closed; `0010` is `Site.edge_owner` only. `HUB_TEST_ZONE_SLUGS` allowlist; `HUB_TEST_DNS_ZONE` retired. `findings` is the canonical topic. Fail-closed until planted stays.
