# Phase 7 exit demo — recorded (P7-RESTORE-DEMO)

**Date:** 2026-08-25 · **Branch:** `master` · **Recorded by:** Phase 7.0
Task 2. **T1 inject only.** This is not a live docker overwrite, live
AWS, named committed partner, or Playwright success. No KEK was used.
No live volume was overwritten. No new token env was added.

## What the milestone asked (design note §4)

A site with a sealed dump, T1 touch + type-the-name, injected
`restore_to_clean` → 201 ok; `RESTORE_CLEAN` CheckRun metadata has
`unit_id` and `checkrun_pk`; response has no dump bytes; live
SiteInstance untouched; command block still on GET list. Wrong confirm
→ 4xx. Missing dump → 4xx and `backup-restore-failed`. Unseal uses
`BACKUP_KEY`, never the KEK.

Record: `conformance/demos/phase-7.md`. This record **does not claim**
live docker overwrite, a KEK restore, Azure, Router Advisor, preview
environments, LAN ghosts, Pulumi, or U1. `PART-U1-NAMED-PARTNER` stays
uncovered until Joseph writes `conformance/demos/named-partner.md`.
Everyday `make review-round` (phase 5) may go green while U1 is
uncovered. This session did not run `make review-round` or two
consecutive `make conformance-7` rounds; those gates re-earn green from
a fresh run-report. `make conformance-7` is the phase gate and
**excludes t2/t3**:
`python conformance/check.py --phase 7 --exclude-tier t2 --exclude-tier t3`.
No invented token env. No Playwright.

## The honest state of this host

T1. Inject actually driven this session:

- `restore_to_clean=` wrap on `provision.views.restore_to_clean` (HTTP)
  and the same inject on `provision.backup.restore_to_clean` (direct).
  Default primitive writes a tempfile and deletes it. No live docker.

`HUB_TEST_MODE` is off unless a test flips it. No invented token env.
NAV is still six.

## Still outstanding — named, not greened

- `PART-U1-NAMED-PARTNER` stays uncovered. `conformance/demos/named-partner.md`
  is absent. This record does not claim a named committed partner.
- Router Advisor, preview environments (private repos), LAN discovery
  ghosts, Pulumi/managed-DB/LB, Azure adapter, overwrite-live restore
  are later Phase 7 polish, not this wave.
- Everyday `conformance` / `review-round` stay `--phase 5 --exclude-tier t2
  --exclude-tier t3`. `conformance-7` is not a `review-round` or
  `nightly-gates` prereq.

## Acceptance transcription — real nodeids

`tests/acceptance/test_phase_7.py` (`@pytest.mark.acceptance(phase=7)`),
each body calls the Task 1 proof:

- `test_restore_into_clean_container_t1`
- `test_restore_command_block_remains`
- `test_nav_stays_six`
- `test_demo_does_not_claim_live_docker_or_kek`
