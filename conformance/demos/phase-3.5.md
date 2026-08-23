# Phase 3.5 exit demo — recorded (P3B-ADOPT-DEMO)

**Date:** 2026-08-23 · **Branch:** `p3b-t9` · **Recorded by:** Task 9
on BASE `41e5b7d` (merge of Tasks 0–7) plus the acceptance / waiver / demo
files in this change. **T1 fakes only.** This is not a live Cloudflare
or Let's Encrypt success. The existing test-plane token env was not set
on this host and was not required. No new token env was added.

## What the milestone asked (design note §4)

Connect Cloudflare (existing 12b) → plant Origin-CA from a Hub-local file
under an Origin-CA subdir → `POST /api/v1/projects/` binds `Site.dns_zone`
(eligible purpose) and `primary_target` (no unbound Finding, because no
unbound public Site exists) → §F3 card leaves Home → enroll/use a target
that is occupied → fresh-host guard offers adopt, not only refuse → plan
classifies the three fixture stacks (web+worker+beat+migrate; web+site-Caddy;
web only) → MUST start `adopt_flow` with `desired["dns"]` from
`dns_provider_for` → public: temp `{slug}-adopt-{8hex}` upserts in the
site's `DnsZone`; mesh-only: no temp name, verify over mesh seams → live
site stays up until flip → verify succeeds → flip prod name → old path
decommissioned, registered volumes still present (never `docker volume rm`)
→ cancel/abandon deletes the temp name (flow + 24 h reaper) → a compose
with two public services refuses with a Finding.

`make conformance-3.5` is the 3b gate and excludes t2/t3. `conformance-3`
remains the all-tiers Phase 3 nightly gate. No 24-hour Hub unavailability
claim. DNS-01 still not due.

## The honest state of this host

T1. `FakeDnsProvider` + `AdoptTransport` + Hub-local plant files. The
test-plane token env is unset (`cf_token_set False` this session).
`HUB_TEST_ZONE_SLUGS` is the allowlist; the retired zone-name env is not
used. Multipass is not part of this record. Task 8 UI landed; HTTP start
still 404. The MUST demo does not wait on that HTTP.

## What actually landed (Tasks 0–7, T1)

This session re-ran the marked T1 files on `41e5b7d` before the record
files: **81 passed** across `test_site_dns_bind.py`,
`test_origin_ca_plant.py`, `test_first_run_checklist.py`,
`test_adopt_compose.py`, `test_adopt_flow.py`, `test_adopt_reaper.py`,
`test_provision_fresh_host.py`, `test_certs_phase_pin.py`,
`test_site_edge_owner.py`. Then the named acceptance file was written
and its nine behavioural clauses passed on those same fakes; the two
record clauses stayed red until this file and the two adopt-waiver
retirements existed.

### Settings-bind + Origin-CA plant

`POST /api/v1/projects/` auto-binds the single eligible `DnsZone`
(`purpose=prod`, or `purpose=test` only under the triple key) and the
single enrolled `Target` as `primary_target`. Zero eligible zones →
HTTP 409 and zero Project, Site, and Finding rows.
`site-dns-unbound:{pk}` is illegal. Mesh-only may omit the FK.

Plant is `POST /api/v1/dns-accounts/{id}/origin-ca-plant/` with body
`{path}` only. A 0600 regular file under an Origin-CA subdir is vaulted
as `API_TOKEN` / `owner_type=dns_account` / `owner_id=ref`. A paste
field is 400; Settings-connect still vaults the DNS token only.
`resolve_production_seams` still refuses until planted.

### §F3 checklist owns Home

`GET /api/v1/first-run/` derives `owns_home` from Target / zone / plant /
Project. `Home.jsx` renders the checklist card while `owns_home` is true,
then today's map + fleet. Topic stays `findings`. After a 201 project
create, the client refetches first-run immediately — project create
never files a Finding.

### Occupied host → adopt pointer, not a dead end

`provision_host` still refuses occupied 80/443 (E6 never-take-down) and
now names `adoption_plan` / the adopt flow. Probe-only; no catalog
import. Task 5 T1:
`tests/test_provision_fresh_host.py::test_occupied_80_refuses_and_names_adopt`.

### Compose plan is one V5 Site

`provision/adopt.py` `read_compose` / `classify_services` / `adoption_plan`
on the three fixture stacks under `tests/fixtures/compose/`:

- `web-worker-beat-migrate` → one service + jobs (worker/beat/migrate) +
  db/redis pointers + named volumes `pgdata`/`media`
- `web-site-caddy` → `Site.edge_owner=site_caddy`
- `web-only` → one service, `host_caddy`, no Manifest row

Two uncompressible public services (`two-public`) refuse with a Finding.
`yaml.safe_load` executes nothing. Paste is not an argument.

### Adopt flow (public + mesh) on FakeDnsProvider

`deploys/adopt_flow.py` MUST start. Public: temp
`{slug}-adopt-{8hex}.{DnsZone.name}` upserts on `Site.dns_zone` (no
dedicated adoption zone); `CheckRun.results` stay the closed S2 schema
`{schema_version, site_id, temp_name, stage, started_at}`. Verify
(JSON healthz on the adopt container, current image tag) before flip.
`test_live_site_stays_up_until_flip` / QE I3: old container is still
`running` through temp DNS + verify; `docker stop` of the old name
happens after flip, not before. Flip before verify raises `AdoptRefused`
and leaves prod on `198.51.100.1`. Cleanup deletes the temp name, never
prod. Mesh-only: `temp_name=""`, `desired["dns"] is None`, Transport
healthz, decommission still runs.

Registered volumes survive decommission: `adopt_flow` never issues
`docker volume rm` for a `SiteVolume` name (M1). Reaper
(`adopt-temp-reaper`) calls the same `cleanup` after 24 h from
`results.started_at` — an abandon TTL, **not** a REL-P2 claim.

## Adopt waivers retired on those T1 proofs

`PROV-J7-COMPOSE-AWARE-ADOPT` and `PROV-E6-ADOPT-TEMP-SUBDOMAIN` are
**RETIRED** 2026-08-23 (Task 9) because the marked T1 files above are
green. Retirement does not wait on a live zone token.

## Still outstanding — named, not greened

- `REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven` **stays in WAIVERS.md**
  (D-042). The 24-hour form is a dated calendar item. This record is
  T1 adopt fakes. The REL-P2 duration is still not claimed. Not this phase.
- `TLS-B2-HUB-DNS01-UNPROXIED` stays **phase 4**. Unproxied refusal stays
  (`UnproxiedCertUnsupported` / Sites-screen). DNS-01 is not due. The
  full-text `SEC-B2-NO-DNS-TOKENS-ON-TARGETS` waiver stays (Hub-central
  DNS-01 clause unimplemented).
- `HARNESS-T3-LE-STAGING` stays waived (`no-test-zone-credentials`).
  Leftover Task 8 owns that line. 3b neither freezes nor retires it.
- Task 8 UI landed; HTTP start still 404.

## Acceptance transcription — real nodeids

`tests/acceptance/test_phase_3_5.py` (`@pytest.mark.acceptance(phase=3.5)`),
T1 fakes, this session:

- `::test_public_site_binds_dns_zone`
- `::test_public_site_create_with_no_eligible_zone_creates_nothing`
- `::test_origin_ca_is_planted_from_a_hub_file_not_a_paste`
- `::test_f3_checklist_owns_home_until_done`
- `::test_compose_plan_is_one_v5_site`
- `::test_temp_subdomain_on_site_zone_cleans_up`
- `::test_flip_refuses_before_verify`
- `::test_live_site_stays_up_until_flip`
- `::test_registered_volume_survives_decommission_without_docker_volume_rm`
- `::test_rel_p2_24h_still_not_claimed`
- `::test_hub_central_dns01_still_not_due`

No `@pytest.mark.req` on `SEC-B2-NO-DNS-TOKENS-ON-TARGETS` or
`TLS-B2-HUB-DNS01-UNPROXIED`.

## Gates

`conformance-3.5` = `python conformance/check.py --phase 3.5 --exclude-tier t2 --exclude-tier t3`.
`conformance-3` stays all-tiers Phase 3. Live 3.5 tiers were never added
(new 3b ids are tier-less). This record does not claim `make review-round`
or `make conformance-3.5` ran in this Task 9 session — those gates re-earn
green from a fresh run-report. The proofs this file records are the T1
pytest nodeids above.
