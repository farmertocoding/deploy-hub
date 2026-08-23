# Phase 3b tasks — Adopt + first-run bind

SDD-ready work list for Implementers. Architect design note:
`docs/phase-3b-design-note.md` (panel §7 is binding). Do not start a task whose
dependencies are open. Do not start implementation from this design session.
Do not invent a path, env, Finding fingerprint, CheckRun key, or gate shape
that the design note does not name.

**Branch:** cut task branches from `p3b-design` (which carries these two docs).
Never implement on `master`. Do not merge master into a task branch for this
wave. Sensitive-path merges to `master` go through the recorded expert-panel
vote. Adopt's starting text was Phase-3 Task 15; the §1.12 holes are closed
in the design note — implement that text, not the old "do not start without
answers" paragraph.

## Global constraints (every task)

- Every remote effect on a target goes through `Transport`; argv lists, never
  interpolated strings; file content via `put()`, never heredocs.
- Cloudflare HTTP lives **only** under `providers/`. `deploys/` receives a
  provider and a `DnsZone` in `desired`; it never constructs or imports a
  Cloudflare client (SEC-B2). `provision/adopt.py` parses YAML and executes
  nothing (M1).
- Secrets through the vault. Origin-CA key bytes never in a Settings form,
  request body, Finding, artifact, Manifest, CheckRun, or target-bound
  surface. Plant is Hub-local file → `vault.put(kind=Secret.Kind.API_TOKEN,
  owner_type="dns_account", owner_id=ref)` → `DnsAccount.origin_ca_key_ref`
  (the shape `origin_cert_issuer_for` already loads).
- **Pinned env names:** `HUB_TEST_ZONE_SLUGS` is the one allowlist;
  `HUB_TEST_DNS_ZONE` is retired; `HUB_TEST_CF_TOKEN` stays the existing
  test-plane token env — **do not invent it**. Test-plane Origin-CA plant
  stays `HUB_TEST_ORIGIN_CA_KEY` in `tests/harness/cf_zone.py`. Do not add a
  product env for the Origin-CA key.
- Test-plane construction stays triple-keyed: `HUB_TEST_MODE` **and**
  `purpose == test` **and** the name on `HUB_TEST_ZONE_SLUGS`.
- **`0009_phase3.py` is closed.** The only 3b migration is Task 1's
  `0010_phase3b.py` on `Site.edge_owner` only. No new tables. No Site FK on
  `CheckRun`. No `Site.tier`. Prefer `Site` / `DnsZone` / `Finding` /
  `DnsRecord` / `SiteVolume` / `BackupUnit` / `CheckRun`.
- **`findings` is the canonical realtime topic** (D-045).
- Every new step is `ensure_X(desired)` and run-twice with **zero** mutating
  Transport calls the second time (§D6).
- New alert kinds need a row in `monitor/alert_rules.py` first. Adopt plan
  Findings file through `core.findings.finding()` (same as seams). Named
  fingerprints only: `adopt-temp-orphan:{site_pk}:{name}`,
  `adopt-db-url-missing:{site_pk}`, `adopt-cache-url-missing:{site_pk}`.
  **`site-dns-unbound:{pk}` is illegal** — never file it.
- `TLS-B2-HUB-DNS01-UNPROXIED` stays **phase 4**. Do not mark the full-text
  `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`. Unproxied refusal stays.
- LE-staging credentialed run is a leftover, **not** 3b MUST. Leftover Task 8
  owns that line if credentials exist. 3b does not freeze or retire
  `HARNESS-T3-LE-STAGING`.
- Do not claim a 24 h Hub-down. The adopt abandon window is a DNS-record TTL,
  not REL-P2.
- Reviewer never writes the code they review (D-014).
- Sensitive paths wait for the panel vote: existing Phase-3 list plus
  `provision/adopt.py`, `deploys/adopt_flow.py`.
- Tiers: T1 = fakes. T2 = `hub-test-target`. T3 = Multipass. A `tier: t2|t3`
  req is verified only by a passed marked test (D-024). **New 3b ids are
  tier-less** and T1-verifiable; a mistaken `tier: t2|t3` cannot verify here.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` in the
  round they judge. Registry edits are Task 0.
- TDD: failing test first. Long "why" HEREDOC commits; no amend.

Protective cut (**D-047**): MUST = Tasks 0–7 and 9. Task 8 (sim/UI polish,
HTTP start) is the named first slip candidate. App-log viewer, scheduled-jobs
UI, Hub-central DNS-01, backup UI, LE-staging, 24 h Hub-down are out of this
phase.

## Parallel waves

| Shared file | Order |
|---|---|
| `conformance/requirements.yaml` / `check.py` / `DECISIONS.md` / `deploys/certs.py` | Task 0 |
| `core/models.py` / `0010_phase3b.py` | Task 1 |
| `core/zone_views.py` / Settings / project create | Task 2 after 1 |
| `frontend/src/screens/Home.jsx` | Task 3 after 2 |
| `provision/adopt.py` + `PATCH /api/v1/sites/{id}/` | Task 4 after 1 |
| `provision/service.py` | Task 5 after 4 |
| `deploys/adopt_flow.py` | Task 6 after 1+2+4 |
| Beat / reaper | Task 7 after 6 |
| sim + Sites adopt UI | Task 8 after 3+6 |
| acceptance + demo | Task 9 after MUST |

---

## Task 0 — Unblock `check.py --phase 3.5` (D-047…D-053)

**Title:** Phase-3.5 due set exists; adopt ids bump off Phase 3; DNS-01 stays 4;
`conformance-3.5` excludes live tiers.

**Files created/touched:**
- `DECISIONS.md` — rows D-047…D-053 (text from the design note §5).
- `conformance/requirements.yaml` (sensitive) — add `DNS-SITE-ZONE-BIND`,
  `TLS-B2-ORIGIN-CA-PLANT`, `UX-F3-FIRST-RUN-CHECKLIST`, `P3B-ADOPT-DEMO`
  (`verify: demo`, `demo: conformance/demos/phase-3.5.md`). **No `tier:` key
  on these four** (QE I4). Set `PROV-J7-COMPOSE-AWARE-ADOPT` and
  `PROV-E6-ADOPT-TEMP-SUBDOMAIN` to **`phase: 3.5`** (do not change their
  `text:` / `text_hash:`). `TLS-B2-HUB-DNS01-UNPROXIED` stays `phase: 4`.
- `WAIVERS.md` — keep the two adopt lines until Task 9 retires them on T1
  green; rewrite the SEC-B2 waiver's "built in Phase 3b" clause to **phase 4**
  (design note §1.2). Do not retire REL-P2 24 h. **Do not write "keep the
  LE-staging waiver."** 3b does not freeze `HARNESS-T3-LE-STAGING`; leftover
  Task 8 owns retirement if credentials exist.
- `Makefile` — add `conformance-3.5` **exactly**:
  `python conformance/check.py --phase 3.5 --exclude-tier t2 --exclude-tier t3`.
  Add it to `.PHONY`. Do **not** make an all-tiers 3.5 target. Leave
  `conformance` / `review-round` as Phase 3 minus live tiers. Leave
  `conformance-3` as **all-tiers Phase 3** (nightly). Do **not** claim
  `conformance-3` excludes live tiers (QE I1 / C1 GATE-3.5).
- `deploys/certs.py` — retcon `UnproxiedCertUnsupported` docstring and the
  unproxied Finding `fix_action` from "Phase 3b" to **phase 4**.
- `tests/test_no_token_exfiltration.py` — retcon
  `test_no_acme_dns_challenge_block_is_ever_generated` docstring from
  "Phase 3b" to **phase 4**. Do not mark full-text
  `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`.
- `conformance/paths.yaml` + `.github/CODEOWNERS` — `deploys/adopt_flow.py`
  if not already listed beside `provision/adopt.py`.

**Exact req ids proven:** none go green here. This task makes the 3.5 due set.

**Tests to write:**
- `tests/test_conformance_gate.py` (extend) —
  `test_phase_3_5_due_set_includes_bind_plant_f3_and_adopt`;
  `test_phase_3_due_set_no_longer_requires_adopt_ids`;
  `test_tls_b2_hub_dns01_stays_phase_4`;
  `test_new_phase_3_5_ids_have_no_tier`.
- `tests/test_makefile_nightly.py` (extend) —
  `test_conformance_3_5_target_exists`;
  `test_conformance_3_5_is_phase_3_5_minus_live_tiers`
  (recipe contains `--phase 3.5`, `--exclude-tier t2`, `--exclude-tier t3`);
  `test_review_round_conformance_is_still_phase_3_minus_live_tiers`
  (this asserts the existing `conformance` target, **not** `conformance-3`).
  Do not add a test that claims `conformance-3` excludes live tiers.
  Existing `test_nightly_gates_use_conformance_3` already pins all-tiers
  Phase 3 — leave that truth alone.
- `tests/test_certs_phase_pin.py` or extend the existing certs/unproxied
  tests so the retconned "phase 4" copy is what the suite reads. No
  `HUB_TEST_CF_TOKEN` invention.

**Dependencies:** none.

---

## Task 1 — `Site.edge_owner` + adopt CheckRun kind (`0010_phase3b.py`)

**Title:** One Site column for Caddy ownership; adopt progress reuses CheckRun.

**Files created/touched:**
- `core/models.py` — `Site.edge_owner` (`host_caddy` \| `site_caddy`, default
  `host_caddy`); `CheckRun.Kind.ADOPT = "adopt"`. Do not add a Site FK to
  `CheckRun`. Do not add `Site.tier`. When `kind == adopt`, `clean()` requires
  `results` keys exactly `{schema_version, site_id, temp_name, stage,
  started_at}` (design note §7 I-run / S2).
- `core/migrations/0010_phase3b.py` — **`Site.edge_owner` only.** Do not add
  tables. Do not migrate CheckRun (CharField choices).

**Exact req ids proven:** none yet (column + kind only).

**Tests to write:**
- `tests/test_site_edge_owner.py` —
  `test_new_site_defaults_to_host_caddy`;
  `test_edge_owner_rejects_unknown_value`;
  `test_checkrun_kind_adopt_saves_without_a_new_table`;
  `test_adopt_checkrun_results_require_site_id_and_closed_schema`;
  `test_checkrun_has_no_site_fk`.

**Dependencies:** Task 0.

---

## Task 2 — Settings-bind `Site.dns_zone` + Origin-CA file plant (Architect I1)

**Title:** A Settings-connected account can finish a deployable public site
without pasting an Origin-CA key.

**Files created/touched:**
- `wizard/views.py` / `core/` create view — `POST /api/v1/projects/` body =
  `name` + (`git_url` + optional `git_ref` default `main` **xor** `local_path`)
  + `domain` / `exposure` / `proxied` + optional `dns_zone` / `primary_target`.
  One transaction: Project + Site, or neither.
  Public: bind `dns_zone` from the **eligible** set (design note §7 I-purpose).
  Exactly one eligible → auto-bind. Several eligible → body `dns_zone`
  required (must be a member of eligible). Zero eligible → **409, zero
  Project, zero Site, zero Finding**. Requested zone not eligible → same 409.
  Never file `site-dns-unbound:{pk}`. Mesh-only may omit the FK.
  `primary_target`: exactly one enrolled `Target` → auto-bind; several → body
  required; zero → 409, zero rows. Public requires non-blank `domain`.
  409 = fleet-state refuse; 400 = malformed body.
- `core/zone_views.py` — `POST /api/v1/dns-accounts/{id}/origin-ca-plant/`
  body `{path}`. Allowlisted roots **only**: `/etc/deploy-hub/origin-ca/` and
  `/var/lib/deploy-hub/origin-ca/`. Algorithm: `Path.resolve(strict=True)` +
  regular file + no symlink + `st_mode & 0o777 == 0o600` + deny
  `Path(settings.VAULT_KEYFILE).resolve()`. Then
  `vault.put(kind=Secret.Kind.API_TOKEN, owner_type="dns_account",
  owner_id=ref)` and set `origin_ca_key_ref` (reuse ref if set, else
  `uuid.uuid4().hex`). Refuse path traversal, 0644, symlink, `VAULT_KEYFILE`,
  and any body that contains key bytes. Response is planted / not planted —
  never the key.
- `frontend/src/screens/Settings.jsx` — Cloudflare panel grows plant status +
  path field + Plant. Connect form stays DNS-token only (existing copy).
- `deploys/seams.py` — fail-closed until planted **stays**. After plant,
  proxied public deploy constructs the issuer.
- Generated client / zod as needed.

**Exact req ids proven:** DNS-SITE-ZONE-BIND; TLS-B2-ORIGIN-CA-PLANT.

**Tests to write:**
- `tests/test_site_dns_bind.py` —
  `test_public_site_create_auto_binds_the_single_eligible_zone`;
  `test_public_site_create_with_no_eligible_zone_is_409_and_creates_nothing`
  (**replaces** `test_public_site_create_with_no_zone_files_unbound_finding_and_409`
  — delete that name; assert 409 and zero new Sites / zero new Findings);
  `test_public_site_create_with_several_eligible_zones_requires_dns_zone`
  (QE I2);
  `test_purpose_test_zone_binds_only_under_test_plane`;
  `test_public_site_binds_purpose_prod_zone`;
  `test_requested_ineligible_zone_is_409_and_creates_nothing`;
  `test_one_enrolled_target_auto_binds_primary_target`;
  `test_several_targets_require_primary_target_in_the_body`;
  `test_zero_targets_is_409_and_creates_nothing`;
  `test_mesh_only_site_may_omit_dns_zone`.
- `tests/test_origin_ca_plant.py` —
  `test_plant_from_allowlisted_0600_file_sets_origin_ca_key_ref`;
  `test_plant_rejects_path_outside_origin_ca_subdir`;
  `test_plant_rejects_0644_file` (S5);
  `test_plant_rejects_symlink` (S5);
  `test_plant_rejects_vault_keyfile_path` (S5);
  `test_plant_request_and_response_contain_no_key_bytes`;
  `test_plant_uses_api_token_dns_account_vault_shape`;
  `test_connect_endpoint_still_does_not_accept_an_origin_ca_key`;
  `test_seams_still_refuse_until_planted`;
  `test_seams_construct_issuer_after_plant`.
- Extend `tests/test_cloudflare_connect.py` so connect remains DNS-token only.

**Dependencies:** Task 1.

---

## Task 3 — §F3 first-run checklist owns Home

**Title:** Home is a checklist until target + (CF/plant if public) + project
exist; then it is today's map + fleet.

**Files created/touched:**
- `frontend/src/screens/Home.jsx` + a small checklist module — card owns the
  screen until applicable items are done. Items: enroll first target;
  connect Cloudflare (skip when first site is `mesh_only`); plant Origin-CA
  (skip mesh-only / until a proxied public site exists; required before that
  deploy); add a project (the Task 2 POST that binds `dns_zone` and
  `primary_target`). Each item is one sentence + the one button that
  populates it (§F3).
- Snapshot/API for checklist progress (Home already has the shell events
  client; do not open a second socket). Topic stays `findings` for attention;
  checklist completion is derived state, not a new topic.
- `frontend/src/sim.js` — empty / mid-checklist / done fixtures. Do not add
  an unbound-public-Site fixture (that state is illegal).

**Exact req ids proven:** UX-F3-FIRST-RUN-CHECKLIST.

**Tests to write:**
- `frontend/tests/checklist.test.ts` —
  `checklist_owns_home_until_items_are_done`;
  `mesh_only_first_site_skips_cloudflare_and_plant`;
  `proxied_public_path_requires_plant_before_done`;
  `done_checklist_reveals_map_and_fleet`.
- `tests/test_first_run_checklist.py` —
  `test_checklist_derives_from_target_zone_plant_and_project`;
  `test_mesh_only_skips_cf_items`.

**Dependencies:** Task 2.

---

## Task 4 — Compose-aware adoption plan (Phase-3 Task 15 reader)

**Title:** Read the compose stack, propose one V5 manifest, never execute it.

Design-note answers: **(a)** V5 / one Site · **(b)** clone / `local_path`
only · **(e)** write `Site.edge_owner` once · **I-edge** PATCH.

**Files created/touched:**
- `provision/adopt.py` (**new, sensitive**) — `read_compose(path)` via
  `yaml.safe_load`, executing nothing; filename order from design note §1.1(b);
  `classify_services()` → web / worker / beat-scheduler / one-shot migrate /
  db / cache / site-owned edge; `adoption_plan(project)` emits Findings
  (what / why / exact fix) plus one manifest proposal, a `SiteVolume` list
  (N6), and sets `Site.edge_owner`. Two uncompressible public services →
  refuse Finding. Operator paste is not an argument. Do not walk
  `/srv/sites/{slug}` for compose. Cache/redis is classified as a pointer,
  not a Hub-provisioned cache.
- `PATCH /api/v1/sites/{id}/` — serializer fields `{edge_owner}` **only**.
  Must not accept or clear `dns_zone`. Ambiguous (Finding blocks until this
  PATCH) = a 80/443 publisher whose image is not caddy/nginx/traefik, **or**
  two different edge images.
- `tests/fixtures/compose/` — three §J7 shapes: web+worker+beat+one-shot
  migrate; web+site-owned-Caddy; web only. Optional fourth: two public
  services (must refuse).

**Exact req ids proven:** PROV-J7-COMPOSE-AWARE-ADOPT (with Task 6).

**Tests to write:**
- `tests/test_adopt_compose.py` —
  `test_worker_beat_and_oneshot_migrate_are_classified`;
  `test_site_owned_edge_container_is_recorded_as_a_decision_on_the_site`;
  `test_named_volumes_appear_in_the_plan`;
  `test_parser_executes_nothing`;
  `test_single_container_stack_still_produces_one_manifest`;
  `test_plan_findings_carry_what_why_and_fix`;
  `test_two_public_services_refuse_with_a_finding`;
  `test_compose_is_read_from_project_tree_not_a_paste`;
  `test_ambiguous_edge_blocks_until_edge_owner_is_set`;
  `test_ambiguous_edge_is_non_edge_image_on_80_443_or_two_edge_images`.
- `tests/test_site_edge_owner.py` (extend) —
  `test_patch_edge_owner_only_field`;
  `test_patch_edge_owner_does_not_clear_dns_zone`.

**Dependencies:** Task 1.

---

## Task 5 — Occupied host points at adopt, not only refuse

**Title:** E6 fresh-host guard learns "stack we can adopt."

**Files created/touched:**
- `provision/service.py` — occupied 80/443 or non-fresh app state still
  refuses *provision*; the explanation points at `adoption_plan` / the adopt
  flow (Phase 3b, already in the refuse string) instead of a dead end.

**Exact req ids proven:** PROV-E6-FRESH-HOST-GUARD stays green; copy is 3b.

**Tests to write:**
- `tests/test_provision_fresh_host.py` (extend) —
  `test_occupied_80_refuses_and_names_adopt`;
  `test_occupied_host_does_not_provision`.

**Dependencies:** Task 4.

---

## Task 6 — Temp-subdomain adopt flow (Phase-3 Task 15 flow)

**Title:** Temp deploy → verify → point DB/volumes → flip DNS → decommission.
Never flip before verify. Never strand a volume. Never `docker volume rm` a
registered name.

Design-note answers: **(c)** name/zone/cleanup · **(d)** point-in-place ·
**I-live / I-run / I-dburl / I-mesh / M1**.

**Files created/touched:**
- `deploys/adopt_flow.py` (**new, sensitive**) — MUST start (Task 8 HTTP may
  slip). `desired` uses the same keys `_assemble_desired` already publishes.
  `desired["dns"]` from `dns_provider_for(site.dns_zone)` (None for
  mesh_only, same as `resolve_production_seams`). This module does not import
  `providers.cloudflare`. Stages, each idempotent:
  upsert temp `{slug}-adopt-{secrets.token_hex(4)}.{zone.name}` on
  **`Site.dns_zone`** through `desired["dns"]` (8hex stored in
  `CheckRun.results["temp_name"]` at first upsert, reused after);
  deploy/verify HTTP 200 + the site's healthz (public) **or** Transport
  healthz over mesh seams (mesh_only — no temp DNS, `temp_name=""`);
  register `SiteVolume` / obtain+vault `DATABASE_URL` per §7 I-dburl (no
  second Postgres, **never** `ensure_site_db`); cache/redis same pointer
  rule; flip the prod name; decommission the old path; `cleanup()` deletes
  the temp `DnsRecord` + provider record and stops temp containers.
  Flip **refuses** unless verify recorded success for the current image tag.
  Live site stays up until flip (E6 never-take-down).
  `live_compose_path` is an explicit argument: unset → no drift check; set →
  `Transport.get` that path only and **block the flip** on drift. No disk
  walk. `/srv/sites/{slug}` is not a default.
  Adopt **refuses** if `site.primary_target` is null.
  `CheckRun(kind=adopt).results` = `{schema_version, site_id, temp_name,
  stage, started_at}` only. Stages: `temp_dns` (public) · `verify` · `flip`
  · `decommission` · `cleanup`.
- SEC-B2: extend `tests/test_no_token_exfiltration.py` over adopt `put` /
  `run` — unmarked, no full-text `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`. Do not
  invent `HUB_TEST_CF_TOKEN`.

**Exact req ids proven:** PROV-E6-ADOPT-TEMP-SUBDOMAIN; PROV-J7 (with Task 4).

**Tests to write:**
- `tests/test_adopt_flow.py` —
  `test_dns_flip_refuses_before_verification`;
  `test_verified_flip_upserts_then_decommissions`;
  `test_abandoned_flip_cleans_up_its_temp_subdomain`;
  `test_temp_name_is_slug_adopt_token_hex_4_on_site_dns_zone`;
  `test_temp_hex_is_stored_on_first_upsert_and_reused`;
  `test_checkrun_results_closed_schema_includes_site_id`;
  `test_no_dedicated_adoption_zone_is_constructed`;
  `test_flow_run_twice_records_zero_mutating_calls`;
  `test_decommission_never_docker_volume_rm_a_registered_name`
  (**replaces** `test_decommission_never_touches_a_registered_volume_without_confirmation`);
  `test_unmapped_named_volume_blocks_the_flip`;
  `test_compose_db_is_pointed_not_reprovisioned`;
  `test_missing_database_url_files_finding_and_skips_ensure_site_db`;
  `test_compose_cache_is_pointed_not_reprovisioned`;
  `test_database_url_never_enters_manifest_checkrun_or_finding`;
  `test_live_compose_path_unset_skips_drift_check`;
  `test_live_compose_path_drift_blocks_the_flip`;
  `test_live_site_stays_up_until_flip` (QE I3);
  `test_mesh_only_adopt_skips_temp_dns_verifies_over_seams_and_still_decommissions`;
  `test_adopt_refuses_without_primary_target`;
  `test_no_cloudflare_import_in_deploys_adopt_flow`.
- `tests/test_no_token_exfiltration.py` (extend) — adopt put/run surfaces
  stay clean of DNS / Origin-CA tokens and env names.

**Dependencies:** Task 1, Task 2, Task 4.

---

## Task 7 — Abandoned-flip reaper

**Title:** A temp name older than 24 h does not live forever if the operator
walks away.

**Files created/touched:**
- `deploys/adopt_flow.py` — `cleanup` remains the one owner.
- Beat entry `adopt-temp-reaper` (hourly) — `CheckRun(kind=adopt)` rows that
  still name a `temp_name` and are older than 24 h from `results.started_at`
  call `cleanup`. Load `Site` from `results["site_id"]`. Reconstruct the
  provider via `dns_provider_for(site.dns_zone)` / `resolve_production_seams`.
  **Never persist a token** on the CheckRun or in reaper state (S4). Failed
  cleanup files `adopt-temp-orphan:{site_pk}:{name}` (P2) on `findings`.
  This is not a Hub-down and not REL-P2. Mesh-only rows with empty
  `temp_name` still get `cleanup` (containers).

**Exact req ids proven:** PROV-E6-ADOPT-TEMP-SUBDOMAIN (cleanup half).

**Tests to write:**
- `tests/test_adopt_reaper.py` —
  `test_reaper_deletes_temp_older_than_24h`;
  `test_reaper_leaves_fresh_temp_alone`;
  `test_cleanup_failure_files_orphan_finding`;
  `test_reaper_does_not_delete_prod_name_or_registered_volume`;
  `test_reaper_reconstructs_provider_from_site_dns_zone_and_stores_no_token`.

**Dependencies:** Task 6.

---

## Task 8 — Adopt UI + simulation states (may slip)

**Title:** Sites can start adopt from the plan; every new state is in `sim.js`.
HTTP start may slip; MUST start is Task 6 `adopt_flow`.

**Files created/touched:**
- `frontend/src/screens/Sites.jsx` — adopt plan + start/cancel (T2 on flip /
  decommission). `edge_owner` shown, not prompted per run. Do not invent a
  live-compose file picker that walks `/srv/sites/{slug}`; if the UI grows a
  path field it is the explicit `live_compose_path` argument.
- `frontend/src/sim.js` — plan / verify / flipped / abandoned / unplanted
  fixtures, including `cert_refusal`. **No unbound-public-Site fixture**
  (illegal under `site_public_requires_dns_zone`).
- UX-F8 seed rule: a new state without a sim fixture is a round finding.

**Exact req ids proven:** none new (UX-F8 already retired; keep the seed
honest). Slip this task with a dated note, not a quiet missing state. The
MUST demo does not wait on this HTTP.

**Tests to write:**
- `frontend/tests/adopt.test.ts` —
  `adopt_actions_are_t2_with_a_diff`;
  `edge_owner_is_displayed_not_prompted_per_run`;
  `sim_covers_plan_verify_flip_abandon`.

**Dependencies:** Task 3, Task 6.

---

## Task 9 — Acceptance + demo record

**Title:** The §4 demo is a checked-in record; adopt waivers die on T1 fakes.

**Files created/touched:**
- `tests/acceptance/test_phase_3_5.py` — one test per milestone clause in
  design-note §4, `@pytest.mark.acceptance(phase=3.5)`. **T1 fakes only.**
  Do not require a live CF token. Do not invent `HUB_TEST_CF_TOKEN`.
- `conformance/demos/phase-3.5.md` (+ directory if needed).
- `WAIVERS.md` — retire `PROV-J7-COMPOSE-AWARE-ADOPT` and
  `PROV-E6-ADOPT-TEMP-SUBDOMAIN` only after Tasks 4+6+7 are green on T1.
  Do not retire REL-P2 24 h or the SEC-B2 DNS-01 clause. Do not retire or
  freeze `HARNESS-T3-LE-STAGING` (leftover Task 8 owns that line).

**Exact req ids proven:** P3B-ADOPT-DEMO.

**Tests to write:**
- `tests/acceptance/test_phase_3_5.py` —
  `test_public_site_binds_dns_zone`;
  `test_public_site_create_with_no_eligible_zone_creates_nothing`;
  `test_origin_ca_is_planted_from_a_hub_file_not_a_paste`;
  `test_f3_checklist_owns_home_until_done`;
  `test_compose_plan_is_one_v5_site`;
  `test_temp_subdomain_on_site_zone_cleans_up`;
  `test_flip_refuses_before_verify`;
  `test_live_site_stays_up_until_flip`;
  `test_registered_volume_survives_decommission_without_docker_volume_rm`;
  `test_rel_p2_24h_still_not_claimed`;
  `test_hub_central_dns01_still_not_due`.

**Dependencies:** Tasks 0–7 (MUST). Task 8 if it landed.

---

## Deferred (3b-later / other phases)

| Item | Why | Where |
|---|---|---|
| App-log viewer §E3 | Own topic + authz; no id today | 3b-later |
| Scheduled-jobs UI §E8 / `jobs_image` §N7 | Arbitrary-command UI; V3 tiers already exist | 3b-later |
| Hub-central DNS-01 | Registered `TLS-B2-HUB-DNS01-UNPROXIED` **phase 4**; unproxied refusal stays | Phase 4 |
| Backup/restore operator surface §E5 | Restore drill + §B3 | Phase 4 |
| LE-staging credentialed run | Leftover Task 8 owns the line; do not invent `HUB_TEST_CF_TOKEN` | leftover |
| 24 h Hub-down | D-042 | not this phase |
