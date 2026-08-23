# Phase 4 tasks — Security suite

SDD-ready work list for Implementers. Architect design note:
`docs/phase-4-design-note.md` (panel §7 is binding). Do not start a task whose
dependencies are open. Do not start implementation from the design session
until the design panel records MERGE. Do not invent a path, env, Finding
fingerprint, CheckRun key, or gate shape that the design note does not name.

**Branch:** cut task branches from `p4-design` (which carries these two docs).
Never implement on `master`. Sensitive-path merges to `master` go through the
recorded expert-panel vote.

## Global constraints (every task)

- Every remote effect on a target goes through `Transport`; argv lists, never
  interpolated strings; file content via `put()`, never heredocs.
- Cloudflare HTTP lives **only** under `providers/`. `deploys/` never
  constructs or imports a Cloudflare client. Edge playbook takes
  `EdgeProtection | None` from `edge_protection_for(zone)`.
- Secrets through the vault. No DNS/edge/Origin-CA/Tailscale/KMS token in a
  Finding, CheckRun, log, task arg, or `AuditEvent.detail`.
- **Pinned env names:** `HUB_TEST_ZONE_SLUGS` is the one allowlist;
  `HUB_TEST_DNS_ZONE` is retired; **do not invent `HUB_TEST_CF_TOKEN`**.
  Tailscale: `HUB_TAILSCALE_API_TOKEN_REF` (vault owner-id, default `""`).
  KMS: `VAULT_KEK_BACKEND=kms` refuse-unless-configured.
- Test-plane construction stays triple-keyed: `HUB_TEST_MODE` **and**
  `purpose == test` **and** the name on `HUB_TEST_ZONE_SLUGS`.
- **`0009` and `0010` are closed.** The only Hub migration is Task 1's
  `0011_phase4.py` on DnsZone + AuditEvent. django-otp-webauthn third-party
  migrations are allowed. No `Site.tier`. No CheckRun Site FK.
- **`findings` is the canonical realtime topic.** Task 8 retires `alerts`.
- Every new mutating playbook is run-twice with **zero** mutating Transport
  calls the second time (§D6, D-018).
- New alert kinds need a row in `monitor/alert_rules.py` first.
- `TLS-B2-HUB-DNS01-UNPROXIED` is the named first slip. Do not mark full-text
  `SEC-B2-NO-DNS-TOKENS-ON-TARGETS`. Unproxied refusal stays.
- Do not claim a 24 h Hub-down (D-042). Do not enable live AWS KMS or live S3
  (Joseph interrupt).
- Reviewer never writes the code they review (D-014).
- Tiers: T1 = fakes. T2 = `hub-test-target`. T3 = Multipass. A `tier: t2|t3`
  req is verified only by a passed marked test (D-024). **New Phase 4 ids are
  tier-less.** Do not extend `VALID_TIERS` with `t4`.
- Do not edit `REVIEW_CHECKLIST.md` or `conformance/requirements.yaml` in the
  round they judge. Registry edits are Task 0.
- TDD: failing test first. Long "why" HEREDOC commits; no amend.

Protective cut (**D-054**): MUST = Tasks 0–10 and 12. Task 11 (DNS-01 / live
S3 / YubiKey / tailnet-lock writeup) is the named slip line. First slip =
Hub-central DNS-01.

## Parallel waves

| Shared file | Order |
|---|---|
| `conformance/requirements.yaml` / `Makefile` / `DECISIONS.md` / `WAIVERS.md` / `conformance/paths.yaml` | Task 0 |
| `core/models.py` / `0011_phase4.py` / `core/audit.py` | Task 1 after 0 (only writer) |
| `core/otp.py` / `core/permissions.py` / `core/middleware.py` / `frontend/src/actions.js` / `frontend/src/App.jsx` | Task 2 after 0 |
| `scanner/core.py` / `fallbacks.py` / wizard | Task 3 after 0 (after Task 0 SCAN-M4) |
| `providers/cloudflare.py` / `monitor/attack_*.py` / `scaling/attack_gate.py` | Task 4 after 0 |
| `monitor/topology.py` | Task 5 after 0 |
| `provision/ssh_rotate.py` / `core/actions.py` (ssh.rotate row) | Task 6 after 0 |
| `provision/backup.py` / Sites UI | Task 7 after 1 (and after Task 4 if both touch Sites.jsx) |
| `realtime/authorize.py` / compose parse / exhaust gate | Task 8 after 0 |
| `providers/tailscale.py` | Task 9 after 0 |
| `vault/kek.py` / `vault/service.py` | Task 10 after 0 |
| acceptance + demo | Task 12 after MUST |

Tasks 2, 3, 4, 5, 6, 8, 9, 10 are independent after Task 0 and **may run in
parallel worktrees**. Task 1 is the schema wave — do not collide with it on
`core/models.py`. Task 6 adds one ACTION_TIERS row; Task 2 owns
`presentation()` / permissions. If both touch `core/actions.py`, Task 6 waits
for Task 2 or only appends the `ssh.rotate` tuple.

---

## Task 0 — Unblock `check.py --phase 4` (D-054…D-064)

**Title:** Phase-4 due set exists; SCAN-M4 splits D-012; DNS-01 waived as first
slip; `conformance-4` excludes live tiers; sensitive paths claimed.

**Files created/touched:**
- `DECISIONS.md` — rows D-054…D-064 (text from the design note §5).
- `conformance/requirements.yaml` (sensitive) — add the new ids in design
  note §3 (**no `tier:` key**). Do not change `text:` / `text_hash:` of
  existing ids. `TLS-B2-HUB-DNS01-UNPROXIED` stays `phase: 4`.
- `tests/test_scanner_declarations.py` — **SCAN-M4:** strip full-text
  `SCAN-DECLARED-TEST-MATERIAL` / `SCAN-DECLARED-GUARDS` markers **or** move
  them onto a new `SCAN-DECLARED-PARSER` id. Tests keep running. Full-text
  ids stay unmarked until Task 3.
- `tests/test_d017_declared_reqs_not_phase_2.py` — keep SCAN-DECLARED ids at
  `phase: 4` and not-retired. **Stop** requiring full-text markers on
  `tests/test_scanner_declarations.py`. Point the rewrite at
  `test_scan_declared_full_text_is_not_verified_by_parser_only_tests`.
- `tests/test_d023_actions_not_required.py` — pin `conformance` to
  `--phase 4 --exclude-tier t2 --exclude-tier t3`. Leave `conformance-3` as
  all-tiers `--phase 3` with **no** `--exclude-tier`.
- `WAIVERS.md` — `WAIVED: TLS-B2-HUB-DNS01-UNPROXIED` (first slip, unproxied
  refusal remains). Clause-scoped SCAN-DECLARED full-text waiver until Task 3.
  Do not retire REL-P2 / LE-staging / SEC-B2 full-text.
- `Makefile` — `conformance` becomes `--phase 4 --exclude-tier t2 --exclude-tier t3`.
  Add `conformance-4` as the same recipe. Leave `conformance-3` as **all-tiers
  Phase 3**. Leave `conformance-3.5` unchanged. Do **not** add an all-tiers 4
  target. Do **not** add `t4` to anything.
- `conformance/paths.yaml` + `.github/CODEOWNERS` — claim the sensitive-path
  additions in the design note (files that do not exist yet are listed).
- `docs/phase-4-design-note.md` / this file — already on the branch.

**Exact req ids proven:** none go green here except the gate shape. This task
makes the phase-4 due set honest.

**Tests to write:**
- `tests/test_conformance_gate.py` (extend) —
  `test_phase_4_due_set_includes_webauthn_l5_topo_ssh_backup`;
  `test_tls_b2_hub_dns01_stays_phase_4`;
  `test_new_phase_4_ids_have_no_tier`;
  `test_scan_declared_full_text_is_not_verified_by_parser_only_tests`.
- `tests/test_makefile_nightly.py` — **delete or rewrite**
  `test_review_round_conformance_is_phase_3_minus_live_tiers` and
  `test_review_round_conformance_is_still_phase_3_minus_live_tiers` so they
  cannot remain as `--phase 3` pins on `conformance`. Replacement:
  `test_review_round_conformance_is_phase_4_minus_live_tiers`. Keep
  `test_nightly_gates_use_conformance_3` unchanged (all-tiers Phase 3).
  Also: `test_conformance_4_target_exists`;
  `test_conformance_4_is_phase_4_minus_live_tiers`;
  `test_conformance_3_still_all_tiers_phase_3`;
  `test_conformance_4_is_not_a_nightly_gates_prereq`.
  Do not add a test that claims `conformance-3` excludes live tiers.
  Do not add `t4` assertions.

**Dependencies:** none.

---

## Task 1 — Schema wave `0011_phase4.py`

**Title:** DnsZone `(provider, name)` unique + AuditEvent hash chain + every
CheckRun kind this phase needs.

**Files:** `core/models.py` (**this task is the only writer this phase**),
`core/migrations/0011_phase4.py`, `core/audit.py`,
`tests/test_dns_zone_unique.py` (or extend existing), `tests/test_audit.py`.

**Do:**
- Denormalize `DnsZone.provider` from `account.provider`. `save()` /
  `full_clean()` copy `account.provider`.
- `UniqueConstraint(fields=["provider", "name"], name="uniq_dnszone_provider_name")`.
- Keep `uniq_dnszone_account_name`. `clean()` stays.
- `AuditEvent.prev_hash`. `audit()` writes
  `sha256((prev_hash + canonical_row).encode("utf-8")).hexdigest()` (sorted-key
  JSON, no whitespace). Genesis empty prev. Never blocks on S3.
- Nullable `AuditEvent.shipped_at`.
- Python-only Kind values: `ssh_rotate`, `backup`, `attack_playbook`,
  `tailscale_devices`. BACKUP `clean()` keys exactly
  `{schema_version, unit_id, site_id, bytes, digest, stored_at}` (`bytes` =
  int size).
- `detail` still must not grow vault plaintext.
- Later tasks do **not** edit `core/models.py`.

**Tests:**
- `test_two_accounts_cannot_share_a_provider_zone_name`
- `test_dnszone_save_copies_account_provider`
- `test_audit_event_prev_hash_chains`
- `test_audit_genesis_empty_prev`
- `test_audit_does_not_call_s3`
- `test_checkrun_kind_backup_closed_schema`
- `test_checkrun_kinds_ssh_rotate_attack_tailscale_exist`

**Dependencies:** Task 0.

---

## Task 2 — WebAuthn + T1 touch + idle timeout + sim Shell

**Title:** django-otp-webauthn primary, TOTP fallback, phone passkey,
`require_recent_touch`, idle middleware, T1 type-the-name, sim mounts Shell.

**Files:** `core/otp.py`, `core/views.py`, `core/urls.py`,
`core/permissions.py` (new), `core/middleware.py`, `core/actions.py` (no id
change except Task 6's row if sequenced here), `frontend/src/App.jsx`,
`frontend/src/actions.js`, `frontend/src/screens/Login.jsx` (extract),
`frontend/src/screens/Settings.jsx` (Security tab), `frontend/src/sim.js`,
`frontend/tests/actions.test.ts`, `frontend/tests/simulation-states.test.ts`,
`hub/settings/base.py` (`INSTALLED_APPS` only), `requirements.txt`
(`django-otp-webauthn`).

**Do:**
- Enroll WebAuthn under `/api/auth/webauthn/`.
- Login accepts assertion **or** TOTP **or** recovery.
- Forced first-run is WebAuthn then recovery-codes-once then phone passkey
  prompt. TOTP is Settings fallback + login “Use authenticator code instead”.
- `RequireRecentTouch` reads `hardware_touch_at` written **only** by
  `POST /api/auth/webauthn/touch/`.
- T1 = touch + type-the-name. T3 never uses the permission.
- Two WebAuthn credentials before T1 is available; TOTP-only keeps T1 refused.
- `IdleTimeoutMiddleware` on existing `HUB_SESSION_IDLE_TIMEOUT`.
- `presentation()`: T1 `stepUp: "required"`, T3 `stepUp: "none"`.
- `?sim=` mounts Shell. Extract Login/Enroll. Fixtures in the design note
  UX table. T1 overlay in the 390 px phone set.
- Do not add Playwright. Do not extend `VALID_TIERS`.

**Tests:**
- `test_webauthn_enroll_and_confirm`
- `test_login_accepts_webauthn_or_totp_or_recovery`
- `test_second_passkey_enrolls`
- `test_t1_target_delete_refuses_without_recent_touch`
- `test_t1_requires_type_the_name`
- `test_t1_totp_does_not_write_hardware_touch_at`
- `test_t1_refused_until_two_webauthn_credentials`
- `test_t3_rollback_never_uses_require_recent_touch`
- `test_idle_timeout_expires_session`
- frontend: `rollback_restart_and_rerun_are_t3_and_never_behind_step_up` stays
  (T3 `stepUp: "none"`)
- frontend: rewrite `t1_rows_are_named_and_refused_not_weakened` — T1
  `stepUp: "required"`; after WebAuthn touch + type-the-name the action runs;
  TOTP still does not
- frontend: sim Shell mounts Login/Enroll/T1 overlay
- `test_login_webauthn_and_recovery_do_not_write_hardware_touch_at`

**Dependencies:** Task 0.

---

## Task 3 — D-012 re-land

**Title:** Re-wire declarations; invert parking tests; E2E the five attacks.

**Files:** `scanner/core.py`, `scanner/modules/fallbacks.py`,
`wizard/questions.py`, `wizard/service.py`, `wizard/materialize.py`,
`tests/test_d012_out_of_phase_1.py`, `tests/test_scanner_declarations.py`
(keep running; markers per Task 0), new `tests/test_d012_reland.py`.

**Do:** Load once in `scan()`. Heuristic axis labelled; **tier does not drop
at scan time**. Wizard acceptance is the grant. Invert the two no-import
tests. Do not rewrite `scanner/declarations.py`.

**Tests:**
- `test_declared_heuristic_still_blocks_until_wizard_accept`
- `test_proof_axis_unaffected_under_declaration`
- `test_root_declaration_warns_and_downgrades_nothing`
- `test_reason_edit_invalidates_confirm_id`
- `test_index_prepend_does_not_revive_orphaned_true`
- `test_scan_loads_declarations_module`
- existing parser tests stay green
- Each of the five attacks must go through `wizard.materialize.preflight` /
  `materialize` against a real DB, not `confirm_question_id()` alone (C1).

**Exact req ids:** `SCAN-DECLARED-TEST-MATERIAL`, `SCAN-DECLARED-GUARDS`
(full-text markers land here). Retire the Task 0 clause waiver.

**Dependencies:** Task 0.

---

## Task 4 — Attack playbook L5 + never-scale

**Title:** Detector + playbook + CloudflareEdge + attack_gate + visible state.

**Files:** `providers/cloudflare.py` (`CloudflareEdge`),
`providers/registry.py` (`edge_protection_for`), `providers/fakes.py`,
`monitor/attack_detector.py` (new), `monitor/attack_playbook.py` (new),
`scaling/attack_gate.py` (new), `monitor/pager.py` (hash click_url),
`frontend/src/screens/Sites.jsx` (AttackState), `frontend/src/screens/Home.jsx`
(banner), `tests/test_attack_playbook.py`,
`tests/test_no_token_exfiltration.py` (extend).

**Tests:**
- `test_edge_protection_for_is_the_only_constructor`
- `test_playbook_sets_under_attack_and_bans_ip`
- `test_playbook_without_edge_ref_notifies_only`
- `test_playbook_run_twice_zero_mutating_calls`
- `test_attack_playbook_engaged_is_p1`
- `test_refuse_if_attack_blocks_scale`
- `test_playbook_never_puts_edge_token_on_target`
- `test_pager_click_url_is_hash_findings`
- `test_dns_client_never_loads_edge_token_ref`
- `test_edge_client_never_loads_dns_token_ref`

**Dependencies:** Task 0. Do not edit `core/models.py` (Kind.ATTACK_PLAYBOOK is Task 1).

---

## Task 5 — Topology advisor r1–r5

**Title:** Findings on map v1, no new graph library.

**Files:** `monitor/topology.py` (new), `monitor/map_graph.py` (call-out only),
`tests/test_topology.py`, simulation seed if new states.

**Tests:**
- `test_hub_colocated_with_public_site_is_critical`
- `test_blast_radius_finding`
- `test_missing_per_site_docker_network_finding`
- `test_db_off_mesh_finding`
- `test_hub_and_public_origin_same_lan_finding`
- `test_topology_does_not_import_a_graph_library`

**Dependencies:** Task 0.

---

## Task 6 — Quarterly SSH rotation

**Title:** Dual-key playbook + Beat + T1 + host-key-mismatch Finding.

**Files:** `provision/ssh_rotate.py` (new), `core/actions.py` (`ssh.rotate`
T1),
`monitor/alert_rules.py` (`ssh-rotation-incomplete`, `ssh-rotation-stale-key`),
`core/ssh.py` (`raise_alert` on host-key mismatch), `hub/settings/base.py`
Beat `ssh-rotate-quarterly` 90 d, `tests/test_ssh_rotate.py`.

**Do:** Dual-key overlap per design note §7 C8. Private key never leaves the
vault. Never `ssh-keygen` on the target.

**Tests:**
- `test_ssh_rotate_generate_append_probe_revoke`
- `test_ssh_rotate_run_twice_zero_mutating_calls`
- `test_incomplete_rotation_is_p1`
- `test_stale_old_key_after_revoke_intended_is_p2`
- `test_overlap_is_not_a_finding`
- `test_private_key_never_leaves_vault`
- `test_ssh_rotate_is_t1`
- `test_host_key_mismatch_files_finding`

**Dependencies:** Task 0. Do not edit `core/models.py` (Kind.SSH_ROTATE is
Task 1). If Task 2 is in flight on `core/actions.py`, append only the new
tuple after Task 2 merges, or take Task 2's branch as parent.

---

## Task 7 — Backup operator surface

**Title:** Persist + Beat + P1 + Sites list + test-now + restore command block
+ restore-drill body.

**Files:** `provision/backup.py`, `provision/tasks.py` or `monitor/tasks.py`,
`hub/settings/base.py` (`backup-nightly`), views for
`GET /api/v1/sites/{id}/backups/` and
`POST /api/v1/sites/{id}/backups/{unit_id}/test/` (T2),
`frontend/src/screens/Sites.jsx`, `monitor/drills.py` (restore body),
`tests/test_backup_operator.py`.

**Do:** Persist sealed bytes at `/var/lib/deploy-hub/backups/{checkrun_pk}`
(0600). Results metadata only (`bytes` = int size). `raise_alert` on
failure **and** missing nightly. Restore is a `<pre>` command block, no POST.
Restore-drill SKIPPED only when no BackupUnit. Never the KEK. Do not edit
`core/models.py` (Kind.BACKUP + closed keys are Task 1). Task 7 takes
`Sites.jsx` **after** Task 4 (AttackState) or Task 4 exports AttackState as a
component Task 7 does not touch.

**Tests:**
- `test_backup_list_hides_key_material`
- `test_test_backup_now_seals_with_backup_key_not_kek`
- `test_restore_is_command_block_not_a_post`
- `test_no_restore_route_exists`
- `test_failed_dump_files_hub_db_or_backup_failure`
- `test_missing_nightly_files_same_kind`
- `test_restore_drill_skipped_only_when_siteless`

**Dependencies:** Task 0 + Task 1 (closed BACKUP schema). Prefer after Task 4
if both touch `Sites.jsx`.

---

## Task 8 — Leftover honesty

**Title:** D-045 retire, SEC-B4 parse, SEC-69 exhaust.

**Files:** `realtime/authorize.py`, tests that asserted the `alerts` alias,
`tests/test_redis_crown_jewel.py` (new), `docker-compose.yml` (read-only),
exhaust plugin / `scripts_dev/` as needed, `tests/test_secrets_in_exhaust.py`,
`WAIVERS.md` (retire two lines).

**Tests:**
- `test_alerts_topic_is_unauthorized`
- `test_findings_topic_unchanged`
- `test_compose_redis_unpublished_and_requirepass`
- `test_celery_serializers_are_json`
- `test_exhaust_gate_flags_plaintext_in_captured_output`
- `test_exhaust_gate_flags_plaintext_in_celery_kwargs`

**Dependencies:** Task 0. DnsZone unique is Task 1.

---

## Task 9 — Tailscale seam + skip-unless poll

**Title:** `providers/tailscale.py` + Beat + dated waiver if no ref.

**Files:** `providers/tailscale.py` (new), `providers/fakes.py`,
`monitor/tasks.py`, `hub/settings/base.py` (`HUB_TAILSCALE_API_TOKEN_REF=""`),
`monitor/alert_rules.py` (`tailscale-unknown-device` P2),
`tests/test_tailscale_devices.py`, `WAIVERS.md` only if skip.

**Tests:**
- `test_unknown_device_files_finding`
- `test_hub_created_target_is_silent`
- `test_absent_ref_skips_and_does_not_green_a_live_tier`
- `test_no_token_in_finding_or_checkrun`

**Dependencies:** Task 0. Do not edit `core/models.py` (Kind.TAILSCALE_DEVICES is Task 1).

---

## Task 10 — KmsKEK T1 adapter + DEK cache

**Title:** `providers/kms.py` port + `KmsKEK` + moto + refuse-unless-configured
+ process-memory DEK cache.

**Files:** `providers/kms.py` (new; the only module that may import boto3 for
KMS), `providers/fakes.py`, `vault/kek.py` (takes the port; **no boto3**),
`vault/service.py` (DEK cache), `hub/settings/base.py`
(`HUB_VAULT_KMS_KEY_ID` → `VAULT_KMS_KEY_ID=""`), `requirements-dev.txt`
(moto if missing), `tests/test_kms_kek.py` (**must not import boto3**).

**Tests:**
- `test_kms_kek_wrap_unwrap_with_moto`
- `test_kms_backend_refuses_unless_configured`
- `test_kms_backend_refuses_when_key_id_empty`
- `test_keyfile_backend_still_default_in_tests`
- `test_rewrap_from_local_to_kms_under_moto`
- `test_dek_cache_survives_kms_blip`
- `test_vault_and_kms_tests_do_not_import_boto3`
- **no live AWS test**

**Dependencies:** Task 0 (kek_id column already exists).

---

## Task 11 — SLIP adapters (do not block MUST demo)

**Title:** Fake audit S3 shipper skip-unless-bucket; DNS-01 stays refused;
YubiKey ② / tailnet-lock evaluation writeup.

**Files:** optional `core/audit_ship.py`, `deploys/certs.py` (refusal copy
stays “phase 4” until DNS-01 lands), `docs/` evaluation notes.

**Tests:** existing unproxied refusal tests stay. If shipper lands:
`test_fake_shipper_appends_hash_chain`; `test_absent_bucket_skips`;
`test_audit_write_does_not_block_on_s3_down`.

**Dependencies:** Task 1 for hash chain. MUST demo does not wait.

---

## Task 12 — Acceptance + demo

**Title:** `tests/acceptance/test_phase_4.py` + `conformance/demos/phase-4.md`

**Files:** those two. One acceptance test per §4 clause,
`@pytest.mark.acceptance(phase=4)`.

**Dependencies:** Tasks 1–10 (not 11).
