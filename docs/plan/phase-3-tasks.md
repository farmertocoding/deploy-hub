# Phase 3 tasks — DNS automation + monitoring + map v1

SDD-ready work list for Implementers. Architect design note:
`docs/phase-3-design-note.md`. Do not start a task whose dependencies are open.
Do not start implementation from this design session.

**Branch:** cut task branches from `phase-3` (which carries these two docs).
Never implement on `master`. Sensitive-path merges to `master` go through the
recorded expert-panel vote — the Phase 2.5 precedent — not a silent auto-merge;
still name the sensitive files per task so the panel knows what it is voting on.

## Global constraints (every task)

- Every remote effect on a target goes through `Transport`; argv lists, never
  interpolated strings; file content via `put()`, never heredocs.
- Cloudflare / cloud / ntfy HTTP clients live **only** under `providers/`
  (`tests/test_import_rule.py` enforces it). `deploys/` receives a provider in
  `desired`; it never constructs or imports one, and never reaches `scanner/`.
- Secrets through the vault. Prod DNS tokens **never** on a target (SEC-B2) and
  scoped per zone (SEC-B5). ntfy publish tokens and topic names are vault
  secrets (M3). No secret in logs, task args, build contexts, push bodies.
- Locks in Postgres (§A5). Builds on the target, never the Hub (§B1).
- Every new step/repair is `ensure_X(desired)` — probe, act on diff — and every
  playbook runs twice in tests with **zero mutating Transport calls** the second
  time (§D6).
- New alert classes: a row in `monitor/alert_rules.py` first, or `classify()`
  raises. No per-alert channel choice; alert-protocol §2 is the authority.
- Mockup-first: plain readable Python/React, no premature optimization, no new
  frontend dependency without a DECISION (D-041 keeps the map dependency-free).
- Reviewer never writes the code they review (D-014 session split).
- Sensitive paths (`providers/**`, `catalog/**`, `scripts/**`, `vault/**`,
  `core/transport.py`, `core/ssh.py`, `core/views.py`, `core/otp.py`,
  `core/middleware.py`, `realtime/authorize.py`, `realtime/consumers.py`,
  `conformance/requirements.yaml`, `conformance/check.py`, CI, plus the new
  `monitor/pager.py`, `monitor/alert_rules.py`, `deploys/certs.py`,
  `provision/adopt.py` added by Task 0) wait for the panel vote.
- Tiers: T1 = fakes, no docker/VM. T2 = `hub-test-target`. T3 = Multipass
  (live on this host). A `tier: t2|t3` req is verified only by a passed test
  carrying that marker (D-024 + panel F1); a skip is `skipped-only` and red
  unless a dated `WAIVERS.md` line names the reason, and the line must be
  self-refusing when the reason disappears (D-043).
- Credential-gated work (Cloudflare test zone / LE) is **skipped-only + waiver**
  shaped, exactly like D-031 — never a T1 sibling standing in for a live leg.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` in the
  round they judge. Registry edits are Task 0; a later Scribe pass may follow.

Protective cut (**D-044**): MUST = Tasks 0–10, 12–16, 19, plus Task 17's
self-refusing-probe half. Tasks 11, 18 and Task 17's credentialed body may slip
with an honest waiver.

**Parallel waves.** After Task 0: wave A = 1, 4, 8, 10, 12, 16, 18 (disjoint
file sets). Wave B = 2, 3 (need 1), 5 (needs 4), 9 (needs 8), 13 (needs 4+12),
14 (needs 12), 15 (needs 1+3+12). Wave C = 6, 7 (need 5), 11, 17, 19.

---

## Task 0 — Unblock `check.py --phase 3` (D-032, D-039, D-040)

**Title:** Registry additions, phase-3 gate targets, t3-marker integrity, custody parity.

**Files created/touched:**
- `DECISIONS.md` — rows D-032…D-044 (text from the design note §5).
- `conformance/requirements.yaml` (sensitive) — add the 16 ids in design note
  §3 with `phase: 3` (`SEC-F5-T1-HARDWARE-TOUCH` is `phase: 4`);
  `DNS-CF-T3-LIVE` carries `tier: t3`, `TLS-B2-ORIGIN-CERT-PUSH` carries
  `tier: t2`; `P3-DNS-MONITOR-DEMO` is `verify: demo` with
  `demo: conformance/demos/phase-3.md` + `conformance/demos/phase-3/`.
  Flip `MON-DEADMAN-EXTERNAL` and `PROV-J7-COMPOSE-AWARE-ADOPT` from
  `verify: checklist` to `verify: test` (D-039) — do **not** touch their
  `text:`/`text_hash:`. Do not bump any phase-2/2.5 id. Do not retire a waiver
  here.
- `conformance/check.py` (sensitive) — **I1 fix**: a test carrying
  `@pytest.mark.t3` must also be host-gated (a `multipass_available()`-derived
  `skipif`, or residence in a module whose `pytestmark` carries one). A
  self-declared `t3` mark with no host gate is red, so a T1-runnable test can
  never verify a `tier: t3` req by declaring itself live.
- `Makefile` — `conformance` becomes
  `--phase 3 --exclude-tier t3 --exclude-tier t2`; add `conformance-3`
  (`--phase 3`, all tiers); `nightly-gates` uses `conformance-3` instead of
  `conformance-2.5`; keep `conformance-2.5` as a named historical target only
  if a test still reads it — otherwise delete it in the same change and update
  `tests/test_makefile_nightly.py`.
- `conformance/paths.yaml` + `.github/CODEOWNERS` — add `monitor/pager.py`,
  `monitor/alert_rules.py`, `deploys/certs.py`, `provision/adopt.py`. **Custody
  parity becomes two-way**: every CODEOWNERS entry under the repo's own trees
  must have a `paths.yaml` counterpart, not just the reverse (2.5 parked
  finding).
- `tests/acceptance/__init__.py` — no change; the phase-3 module lands in Task 19.

**Exact req ids proven:** none new go green here. This task makes the phase-3
due set exist and the `t3` marker honest; every other id is proven by its task.

**Tests to write:**
- `tests/test_conformance_gate.py` (extend) —
  `test_phase_3_due_set_includes_every_phase_3_id`;
  `test_verify_test_conversion_requires_a_marked_test`
  (throwaway tree: MON-DEADMAN-EXTERNAL as `verify: test` with no marker is
  `uncovered`, not silently green);
  `test_self_declared_t3_mark_without_host_gate_is_red`;
  `test_host_gated_t3_mark_is_accepted`.
- `tests/test_makefile_nightly.py` (extend) —
  `test_review_round_conformance_is_phase_3_minus_live_tiers`;
  `test_nightly_gates_use_conformance_3`.
- `tests/test_proc_rules.py` (extend) —
  `test_codeowners_entries_all_appear_in_paths_yaml`
  (the reverse direction of the existing parity test);
  `test_phase_3_sensitive_modules_are_listed`.

**Dependencies:** none.

---

## Task 1 — `DnsZone` + the product Cloudflare adapter (D-033, D-034)

**Title:** One zone identity, one Cloudflare client, per-zone token from the vault.

**Files created/touched:**
- `core/models.py` + `core/migrations/` — `DnsZone(name unique, provider
  slug default "cloudflare", token_ref (vault owner id, never the token),
  purpose ∈ {prod, test} default prod, proxied_default bool)`; `DnsRecord`
  gains `zone` FK (nullable for existing rows), `observed_value`,
  `last_verified` (§D3).
- `providers/cloudflare.py` (sensitive) — `CloudflareDnsProvider(DnsProvider)`
  constructed **only** from a `DnsZone`: resolves the zone id once by name and
  caches it, and every mutating call re-checks that the resolved zone id is the
  one the row names. Reads the token from the vault by `token_ref`; the token
  appears in the `Authorization` header and nowhere else (no logs, no
  exception text). `list_records` / `upsert_record` / `delete_record` /
  `get_nameservers` / `capabilities()` per §D5, `proxied` honoured, pagination
  followed (the 2.5 unpaginated-list minor).
- `providers/registry.py` (sensitive) — `dns_provider_for(zone)`: the only
  construction path. Under `HUB_TEST_MODE` it refuses any zone that is not
  `purpose=test` **and** allowlisted (`assert_test_zone` semantics extended to
  `DnsZone`); outside test mode it refuses `purpose=test` (D-034). Returns
  `FakeDnsProvider` when settings say simulation.
- `core/test_mode.py` (sensitive) — accept a `DnsZone` as well as a
  `NetworkZone`; one allowlist source, retiring the `HUB_TEST_ZONE_SLUGS` /
  `HUB_TEST_DNS_ZONE` dual namespace (2.5 parked finding). Keep the existing
  `NetworkZone` behaviour and its tests green.
- `providers/fakes.py` — `FakeDnsProvider` gains the `zone`-object call shape
  and a recorded-call log so run-twice assertions work.
- `deploys/pipeline.py` — resolve the provider via `dns_provider_for` when the
  caller did not inject one; do not import `providers.cloudflare` directly.

**Exact req ids proven:** DNS-CF-PRODUCT-ADAPTER. SEC-B2 partial (no token
path to a target; completed by Task 3).

**Tests to write:**
- `tests/test_cloudflare_adapter.py` (T1, `urlopen` doubled) —
  `test_upsert_is_a_diff_not_a_blind_write`;
  `test_list_records_follows_pagination`;
  `test_token_never_appears_in_repr_logs_or_exceptions`;
  `test_zone_id_is_rechecked_before_every_mutation`;
  `test_delete_absent_record_is_success`;
  `test_capabilities_declares_proxied`.
- `tests/test_dns_zone_wall.py` —
  `test_test_mode_refuses_prod_zone`;
  `test_prod_mode_refuses_test_purpose_zone`;
  `test_unallowlisted_test_zone_refused_under_test_mode`;
  `test_dns_provider_for_is_the_only_construction_path`
  (AST scan: no `CloudflareDnsProvider(` outside `providers/registry.py` and
  its own tests);
  `test_single_zone_allowlist_namespace`
  (a zone allowlisted one way is allowlisted the other way; no second env var
  authorizes a mutation).
- `tests/test_pipeline_dns.py` (extend) —
  `test_ensure_dns_twice_records_zero_mutating_calls`.

**Dependencies:** Task 0.

---

## Task 2 — SEC-B5 token-scope audit

**Title:** The most powerful credential gets a standing check, not a rule in a doc.

**Files created/touched:**
- `providers/cloudflare.py` (sensitive) — `verify_token()` calling
  `/user/tokens/verify` plus the token's permission listing; returns
  `{status, scopes, zones}`. No mutation.
- `monitor/token_audit.py` — `audit_cloudflare_tokens()`: for each `DnsZone`,
  compare the returned scopes against the declared minimum
  (`Zone:DNS:Edit` on that zone id for the `dns` ref; `Zone:Firewall
  Services:Edit` + `Zone Settings:Edit` for the `edge` ref, which is modelled
  and audited now and used in Phase 4). Excess scope, a Global-API-Key shape
  (no scope list), an inactive token, or a token valid for zones the row does
  not name → one Finding (P2) per fingerprint + `CheckRun(kind=cf_token_scope)`.
- `monitor/tasks.py` + `hub/settings/base.py` — Beat `cf-token-scope-daily`
  on queue `probes`.
- `core/models.py` — `CheckRun.Kind` gains `cf_token_scope`.

**Exact req ids proven:** SEC-B5-CF-TOKEN-SCOPING.

**Tests to write:**
- `tests/test_cf_token_audit.py` —
  `test_exact_minimum_scope_is_clean`;
  `test_excess_zone_scope_files_a_p2_finding`;
  `test_global_api_key_shape_is_refused_not_warned`;
  `test_inactive_token_files_a_finding`;
  `test_audit_writes_a_checkrun_every_run`;
  `test_audit_makes_no_mutating_api_call`;
  `test_finding_fingerprint_is_stable_across_runs`.

**Dependencies:** Task 1, Task 4 (Finding model). May land with the Finding
helper stubbed behind an import if Task 4 is still in flight — do not duplicate
the model.

---

## Task 3 — Origin certificates, `TlsCertificate`, and the unproxied refusal (D-035)

**Title:** SEC-B2 proven by what the pipeline refuses to do.

**Files created/touched:**
- `providers/base.py` (sensitive) — `OriginCertIssuer.issue(zone, hostnames,
  *, validity_days)` → `{certificate, expires_at}`.
- `providers/cloudflare.py` (sensitive) — implement it against the Origin CA
  endpoint; the Hub generates the keypair and sends only the CSR.
- `providers/fakes.py` — `FakeOriginCertIssuer` emitting a self-signed pair so
  T1/T2 never call Cloudflare.
- `deploys/certs.py` (**new, sensitive**) — `ensure_site_certificate(desired)`:
  proxied site → issue-or-reuse (reuse when `not_after` is beyond the renewal
  window), private key into the vault, cert+key pushed with
  `transport.put(..., mode=0o400)` under `/srv/sites/{slug}/tls/`, checksum
  verified after write (§B6). Unproxied public site → raise
  `UnproxiedCertUnsupported` naming Phase 3b; **never** write a DNS token, an
  ACME DNS provider block, or a `CLOUDFLARE_API_TOKEN` env into any target
  artifact.
- `core/models.py` + migrations — `TlsCertificate` per design note §2;
  `CheckRun.Kind` gains `cert_expiry`.
- `deploys/steps.py` — `ensure_route_tls` calls `ensure_site_certificate` and
  points the Caddy route at the pushed files; unchanged for `mesh_only`. Same
  change fixes the `_ws_frame` extended-length read loops at lines ~482/487
  (break on empty read instead of relying on the 60 s transport timeout —
  2.5 re-review minor).
- `monitor/cert_watch.py` — daily scan of `TlsCertificate.not_after` against
  the V9 thresholds; emits Findings at P3/P2/P1 and a `CheckRun`.
- `hub/settings/base.py` — Beat `cert-expiry-daily`.

**Exact req ids proven:** SEC-B2-NO-DNS-TOKENS-ON-TARGETS;
TLS-B2-ORIGIN-CERT-PUSH (`tier: t2`); TLS-V9-CERT-THRESHOLDS.

**Tests to write:**
- `tests/test_origin_certs.py` (T1) —
  `test_proxied_site_gets_origin_cert_and_key_in_vault`;
  `test_key_is_pushed_0400_and_checksum_verified`;
  `test_unproxied_public_site_refuses_by_name`;
  `test_refusal_leaves_zero_mutating_calls`;
  `test_reissue_is_skipped_inside_the_renewal_window`
  (run-twice: second call records no mutation);
  `test_no_dns_token_in_any_pushed_artifact`
  (scan every `put()` payload and every generated Caddy/env body for the token
  value, the vault ref, and `dns_challenge`/`acme_dns` keys).
- `tests/test_cert_thresholds.py` —
  `test_uploaded_45_21_7_maps_to_p3_p2_p1`;
  `test_auto_renewed_7_and_1_map_to_p2_and_p1`;
  `test_expired_cert_is_p1_not_silence`;
  `test_threshold_table_matches_alert_protocol_v9`.
- `tests/test_t2_cert_push.py` (`@pytest.mark.t2`) —
  `test_t2_cert_and_key_land_0400_on_hub_test_target`;
  `test_t2_caddy_reload_serves_the_pushed_cert`.
- `tests/test_ws_frame_read_loop.py` —
  `test_extended_length_read_breaks_on_empty_read`.

**Dependencies:** Task 1.

---

## Task 4 — The `Finding` model and inbox API (§F2)

**Title:** One attention queue; accept-risk costs a sentence.

**Files created/touched:**
- `core/models.py` + migrations — `Finding` per §F2 (`source_engine`,
  `severity ∈ {p1,p2,p3}` aligned to alert-protocol, `entity_type`/`entity_id`,
  `title`, `body`, `fix_action` nullable, `state ∈ {new, acked, snoozed,
  accepted_risk, resolved}`, `first_seen`, `last_seen`, `fingerprint` unique,
  `accepted_reason`).
- `core/findings.py` — `finding(source_engine, fingerprint, **fields)`
  upsert helper (one line to emit, like `audit()`); `accept_risk(finding,
  reason)` refuses an empty/whitespace reason; a changed fingerprint creates a
  new row rather than reviving an accepted one.
- `monitor/views.py` + `monitor/urls.py` + `hub/urls.py` — DRF list/detail/
  transition endpoints under `/api/v1/findings/`, §4.5 serializers, filters by
  state/severity/entity. Every state change writes an `AuditEvent`.
- `realtime/authorize.py` (sensitive) — append `findings` to the topic table;
  `realtime/publish.py` call on every create/transition.
- `frontend/src/api/` — regenerate (`make generate-client`).

**Exact req ids proven:** UX-F2-FINDING-MODEL (model + API half; the UI half is
Task 13).

**Tests to write:**
- `tests/test_findings.py` —
  `test_same_fingerprint_updates_last_seen_not_a_second_row`;
  `test_accept_risk_requires_a_reason`;
  `test_accepted_risk_resurfaces_when_fingerprint_changes`;
  `test_ack_is_not_resolve`;
  `test_every_transition_writes_an_audit_event`;
  `test_finding_copy_carries_what_why_and_exact_fix`
  (the §6.6 three-part shape is a field contract, not prose discipline).
- `tests/test_findings_api.py` —
  `test_list_requires_session`;
  `test_transition_endpoint_validates_through_serializer`;
  `test_findings_topic_requires_authorize_topic`;
  `test_transition_publishes_to_findings_topic`.

**Dependencies:** Task 0.

---

## Task 5 — The alert rules table (§2) and `classify()` (D-037)

**Title:** An unclassified alert cannot ship, because the function raises.

**Files created/touched:**
- `monitor/alert_rules.py` (**new, sensitive**) — one table transcribed clause
  by clause from alert-protocol.md §2, each row
  `{kind, severity, condition_text, source_clause}` including every review3
  §O1 row (feed data-stale = P2 and never a restart trigger, warm-up budget =
  P2 escalating to P1 only when no ready instance serves, scheduled-job failure
  = P2 with consecutive-failure hysteresis, partner-tier defaults, intake
  unreachable, cron stale, cert thresholds per V9). `classify(kind, **facts)`
  returns the severity or raises `UnclassifiedAlert`.
- `monitor/alerts.py` — `raise_alert(kind, entity, **facts)`: classify →
  fingerprint → `finding()` → hand to the anti-noise engine (Task 6).
- `core/findings.py` — severity vocabulary shared, not re-spelled.

**Exact req ids proven:** ALERT-P1-ROWS.

**Tests to write:**
- `tests/test_alert_rules.py` —
  `test_every_p1_row_of_the_protocol_has_a_rule`
  (parse `docs/plan/alert-protocol.md` §2 bullets; each maps to exactly one
  table row — the transcription cannot silently drift);
  `test_every_rule_names_its_protocol_clause`;
  `test_unknown_kind_raises_unclassified_alert`;
  `test_no_kind_maps_to_two_severities`;
  `test_staleness_is_p2_and_never_a_restart_trigger`
  (ties to the existing ALERT-N3 test);
  `test_warmup_escalates_to_p1_only_without_a_ready_instance`;
  `test_every_emitted_kind_in_the_codebase_is_registered`
  (AST scan for `raise_alert(` literals).

**Dependencies:** Task 4.

---

## Task 6 — The anti-noise engine (§4) (D-038)

**Title:** Hysteresis, flap collapse, root-cause suppression, ack, storm breaker.

**Files created/touched:**
- `core/models.py` + migrations — `AlertState` per design note §2.
- `monitor/antinoise.py` — pure functions over `AlertState` + `UptimeEvent`:
  `observe(fingerprint, ok: bool)` (open after 3 consecutive failures, close
  after 2 consecutive successes); `flap_check` (≥3 open/close cycles in 30 min
  → one P2 `FLAPPING`, suppress individual transitions until 30 min stable);
  `suppressed_by(entity)` (host-down suppresses its sites, zone-down its hosts;
  the surviving alert carries the suppressed list); `storm_breaker(now)`
  (>10 pushes/10 min → one P1 `ALERT STORM (n)` + 10-min summaries until the
  rate drops); `recovery_notice(finding)` on close.
- `monitor/alerts.py` — wire the engine between `classify` and delivery.

**Exact req ids proven:** ALERT-ANTINOISE-HYSTERESIS; ALERT-RECOVERY-NOTICE.

**Tests to write:**
- `tests/test_antinoise.py` —
  `test_two_failures_do_not_open`;
  `test_third_consecutive_failure_opens`;
  `test_one_success_does_not_close`;
  `test_two_consecutive_successes_close_and_send_recovery`;
  `test_three_cycles_in_thirty_minutes_collapse_to_one_flapping_p2`;
  `test_host_down_suppresses_its_sites_and_names_them`;
  `test_zone_down_suppresses_its_hosts`;
  `test_ack_stops_repeats_but_keeps_the_finding_open`;
  `test_unacked_p1_repeats_hourly_and_emails_unacked_at_24h`;
  `test_eleventh_push_in_ten_minutes_becomes_one_storm_alert`;
  `test_storm_mode_exits_when_the_rate_drops`;
  `test_p1_ignores_quiet_hours`.

**Dependencies:** Task 5.

---

## Task 7 — Pager seam + ntfy delivery (D-036, M3)

**Title:** The pager is authenticated, minimized, scrubbed — and fake by default in tests.

**Files created/touched:**
- `providers/base.py` (sensitive) — `Pager.publish(severity, title, body, *,
  tags, click_url)`.
- `providers/ntfy.py` (**new, sensitive**) — one HTTPS publish with
  `Authorization: Bearer <per-server token>`; topic and token resolved from the
  vault by ref; refuses to publish with a bare topic and no token (the
  `server-watch.sh` rule, applied Hub-side).
- `providers/fakes.py` — `FakePager` recording publishes; the default in
  settings for dev/test so no test can page anyone.
- `monitor/pager.py` (**new, sensitive**) — `deliver(finding)`: build the
  minimized push body (object · severity · duration · deep link; host aliases,
  never raw IPs), run it through the scrubber, write `AlertDelivery`, and send
  the email copy which alone carries the break-glass block prefixed
  **"advisory only — re-read from the Findings inbox before typing"**.
- `scripts_dev/scrub.py` (extracted from `scripts_dev/file_nightly_failure.py`)
  — one scrubber, now used by both the nightly bundle and the pager; extend it
  past the single high-entropy class (2.5 re-review minor) to cover bearer
  headers, `ntfy.sh/<topic>` URLs and vault refs.
- `provision/service.py` + `catalog/entries.py` (sensitive) — when Hub-side
  probing goes live for a target, remove that host's `server-watch.sh` cron
  entry (review3 §Q8: no double execution, no double paging); catalog entry
  version bump, never a silent mutation.
- `hub/settings/base.py` — `HUB_PAGER_BACKEND` (default fake), vault refs for
  topics/tokens.

**Exact req ids proven:** ALERT-M3-PAGER-AUTH.

**Tests to write:**
- `tests/test_pager.py` —
  `test_publish_without_a_token_is_refused`;
  `test_topic_and_token_come_from_the_vault_not_settings_literals`;
  `test_push_body_has_no_raw_ip_no_secret_no_break_glass_command`;
  `test_email_copy_carries_break_glass_marked_advisory_only`;
  `test_delivery_row_written_for_every_send_including_failures`;
  `test_default_backend_in_tests_is_the_fake`;
  `test_p1_email_copy_is_sent_even_when_push_fails`.
- `tests/test_scrubber.py` (extend) —
  `test_bearer_header_is_redacted`;
  `test_ntfy_topic_url_is_redacted`;
  `test_multiple_token_classes_in_one_line`.
- `tests/test_server_watch_handoff.py` —
  `test_cron_entry_removed_when_hub_probing_goes_live`;
  `test_catalog_entry_version_bumped_not_mutated`.

**Dependencies:** Task 6.

---

## Task 8 — Dead-man, canary, and `UptimeEvent` (§5, §O3)

**Title:** The heartbeat proves a completed cycle; the canary stops N false pages.

**Files created/touched:**
- `core/models.py` + migrations — `UptimeEvent(entity_type, entity_id, kind,
  state, at, detail)`.
- `monitor/uptime.py` — `probe_cycle()`: probe each site (HTTP for public,
  mesh probe for `mesh_only`), record `UptimeEvent` transitions, feed
  `observe()` from Task 6. ws-class sites use last-tick age + connection count
  from the `/healthz` payload the collector already fetches (§O3), not request
  lines.
- `monitor/deadman.py` — `ping()` fired **only** after a cycle completes every
  target (§C7); `canary_ok()` probes a known-good external endpoint;
  `declare_mass_outage(candidates)` returns either N site alerts or one
  "Hub egress degraded" P2 when the canary fails.
- `monitor/tasks.py` + `hub/settings/base.py` — Beat `probe-uptime` (60 s);
  the dead-man URL is a vault ref.

**Exact req ids proven:** MON-DEADMAN-EXTERNAL (now `verify: test`);
MON-UPTIME-EVENTS.

**Tests to write:**
- `tests/test_deadman.py` —
  `test_ping_only_after_every_target_completed`;
  `test_partial_cycle_does_not_ping`;
  `test_exception_mid_cycle_does_not_ping`;
  `test_deadman_url_is_a_vault_ref_not_a_settings_literal`.
- `tests/test_canary.py` —
  `test_canary_failure_collapses_n_site_alerts_to_one_p2`;
  `test_canary_success_lets_real_site_alerts_through`;
  `test_canary_is_probed_before_the_declaration_not_after`.
- `tests/test_uptime_events.py` —
  `test_transition_writes_one_event_not_one_per_probe`;
  `test_mesh_only_site_is_probed_over_the_mesh_path`;
  `test_ws_site_card_metric_is_last_tick_age_and_connections`;
  `test_probe_cycle_records_zero_mutating_transport_calls`.

**Dependencies:** Task 0 (models) — engine wiring needs Task 6, so land the
engine call behind the same import Task 6 creates.

---

## Task 9 — Drills stop lying (D-042; retires 2.5 I5 / M1 / M2)

**Title:** A real prober, real `due_at` rows, an honest restore stub, a pager drill.

**Files created/touched:**
- `monitor/drills.py` (sensitive) — `run_hub_down_drill` takes a **real**
  default `site_prober` built from a live Site + target (external HTTP GET,
  not a Hub-internal call); passing no prober in prod stops meaning "SKIPPED
  forever" (I5). `run_restore_clean_drill` writes `SKIPPED` with the deferred
  reason, not `SUCCEEDED` (M1). New `run_pager_drill()` — synthetic P1 through
  the real delivery path to the test topic, `CheckRun(kind=pager)`, failure to
  deliver is itself P1 via the email copy (§7).
- `monitor/tasks.py` + `hub/settings/base.py` — each drill Beat job first
  writes/refreshes a `scheduled` `CheckRun` with `due_at` for its next period,
  so `find_missed` has rows to find in prod (M2); add
  `drill-pager-monthly`; `scripts_dev/run_nightly.sh` invokes the hub-down
  drill so nightly exercises a drill body rather than only its tests.
- `WAIVERS.md` — **keep** `REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven`;
  amend the line only to record that the prober is now real and the 24 h form
  is a dated calendar item (D-042).

**Exact req ids proven:** ALERT-PAGER-DRILL; REL-P2-DRILL-STUB (kept honest);
HARNESS-DRILLS-BEAT (bodies still green).

**Tests to write:**
- `tests/test_drills.py` (extend) —
  `test_hub_down_uses_a_real_external_prober_by_default`;
  `test_absent_prober_is_a_configuration_error_not_a_silent_skip`;
  `test_restore_stub_status_is_skipped_not_succeeded`;
  `test_beat_seeds_due_at_for_every_drill_kind`;
  `test_find_missed_fires_on_a_seeded_overdue_row`;
  `test_pager_drill_delivers_a_synthetic_p1_and_writes_a_checkrun`;
  `test_missed_pager_drill_alerts_like_a_down_site`;
  `test_hub_down_still_refuses_to_claim_24h`.
- `tests/test_nightly_runs_a_drill.py` —
  `test_run_nightly_invokes_the_hub_down_drill_body`.

**Dependencies:** Task 7 (pager), Task 8 (prober shares the probe helper).

---

## Task 10 — Log backpressure + traffic ingest (§C4)

**Title:** A bounded pull, a sampled degrade, minute rows the dashboard reads.

**Files created/touched:**
- `catalog/entries.py` + `catalog/files/` (sensitive) — Caddy's native roller
  (`roll_size 100MiB`, `roll_keep 5`) as a versioned entry; logrotate stays as
  the backstop; version bump + rollback command per §D8.
- `monitor/collect_once.py` — per-pull byte cap; over the cap the on-host
  one-liner aggregates counts by status and top IPs and returns
  `{"sampled": true, "summary": {...}}` instead of raw lines. Offsets still
  advance by inode + offset exactly once.
- `monitor/traffic.py` — parse the chunk (or ingest the summary) into minute
  `TrafficStat` rows; `sampled` is carried through, never dropped; re-ingesting
  the same offset is a no-op.
- `core/models.py` + migrations — `TrafficStat`.
- `realtime/authorize.py` (sensitive) + `realtime/publish.py` — `site.{id}.traffic`
  and `host.{id}.metrics` topics.

**Exact req ids proven:** MON-C4-LOG-BACKPRESSURE; MON-TRAFFIC-INGEST.

**Tests to write:**
- `tests/test_log_backpressure.py` —
  `test_pull_never_exceeds_the_byte_cap`;
  `test_over_cap_pull_returns_a_sampled_summary`;
  `test_sampled_flag_survives_into_trafficstat`;
  `test_offset_advances_once_and_reingest_is_a_noop`;
  `test_rotated_inode_resets_offset_without_losing_the_new_file`;
  `test_catalog_rotation_entry_has_check_fix_rollback_and_version`.
- `tests/test_traffic_ingest.py` —
  `test_minute_rows_aggregate_status_counts`;
  `test_malformed_log_line_is_counted_not_fatal`;
  `test_ingest_publishes_to_the_site_traffic_topic`.

**Dependencies:** Task 0.

---

## Task 11 — Retention janitor (§C7) — **may slip (D-044)**

**Title:** The pinned numbers, as one nightly batched delete.

**Files created/touched:**
- `monitor/retention.py` — plain batched `DELETE`s on the §C7 numbers
  (HostMetric raw 14 d / hourly rollup 1 y · UptimeEvent 90 d + daily rollup
  kept · TrafficStat minute 48 h / hour 90 d / day forever · deploy logs
  gzipped after 30 d · AuditEvent forever). No partitioning, no TimescaleDB.
- `monitor/tasks.py` + `hub/settings/base.py` — Beat `retention-janitor-nightly`.

**Exact req ids proven:** MON-C7-RETENTION. Slipping leaves an honest waiver
naming disk growth as accepted for the phase.

**Tests to write:**
- `tests/test_retention.py` —
  `test_each_table_uses_its_pinned_horizon`;
  `test_auditevent_is_never_deleted`;
  `test_rollup_rows_survive_raw_deletion`;
  `test_janitor_is_batched_and_idempotent`.

**Dependencies:** Task 10. **Not on the MUST line.**

---

## Task 12 — Frontend shell: IA/nav, degraded polling, action tiers (§F1, §3.5, §F5)

**Title:** The daily-driver frame — and rollback stays one click.

**Files created/touched:**
- `frontend/src/App.jsx` — object-centric nav: Home, Sites, Targets, Deploys,
  Findings, Settings (Vault is a Settings tab until Phase 4). The demo pane
  becomes a Settings/Developer tab, not the product surface.
- `frontend/src/screens/{Home,Sites,Targets,Deploys,Settings}.jsx` (new) —
  each with the designed empty state (one sentence + the single button that
  populates it) and loading / live / error / degraded states.
- `frontend/src/useEvents.js` — a `degraded` status: when the socket is
  unavailable, poll each subscribed topic's REST snapshot every 10 s, render a
  visible pill naming the mode and the "data as of HH:MM:SS" stamp; resume
  snapshot-then-stream on reconnect (never silently stale).
- `frontend/src/actions.js` (new) + `core/actions.py` (new) — ONE action-tier
  table (T1 / T2 / T3 per §F5) shared by server and client through the
  generated schema: T2 renders a confirm dialog containing the diff summary;
  T3 (rollback, restart, re-run check) is one click + undo toast and carries no
  step-up requirement; T1 requires type-the-name + `require_recent_touch`
  (TOTP today — the hardware clause is Phase 4, D-040).
- `frontend/src/api/` — regenerate.

**Exact req ids proven:** UX-F1-IA-NAV; RT-35-DEGRADED-POLLING;
UX-F5-ACTION-TIERS (T2/T3 clauses; the T1 hardware clause is waived and carried
by `SEC-F5-T1-HARDWARE-TOUCH` at phase 4).

**Tests to write:**
- `frontend/tests/nav.test.ts` —
  `advisors_are_tabs_not_top_level_pages`;
  `every_list_screen_has_an_empty_state`.
- `frontend/tests/degraded.test.ts` —
  `socket_failure_switches_to_ten_second_polling`;
  `degraded_mode_is_visible_not_silent`;
  `reconnect_resnapshots_before_streaming`.
- `tests/test_action_tiers.py` —
  `test_rollback_and_restart_are_t3`;
  `test_no_t3_action_requires_step_up`;
  `test_deploy_and_dns_change_are_t2_with_a_diff_body`;
  `test_target_delete_and_key_export_are_t1`;
  `test_client_and_server_tier_tables_are_one_source`
  (the generated mirror is not a hand-written second copy);
  `test_t1_hardware_clause_is_waived_and_registered_at_phase_4`.

**Dependencies:** Task 0. Runs parallel with the backend waves.

---

## Task 13 — Findings inbox UI, deploy-failure impact, simulation states (§F2, §F4, §F8)

**Title:** Retires the UX-F8 demo-pane waiver by rendering the states.

**Files created/touched:**
- `frontend/src/screens/Findings.jsx` (new) — the inbox: filters, severity
  chips (icon + label, never colour alone), ack / snooze / accept-risk (reason
  required, grey chip), the §6.6 what / why / exact-fix layout.
- `deploys/failure_impact.py` (new) — the §F4 partial-states table: failed step
  → impact line ("Old version still serving — site unaffected" vs "Site may be
  unreachable"), including the N1 recreate rows. The alert body and the UI read
  the **same** table.
- `frontend/src/screens/Deploys.jsx` — 9-step vertical stepper; on failure the
  banner leads with the impact line and offers at most three actions (Retry
  from step N / Roll back / Abort & clean up), each naming what it will do.
- `simulation/seed_v1.json` + `realtime/simulation.py` + `frontend/src/sim.js`
  — seed and scripted events for every new state: finding severities and each
  finding state, degraded polling, deploy failure at a named step (both
  strategies), warming with elapsed/expected copy, data-stale badge,
  single-instance, cert-expiring, alert-storm, host-down suppression, map
  empty/populated.
- `WAIVERS.md` — retire
  `frontend/src/App.jsx+UX-F8-SIMULATION-STATES+demo-pane-no-site-deploy-topics`
  and `simulation/seed_v0.json+review3-N2+warming-omits-elapsed-expected`
  **only** once the named tests render those states.

**Exact req ids proven:** UX-F2-FINDING-MODEL (UI half); UX-F4-FAILURE-IMPACT;
UX-F8-SIMULATION-STATES (waiver retired).

**Tests to write:**
- `frontend/tests/findings.test.ts` —
  `accept_risk_requires_a_reason`;
  `severity_is_never_colour_only`;
  `ack_does_not_remove_the_finding_from_the_inbox`.
- `frontend/tests/simulation-states.test.ts` —
  `every_new_state_renders_in_simulation_mode`
  (enumerate the seed's states; a state with no rendering assertion fails).
- `tests/test_failure_impact.py` —
  `test_every_step_has_an_impact_line`;
  `test_recreate_strategy_says_site_is_down_not_old_version_serving`;
  `test_alert_body_and_ui_read_the_same_table`;
  `test_failure_offers_at_most_three_actions`.

**Dependencies:** Task 4, Task 12.

---

## Task 14 — Map v1 (§9.6.1, D-041)

**Title:** Zones → hosts → containers, dependency-free, with a list-view toggle.

**Files created/touched:**
- `monitor/map_graph.py` — `graph_snapshot()` → `{nodes: [zone|host|container|
  hub|edge], edges: [{a, b, path ∈ {public, mesh}}], seq}` built from models,
  never from JSON blobs (§D3).
- `monitor/views.py` + `monitor/urls.py` — `{seq, data}` snapshot endpoint per
  §D7; `realtime/authorize.py` (sensitive) appends `map.graph`; publish on
  graph change.
- `frontend/src/Map.jsx` (new) — plain SVG: nested zone groups, solid public /
  dashed mesh edges, status by icon+label, container count chips when a host
  exceeds N children, and a list-view toggle that shows the same data.
- `frontend/src/screens/Home.jsx` — map + fleet cards as one composite screen.

**Exact req ids proven:** MAP-96-GRAPH-V1.

**Tests to write:**
- `tests/test_map_graph.py` —
  `test_graph_is_derived_from_models_not_a_stored_blob`;
  `test_hub_is_a_distinct_node`;
  `test_mesh_paths_are_marked_mesh_and_public_public`;
  `test_snapshot_returns_seq_and_data`;
  `test_thirty_node_fleet_renders_within_the_snapshot_contract`.
- `frontend/tests/map.test.ts` —
  `list_view_toggle_shows_the_same_nodes`;
  `status_is_icon_plus_label_not_colour`;
  `empty_fleet_shows_the_onboarding_hint`.

**Dependencies:** Task 12 (shell), Task 10 (host metrics feed the colours; the
map degrades to structure-only without it).

---

## Task 15 — Adopt-existing-site, compose-aware (§E6, J7 finding 3)

**Title:** Read the compose stack, propose a plan, never flip DNS before verifying.

**Files created/touched:**
- `provision/adopt.py` (**new, sensitive**) — `read_compose(path)` parses
  `docker-compose*.yml` with `yaml.safe_load` and **executes nothing** (M1);
  `classify_services()` → web / worker / beat-scheduler / one-shot migrate /
  db / cache / site-owned edge; `adoption_plan(project)` emits Findings (what /
  why / exact fix) plus one V5-shaped manifest proposal (one service container
  + optional static + optional jobs) and a volumes list (N6). Site-owned Caddy
  vs host Caddy is a **decision surfaced to the operator**, never auto-taken.
- `provision/service.py` — the E6 fresh-host guard learns "occupied by a stack
  we can adopt" and points at the plan instead of only refusing.
- `deploys/adopt_flow.py` — temp-subdomain deploy → verify (HTTP 200 + the
  site's own healthz contract) → DNS flip through `dns_provider_for` → old path
  decommission; each stage is idempotent and the flip **refuses** unless the
  verify stage recorded success for the current image tag.
- `tests/fixtures/compose/` — three fixture stacks from the §J7 inventory
  shapes: web+worker+beat+one-shot-migrate; web+site-owned-Caddy; web only.

**Exact req ids proven:** PROV-J7-COMPOSE-AWARE-ADOPT (now `verify: test`);
PROV-E6-ADOPT-TEMP-SUBDOMAIN.

**Tests to write:**
- `tests/test_adopt_compose.py` —
  `test_worker_beat_and_oneshot_migrate_are_classified`;
  `test_site_owned_edge_container_is_surfaced_as_a_decision`;
  `test_named_volumes_appear_in_the_plan`;
  `test_parser_executes_nothing`
  (no `subprocess`, no `docker compose config`, no import of project code);
  `test_single_container_stack_still_produces_one_manifest`;
  `test_plan_findings_carry_what_why_and_fix`.
- `tests/test_adopt_flow.py` —
  `test_dns_flip_refuses_before_verification`;
  `test_verified_flip_upserts_then_decommissions`;
  `test_flow_run_twice_records_zero_mutating_calls`;
  `test_decommission_never_touches_a_registered_volume_without_confirmation`.

**Dependencies:** Task 1 (DNS), Task 3 (certs on the temp subdomain), Task 12
(the plan needs a screen; a CLI-only plan is acceptable if 12 slips).

---

## Task 16 — Break-glass runbook gains impact and real DNS copy (§P5, §F4)

**Title:** Retires the SEC-P5 waiver the Phase 2 round left for this phase.

**Files created/touched:**
- `deploys/breakglass.py` — the runbook gains: the impact line for the current
  state (from `deploys/failure_impact.py`), the exact DNS commands now that a
  real adapter exists (**Hub-side** commands only — the runbook must not tell
  the operator to run a token-bearing command on the target), the alert-protocol
  §3 advisory-only note, and the site's cert mode + expiry. Still `0400`, still
  no secrets.
- `WAIVERS.md` — retire
  `deploys/breakglass.py+SEC-P5+runbook-lacks-impact-and-dns` once the named
  tests pass.

**Exact req ids proven:** SEC-P5-BREAK-GLASS (waiver retired).

**Tests to write:**
- `tests/test_breakglass.py` (extend) —
  `test_runbook_states_impact_before_commands`;
  `test_dns_section_names_hub_side_commands_only`;
  `test_runbook_contains_no_token_and_no_secret`;
  `test_runbook_is_0400_and_root_owned`;
  `test_advisory_only_note_present`.

**Dependencies:** Task 3 (cert fields), Task 13 (`failure_impact` table). The
impact half may land ahead of Task 13 only by importing the same module.

---

## Task 17 — Live Cloudflare / LE leg, credential-gated (D-043) — body **may slip**

**Title:** Skip is not a green, and the waiver refuses itself once the token exists.

**Files created/touched:**
- `tests/harness/cf_zone.py` (sensitive: `tests/harness/**`) — a session
  fixture that allowlists the configured test `DnsZone`, drives the **product**
  adapter (D-034), and reaps every record it created in `finally`.
- `tests/test_t3_cf_live.py` — `@pytest.mark.t3` + host gate: upsert A proxied
  → list → resolve → Origin cert issued and pushed → HTTPS 200 + security
  headers → `wss://` one frame through CF+Caddy for ws sites → delete → assert
  the zone is clean.
- `tests/harness/multipass.py` / `monitor/reaper.py` (sensitive) —
  `waiver_illegal_if(credentials_present)` extended so the
  `HARNESS-T3-LE-STAGING` waiver is **self-refusing** the moment
  `HUB_TEST_CF_TOKEN` + `HUB_TEST_DNS_ZONE` are set (2.5 finding M4). **This
  half is MUST even when the credentialed body slips.**
- `WAIVERS.md` — keep `HARNESS-T3-LE-STAGING+no-test-zone-credentials` and add
  `DNS-CF-T3-LIVE+no-test-zone-credentials` while the token is absent; retire
  both on the first credentialed green run, in the same change that records the
  run under `conformance/demos/phase-3/`.

**Exact req ids proven:** DNS-CF-T3-LIVE (`tier: t3`); HARNESS-T3-LE-STAGING
(retired only with credentials).

**Tests to write:**
- `tests/test_le_waiver_self_refusal.py` (T1, always runs) —
  `test_le_waiver_is_red_when_credentials_are_present`;
  `test_le_waiver_is_allowed_when_credentials_are_absent`;
  `test_cf_live_waiver_follows_the_same_probe`.
- `tests/test_t3_cf_live.py` (T3) —
  `test_product_adapter_upserts_and_deletes_in_the_test_zone`;
  `test_origin_cert_serves_https_with_security_headers`;
  `test_records_reaped_in_finally`;
  `test_no_prod_zone_is_reachable_from_this_run`.

**Dependencies:** Task 1, Task 3. Requires Joseph's test-zone token; absent it,
the T3 body is skipped-only and only the probe half lands.

---

## Task 18 — Seam hygiene: 2.5 parked I2 and I4 — **may slip (D-044)**

**Title:** A product module stops importing from `tests/`; one Multipass driver.

**Files created/touched:**
- `deploys/worker_entry.py` — drop the `sys.path` insert into `tests/`; the
  fake transport used by `--fake` moves to `providers/fakes.py` (or
  `deploys/testing.py`), so a product entry point no longer depends on the test
  tree. Keep the `HUB_TEST_DATABASE` rebind but gate it on `HUB_TEST_MODE` so a
  prod worker cannot be repointed by an env var.
- `tests/harness/multipass.py` (sensitive) — becomes a thin wrapper over
  `monitor/reaper.py`'s argv builders; the duplicated driver goes (I4).
- `providers/test_dns.py` (sensitive) — retire in favour of the product adapter
  once Task 17's live leg is green (D-034); otherwise leave it and record why.

**Exact req ids proven:** none new; ARCH-D4-IMPORT-RULE and the existing
harness reqs must stay green.

**Tests to write:**
- `tests/test_worker_entry.py` —
  `test_worker_entry_does_not_import_from_tests`;
  `test_database_rebind_requires_test_mode`;
  `test_fake_child_still_completes_a_deployment`.
- `tests/test_harness_driver_single_source.py` —
  `test_multipass_argv_has_one_definition`.

**Dependencies:** none (file sets disjoint from every other task). **Not on the
MUST line.**

---

## Task 19 — Acceptance, demo record, phase gate

**Title:** `make conformance-3` can go green honestly.

**Files created/touched:**
- `tests/acceptance/test_phase_3.py` — one test per milestone clause,
  `@pytest.mark.acceptance(phase=3)` + `@pytest.mark.req(...)`. T1 clauses run
  in `review-round`; live clauses carry their tier marker and host gate.
- `conformance/demos/phase-3.md` + `conformance/demos/phase-3/` — the live run
  transcript with real nodeids (Multipass + Cloudflare test zone if the token
  exists), the pager transcript (fake or test topic), the adopt-flow record,
  the map screenshot/list dump, and the dated 24 h REL-P2 calendar item.
- `conformance/requirements.yaml` (sensitive) — `P3-DNS-MONITOR-DEMO` `demo:`
  paths only; no new ids here.
- `WAIVERS.md` — file **only** what is true: the UX-F5 hardware clause
  (pointing at `SEC-F5-T1-HARDWARE-TOUCH`, phase 4); LE/CF credential lines if
  Task 17 slipped; retention if Task 11 slipped; **keep** REL-P2 24 h and the
  D-025 alpine line; retire UX-F8 and SEC-P5 only if Tasks 13 and 16 landed.
- `docs/plan/deploy-system-plan.md` / `plan-addendum-2026-07-30.md` — Scribe
  amends the §I Phase-3 line for the D-032 split (Phase 3b) at exit, in its own
  change.

**Exact req ids proven:** P3-DNS-MONITOR-DEMO; every MUST id via acceptance
transcription or an honest waiver.

**Tests to write:**
- `tests/acceptance/test_phase_3.py` —
  `test_product_adapter_is_the_only_cloudflare_client_path`;
  `test_no_dns_token_reaches_a_target`;
  `test_token_scope_audit_files_a_finding_on_excess`;
  `test_origin_cert_pushed_and_caddy_serves_it`;
  `test_unclassified_alert_kind_cannot_ship`;
  `test_three_failures_open_one_p1_and_two_successes_close_it`;
  `test_host_down_suppression_collapses_site_alerts`;
  `test_push_body_is_minimized_and_scrubbed`;
  `test_deadman_pings_only_after_a_completed_cycle`;
  `test_log_pull_is_capped_and_degrades_sampled`;
  `test_findings_inbox_requires_a_reason_to_accept_risk`;
  `test_rollback_is_one_click_and_never_step_up_gated`;
  `test_ws_unavailable_degrades_to_visible_polling`;
  `test_map_v1_snapshot_and_list_view`;
  `test_adopt_plan_is_compose_aware_and_flip_refuses_before_verify`;
  `test_breakglass_has_impact_and_hub_side_dns`;
  `test_rel_p2_24h_still_not_claimed`.

**Dependencies:** Tasks 0–10, 12–16 (MUST line). Tasks 11, 17, 18 as needed for
a waiver-free `conformance-3`; if the cut is taken, this task files the waiver
lines instead of pretending those ids shipped.

---

## Deferred out of Phase 3 (with reasons)

| Item | Reason | Retirement condition |
|---|---|---|
| App-log viewer (§E3) | Roadmap-Phase-3 by the 07-30 line, but the brief's binding scope is DNS/monitoring/map/UX; a live `docker logs --follow` topic is its own surface with its own authz story. No registry id exists, so the gate is unaffected (D-032). | Phase 3b task with a `site.{id}.applog` topic + authorize_topic row. |
| Scheduled-jobs UI (§E8) + `jobs_image` (§N7) | Arbitrary-command-execution surface that review3 §V3 puts behind T2/T1 friction — it needs the action-tier table (Task 12) to exist first, and the partner prohibition test. Cheaper and safer as the first Phase 3b task. | Phase 3b, after UX-F5 tiers are green. |
| First-run checklist (§F3) | Depends on the Cloudflare connect flow *and* the `mesh_only` skip path; the IA lands this phase, the onboarding flow reads better once real screens exist. | Phase 3b. |
| Backup/restore operator surface (§E5/§N6) and the real restore-drill body | The restore drill needs the backup registry to exist; Phase 3 keeps the stub honest (`SKIPPED`) rather than shipping half a restore. | Phase 4, with §B3 audit shipping. |
| Hub-central DNS-01 for unproxied sites | D-035: the alternative (Caddy DNS-01) puts a zone token on every target, which is the exact SEC-B2 violation. A named refusal is the honest interim. | Phase 3b, Hub-side ACME client + push. |
| Attack playbook / `EdgeProtection` implementation | Phase 4 security suite; Phase 3 models and audits the `edge` token so the scoping check is real today. | Phase 4. |
| WebAuthn hardware touch for T1 actions | Needs `django-otp-webauthn` (Phase 4). Carried by `SEC-F5-T1-HARDWARE-TOUCH` + a named waiver so it cannot be forgotten (D-040). | Phase 4. |
| REL-P2 24 h live Hub-down | A 24 h wall-clock drill cannot sit inside a 1–2 week phase's review loop; Phase 3 makes the drill real at the §G 30-min form and schedules the 24 h run as a dated calendar item. | A dated 24 h record (D-042). |
| D-025 alpine T2 fixture image (PIPE-S4) | Environmental (vfs overlay-on-overlay, D-015); nothing in Phase 3 changes it and inventing a green would be the defect the waiver records. | A runner with nested overlay2, or registry-pulled images. |
| 2.5 minors not scheduled: `find_missed` AST-shape gaps, `waiver_illegal_if` bool latch, vacuous reaper prefix assertion, tautological waiver-linkage assert, unpinned guest Caddy tarball, `tmp/` artifact accumulation | Test-quality nits with no product consequence this phase; they do not gate any phase-3 id. | A cleanup pass at Phase 4 entry, or the round that touches the file. |
