# Phase 2.5 exit demo — recorded (P25-HARNESS-DEMO)

**Date:** 2026-08-22 · **Branch:** `phase-2.5` · **Recorded by:** Task 16
session on HEAD `30c93e4` plus the acceptance/registry/waiver files in this
change. Run tails under `conformance/demos/phase-2.5/` are from this session's
real runs; nothing here is synthesized.

**Amended 2026-08-22 (panel fix wave):** Multipass 1.16.3 was installed on
this host after the original record, the panel's fix wave landed (FIX-0..9),
and the live T3 leg ran green — see "The T3 leg, now live" below and
`phase-2.5/t3-run.txt`. The two host-without-multipass waivers are retired;
only the LE-staging credential waiver stands.

## What the milestone asked (design note §4)

Local Multipass: provision a throwaway VM → harden+verify (ufw/fail2ban real)
→ deploy `sample-site/` and `sample-node-site/` → HTTP ready → v2 →
rollback-within-60s → toxiproxy SSH timeout → resume → teardown + reaper
empty. LE/HTTPS/wss-via-CF when `HUB_TEST_DNS_ZONE` is set. Host without
Multipass: a dated `WAIVERS.md` line, and a probe that fails if Multipass is
present while T3 was skipped. `make conformance-2.5` green.

## The honest state of this host

**As originally recorded (Task 16):** Multipass could not run here and there
were no Cloudflare test-zone credentials. Evidence:
`phase-2.5/multipass-absent.txt` (`multipass version` → command not found,
exit 127, kept as the historical pre-install state) and
`phase-2.5/le-staging-outstanding.txt`. The three skipped-only ids were
**waived, not greened**.

**As it stands after the fix wave:** Multipass 1.16.3 is installed
(`multipass version` succeeds), which made the two host-without-multipass
lines self-refusing red — exactly as designed
(`tests/harness/multipass.py::waiver_illegal_if` +
`tests/acceptance/test_phase_2_5.py::test_t3_skip_cannot_verify_tier_t3`) —
so the wave ran the live T3 leg green and retired them. The one waiver still
in force, verbatim by id and reason key:

- `HARNESS-T3-LE-STAGING` — no-test-zone-credentials (2026-08-22)

## The T3 leg, now live (Multipass — first recorded run)

`CONFORMANCE_RUN_REPORT=off python -m pytest -q -m t3 -p no:cacheprovider` →
**16 passed, 3 skipped in 215.94s**; `multipass list` afterwards →
`No instances found.` (reaper-empty teardown). Full tail and all 19 collected
nodeids with their real outcomes: `phase-2.5/t3-run.txt`. Highlights, all on
one throwaway `hub-t3-sess-*` VM:

- provision (fresh-host probe, port 80 free) → guest docker + Caddy →
  PROFILE=target harden → `ufw` active, fail2ban active, ignoreip is the
  singular HUB_MESH_IP — `tests/test_t3_deploy.py::test_provision_fresh_multipass_then_harden`,
  `tests/test_t3_ufw_truth.py` (5 passed)
- `sample-site/` deployed through the real pipeline with its
  `DJANGO_SECRET_KEY` delivered via the vault env bundle (panel C1/F3 fix) →
  HTTP ready through on-VM Caddy — `::test_deploy_sample_site_http_ready`
- `sample-node-site` fixture: ready-before-cutover, volume survives v2,
  one ws frame through Caddy (the pipeline's own smoke now performs a real
  ws handshake), rollback under 60s — 4 passed
- honest no-mesh posture: harden printed "does not prove HARD-V2", no
  tailscale0 interface or rule exists (the dummy standin is gone; panel C2)
- the 3 skips are the LE-staging credential gates, still waived (D-031)

## What executed live (T2, docker — no Multipass required)

**SIGKILL worker-death matrix** (`REL-P3-WORKER-DEATH`), all in
`tests/test_crash_kill_matrix_sigkill.py`:

- `test_sigkill_after_step_n_child_dies_parent_survives[1]` … `[9]` — a
  `python -m deploys.worker_entry` child is SIGKILLed after each ensure_*;
  pytest survives, the crashed step is never marked succeeded
- `test_heartbeat_sweep_resumes_sigkilled_child` — stale heartbeat → sweep →
  succeeded
- `test_runtimeerror_hook_still_raises_in_process` — the Phase 2 hook is
  unchanged and is not a pass for this id
- `test_t2_sigkill_worker_resumes_on_hub_test_target` (t2) — live SshTransport
  child SIGKILL after step 4 on hub-test-target, sweep resumes to succeeded

**toxiproxy mid-deploy timeout → resume** (`HARNESS-T3-TOXIPROXY`, live on T2):
`tests/test_toxiproxy_resume.py::test_ssh_timeout_mid_deploy_resumes` — a real
SshTransport through toxiproxy, timeout armed after step 2, the stalled step is
never succeeded, `sweep_stale_deployments` resumes to succeeded.

**Combined-run history, told straight:** the first all-tiers `pytest -q` on
`8065ff6` was red in T2 — a surviving `site-*` container and Caddy route on the
shared hub-test-target broke the next test's `docker run` and route PUT. Fixed
in `286c9ea` (the `hub_target` fixture now wraps the session target with
per-test `site-*` cleanup); after the fix `pytest -q -m t2` = **11 passed,
1 skipped** — the one skip is the documented D-025 alpine stub
(`tests/test_pipeline_sample_node_site.py`, PIPE-S4 waiver kept). This session's
run tails: T1 in `phase-2.5/t1-run.txt`, all-tiers in
`phase-2.5/all-tiers-run.txt`, conformance outputs in
`phase-2.5/conformance.txt`. `make conformance-2.5` itself always re-reads a
fresh full-suite report bound to the tree it grades, so the committed gate is
never these quoted tails — they are the session record, the gate re-earns its
green on every run.

## REL-P2 — 24h still outstanding, named

`REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven` **stays in WAIVERS.md**
(D-026). What Phase 2.5 adds toward it, without claiming it:

- the Beat Hub-down drill stub writes a `CheckRun` with `duration_s=1800`
  (< 86400) and no 24h flag — `tests/test_drills.py::test_hub_down_does_not_claim_24h`
- `--restart unless-stopped` is on `_docker_run_argv` —
  `tests/test_ensure_start.py::test_docker_run_argv_includes_restart_unless_stopped`
- a missed drill is an AuditEvent —
  `tests/test_checkrun.py::test_missed_drill_writes_audit_event`

Do not read this record as a 24h drill. The 24h live form remains the waiver's
retirement condition.

## Acceptance transcription

`tests/acceptance/test_phase_2_5.py` (`@pytest.mark.acceptance(phase="2.5")`),
one test per milestone clause: B9 wall refuses a prod zone before any
mutation; missed drill audits; `core/ssh.py` + the harness custody set are
sensitive paths; SIGKILL child resumes; T1 timeout leaves a resume pointer
(the live toxiproxy proof stays the named T2 nodeid); `--restart
unless-stopped`; a t3 skip cannot verify `tier: t3`; review-round excludes
tier t3; both fixture trees exist; the two t3 clauses
(`test_t3_both_fixtures_ready_v2_rollback_reaper`, `test_t3_ufw_truth`) carry
`@pytest.mark.t3` and are skipped-only here; REL-P2 24h is not claimed.

## Review panel and merge authority (delegated 2026-08-22)

Joseph delegated the sensitive-path merge click for this phase to a recorded
expert-panel vote ("make this process automation decide and review by team of
experts", 2026-08-22). The panel reviewed the whole branch diff
(`2d6e99c..c3573c4`, 467KB package) on three independent seats/models:

- **Architect** (claude-opus-5-thinking-high): MERGE-AFTER-FIXES — C1
  (sample-site T3 env path), C2 (dummy-tailscale0 manufactured mesh green).
- **Security** (gpt-5.6-sol-medium): MERGE-AFTER-FIXES — S1 (DNS zone binding),
  S2 (nightly bundle scrubber), S3 (reaper custody).
- **QE/SRE** (claude-fable-5-thinking-high): MERGE-AFTER-FIXES — F1
  (review-round red-by-construction), F2 (nightly could never exit 0),
  F3 (=C1), F4 (T3 VM isolation).

One fix wave (`c3573c4..fc8e563`, 13 commits) addressed all ten findings plus
the live-T3 boot defect; the scoped re-review verdicted every finding
ADDRESSED, judged the three disclosed extras sound (`# nosec` markers,
`_ws_frame` rewrite, no-route fail-fast), found no new Critical/Important
breakage, and answered "safe to merge to master per the panel's conditional
votes: yes". Findings parked for the next phase are in the SDD ledger:
self-declared t3 marks (I1), `worker_entry` test-tree reach (I2), duplicated
Multipass driver (I4), drill prober wiring (I5), restore-stub status (M1),
`find_missed` prod inertness (M2), LE waiver probe (M4), ws-probe read loops.

## Follow-up, still open

1. ~~First local Multipass T3 run — retires the two host-without-multipass
   waivers.~~ Done 2026-08-22 (fix wave): `phase-2.5/t3-run.txt`, waivers
   retired.
2. First credentialed LE-staging + wss-through-CF run — retires
   `HARNESS-T3-LE-STAGING`.
3. REL-P2 24h live drill — retires
   `REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven`.
4. Real T2 fixture image (vfs `npm ci`) — retires the D-025 alpine PIPE-S4
   waiver.
