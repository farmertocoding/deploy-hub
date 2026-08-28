# Phase 3 tasks — DNS automation + monitoring + map v1

SDD-ready work list for Implementers. Architect design note:
`docs/phase-3-design-note.md` (**r2**, amended under the panel's unanimous
APPROVE-WITH-CHANGES). Do not start a task whose dependencies are open. Do not
start implementation from this design session.

**Branch:** cut task branches from `phase-3` (which carries these two docs).
Never implement on `master`. Sensitive-path merges to `master` go through the
recorded expert-panel vote — the Phase 2.5 precedent — not a silent auto-merge;
still name the sensitive files per task so the panel knows what it is voting on.

## Global constraints (every task)

- Every remote effect on a target goes through `Transport`; argv lists, never
  interpolated strings; file content via `put()`, never heredocs.
- Cloudflare / cloud / ntfy HTTP clients live **only** under `providers/`
  (`tests/test_import_rule.py` enforces it). `deploys/` receives a provider and
  a `DnsZone` in `desired`; it never constructs or imports one, and never
  reaches `scanner/`.
- Secrets through the vault. Prod DNS tokens **never** on a target (SEC-B2) and
  scoped per zone, enforced **synchronously at client construction** (SEC-B5).
  ntfy publish tokens and topic names are vault secrets (M3). No secret in
  logs, task args, build contexts, deployment artifacts, or push bodies.
- **Pinned env names** (design note §2): `HUB_TEST_ZONE_SLUGS` is the one
  allowlist (it names `DnsZone.name` values as well as `NetworkZone.slug`s);
  `HUB_TEST_DNS_ZONE` is retired; `HUB_TEST_CF_TOKEN` stays the test-plane
  token env. Test-plane construction is triple-keyed: `HUB_TEST_MODE` **and**
  `purpose == test` **and** the name on `HUB_TEST_ZONE_SLUGS`.
- **One schema wave.** Every phase-3 model change lands in **Task 1**'s single
  migration. A later task that discovers it needs one rebases in the order
  T1 → T3 → T4 → T6 → T8 → T10 and says so in its report.
- **`findings` is the canonical realtime topic** (D-045); `alerts` stays a
  deprecated alias for one phase with a test asserting identical payloads.
- Every new step/repair is `ensure_X(desired)` — probe, act on diff — and every
  playbook runs twice in tests with **zero mutating Transport calls** the second
  time (§D6).
- New alert classes: a row in `monitor/alert_rules.py` first, or `classify()`
  raises. No per-alert channel choice; alert-protocol §2 is the authority, and
  every delivery behaviour it names has a module **and** a Beat entry.
- **Clause-scoped ids (SCAN-M4 precedent).** `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`
  and `UX-F5-ACTION-TIERS` carry **no `@pytest.mark.req`** this phase; their
  tests run unmarked, the ids sit `uncovered`, and Task 19 files the
  clause-scoped waivers. The buildable clauses are proven through
  `SEC-B2-NO-TOKEN-ON-TARGET` and `UX-F5-T2-T3-FRICTION`; the unbuilt ones are
  registered at phase 4 (`TLS-B2-HUB-DNS01-UNPROXIED`,
  `SEC-F5-T1-HARDWARE-TOUCH`). A full-text marker on either id is a round
  finding, not a shortcut.
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

Protective cut (**D-044**, amended by the panel): MUST = Tasks 0–10, 12–14, 16,
19, plus Task 17's self-refusing-probe half. **Task 15 (adopt) is may-slip /
Phase 3b**; Tasks 11, 18 and Task 17's credentialed body may slip. **Task 14
(map v1) is MUST but the named first slip candidate** — cutting it means a
`MAP-96-GRAPH-V1` waiver at exit, and cutting Task 15 means a waiver or a phase
bump for `PROV-J7-COMPOSE-AWARE-ADOPT` + `PROV-E6-ADOPT-TEMP-SUBDOMAIN`
(the D-020 precedent). Say which at exit; do not let an id go quietly.

## Parallel waves, derived from the tasks' actual file sets

**Serialization points (one writer at a time, in this order):**

| Shared file | Order |
|---|---|
| `core/models.py` + `core/migrations/` | **Task 1 only.** Later discovery rebases T1 → T3 → T4 → T6 → T8 → T10 |
| `providers/cloudflare.py` | T1 → T2 → T3 |
| `providers/base.py` / `providers/fakes.py` | T1 → T3 → T7 |
| `realtime/authorize.py` + `realtime/publish.py` | T4 → T10 → T14 |
| `frontend/src/api/` (generated) | T4 → T12 → T13; regenerate after each merge, never hand-edit |
| `monitor/tasks.py` + `hub/settings/base.py` (Beat) | T2 → T3 → T7 → T8 → T9 → T11 |
| `monitor/alerts.py` | T5 → T6 → T7 |
| `deploys/steps.py` | T1 (dns zone arg) → T3 (cert substep) → T18 (`_ws_frame`) |
| `WAIVERS.md` | T9 → T13 → T16 → T17 → T19 |
| `catalog/entries.py` | T7 → T10 |

**Waves:**

- **Wave A (after Task 0):** **1** (schema wave + adapter) · **12a** (frontend
  shell, nav, degraded polling, action tiers — no backend model dependency) ·
  **18** (seam hygiene; file set disjoint from everything else).
- **Wave B (after 1):** **2** (verify + scope audit) · **4** (Finding model +
  API) · **8** (uptime/dead-man/canary) · **10** (backpressure + traffic).
- **Wave C:** **3** (certs; `providers/cloudflare.py` after 2) · **5** (rules
  table, after 4) · **12b** (Cloudflare-connect Settings, after 2) · **14**
  (map, after 4+10+12a for the topic and the shell).
- **Wave D:** **6** (anti-noise, after 5) · **13** (Findings UI + failure impact
  + simulation, after 4+12) · **11** (retention, after 10).
- **Wave E:** **7** (pager + delivery owners, after 6) · **16** (break-glass,
  after 3+13 — it reads `deploys/failure_impact.py` and the cert fields) ·
  **17** (live CF/LE, after 1+3).
- **Wave F:** **9** (drills, after 7+8) · **15** (adopt, may-slip, after 1+3+12).
- **Wave G:** **19** (acceptance, demo, gate).

Critical path: **0 → 1 → 4 → 5 → 6 → 7 → 9 → 19.** Tasks 12a, 18, 10, 8 and 14
are the parallel slack; if the phase runs long, Task 14 is cut first (D-044).

---

## Task 0 — Unblock `check.py --phase 3` (D-032, D-035, D-039, D-040)

**Title:** Registry additions and clause splits, phase-3 gate targets, t3-marker integrity, custody parity.

**Files created/touched:**
- `DECISIONS.md` — rows D-032…D-046 (text from design note §5).
- `conformance/requirements.yaml` (sensitive) — add the 20 ids in design note
  §3. `TLS-B2-HUB-DNS01-UNPROXIED` and `SEC-F5-T1-HARDWARE-TOUCH` are
  **`phase: 4`**; `DNS-CF-T3-LIVE` carries `tier: t3`;
  `TLS-B2-ORIGIN-CERT-PUSH` carries `tier: t2`; `P3-DNS-MONITOR-DEMO` is
  `verify: demo` with `demo: conformance/demos/phase-3.md` +
  `conformance/demos/phase-3/`. Flip `MON-DEADMAN-EXTERNAL` and
  `PROV-J7-COMPOSE-AWARE-ADOPT` from `verify: checklist` to `verify: test`
  (D-039) — do **not** touch their `text:` / `text_hash:`, and do not touch
  the `text:` of `SEC-B2-NO-DNS-TOKENS-ON-TARGETS` or `UX-F5-ACTION-TIERS`
  (their clause split is expressed by the new ids + Task 19's waivers, never by
  narrowing a hashed text).
- `conformance/check.py` (sensitive) — **I1 fix**: a test carrying
  `@pytest.mark.t3` must also be host-gated, and the gate must **derive from
  `multipass_available()`** — a `skipif` on any other condition (an env var, a
  bare `False`, a module constant) is red, as is a `t3` mark with no gate at
  all. Module-level `pytestmark` carrying the derived gate satisfies it.
- `Makefile` — `conformance` becomes
  `--phase 3 --exclude-tier t3 --exclude-tier t2`; add `conformance-3`
  (`--phase 3`, all tiers); `nightly-gates` uses `conformance-3` instead of
  `conformance-2.5`; delete `conformance-2.5` in the same change and update
  `tests/test_makefile_nightly.py`.
- `conformance/paths.yaml` + `.github/CODEOWNERS` — add `monitor/pager.py`,
  `monitor/alert_rules.py`, `deploys/certs.py`, `provision/adopt.py`. **Custody
  parity becomes two-way**: every CODEOWNERS entry under the repo's own trees
  must have a `paths.yaml` counterpart, not only the reverse (2.5 finding).

**Exact req ids proven:** none new go green here. This task makes the phase-3
due set exist and the `t3` marker honest; every other id is proven by its task.

**Tests to write:**
- `tests/test_conformance_gate.py` (extend) —
  `test_phase_3_due_set_includes_every_phase_3_id`;
  `test_phase_4_ids_are_not_due_at_phase_3`;
  `test_verify_test_conversion_requires_a_marked_test`;
  `test_self_declared_t3_mark_without_host_gate_is_red`;
  `test_t3_gate_not_derived_from_multipass_available_is_red`;
  `test_host_gated_t3_mark_is_accepted`.
- `tests/test_clause_split_ids.py` —
  `test_sec_b2_full_text_id_carries_no_marker`;
  `test_ux_f5_full_text_id_carries_no_marker`
  (AST scan of the suite: a marker on either id fails, so the SCAN-M4 shape
  cannot erode);
  `test_split_clause_ids_exist_and_name_their_phase`.
- `tests/test_makefile_nightly.py` (extend) —
  `test_review_round_conformance_is_phase_3_minus_live_tiers`;
  `test_nightly_gates_use_conformance_3`.
- `tests/test_proc_rules.py` (extend) —
  `test_codeowners_entries_all_appear_in_paths_yaml`;
  `test_phase_3_sensitive_modules_are_listed`.

**Dependencies:** none.

---

## Task 1 — Schema wave, `DnsAccount`/`DnsZone`, fail-closed product adapter (D-033, D-034, D-046)

**Title:** One migration, one zone identity, one Cloudflare client that refuses to exist over-scoped.

**Files created/touched:**
- `core/models.py` + **one** `core/migrations/00XX_phase3.py` — the whole
  phase-3 schema in a single wave (design note §2): `DnsAccount`, `DnsZone`
  (unique on `(provider, name)` through the account; `provider_zone_id`;
  `purpose`; `proxied_default`, documented in the field help text as a
  **Cloudflare capability** surfaced by `capabilities()`, not a
  provider-neutral setting), `TlsCertificate`, `Finding`, `AlertState`,
  `AlertDelivery`, `UptimeEvent`, `TrafficStat`; `Site.dns_zone` FK
  (**nullable only for `mesh_only`**, enforced by a `CheckConstraint` plus
  `Site.clean()`), `Site.proxied` (default `True`); `DnsRecord.zone` FK +
  `observed_value` + `last_verified`; `CheckRun.Kind` += `pager`,
  `cf_token_scope`, `cert_expiry`. Behaviour for these models lands in their
  own tasks; this task ships the fields, constraints and `__str__`s only.
- `providers/cloudflare.py` (sensitive) — `CloudflareDnsProvider(DnsProvider)`
  constructed only from a `DnsZone`. Bearer only: an `X-Auth-Key` /
  `X-Auth-Email` credential shape is refused before any request. Full §D5
  surface, `proxied` honoured, list pagination followed (2.5 minor). The token
  appears in the `Authorization` header and nowhere else — not in `repr`, logs,
  or exception text.
- `providers/registry.py` (sensitive) — `dns_provider_for(zone)`, the only
  construction path, performing **synchronous fail-closed enforcement** before
  returning a client: (a) `GET /client/v4/user/tokens/verify` →
  `success is True` and `result.status == "active"`; (b) zone-authorization
  probe `GET /client/v4/zones?per_page=50` → **exactly one** result whose `id`
  equals `zone.provider_zone_id`; more, fewer, or a mismatch refuses; (c)
  purpose wall — under `HUB_TEST_MODE` only a triple-keyed test zone, outside
  it never a `purpose=test` zone. The verified result is cached per
  (token_ref, zone) for a bounded TTL (default 15 min) and re-verified on
  expiry or on any auth error; a verification failure fails closed and files a
  Finding. See D-046 for why `verify` alone cannot establish scope.
- `core/test_mode.py` (sensitive) — accept a `DnsZone` as well as a
  `NetworkZone` against the single `HUB_TEST_ZONE_SLUGS` allowlist; retire the
  `HUB_TEST_DNS_ZONE` namespace. Existing `NetworkZone` behaviour and tests
  stay green.
- `providers/fakes.py` — `FakeDnsProvider` accepts a `DnsZone`, records calls.
- `deploys/pipeline.py` + `deploys/steps.py` — `desired["dns_zone"]` is
  resolved from **`Site.dns_zone`** (never `Site.primary_target.zone`, which is
  a `NetworkZone` and cannot produce a client); `ensure_dns` takes it and
  passes it to the injected provider.

**Exact req ids proven:** DNS-CF-PRODUCT-ADAPTER.

**Tests to write:**
- `tests/test_cloudflare_adapter.py` (T1, `urlopen` doubled) —
  `test_upsert_is_a_diff_not_a_blind_write`;
  `test_list_records_follows_pagination`;
  `test_token_never_appears_in_repr_logs_or_exceptions`;
  `test_delete_absent_record_is_success`;
  `test_capabilities_declares_proxied`.
- `tests/test_dns_zone_wall.py` —
  `test_global_api_key_header_shape_is_refused_before_any_request`;
  `test_inactive_token_refuses_construction`;
  `test_two_zone_probe_result_refuses_construction`
  (excess access is refused at construction, not reported tomorrow);
  `test_zone_id_mismatch_refuses_construction`;
  `test_verification_failure_fails_closed_and_files_a_finding`;
  `test_verified_scope_is_cached_and_reverified_after_ttl`;
  `test_test_mode_requires_all_three_keys`
  (`HUB_TEST_MODE` + `purpose=test` + allowlist — drop any one and it refuses);
  `test_prod_mode_refuses_test_purpose_zone`;
  `test_dns_provider_for_is_the_only_construction_path`
  (AST scan: no `CloudflareDnsProvider(` outside `providers/registry.py` and
  its own tests);
  `test_single_zone_allowlist_namespace`
  (`HUB_TEST_DNS_ZONE` authorizes nothing anywhere in the tree).
- `tests/test_site_dns_zone.py` —
  `test_public_site_without_dns_zone_is_refused_by_constraint`;
  `test_mesh_only_site_may_have_no_dns_zone`;
  `test_dns_zone_unique_per_provider_and_name`;
  `test_pipeline_passes_a_dnszone_not_a_networkzone`.
- `tests/test_pipeline_dns.py` (extend) —
  `test_ensure_dns_twice_records_zero_mutating_calls`.

**Dependencies:** Task 0.

---

## Task 2 — SEC-B5 token-scope audit (defense-in-depth behind Task 1's wall)

**Title:** The standing check, now that the edge token has a model home.

**Files created/touched:**
- `providers/cloudflare.py` (sensitive) — `verify_token(token_ref)` returning
  `{status, zones}` from the same pinned endpoint + probe Task 1 uses; no
  mutation, no second spelling of the rule.
- `monitor/token_audit.py` — `audit_cloudflare_credentials()`: for each
  `DnsAccount`, check the `dns` ref against its zones' declared minimum, the
  `edge` ref against `Zone:Firewall Services:Edit` + `Zone Settings:Edit` on
  the same zones (modelled now, used by the Phase-4 playbook), and the
  Origin-CA ref's presence. Excess zone access, an inactive token, a
  Global-API-Key shape, or a token reachable for zones no row names → one
  Finding (P2) per fingerprint + `CheckRun(kind=cf_token_scope)`.
- `monitor/tasks.py` + `hub/settings/base.py` — Beat `cf-token-scope-daily`
  on queue `probes`.

**Exact req ids proven:** SEC-B5-CF-TOKEN-SCOPING.

**Tests to write:**
- `tests/test_cf_token_audit.py` —
  `test_exact_minimum_scope_is_clean`;
  `test_excess_zone_access_files_a_p2_finding`;
  `test_global_api_key_shape_is_refused_not_warned`;
  `test_inactive_token_files_a_finding`;
  `test_edge_token_ref_is_audited_from_its_model_home`;
  `test_audit_writes_a_checkrun_every_run`;
  `test_audit_makes_no_mutating_api_call`;
  `test_audit_and_construction_share_one_verification_helper`
  (the audit cannot drift from the enforcement it backs up);
  `test_finding_fingerprint_is_stable_across_runs`.

**Dependencies:** Task 1.

---

## Task 3 — Origin certificates, key lifecycle, and the visible refusal (D-035)

**Title:** SEC-B2's buildable clause, proven across every target-bound surface.

**Files created/touched:**
- `providers/base.py` (sensitive) — `OriginCertIssuer.issue(zone, hostnames,
  *, validity_days)` → `{certificate, expires_at}`.
- `providers/cloudflare.py` (sensitive) — implement against the Origin CA
  endpoint using the account's `origin_ca_key_ref`; the Hub generates the
  keypair and sends only the CSR.
- `providers/fakes.py` — `FakeOriginCertIssuer` emitting a self-signed pair so
  T1/T2 never call Cloudflare.
- `deploys/certs.py` (**new, sensitive**) — `ensure_site_certificate(desired)`
  with the full key lifecycle: **vault-first** (the private key is stored, and
  a new vault version created, before any byte leaves the Hub); never written
  into a `DeploymentArtifact`, manifest, env file, log line or task kwarg;
  pushed into a `0700 root:root` `/srv/sites/{slug}/tls/` created by an
  idempotent ensure step; **atomic write** (put to a temp name in that
  directory, `chmod 0400`, `mv` into place — argv, never a shell string);
  **key/cert match asserted** (the cert's public key equals the key's) before
  any Caddy reload; **replacement cleanup** — the superseded pair is removed
  only after the new pair serves, and a failed reload restores the previous
  pair; **rotation** — reissue inside the renewal window writes a new vault
  version and leaves the old one readable until cutover, so a rollback has a
  key to roll back to. Unproxied public site → `UnproxiedCertUnsupported`
  **and** a P2 Finding whose fix_action names Phase 3b, surfaced as a Sites
  screen state (Task 12/13 render it); never a bare traceback.
- `monitor/cert_watch.py` — daily scan of `TlsCertificate.not_after` against
  the V9 thresholds; Findings at P3/P2/P1 + a `CheckRun(kind=cert_expiry)`.
- `deploys/steps.py` — `ensure_route_tls` calls `ensure_site_certificate` and
  points the Caddy route at the pushed files; unchanged for `mesh_only`.
  (The `_ws_frame` read-loop fix moved to Task 18 per the panel.)
- `hub/settings/base.py` — Beat `cert-expiry-daily`.

**Exact req ids proven:** SEC-B2-NO-TOKEN-ON-TARGET; TLS-B2-ORIGIN-CERT-PUSH
(`tier: t2`); TLS-V9-CERT-THRESHOLDS. **Not** the full-text
`SEC-B2-NO-DNS-TOKENS-ON-TARGETS` — no marker, per the clause split.

**Tests to write:**
- `tests/test_origin_certs.py` (T1) —
  `test_key_is_vaulted_before_the_first_push`;
  `test_key_written_atomically_0400_in_a_0700_root_dir`;
  `test_key_cert_mismatch_refuses_before_reload`;
  `test_failed_reload_restores_the_previous_pair`;
  `test_superseded_pair_removed_only_after_the_new_one_serves`;
  `test_rotation_creates_a_new_vault_version_and_keeps_the_old_readable`;
  `test_reissue_is_skipped_inside_the_renewal_window`
  (run-twice: second call records no mutation);
  `test_unproxied_public_site_refusal_files_a_finding_with_a_fix_action`;
  `test_refusal_leaves_zero_mutating_calls`.
- `tests/test_no_token_exfiltration.py` — the all-surfaces scan (panel r2):
  `test_no_dns_token_in_put_payloads`;
  `test_no_dns_token_in_run_argv`;
  `test_no_dns_token_in_env_files_or_env_snapshots`;
  `test_no_dns_token_in_celery_task_kwargs`;
  `test_no_dns_token_in_deployment_artifacts_or_manifest`;
  `test_no_dns_token_in_generated_caddy_or_dockerfile_text`;
  `test_recorded_transport_call_log_is_token_free`;
  `test_no_acme_dns_challenge_block_is_ever_generated`
  (the scan takes the live token value, the vault ref, and the env-var names,
  and runs over a full simulated deploy — not a spot check of two files).
- `tests/test_cert_thresholds.py` —
  `test_uploaded_45_21_7_maps_to_p3_p2_p1`;
  `test_auto_renewed_7_and_1_map_to_p2_and_p1`;
  `test_expired_cert_is_p1_not_silence`;
  `test_threshold_table_matches_alert_protocol_v9`.
- `tests/test_t2_cert_push.py` (`@pytest.mark.t2`) —
  `test_t2_cert_and_key_land_0400_in_a_0700_dir_on_hub_test_target`;
  `test_t2_caddy_reload_serves_the_pushed_cert`.

**Dependencies:** Task 1, Task 2 (`providers/cloudflare.py` writer order).

---

## Task 4 — The `Finding` model and inbox API (§F2, D-045)

**Title:** One attention queue, one topic.

**Files created/touched:**
- `core/findings.py` — `finding(source_engine, fingerprint, **fields)` upsert
  helper (one line to emit, like `audit()`); `accept_risk(finding, reason)`
  refuses an empty/whitespace reason; a changed fingerprint creates a new row
  rather than reviving an accepted one. (The model itself shipped in Task 1.)
- `monitor/views.py` + `monitor/urls.py` + `hub/urls.py` — DRF list/detail/
  transition endpoints under `/api/v1/findings/`, §4.5 serializers, filters by
  state/severity/entity, `{seq, data}` snapshot shape (§D7). Every state change
  writes an `AuditEvent`.
- `realtime/authorize.py` (sensitive) — append `findings`; keep `alerts` as a
  deprecated alias mapping to the same group, with a comment naming D-045 and
  the phase it is removed in. `realtime/publish.py` — publish on every create
  and transition.
- `frontend/src/api/` — regenerate (`make generate-client`).

**Exact req ids proven:** UX-F2-FINDING-MODEL (model + API half; UI half is
Task 13).

**Tests to write:**
- `tests/test_findings.py` —
  `test_same_fingerprint_updates_last_seen_not_a_second_row`;
  `test_accept_risk_requires_a_reason`;
  `test_accepted_risk_resurfaces_when_fingerprint_changes`;
  `test_ack_is_not_resolve`;
  `test_every_transition_writes_an_audit_event`;
  `test_finding_copy_carries_what_why_and_exact_fix`.
- `tests/test_findings_api.py` —
  `test_list_requires_session`;
  `test_transition_endpoint_validates_through_serializer`;
  `test_findings_topic_requires_authorize_topic`;
  `test_alerts_alias_delivers_the_same_payload_as_findings`;
  `test_snapshot_returns_seq_and_data`.

**Dependencies:** Task 1.

---

## Task 5 — The alert rules table (§2) and `classify()` (D-037)

**Title:** An unclassified alert cannot ship, because the function raises.

**Files created/touched:**
- `monitor/alert_rules.py` (**new, sensitive**) — one table transcribed clause
  by clause from alert-protocol.md §2, each row `{kind, severity,
  condition_text, source_clause}`, including every review3 §O1 row (feed
  data-stale = P2 and never a restart trigger, warm-up budget = P2 escalating
  to P1 only when no ready instance serves, scheduled-job failure = P2 with
  consecutive-failure hysteresis, partner-tier defaults, intake unreachable,
  cron stale, cert thresholds per V9) and the phase-3 kinds (dead-man POST
  failure, cf-token-scope drift, unproxied-cert refusal, drill missed/skipped).
  `classify(kind, **facts)` returns the severity or raises `UnclassifiedAlert`.
- `monitor/alerts.py` — `raise_alert(kind, entity, **facts)`: classify →
  fingerprint → `finding()` → hand to the anti-noise engine (Task 6).

**Exact req ids proven:** ALERT-P1-ROWS.

**Tests to write:**
- `tests/test_alert_rules.py` —
  `test_every_p1_row_of_the_protocol_has_a_rule`
  (parse `docs/plan/alert-protocol.md` §2; each bullet maps to exactly one row
  — the transcription cannot silently drift);
  `test_every_rule_names_its_protocol_clause`;
  `test_unknown_kind_raises_unclassified_alert`;
  `test_no_kind_maps_to_two_severities`;
  `test_staleness_is_p2_and_never_a_restart_trigger`;
  `test_warmup_escalates_to_p1_only_without_a_ready_instance`;
  `test_deadman_post_failure_has_a_row`;
  `test_every_emitted_kind_in_the_codebase_is_registered`
  (AST scan for `raise_alert(` literals).

**Dependencies:** Task 4.

---

## Task 6 — The anti-noise engine (§4) (D-038)

**Title:** Hysteresis, flap collapse, root-cause suppression, ack, storm breaker, P2 grouping.

**Files created/touched:**
- `monitor/antinoise.py` — pure functions over `AlertState` + `UptimeEvent`:
  `observe(fingerprint, ok)` (open after 3 consecutive failures, close after 2
  consecutive successes); `flap_check` (≥3 open/close cycles in 30 min → one P2
  `FLAPPING`, individual transitions suppressed until 30 min stable);
  `suppressed_by(entity)` (host-down suppresses its sites, zone-down its hosts;
  the surviving alert carries the suppressed list); **`group_p2(window=600)`**
  (>1 P2 in 10 min → one grouped push — the §1-table behaviour that had no
  owner in r1); `storm_breaker(now)` (>10 pushes/10 min → one P1
  `ALERT STORM (n)` + 10-min summaries until the rate drops);
  `recovery_notice(finding)` on close.
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
  `test_two_p2_within_ten_minutes_become_one_grouped_push`;
  `test_a_single_p2_is_not_delayed_by_grouping`;
  `test_ack_stops_repeats_but_keeps_the_finding_open`;
  `test_eleventh_push_in_ten_minutes_becomes_one_storm_alert`;
  `test_storm_mode_exits_when_the_rate_drops`;
  `test_p1_ignores_quiet_hours`.

**Dependencies:** Task 5.

---

## Task 7 — Pager seam, identities, and the named delivery owners (D-036, D-037)

**Title:** Authenticated, minimized, scrubbed — and every protocol behaviour has a Beat entry.

**Files created/touched:**
- `providers/base.py` (sensitive) — `Pager.publish(severity, title, body, *,
  tags, click_url)`.
- `providers/ntfy.py` (**new, sensitive**) — one HTTPS publish with
  `Authorization: Bearer <publisher token>`; topic and token resolved from the
  vault by ref; refuses to publish with a bare topic and no token.
  **Three publisher identity classes**, never one shared secret: `hub`,
  `healthchecks`, and `target:<id>` issued at provisioning; the
  subscriber/read credential is a separate protected-topic token that no
  publisher token can use, and nothing in the Hub ever publishes with it.
- `providers/fakes.py` — `FakePager` recording publishes; the default backend
  in dev/test settings so no test can page anyone.
- `monitor/pager.py` (**new, sensitive**) — `deliver(finding)`: minimized push
  body (object · severity · duration · deep link; host aliases, never raw IPs),
  scrubbed, `AlertDelivery` row recording **which backend delivered**, and the
  email copy that alone carries the break-glass block prefixed *"advisory only
  — re-read from the Findings inbox before typing"*.
- `monitor/alerts.py` — `repeat_unacked()`: re-push open unacked P1s hourly and
  send the 24 h `[UNACKED]` email. It runs on its **own** Beat entry
  (`alert-repeat-unacked`, 300 s scan), deliberately not piggybacked on
  `probe-uptime`: a stalled probe cycle must not silence a repeat.
- `monitor/digest.py` (**new**) — `build_digest(day)` (08:00 local P3 digest,
  Celery crontab honouring `TIME_ZONE`) and `build_weekly_rollup(week)`
  (Monday 08:00), each rendering the same Finding set the inbox shows.
- `hub/settings/base.py` — Beat `alert-repeat-unacked`, `digest-daily`,
  `digest-weekly`; `HUB_PAGER_BACKEND` (default fake); vault refs for topics
  and each publisher identity; **email assumption stated**: Django's mail
  backend — `locmem` in tests, env-configured SMTP (`HUB_SMTP_*`) in prod; a
  failed send files a Finding and never blocks the push path.
- `monitor/scrub.py` (extracted from `scripts_dev/file_nightly_failure.py`)
  — one production-packaged scrubber for both the nightly bundle and the pager; extended past the
  single high-entropy class to bearer headers, `ntfy.sh/<topic>` URLs and vault
  refs.
- `provision/service.py` + `catalog/entries.py` (sensitive) — when Hub-side
  probing goes live for a target, remove that host's `server-watch.sh` cron
  (review3 §Q8) **and revoke that target's publish token**: via the ntfy
  account API where configured, otherwise mark the vault ref revoked (the Hub
  refuses to reissue it) and file a P2 Finding carrying the one manual step.
  Catalog entry version bump, never a silent mutation.

**Exact req ids proven:** ALERT-M3-PAGER-AUTH; ALERT-DELIVERY-BEHAVIORS.

**Tests to write:**
- `tests/test_pager.py` —
  `test_publish_without_a_token_is_refused`;
  `test_hub_healthchecks_and_target_identities_are_distinct_refs`;
  `test_subscriber_credential_is_never_used_to_publish`;
  `test_push_body_has_no_raw_ip_no_secret_no_break_glass_command`;
  `test_email_copy_carries_break_glass_marked_advisory_only`;
  `test_delivery_row_records_the_backend_and_the_outcome`;
  `test_default_backend_in_tests_is_the_fake`;
  `test_p1_email_copy_is_sent_even_when_push_fails`;
  `test_failed_email_files_a_finding_and_does_not_block_the_push`.
- `tests/test_delivery_behaviors.py` —
  `test_unacked_p1_repeats_hourly_on_its_own_beat_entry`;
  `test_repeat_does_not_depend_on_the_probe_cycle_running`;
  `test_unacked_24h_sends_the_unacked_email`;
  `test_daily_digest_runs_at_0800_local_and_contains_only_p3`;
  `test_weekly_rollup_has_an_owner_and_a_beat_entry`;
  `test_grouped_p2_push_is_delivered_once`.
- `tests/test_scrubber.py` (extend) —
  `test_bearer_header_is_redacted`;
  `test_ntfy_topic_url_is_redacted`;
  `test_multiple_token_classes_in_one_line`.
- `tests/test_server_watch_handoff.py` —
  `test_cron_entry_removed_when_hub_probing_goes_live`;
  `test_target_publish_token_is_revoked_or_marked_with_a_finding`;
  `test_catalog_entry_version_bumped_not_mutated`.

**Dependencies:** Task 6.

---

## Task 8 — Dead-man, canary, and `UptimeEvent` (§5, §O3, D-039)

**Title:** The heartbeat proves a completed cycle; its own failure is not silence.

**Files created/touched:**
- `monitor/uptime.py` — `probe_cycle()`: probe each site (HTTP for public;
  **`mesh_only` over Hub→tailnet HTTP through the existing seams — never a
  second per-minute SSH session**, which §C3 exists to prevent), record
  `UptimeEvent` transitions, feed `observe()` from Task 6. ws-class sites use
  last-tick age + connection count from the `/healthz` payload the collector
  already fetches (§O3).
- `monitor/deadman.py` — `ping()` fired **only** after a cycle completes every
  target (§C7); a non-2xx or unreachable receiver **files its own Finding**
  (panel r2) rather than logging quietly; `canary_ok()` probes a known-good
  external endpoint; `declare_mass_outage(candidates)` returns either N site
  alerts or one "Hub egress degraded" P2 when the canary fails.
- `monitor/tasks.py` + `hub/settings/base.py` — Beat `probe-uptime` (60 s); the
  dead-man URL is a vault ref.

**Exact req ids proven:** MON-DEADMAN-EXTERNAL (now `verify: test`);
MON-UPTIME-EVENTS.

**Tests to write:**
- `tests/test_deadman.py` —
  `test_ping_only_after_every_target_completed`;
  `test_partial_cycle_does_not_ping`;
  `test_exception_mid_cycle_does_not_ping`;
  `test_failed_ping_files_its_own_finding`;
  `test_deadman_url_is_a_vault_ref_not_a_settings_literal`.
- `tests/test_canary.py` —
  `test_canary_failure_collapses_n_site_alerts_to_one_p2`;
  `test_canary_success_lets_real_site_alerts_through`;
  `test_canary_is_probed_before_the_declaration_not_after`.
- `tests/test_uptime_events.py` —
  `test_transition_writes_one_event_not_one_per_probe`;
  `test_mesh_only_site_is_probed_over_http_not_a_new_ssh_session`
  (assert zero additional `Transport` sessions per cycle);
  `test_ws_site_card_metric_is_last_tick_age_and_connections`;
  `test_probe_cycle_records_zero_mutating_transport_calls`.

**Dependencies:** Task 1 (models); the `observe()` call lands behind Task 6's
import — coordinate at merge, do not fork the engine.

---

## Task 9 — Drills stop lying (D-042; retires 2.5 I5 / M1 / M2)

**Title:** A real prober, real `due_at` rows, an honest restore stub, a pager drill that names its backend.

**Files created/touched:**
- `monitor/drills.py` (sensitive) — `run_hub_down_drill` takes a **real**
  default `site_prober` built from a live Site + target (external HTTP GET, not
  a Hub-internal call). **No eligible site** (the ordinary state on this host
  between T3 sessions) is a defined outcome, not a crash and not a fake green:
  `CheckRun` `SKIPPED` whose `results.reason` names it, plus a P2 Finding, and
  `make nightly` still **exits 0**. A missing prober where a site *does* exist
  is a configuration error. `run_restore_clean_drill` writes `SKIPPED` with the
  deferred reason, not `SUCCEEDED` (M1). New `run_pager_drill()` — synthetic P1
  through the real delivery path; the `CheckRun` records
  `results.backend` and is `SUCCEEDED` **only** when a real backend delivered;
  a fake-backend run is `SKIPPED` with `backend: fake`, so a drill that paged
  nobody is a distinguishable state.
- `monitor/tasks.py` + `hub/settings/base.py` — each drill Beat job first
  writes/refreshes a `scheduled` `CheckRun` with `due_at` for its next period,
  so `find_missed` has rows to find in prod (M2); add `drill-pager-monthly`;
  `scripts_dev/run_nightly.sh` invokes the hub-down drill so nightly exercises
  a drill body, not only its tests.
- `WAIVERS.md` — **keep** `REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven`;
  amend only to record that the prober is now real and the 24 h form is a dated
  calendar item (D-042).

**Exact req ids proven:** ALERT-PAGER-DRILL; REL-P2-DRILL-STUB (kept honest);
HARNESS-DRILLS-BEAT (bodies still green).

**Tests to write:**
- `tests/test_drills.py` (extend) —
  `test_hub_down_uses_a_real_external_prober_by_default`;
  `test_no_eligible_site_is_skipped_with_a_reason_and_a_p2_finding`;
  `test_nightly_exits_zero_on_a_host_with_no_live_site`;
  `test_missing_prober_with_a_live_site_is_a_configuration_error`;
  `test_restore_stub_status_is_skipped_not_succeeded`;
  `test_beat_seeds_due_at_for_every_drill_kind`;
  `test_find_missed_fires_on_a_seeded_overdue_row`;
  `test_pager_drill_records_which_backend_delivered`;
  `test_fake_backend_pager_drill_is_skipped_not_succeeded`;
  `test_missed_pager_drill_alerts_like_a_down_site`;
  `test_hub_down_still_refuses_to_claim_24h`.
- `tests/test_nightly_runs_a_drill.py` —
  `test_run_nightly_invokes_the_hub_down_drill_body`.

**Dependencies:** Task 7 (pager), Task 8 (shares the probe helper). **Wave F.**

---

## Task 10 — Log backpressure + traffic ingest (§C4)

**Title:** A bounded pull, a sampled degrade, minute rows the dashboard reads.

**Files created/touched:**
- `catalog/entries.py` + `catalog/files/` (sensitive) — Caddy's native roller
  (`roll_size 100MiB`, `roll_keep 5`) as a versioned entry with check/fix/
  rollback; logrotate stays the backstop; version bump per §D8.
- `monitor/collect_once.py` — per-pull byte cap; over the cap the on-host
  one-liner aggregates counts by status and top IPs and returns
  `{"sampled": true, "summary": {...}}` instead of raw lines. Offsets still
  advance by inode + offset exactly once.
- `monitor/traffic.py` — parse the chunk (or ingest the summary) into minute
  `TrafficStat` rows; `sampled` is carried through, never dropped; re-ingesting
  the same offset is a no-op.
- `realtime/authorize.py` (sensitive) + `realtime/publish.py` —
  `site.{id}.traffic` and `host.{id}.metrics` topics.

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

**Dependencies:** Task 1.

---

## Task 11 — Retention janitor (§C7) — **may slip (D-044)**

**Title:** The pinned numbers, as one nightly batched delete.

**Files created/touched:**
- `monitor/retention.py` — batched `DELETE`s on the §C7 numbers (HostMetric raw
  14 d / hourly 1 y · UptimeEvent 90 d + daily rollup · TrafficStat minute 48 h
  / hour 90 d / day forever · deploy logs gzipped after 30 d · AuditEvent
  forever). No partitioning, no TimescaleDB.
- `monitor/tasks.py` + `hub/settings/base.py` — Beat `retention-janitor-nightly`.

**Exact req ids proven:** MON-C7-RETENTION. Slipping leaves an honest waiver
naming accepted disk growth for the phase.

**Tests to write:**
- `tests/test_retention.py` —
  `test_each_table_uses_its_pinned_horizon`;
  `test_auditevent_is_never_deleted`;
  `test_rollup_rows_survive_raw_deletion`;
  `test_janitor_is_batched_and_idempotent`.

**Dependencies:** Task 10. **Not on the MUST line.**

---

## Task 12 — Frontend shell, degraded polling, action tiers, Cloudflare connect (§F1, §3.5, §F5, §F6)

**Title:** The daily-driver frame — rollback stays one click, and the operator can actually connect Cloudflare.

Split for the wave table: **12a** (shell, nav, degraded polling, tiers) has no
backend dependency and runs in wave A; **12b** (Cloudflare-connect Settings)
needs Task 2's verification helper and runs in wave C.

**Files created/touched:**
- `frontend/src/App.jsx` — object-centric nav: Home, Sites, Targets, Deploys,
  Findings, Settings (Vault is a Settings tab until Phase 4). The demo pane
  becomes a Settings/Developer tab, not the product surface.
- `frontend/src/screens/{Home,Sites,Targets,Deploys,Settings}.jsx` (new) — each
  with the designed empty state (one sentence + the single button that
  populates it) and loading / live / error / degraded states. The Sites screen
  renders the **unproxied-cert refusal** as a visible site state with its
  Finding link (Task 3).
- `frontend/src/useEvents.js` — a `degraded` status: when the socket is
  unavailable, poll each subscribed topic's REST snapshot every 10 s, show a
  pill naming the mode plus the "data as of HH:MM:SS" stamp, and resume
  snapshot-then-stream on reconnect.
- `frontend/src/actions.js` + `core/actions.py` (new) — ONE action-tier table
  (§F5) shared server↔client through the generated schema: T2 renders a confirm
  dialog containing the diff summary; T3 (rollback, restart, re-run check) is
  one click + undo toast with **no** step-up requirement; T1 requires
  type-the-name + `require_recent_touch` (TOTP today; the hardware clause is
  Phase 4, D-040).
- **12b** `core/zone_views.py` + `core/urls.py` (new endpoint; `core/views.py`
  is untouched so the auth-code custody stays clean) + the Settings screen's
  Cloudflare panel: paste token → server-side verify through **Task 2's
  helper** (pinned endpoint + zone-set probe) → on success create the
  `DnsAccount` + `DnsZone` rows; a token that resolves to more than one zone,
  an inactive token, or a Global-API-Key shape is **refused at this screen**
  with the reason. §F3's first-run checklist that owns the home screen stays
  Phase 3b.
- **§F6 phone widths** — exactly three screens are made responsive: finding
  detail, site status (with its T3 actions), deployment status. The map is
  explicitly desktop-only and no alert deep link routes through it.
- `frontend/src/api/` — regenerate.

**Exact req ids proven:** UX-F1-IA-NAV; RT-35-DEGRADED-POLLING;
UX-F5-T2-T3-FRICTION. **Not** the full-text `UX-F5-ACTION-TIERS` — no marker,
per the clause split; its tests run unmarked and Task 19 files the waiver.

**Tests to write:**
- `frontend/tests/nav.test.ts` —
  `advisors_are_tabs_not_top_level_pages`;
  `every_list_screen_has_an_empty_state`;
  `three_named_screens_render_at_phone_width`;
  `map_is_not_in_the_phone_scope`.
- `frontend/tests/degraded.test.ts` —
  `socket_failure_switches_to_ten_second_polling`;
  `degraded_mode_is_visible_not_silent`;
  `reconnect_resnapshots_before_streaming`.
- `tests/test_action_tiers.py` —
  `test_rollback_and_restart_are_t3`;
  `test_no_t3_action_requires_step_up`;
  `test_deploy_and_dns_change_are_t2_with_a_diff_body`;
  `test_target_delete_and_key_export_are_t1`;
  `test_client_and_server_tier_tables_are_one_source`.
- `tests/test_cloudflare_connect.py` —
  `test_valid_single_zone_token_creates_account_and_zone_rows`;
  `test_multi_zone_token_is_refused_with_the_reason`;
  `test_inactive_or_global_key_is_refused`;
  `test_token_is_vaulted_and_never_returned_by_the_api`;
  `test_connect_uses_the_same_verification_helper_as_construction`.

**Dependencies:** Task 0 (12a); Task 1 + Task 2 (12b).

---

## Task 13 — Findings inbox UI, deploy-failure impact, simulation states (§F2, §F4, §F8)

**Title:** Retires the UX-F8 demo-pane waiver by rendering the states.

**Files created/touched:**
- `frontend/src/screens/Findings.jsx` (new) — the inbox: filters, severity
  chips (icon + label, never colour alone), ack / snooze / accept-risk (reason
  required, grey chip), the §6.6 what / why / exact-fix layout, phone width.
- `deploys/failure_impact.py` (new) — the §F4 partial-states table: failed step
  → impact line ("Old version still serving — site unaffected" vs "Site may be
  unreachable"), including the N1 recreate rows. The alert body, the break-glass
  runbook (Task 16) and the UI read the **same** table.
- `frontend/src/screens/Deploys.jsx` — 9-step vertical stepper; on failure the
  banner leads with the impact line and offers at most three actions (Retry
  from step N / Roll back / Abort & clean up), each naming what it will do.
- `simulation/seed_v1.json` + `realtime/simulation.py` + `frontend/src/sim.js`
  — seed and scripted events for every new state: each finding severity and
  state, degraded polling, deploy failure at a named step (both strategies),
  warming with elapsed/expected copy, data-stale badge, single-instance,
  cert-expiring, unproxied-cert refusal, alert storm, host-down suppression,
  map empty/populated. Events publish on `findings` (D-045).
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
  `ack_does_not_remove_the_finding_from_the_inbox`;
  `finding_detail_renders_at_phone_width`.
- `frontend/tests/simulation-states.test.ts` —
  `every_new_state_renders_in_simulation_mode`
  (enumerate the seed's states; a state with no rendering assertion fails).
- `tests/test_failure_impact.py` —
  `test_every_step_has_an_impact_line`;
  `test_recreate_strategy_says_site_is_down_not_old_version_serving`;
  `test_alert_body_ui_and_runbook_read_the_same_table`;
  `test_failure_offers_at_most_three_actions`.

**Dependencies:** Task 4, Task 12.

---

## Task 14 — Map v1 (§9.6.1, D-041) — MUST, **first slip candidate**

**Title:** Zones → hosts → containers, dependency-free, with a list-view toggle.

**Files created/touched:**
- `monitor/map_graph.py` — `graph_snapshot()` → `{nodes: [zone|host|container|
  hub|edge], edges: [{a, b, path ∈ {public, mesh}}], seq}` built from models,
  never from a stored JSON blob (§D3). **A "zone" node is a `NetworkZone`** —
  the network the targets sit in. The new `DnsZone` is a DNS-provider object
  and never appears on the topology graph; sites carry their DNS zone as a
  detail field, not as a parent node.
- `monitor/views.py` + `monitor/urls.py` — `{seq, data}` snapshot endpoint per
  §D7; `realtime/authorize.py` (sensitive) appends `map.graph`; publish on
  graph change.
- `frontend/src/Map.jsx` (new) — plain SVG: nested `NetworkZone` groups, solid
  public / dashed mesh edges, status by icon+label, container count chips above
  N children, and a list-view toggle showing the same data. Desktop-only (§F6).
- `frontend/src/screens/Home.jsx` — map + fleet cards as one composite screen.

**Exact req ids proven:** MAP-96-GRAPH-V1. Cutting this task means a
`MAP-96-GRAPH-V1` waiver filed by Task 19, named in the demo record.

**Tests to write:**
- `tests/test_map_graph.py` —
  `test_graph_is_derived_from_models_not_a_stored_blob`;
  `test_zone_nodes_are_networkzones_not_dnszones`;
  `test_hub_is_a_distinct_node`;
  `test_mesh_paths_are_marked_mesh_and_public_public`;
  `test_snapshot_returns_seq_and_data`;
  `test_thirty_node_fleet_renders_within_the_snapshot_contract`.
- `frontend/tests/map.test.ts` —
  `list_view_toggle_shows_the_same_nodes`;
  `status_is_icon_plus_label_not_colour`;
  `empty_fleet_shows_the_onboarding_hint`.

**Dependencies:** Task 4 + Task 10 (topic writer order), Task 12a (shell).

---

## Task 15 — Adopt-existing-site, compose-aware — **may slip / Phase 3b (D-044)**

**Title:** Read the compose stack, propose a plan, never flip DNS before verifying.

**Spec holes to close before implementation** (panel ruling 5; recorded in
design note §1.12): (a) compose-as-unit vs V5 compression — one Site or a
multi-container Site the data model does not have; (b) where the compose file
comes from (cloned git URL per §A4 / operator paste / read off the live host);
(c) temp-subdomain naming and which zone it lives in, plus cleanup on an
abandoned flip; (d) the DB/volume pointer — does adopted data move, get shared,
or get pointed at in place (§N6 forbids a silent strand); (e) where the
site-owned-Caddy-vs-host-Caddy call is recorded per adopted site. An
Implementer who starts this task without written answers is starting the wrong
task.

**Files created/touched:**
- `provision/adopt.py` (**new, sensitive**) — `read_compose(path)` via
  `yaml.safe_load`, **executing nothing** (M1); `classify_services()` → web /
  worker / beat-scheduler / one-shot migrate / db / cache / site-owned edge;
  `adoption_plan(project)` emitting Findings (what / why / exact fix) plus one
  manifest proposal and a volumes list (N6), with the Caddy-ownership decision
  recorded on the Site rather than prompted per run.
- `provision/service.py` — the E6 fresh-host guard learns "occupied by a stack
  we can adopt" and points at the plan instead of only refusing.
- `deploys/adopt_flow.py` — temp-subdomain deploy → verify (HTTP 200 + the
  site's own healthz contract) → DNS flip through `dns_provider_for` → old-path
  decommission; each stage idempotent; the flip **refuses** unless verify
  recorded success for the current image tag.
- `tests/fixtures/compose/` — three fixture stacks from the §J7 inventory
  shapes: web+worker+beat+one-shot-migrate; web+site-owned-Caddy; web only.

**Exact req ids proven:** PROV-J7-COMPOSE-AWARE-ADOPT; PROV-E6-ADOPT-TEMP-SUBDOMAIN.
If the task slips, **both ids need a waiver or a phase bump at exit** (D-020
precedent) — Task 19 files it explicitly rather than letting them go quiet.

**Tests to write:**
- `tests/test_adopt_compose.py` —
  `test_worker_beat_and_oneshot_migrate_are_classified`;
  `test_site_owned_edge_container_is_recorded_as_a_decision_on_the_site`;
  `test_named_volumes_appear_in_the_plan`;
  `test_parser_executes_nothing`;
  `test_single_container_stack_still_produces_one_manifest`;
  `test_plan_findings_carry_what_why_and_fix`.
- `tests/test_adopt_flow.py` —
  `test_dns_flip_refuses_before_verification`;
  `test_verified_flip_upserts_then_decommissions`;
  `test_abandoned_flip_cleans_up_its_temp_subdomain`;
  `test_flow_run_twice_records_zero_mutating_calls`;
  `test_decommission_never_touches_a_registered_volume_without_confirmation`.

**Dependencies:** Task 1, Task 3, Task 12. **Not on the MUST line.**

---

## Task 16 — Break-glass runbook gains impact, real DNS copy, and freshness (§P5, §F4, §M3)

**Title:** Retires the SEC-P5 waiver the Phase 2 round left for this phase.

**Files created/touched:**
- `deploys/breakglass.py` — the runbook gains: the impact line for the current
  state (from `deploys/failure_impact.py`), the exact DNS commands now that a
  real adapter exists — **Hub-side only**, because a token-bearing command on
  the target is the SEC-B2 violation the phase is built to prevent — the
  alert-protocol §3 advisory-only note, the site's cert mode + expiry, and
  **freshness metadata**: generated-at timestamp, the deployment id and image
  tag it describes, and a runbook schema version, so an operator reading a
  stale file at 2 a.m. can see that it is stale. Still `0400`, still no secrets.
- `WAIVERS.md` — retire
  `deploys/breakglass.py+SEC-P5+runbook-lacks-impact-and-dns` once the named
  tests pass.

**Exact req ids proven:** SEC-P5-BREAK-GLASS (waiver retired).

**Tests to write:**
- `tests/test_breakglass.py` (extend) —
  `test_runbook_states_impact_before_commands`;
  `test_dns_section_names_hub_side_commands_only`;
  `test_runbook_carries_generated_at_deployment_and_schema_version`;
  `test_runbook_contains_no_token_and_no_secret`;
  `test_runbook_is_0400_and_root_owned`;
  `test_advisory_only_note_present`.

**Dependencies:** Task 3 (cert fields), Task 13 (`failure_impact`). **Wave E.**

---

## Task 17 — Live Cloudflare / LE leg, credential-gated (D-043) — body **may slip**

**Title:** Skip is not a green, and the waiver refuses itself once the token exists.

**Files created/touched:**
- `tests/harness/cf_zone.py` (sensitive: `tests/harness/**`) — a session
  fixture that allowlists the configured test `DnsZone` via
  `HUB_TEST_ZONE_SLUGS` (the pinned name; `HUB_TEST_DNS_ZONE` is gone), drives
  the **product** adapter (D-034) with `HUB_TEST_CF_TOKEN`, and reaps every
  record it created in `finally`.
- `tests/test_t3_cf_live.py` — `@pytest.mark.t3` + a `multipass_available()`
  -derived gate: upsert A proxied → list → resolve → Origin cert issued and
  pushed → HTTPS 200 + security headers → `wss://` one frame through CF+Caddy
  for ws sites → delete → assert the zone is clean.
- `tests/harness/multipass.py` / `monitor/reaper.py` (sensitive) —
  `waiver_illegal_if(credentials_present)` extended so the
  `HARNESS-T3-LE-STAGING` waiver is **self-refusing** the moment
  `HUB_TEST_CF_TOKEN` and a `purpose=test` `DnsZone` both exist (2.5 finding
  M4). **This half is MUST even when the credentialed body slips.**
- `WAIVERS.md` — keep `HARNESS-T3-LE-STAGING+no-test-zone-credentials`, add
  `DNS-CF-T3-LIVE+no-test-zone-credentials` while the token is absent; retire
  both on the first credentialed green run, in the change that records the run
  under `conformance/demos/phase-3/`.

**Exact req ids proven:** DNS-CF-T3-LIVE (`tier: t3`); HARNESS-T3-LE-STAGING
(retired only with credentials).

**Tests to write:**
- `tests/test_le_waiver_self_refusal.py` (T1, always runs) —
  `test_le_waiver_is_red_when_credentials_are_present`;
  `test_le_waiver_is_allowed_when_credentials_are_absent`;
  `test_cf_live_waiver_follows_the_same_probe`;
  `test_probe_reads_the_pinned_env_names_only`.
- `tests/test_t3_cf_live.py` (T3) —
  `test_product_adapter_upserts_and_deletes_in_the_test_zone`;
  `test_origin_cert_serves_https_with_security_headers`;
  `test_records_reaped_in_finally`;
  `test_no_prod_zone_is_reachable_from_this_run`.

**Dependencies:** Task 1, Task 3. Requires Joseph's test-zone token; absent it
the T3 body is skipped-only and only the probe half lands.

---

## Task 18 — Seam hygiene: 2.5 parked I2, I4 and the ws read loop — **may slip (D-044)**

**Title:** A product module stops importing from `tests/`; one Multipass driver; one bounded read loop.

**Files created/touched:**
- `deploys/worker_entry.py` — drop the `sys.path` insert into `tests/`; the
  fake transport used by `--fake` moves to `providers/fakes.py` (or
  `deploys/testing.py`), so a product entry point no longer depends on the test
  tree. Keep the `HUB_TEST_DATABASE` rebind but gate it on `HUB_TEST_MODE` so a
  prod worker cannot be repointed by an env var.
- `deploys/steps.py` — `_ws_frame`'s extended-length read loops (~lines
  482/487) break on an empty read instead of relying on the 60 s transport
  timeout (2.5 re-review minor; moved here from Task 3 per the panel).
- `tests/harness/multipass.py` (sensitive) — a thin wrapper over
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
- `tests/test_ws_frame_read_loop.py` —
  `test_extended_length_read_breaks_on_empty_read`.
- `tests/test_harness_driver_single_source.py` —
  `test_multipass_argv_has_one_definition`.

**Dependencies:** none. **Not on the MUST line** — if it slips, the ws read
loop stays bounded by the existing 60 s transport timeout, which is why it is
survivable rather than urgent.

---

## Task 19 — Acceptance, demo record, phase gate

**Title:** `make conformance-3` can go green honestly.

**Files created/touched:**
- `tests/acceptance/test_phase_3.py` — one test per milestone clause,
  `@pytest.mark.acceptance(phase=3)` + `@pytest.mark.req(...)`. T1 clauses run
  in `review-round`; live clauses carry their tier marker and a
  `multipass_available()`-derived gate. **No clause carries the full-text
  SEC-B2 or UX-F5 id.**
- `conformance/demos/phase-3.md` + `conformance/demos/phase-3/` — the live run
  transcript with real nodeids; the Cloudflare-connect screen record; the pager
  transcript naming its backend; **the dead-man receiver's registration as a
  dated artifact** (panel ruling 3); the digest sample; the map list dump; the
  dated REL-P2 24 h calendar item; and, if Task 15 slipped, the statement that
  adopt moved to Phase 3b.
- `conformance/requirements.yaml` (sensitive) — `P3-DNS-MONITOR-DEMO` `demo:`
  paths only; no new ids here.
- `WAIVERS.md` — file **only** what is true: the two clause-scoped lines
  (`SEC-B2-NO-DNS-TOKENS-ON-TARGETS` naming the unbuilt Hub-central-DNS-01
  clause and `TLS-B2-HUB-DNS01-UNPROXIED` as its retirement;
  `UX-F5-ACTION-TIERS` naming the T1 hardware clause and
  `SEC-F5-T1-HARDWARE-TOUCH`); the adopt lines if Task 15 slipped; the map line
  if Task 14 was cut; LE/CF credential lines if Task 17 slipped; retention if
  Task 11 slipped; **keep** REL-P2 24 h and the D-025 alpine line; retire UX-F8
  and SEC-P5 only if Tasks 13 and 16 landed.
- `docs/plan/deploy-system-plan.md` / `plan-addendum-2026-07-30.md` — Scribe
  amends the §I Phase-3 line for the D-032/D-044 split (Phase 3b now also owns
  adopt-existing-site) at exit, in its own change.

**Exact req ids proven:** P3-DNS-MONITOR-DEMO; every MUST id via acceptance
transcription or an honest waiver.

**Tests to write:**
- `tests/acceptance/test_phase_3.py` —
  `test_product_adapter_refuses_an_over_scoped_token_at_construction`;
  `test_no_dns_token_reaches_any_target_bound_surface`;
  `test_token_scope_audit_files_a_finding_on_excess`;
  `test_origin_cert_key_is_vaulted_pushed_0400_and_matched`;
  `test_unproxied_refusal_is_a_finding_and_a_visible_site_state`;
  `test_unclassified_alert_kind_cannot_ship`;
  `test_three_failures_open_one_p1_and_two_successes_close_it`;
  `test_unacked_p1_repeats_on_its_own_beat_entry`;
  `test_two_p2_in_ten_minutes_are_one_grouped_push`;
  `test_host_down_suppression_collapses_site_alerts`;
  `test_push_body_is_minimized_and_scrubbed`;
  `test_deadman_pings_only_after_a_completed_cycle_and_failure_files_a_finding`;
  `test_log_pull_is_capped_and_degrades_sampled`;
  `test_findings_inbox_requires_a_reason_to_accept_risk`;
  `test_rollback_is_one_click_and_never_step_up_gated`;
  `test_ws_unavailable_degrades_to_visible_polling`;
  `test_map_v1_snapshot_and_list_view` (skipped with its waiver if Task 14 was
  cut — never quietly absent);
  `test_breakglass_has_impact_hub_side_dns_and_freshness`;
  `test_nightly_is_green_on_a_host_with_no_live_site`;
  `test_rel_p2_24h_still_not_claimed`.

**Dependencies:** Tasks 0–10, 12–14, 16 (MUST line). Tasks 11, 15, 17, 18 as
needed for a waiver-free `conformance-3`; if the cut is taken, this task files
the waiver lines instead of pretending those ids shipped.

---

## Deferred out of Phase 3 (with reasons)

| Item | Reason | Retirement condition |
|---|---|---|
| **Adopt-existing-site (Task 15)** | Panel ruling 5: five open spec questions (compose-as-unit vs V5, compose source, temp-subdomain naming/zone, DB/volume pointer, Caddy-ownership record) make it the wrong thing to implement under phase-exit pressure. | Phase 3b, once §1.12's five holes have written answers. `PROV-J7` + `PROV-E6-ADOPT-TEMP-SUBDOMAIN` carry a waiver or a phase bump meanwhile. |
| App-log viewer (§E3) | Its own surface with its own authz story; no registry id exists, so the gate is unaffected (D-032). | Phase 3b, with a `site.{id}.applog` topic + authorize_topic row. |
| Scheduled-jobs UI (§E8) + `jobs_image` (§N7) | Arbitrary-command-execution surface behind review3 §V3 friction tiers — it needs the action-tier table (Task 12) to exist first, plus the partner prohibition test. | Phase 3b, after UX-F5 tiers are green. |
| First-run checklist owning the home screen (§F3) | Phase 3 ships the Cloudflare-connect surface it depends on; the checklist itself reads better once real screens exist. | Phase 3b. |
| Backup/restore operator surface (§E5/§N6) and the real restore-drill body | The restore drill needs the backup registry; Phase 3 keeps the stub honest (`SKIPPED`) rather than shipping half a restore. | Phase 4, with §B3 audit shipping. |
| Hub-central DNS-01 for unproxied sites | D-035: the alternative (Caddy DNS-01) puts a zone token on every target — the exact SEC-B2 violation. A visible refusal is the honest interim. | Phase 3b; registered as `TLS-B2-HUB-DNS01-UNPROXIED` at phase 4 so it cannot be forgotten. |
| Attack playbook / `EdgeProtection` implementation | Phase 4 security suite; Phase 3 models and audits the `edge` token so the scoping check is real today. | Phase 4. |
| WebAuthn hardware touch for T1 actions | Needs `django-otp-webauthn` (Phase 4). Carried by `SEC-F5-T1-HARDWARE-TOUCH` + the clause-scoped waiver (D-040). | Phase 4. |
| REL-P2 24 h live Hub-down | A 24 h wall-clock drill cannot sit inside a 1–2 week phase's review loop; Phase 3 makes the drill real at the §G 30-min form. | A dated 24 h record (D-042). |
| D-025 alpine T2 fixture image (PIPE-S4) | Environmental (vfs overlay-on-overlay, D-015); nothing in Phase 3 changes it. | A runner with nested overlay2, or registry-pulled images. |
| 2.5 minors not scheduled: `find_missed` AST-shape gaps, `waiver_illegal_if` bool latch, vacuous reaper prefix assertion, tautological waiver-linkage assert, unpinned guest Caddy tarball, `tmp/` artifact accumulation | Test-quality nits with no product consequence this phase; they gate no phase-3 id. | A cleanup pass at Phase 4 entry, or the round that touches the file. |
