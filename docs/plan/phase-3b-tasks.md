# Phase 3b tasks — Adopt + first-run bind

SDD-ready work list for Implementers. Architect design note:
`docs/phase-3b-design-note.md`. Do not start a task whose dependencies are
open. Do not start implementation from this design session.

**Branch:** cut task branches from `p3b-design` (which carries these two docs).
Never implement on `master`. Sensitive-path merges to `master` go through the
recorded expert-panel vote. Adopt's starting text was Phase-3 Task 15; the
§1.12 holes are closed in the design note — implement that text, not the old
"do not start without answers" paragraph.

## Global constraints (every task)

- Every remote effect on a target goes through `Transport`; argv lists, never
  interpolated strings; file content via `put()`, never heredocs.
- Cloudflare HTTP lives **only** under `providers/`. `deploys/` receives a
  provider and a `DnsZone` in `desired`; it never constructs or imports a
  Cloudflare client (SEC-B2). `provision/adopt.py` parses YAML and executes
  nothing (M1).
- Secrets through the vault. Origin-CA key bytes never in a Settings form,
  request body, Finding, artifact, or target-bound surface. Plant is
  Hub-local file → `vault.put` → `DnsAccount.origin_ca_key_ref`.
- **Pinned env names:** `HUB_TEST_ZONE_SLUGS` is the one allowlist;
  `HUB_TEST_DNS_ZONE` is retired; `HUB_TEST_CF_TOKEN` stays the existing
  test-plane token env — **do not invent it**. Test-plane Origin-CA plant
  stays `HUB_TEST_ORIGIN_CA_KEY` in `tests/harness/cf_zone.py`. Do not add a
  product env for the Origin-CA key.
- Test-plane construction stays triple-keyed: `HUB_TEST_MODE` **and**
  `purpose == test` **and** the name on `HUB_TEST_ZONE_SLUGS`.
- **`0009_phase3.py` is closed.** The only 3b migration is Task 1's
  `0010_phase3b.py` on `Site`. No new tables. Prefer `Site` / `DnsZone` /
  `Finding` / `DnsRecord` / `SiteVolume` / `BackupUnit` / `CheckRun`.
- **`findings` is the canonical realtime topic** (D-045).
- Every new step is `ensure_X(desired)` and run-twice with **zero** mutating
  Transport calls the second time (§D6).
- New alert kinds need a row in `monitor/alert_rules.py` first. Adopt plan
  Findings file through `core.findings.finding()` (same as seams); do not
  invent pager kinds unless the design note names one.
- `TLS-B2-HUB-DNS01-UNPROXIED` stays **phase 4**. Do not mark the full-text
  `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`. Unproxied refusal stays.
- LE-staging credentialed run is a leftover, **not** 3b MUST.
- Do not claim a 24 h Hub-down. The adopt abandon window is a DNS-record TTL,
  not REL-P2.
- Reviewer never writes the code they review (D-014).
- Sensitive paths wait for the panel vote: existing Phase-3 list plus
  `provision/adopt.py`, `deploys/adopt_flow.py`.
- Tiers: T1 = fakes. T2 = `hub-test-target`. T3 = Multipass. A `tier: t2|t3`
  req is verified only by a passed marked test (D-024).
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` in the
  round they judge. Registry edits are Task 0.
- TDD: failing test first. Long "why" HEREDOC commits; no amend.

Protective cut (**D-047**): MUST = Tasks 0–7 and 9. Task 8 (sim/UI polish)
is the named first slip candidate. App-log viewer, scheduled-jobs UI,
Hub-central DNS-01, backup UI, LE-staging, 24 h Hub-down are out of this
phase.

## Parallel waves

| Shared file | Order |
|---|---|
| `conformance/requirements.yaml` / `check.py` / `DECISIONS.md` | Task 0 |
| `core/models.py` / `0010_phase3b.py` | Task 1 |
| `core/zone_views.py` / Settings | Task 2 after 1 |
| `frontend/src/screens/Home.jsx` | Task 3 after 2 |
| `provision/adopt.py` | Task 4 after 1 |
| `provision/service.py` | Task 5 after 4 |
| `deploys/adopt_flow.py` | Task 6 after 1+2+4 |
| Beat / reaper | Task 7 after 6 |
| sim + Sites adopt UI | Task 8 after 3+6 |
| acceptance + demo | Task 9 after MUST |

---

## Task 0 — Unblock `check.py --phase 3.5` (D-047…D-052)

**Title:** Phase-3.5 due set exists; adopt ids bump off Phase 3; DNS-01 stays 4.

**Files created/touched:**
- `DECISIONS.md` — rows D-047…D-052 (text from the design note §5).
- `conformance/requirements.yaml` (sensitive) — add `DNS-SITE-ZONE-BIND`,
  `TLS-B2-ORIGIN-CA-PLANT`, `UX-F3-FIRST-RUN-CHECKLIST`, `P3B-ADOPT-DEMO`
  (`verify: demo`, `demo: conformance/demos/phase-3.5.md`). Set
  `PROV-J7-COMPOSE-AWARE-ADOPT` and `PROV-E6-ADOPT-TEMP-SUBDOMAIN` to
  **`phase: 3.5`** (do not change their `text:` / `text_hash:`).
  `TLS-B2-HUB-DNS01-UNPROXIED` stays `phase: 4`.
- `WAIVERS.md` — keep the two adopt lines until Tasks 4+6 prove them; rewrite
  the SEC-B2 waiver's "built in Phase 3b" clause to **phase 4** (design note
  §1.2). Do not retire LE-staging or REL-P2 24 h.
- `Makefile` — add `conformance-3.5` (`--phase 3.5`). Leave `conformance` /
  `conformance-3` / `review-round` as Phase 3 minus live tiers.
- `conformance/paths.yaml` + `.github/CODEOWNERS` — `deploys/adopt_flow.py`
  if not already listed beside `provision/adopt.py`.

**Exact req ids proven:** none go green here. This task makes the 3.5 due set.

**Tests to write:**
- `tests/test_conformance_gate.py` (extend) —
  `test_phase_3_5_due_set_includes_bind_plant_f3_and_adopt`;
  `test_phase_3_due_set_no_longer_requires_adopt_ids`;
  `test_tls_b2_hub_dns01_stays_phase_4`.
- `tests/test_makefile_nightly.py` (extend) —
  `test_conformance_3_5_target_exists`;
  `test_review_round_conformance_is_still_phase_3_minus_live_tiers`.

**Dependencies:** none.

---

## Task 1 — `Site.edge_owner` + adopt CheckRun kind (`0010_phase3b.py`)

**Title:** One Site column for Caddy ownership; adopt progress reuses CheckRun.

**Files created/touched:**
- `core/models.py` — `Site.edge_owner` (`host_caddy` \| `site_caddy`, default
  `host_caddy`); `CheckRun.Kind.ADOPT = "adopt"`.
- `core/migrations/0010_phase3b.py` — **`Site.edge_owner` only.** Do not add
  tables. Do not migrate CheckRun (CharField choices).

**Exact req ids proven:** none yet (column + kind only).

**Tests to write:**
- `tests/test_site_edge_owner.py` —
  `test_new_site_defaults_to_host_caddy`;
  `test_edge_owner_rejects_unknown_value`;
  `test_checkrun_kind_adopt_saves_without_a_new_table`.

**Dependencies:** Task 0.

---

## Task 2 — Settings-bind `Site.dns_zone` + Origin-CA file plant (Architect I1)

**Title:** A Settings-connected account can finish a deployable public site
without pasting an Origin-CA key.

**Files created/touched:**
- `wizard/views.py` / `core/` create view — `POST /api/v1/projects/` creates
  Project + Site. Public site: one matching-purpose `DnsZone` → bind it;
  several → require `dns_zone` in the body; zero → 409 + Finding
  `site-dns-unbound:{pk}`. Mesh-only may omit the FK.
- `core/zone_views.py` — `POST /api/v1/dns-accounts/{id}/origin-ca-plant/`
  body `{path}`. Read the file only if it is 0600 and under
  `/var/lib/deploy-hub/` or `/etc/deploy-hub/`; `vault.put`; set
  `origin_ca_key_ref`. Refuse path traversal, world-readable files, and any
  body that contains key bytes. Response is planted / not planted — never
  the key.
- `frontend/src/screens/Settings.jsx` — Cloudflare panel grows plant status +
  path field + Plant. Connect form stays DNS-token only (existing copy).
- `deploys/seams.py` — fail-closed until planted **stays**. After plant,
  proxied public deploy constructs the issuer.
- Generated client / zod as needed.

**Exact req ids proven:** DNS-SITE-ZONE-BIND; TLS-B2-ORIGIN-CA-PLANT.

**Tests to write:**
- `tests/test_site_dns_bind.py` —
  `test_public_site_create_auto_binds_the_single_connected_zone`;
  `test_public_site_create_with_no_zone_files_unbound_finding_and_409`;
  `test_mesh_only_site_may_omit_dns_zone`.
- `tests/test_origin_ca_plant.py` —
  `test_plant_from_allowlisted_0600_file_sets_origin_ca_key_ref`;
  `test_plant_rejects_path_outside_prefix`;
  `test_plant_request_and_response_contain_no_key_bytes`;
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
  deploy); add a project (the Task 2 POST). Each item is one sentence + the
  one button that populates it (§F3).
- Snapshot/API for checklist progress (Home already has the shell events
  client; do not open a second socket). Topic stays `findings` for attention;
  checklist completion is derived state, not a new topic.
- `frontend/src/sim.js` — empty / mid-checklist / done fixtures.

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
only · **(e)** write `Site.edge_owner` once.

**Files created/touched:**
- `provision/adopt.py` (**new, sensitive**) — `read_compose(path)` via
  `yaml.safe_load`, executing nothing; filename order from design note §1.1(b);
  `classify_services()` → web / worker / beat-scheduler / one-shot migrate /
  db / cache / site-owned edge; `adoption_plan(project)` emits Findings
  (what / why / exact fix) plus one manifest proposal, a `SiteVolume` list
  (N6), and sets `Site.edge_owner`. Two uncompressible public services →
  refuse Finding. Operator paste is not an argument.
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
  `test_ambiguous_edge_blocks_until_edge_owner_is_set`.

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
Never flip before verify. Never strand a volume.

Design-note answers: **(c)** name/zone/cleanup · **(d)** point-in-place.

**Files created/touched:**
- `deploys/adopt_flow.py` (**new, sensitive**) — stages, each idempotent:
  upsert temp `{slug}-adopt-{8hex}.{zone.name}` on **`Site.dns_zone`** through
  `desired["dns"]` (caller-injected provider; this module does not import
  `providers.cloudflare`); deploy/verify HTTP 200 + the site's healthz;
  register `SiteVolume` / point `DATABASE_URL` (no second Postgres, no
  Hub DB provisioner as default); flip the prod name; decommission the old
  path; `cleanup()` deletes the temp `DnsRecord` + provider record and stops
  temp containers. Flip **refuses** unless verify recorded success for the
  current image tag. Live-host compose, if `Transport.get` finds one, diffs
  against the git compose and **blocks the flip** on drift. `CheckRun(kind=
  adopt)` holds `temp_name` / `stage`.
- SEC-B2: extend the existing no-token scan if this module adds put/run
  surfaces — unmarked, no full-text `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`.

**Exact req ids proven:** PROV-E6-ADOPT-TEMP-SUBDOMAIN; PROV-J7 (with Task 4).

**Tests to write:**
- `tests/test_adopt_flow.py` —
  `test_dns_flip_refuses_before_verification`;
  `test_verified_flip_upserts_then_decommissions`;
  `test_abandoned_flip_cleans_up_its_temp_subdomain`;
  `test_temp_name_is_slug_adopt_hex_on_site_dns_zone`;
  `test_no_dedicated_adoption_zone_is_constructed`;
  `test_flow_run_twice_records_zero_mutating_calls`;
  `test_decommission_never_touches_a_registered_volume_without_confirmation`;
  `test_unmapped_named_volume_blocks_the_flip`;
  `test_compose_db_is_pointed_not_reprovisioned`;
  `test_live_compose_drift_blocks_the_flip`;
  `test_no_cloudflare_import_in_deploys_adopt_flow`.

**Dependencies:** Task 1, Task 2, Task 4.

---

## Task 7 — Abandoned-flip reaper

**Title:** A temp name older than 24 h does not live forever if the operator
walks away.

**Files created/touched:**
- `deploys/adopt_flow.py` — `cleanup` remains the one owner.
- Beat entry `adopt-temp-reaper` (hourly) — `CheckRun(kind=adopt)` rows that
  still name a `temp_name` and are older than 24 h from first upsert call
  `cleanup`. Failed cleanup files `adopt-temp-orphan:{site_pk}:{name}` (P2)
  on `findings`. This is not a Hub-down and not REL-P2.

**Exact req ids proven:** PROV-E6-ADOPT-TEMP-SUBDOMAIN (cleanup half).

**Tests to write:**
- `tests/test_adopt_reaper.py` —
  `test_reaper_deletes_temp_older_than_24h`;
  `test_reaper_leaves_fresh_temp_alone`;
  `test_cleanup_failure_files_orphan_finding`;
  `test_reaper_does_not_delete_prod_name_or_registered_volume`.

**Dependencies:** Task 6.

---

## Task 8 — Adopt UI + simulation states (may slip)

**Title:** Sites can start adopt from the plan; every new state is in `sim.js`.

**Files created/touched:**
- `frontend/src/screens/Sites.jsx` — adopt plan + start/cancel (T2 on flip /
  decommission). `edge_owner` shown, not prompted per run.
- `frontend/src/sim.js` — plan / verify / flipped / abandoned / unbound /
  unplanted fixtures, including `cert_refusal`.
- UX-F8 seed rule: a new state without a sim fixture is a round finding.

**Exact req ids proven:** none new (UX-F8 already retired; keep the seed
honest). Slip this task with a dated note, not a quiet missing state.

**Tests to write:**
- `frontend/tests/adopt.test.ts` —
  `adopt_actions_are_t2_with_a_diff`;
  `edge_owner_is_displayed_not_prompted_per_run`;
  `sim_covers_plan_verify_flip_abandon`.

**Dependencies:** Task 3, Task 6.

---

## Task 9 — Acceptance + demo record

**Title:** The §4 demo is a checked-in record; adopt waivers die when the
tests are green.

**Files created/touched:**
- `tests/acceptance/test_phase_3_5.py` — one test per milestone clause in
  design-note §4, `@pytest.mark.acceptance(phase=3.5)`.
- `conformance/demos/phase-3.5.md` (+ directory if needed).
- `WAIVERS.md` — retire `PROV-J7-COMPOSE-AWARE-ADOPT` and
  `PROV-E6-ADOPT-TEMP-SUBDOMAIN` only after Tasks 4+6+7 are green. Do not
  retire LE-staging, REL-P2 24 h, or the SEC-B2 DNS-01 clause.

**Exact req ids proven:** P3B-ADOPT-DEMO.

**Tests to write:**
- `tests/acceptance/test_phase_3_5.py` —
  `test_public_site_binds_dns_zone`;
  `test_origin_ca_is_planted_from_a_hub_file_not_a_paste`;
  `test_f3_checklist_owns_home_until_done`;
  `test_compose_plan_is_one_v5_site`;
  `test_temp_subdomain_on_site_zone_cleans_up`;
  `test_flip_refuses_before_verify`;
  `test_registered_volume_survives_decommission`;
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
| LE-staging credentialed run | No `HUB_TEST_CF_TOKEN` on this host; leftover Task 8 | leftover |
| 24 h Hub-down | D-042 | not this phase |
