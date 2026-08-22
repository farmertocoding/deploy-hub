# Phase 3 exit demo — recorded (P3-DNS-MONITOR-DEMO)

**Date:** 2026-08-23 · **Branch:** `p3-t19` · **Recorded by:** Task 19
on HEAD `261160d` plus the acceptance / waiver / demo files in this change.
Nothing here is a live Cloudflare or Let's Encrypt success.

## What the milestone asked (design note §4)

Mechanical: `make review-round` twice clean (T1 + phase-3 conformance minus
live tiers). Live on the Multipass host of record: CF-connect → provision →
deploy `sample-site/` → product adapter upsert → Origin cert → P1 / digest /
map / dead-man. **No test-zone token → DNS-CF-T3-LIVE and
HARNESS-T3-LE-STAGING are skipped-only + dated waiver, never a T1-sibling
green.** Record: this file + `conformance/demos/phase-3/`.

## The honest state of this host

See `phase-3/host-state.txt`. Multipass 1.16.3 CLI is installed, so
`multipass_available()` is true, but the daemon socket is down this
session (`cannot connect to the multipass socket`). Live T3 ERRORED at
setup; that is not a host-without-multipass waiver (those lines stay
retired). `HUB_TEST_CF_TOKEN` is not set. `HUB_PAGER_BACKEND` defaults
to `fake`. No live token paste, no LE staging issuance, no ntfy.sh page.

`make conformance-3` on this host is therefore red on the live T2/T3
harness ids (HARNESS-T3-NIGHTLY, HARNESS-T3-UFW-TRUTH, PIPE-S4 T2/T3
legs, REL-P3-WORKER-DEATH T2, HARNESS-T3-TOXIPROXY). Those are
`failed`/`error` outcomes — not waivable. Phase-3 T1 ids and
`TLS-B2-ORIGIN-CERT-PUSH` (T2 cert push, 2 passed) are verified.
`DNS-CF-T3-LIVE` stayed skipped-only + the credential waiver.

The two credentialed ids stay skipped-only behind the existing lines:

- `WAIVED: HARNESS-T3-LE-STAGING — no-test-zone-credentials` (2026-08-22)
- `WAIVED: DNS-CF-T3-LIVE — no-test-zone-credentials` (2026-08-22)

Self-refusing probes still hold (`tests/test_le_waiver_self_refusal.py`).
This record does not invent demo artifacts that imply live CF/LE succeeded.

## Adopt moved to Phase 3b

Task 15 did not land. See `phase-3/adopt-moved-to-3b.txt`.
`PROV-J7-COMPOSE-AWARE-ADOPT` and `PROV-E6-ADOPT-TEMP-SUBDOMAIN` are waived
this exit (D-044 / D-020 precedent). The Scribe amends §I so Phase 3b owns
adopt-existing-site.

## REL-P2 24 h — still not claimed

`REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven` **stays in WAIVERS.md**
(D-042). Dated calendar item: `phase-3/rel-p2-24h-calendar.txt` (2026-08-23).
`tests/acceptance/test_phase_3.py::test_rel_p2_24h_still_not_claimed` keeps
that honest. Do not read this record as a 24 h run.

## Dead-man receiver (panel ruling 3)

`phase-3/deadman-receiver.txt` — **no receiver is registered on this host**,
dated 2026-08-23. The product still files a Finding on a failed POST
(`tests/acceptance/test_phase_3.py::test_deadman_pings_only_after_a_completed_cycle_and_failure_files_a_finding`).
A fake healthchecks signup was not invented.

## Cloudflare-connect screen

`phase-3/cf-connect-screen.txt` — the Settings Cloudflare tab exists
(password field, `POST /api/v1/cloudflare/connect/`, refuse two-zone tokens).
Live token paste is not claimed.

## Pager transcript (backend named)

`phase-3/pager-transcript.txt` — backend **fake** (`FakePager`).
`HUB_PAGER_BACKEND` defaults to fake. No test paged anyone.

## Digest sample

`phase-3/digest-sample.txt` — 08:00 local Beat `digest-daily`, P3 set only.
Not a live SMTP send.

## Map v1 list dump

`phase-3/map-list-dump.txt` — NetworkZone / host / container / Hub / edge
from `graph_snapshot()`, list-view toggle in `Map.jsx`.
`tests/acceptance/test_phase_3.py::test_map_v1_snapshot_and_list_view` ran;
there is no `MAP-96-GRAPH-V1` slip waiver.

## Findings is the canonical topic (D-045)

`realtime/authorize.py` lists `findings` as canonical; `alerts` is the
deprecated alias for one phase. Asserted by
`tests/acceptance/test_phase_3.py::test_findings_inbox_requires_a_reason_to_accept_risk`.

## Retention (Task 11) — not waived

MON-C7 landed. HostMetric has no table (Task 1 never created one); disk
growth from HostMetric is vacuously zero. No MON-C7 slip waiver.

## Acceptance transcription — real nodeids

`tests/acceptance/test_phase_3.py` (`@pytest.mark.acceptance(phase=3)`):

- `::test_product_adapter_refuses_an_over_scoped_token_at_construction`
- `::test_no_dns_token_reaches_any_target_bound_surface`
- `::test_token_scope_audit_files_a_finding_on_excess`
- `::test_origin_cert_key_is_vaulted_pushed_0400_and_matched` (T1; does not mark the t2 id)
- `::test_unproxied_refusal_is_a_finding_and_a_visible_site_state`
- `::test_unclassified_alert_kind_cannot_ship`
- `::test_three_failures_open_one_p1_and_two_successes_close_it`
- `::test_unacked_p1_repeats_on_its_own_beat_entry`
- `::test_two_p2_in_ten_minutes_are_one_grouped_push`
- `::test_host_down_suppression_collapses_site_alerts`
- `::test_push_body_is_minimized_and_scrubbed`
- `::test_deadman_pings_only_after_a_completed_cycle_and_failure_files_a_finding`
- `::test_log_pull_is_capped_and_degrades_sampled`
- `::test_findings_inbox_requires_a_reason_to_accept_risk`
- `::test_rollback_is_one_click_and_never_step_up_gated`
- `::test_ws_unavailable_degrades_to_visible_polling`
- `::test_map_v1_snapshot_and_list_view`
- `::test_breakglass_has_impact_hub_side_dns_and_freshness`
- `::test_nightly_is_green_on_a_host_with_no_live_site`
- `::test_rel_p2_24h_still_not_claimed`
- `::test_cert_expiry_thresholds_match_v9`
- `::test_failed_deploy_shows_impact_and_at_most_three_actions`

No `@pytest.mark.req` on `SEC-B2-NO-DNS-TOKENS-ON-TARGETS` or
`UX-F5-ACTION-TIERS`. Those sit uncovered behind the clause-scoped waivers
that name `TLS-B2-HUB-DNS01-UNPROXIED` and `SEC-F5-T1-HARDWARE-TOUCH`.

## D-025 alpine / PIPE-S4

The existing `tests.test_pipeline_sample_node_site+PIPE-S4-READINESS-GATE+t2-instant-ready-stub`
line stays. Nothing in Phase 3 changes vfs overlay-on-overlay.

## PROC checklist lines (D-022)

`PROC-SENSITIVE-HUMAN-MERGE` and `PROC-REGRESSION-TEST` stay waived. The
panel vote is the standing substitute for the human merge click.

## UX-F8 / SEC-P5

Stay **RETIRED** (Tasks 13 and 16). Not re-waived.
