# Phase 2 tasks — Deploy to own machine

SDD-ready work list for Implementers. Architect design note:
`docs/phase-2-design-note.md`. Do not start a task whose dependencies are open.

## Global constraints (every task)

- Every remote effect through Transport; argv lists never interpolated strings;
  file content via put() never heredocs.
- Cloud/DNS SDK imports only under `providers/`.
- `deploys/` never reaches `scanner/` even transitively.
- Env snapshots through the vault path; no secrets in logs/task-args/build
  contexts.
- Locks in Postgres, not Redis (§A5).
- Builds on the target, never the Hub (§B1). Do not bind Hub docker.sock into
  the test target.
- Reviewer never writes the code they review. Models: Implementer is
  `grok-4.6`; review/planning seats are `fable` except Security (`grok-4.6`);
  Fable-unavailable fallback is `grok-4.6` (D-021).
- Sensitive paths (`scripts/**`, `catalog/`, `conformance/requirements.yaml`,
  CI, vault, SSH transport) wait for Joseph's merge click; still write them on
  this branch.
- Mockup-first: plain readable Python, no premature optimization.
- T1 tests with FakeTransport from the first commit; T2 image `hub-test-target`
  per D-015. T3 (Multipass, ufw truth test) is Phase 2.5 — name it out of scope.
- Cloudflare DNS adapter is Phase 3. Phase 2 may use DnsProvider fakes.
- WebAuthn is Phase 4.

Protective cut (**D-020**): the milestone that MUST ship is **deploy
`sample-node-site/` (TAKKO-shaped fixture) through the real pipeline to
`hub-test-target`, twice, with resume-from-crash and rollback.** Tasks 0–13
plus 21 (acceptance CI half) are on the cut. Tasks 14–20 may slip to Phase 2b;
slipped phase-2 registry ids then need a waiver or a phase bump.

---

## Task 0 — Unblock `check.py --phase 2` (D-017)

**Title:** Bump parked D-012 reqs off Phase 2.

**Files created/touched:**
- `DECISIONS.md` (new row D-017)
- `conformance/requirements.yaml` (sensitive) — `SCAN-DECLARED-TEST-MATERIAL`
  and `SCAN-DECLARED-GUARDS`: `phase: 4`. Do not retire them. Do not change
  `text:` or markers on `tests/test_scanner_declarations.py`.
- `docs/phase-2-design-note.md` is already the ruling; Scribe may cross-link.

**Exact req ids proven:** none (this task removes two ids from the phase-2
gate). After this, `check.py --phase 2` is no longer blocked by parked scanner
work. Remaining phase-2 ids still need the tasks below.

**Tests to write:** `tests/test_d017_declared_reqs_not_phase_2.py` —
`test_scan_declared_ids_are_phase_4` (load the registry; both ids `phase == 4`;
markers still collect).

**Dependencies:** none.

---

## Task 1 — Models and Postgres locks

**Title:** Zone / Target / SiteInstance / Deployment / OperationLock.

**Files created/touched:**
- `core/models.py` — `NetworkZone`; `Target` (zone FK, kind, host, ssh_user,
  `ssh_key_ref`, `host_key_fingerprint`, lifecycle, status); `SiteInstance`
  (`desired_image_tag`, `desired_state ∈ {running, stopped, absent}`,
  `observed_state ∈ {running, stopped, absent, unhealthy, warming}`,
  `observed_at`, `last_reconciled_at`, `consecutive_failures`, internal_port in
  20000–29999); `OperationLock` (`scope ∈ {site, target}`, `object_id`,
  `kind ∈ {deploy, provision, reconcile}`, `holder`, `acquired_at`,
  `heartbeat_at`) unique on `(scope, object_id, kind)`; `DnsRecord`;
  `SiteVolume` (per-Site name, container path, backup policy); extend `Site`
  with `exposure`, `deploy_strategy`, `deploy_policy`, `deploy_window_cron`,
  `maintenance_until`, `reconcile_enabled`, `liveness_path`, `readiness_path`,
  `warmup_timeout_s`, `config_stale`, optional `primary_target`.
- `core/locks.py` — `acquire(scope, object_id, kind, holder)` / `release` /
  `heartbeat`; INSERT, conflict = refuse; Redis is never consulted.
- `deploys/models.py` — `Deployment` (`status ∈ {queued, running, succeeded,
  failed, rolled_back, cancelled, superseded}`, `last_heartbeat`,
  `manifest` FK, `rollback_of` FK nullable); `DeploymentStep` (`seq`, `name ∈
  {build, ship, migrate, start_green, health_check, dns, route_tls,
  smoke_test, cutover}`, `status ∈ {pending, running, succeeded, failed,
  skipped}`, timestamps, `log_text`, `artifacts` JSON); `DeploymentArtifact`
  (`kind`, `content` TEXT).
- `catalog/models.py` — `AppliedCatalogEntry`.
- `core/migrations/`, `deploys/migrations/`, `catalog/migrations/`.

**Exact req ids proven:** REL-A5-POSTGRES-LOCKS (lock table exists; acquire does
not touch Redis).

**Tests to write:**
- `tests/test_locks.py` — `test_lock_lives_in_postgres_not_redis`;
  `test_second_acquire_on_same_site_deploy_refuses`;
  `test_redis_flushdb_does_not_release_held_lock`.
- `tests/test_models_phase2.py` — `test_deployment_status_enum_matches_d2`;
  `test_step_name_enum_matches_d2`; `test_site_instance_observed_warming`;
  `test_site_volume_is_per_site_not_per_deployment`.

**Dependencies:** Task 0 (can overlap; no registry coupling).

---

## Task 2 — Transport.probe seam (D-018)

**Title:** Probe vs mutate so run-twice tests can pass.

**Files created/touched:**
- `core/transport.py` — add `Transport.probe(argv, *, timeout=60)` (read-only;
  argv list; TypeError on a string). `FakeTransport.probe` records
  `("probe", list(argv))` and does **not** join `mutating_calls()`.
  `mutating_calls()` stays `[c for c in self.calls if c[0] in ("run", "put")]`.
  `RecordingTransport.probe` delegates and records.
- `tests/test_smoke.py` — existing `run(["echo", "hello"])` assertion unchanged.

**Exact req ids proven:** PIPE-D6-IDEMPOTENT-STEPS (seam only; later tasks use
it). VAL-45-SHELL-ARGLISTS (probe also rejects strings).

**Tests to write:**
- `tests/test_transport_probe.py` — `test_probe_rejects_shell_string`;
  `test_probe_is_not_a_mutating_call`;
  `test_run_and_put_still_count_as_mutating`;
  `test_get_is_not_mutating`.

**Dependencies:** none (can land in parallel with Task 1).

---

## Task 3 — SshTransport + host-key pin (T1)

**Title:** Real SSH Transport, fail-closed on host-key mismatch.

**Files created/touched:**
- `core/ssh.py` (sensitive: SSH transport) — `SshTransport(Transport)` via
  Fabric; `run`/`probe`/`put`/`get`; known_hosts from
  `Target.host_key_fingerprint`; mismatch: refuse, `audit(...,
  severity=security)`, no retry against a new key.
- `requirements.txt` / `requirements-dev.txt` — add `fabric`.
- Vault: load `Secret.Kind.SSH_PRIVATE_KEY` through `vault.service.get` only;
  never log material.

**Exact req ids proven:** SEC-68-HOSTKEY-PINNING (T1). VAL-45-SHELL-ARGLISTS
(Fabric argv, SFTP put).

**Tests to write:**
- `tests/test_ssh_transport.py` — `test_argv_must_be_a_list`;
  `test_put_does_not_build_a_heredoc`;
  `test_hostkey_mismatch_refuses_and_audits`;
  `test_matching_pin_connects` (fabric.testing / paramiko stub);
  `test_private_key_bytes_never_in_log_or_task_kwargs`.

**Dependencies:** Task 1 (Target + vault ref), Task 2 (probe on the interface).

---

## Task 4 — hub-test-target image + SSH T2

**Title:** D-015 image; real sshd; no Hub docker.sock.

**Files created/touched:**
- `images/hub-test-target/Dockerfile` (and README) — Ubuntu, systemd as PID 1,
  privileged + cgroupns=host, sshd, docker `storage-driver=vfs`, Caddy.
  Multi-arch or locally built; not an amd64-only pull (`jrei/systemd-ubuntu`
  is banned).
- `.github/workflows/push-checks.yml` (sensitive: CI) — T2 job running
  testcontainers against this image. Do **not** `-v /var/run/docker.sock`.
- `tests/conftest.py` — optional `hub_target` fixture.

**Exact req ids proven:** SEC-68-HOSTKEY-PINNING (T2 against real sshd);
SEC-B1-BUILD-OFFHUB (image recipe does not share Hub docker.sock — asserted).

**Tests to write:**
- `tests/test_hub_test_target.py` — `test_sshd_banner`;
  `test_systemd_is_pid1_running`;
  `test_sshd_t_and_dropin` (HARD-R2 shape);
  `test_inner_docker_vfs_builds`;
  `test_hub_docker_sock_not_bound`;
  `test_ssh_transport_run_and_put_roundtrip`.

**Dependencies:** Task 3.

---

## Task 5 — Catalog dataclasses + AppliedCatalogEntry writes

**Title:** Catalog-first entries; version bump = changed semantics.

**Files created/touched:**
- `catalog/entries.py` (sensitive: catalog) — dataclasses: stable `id`, integer
  `version`, `check` / `fix` / `rollback` argv lists, OS variant. First entries:
  ntp/chrony, log rotation, docker-daemon-json, sshd-dropin, ufw-posture-hub,
  ufw-posture-target, fail2ban-ignoreip, caddy. Scripts map to these ids (§Q8).
- `catalog/apply.py` — `apply_entry(target, entry, transport)` writes
  `AppliedCatalogEntry`; second apply of the same version is a no-op (probe then
  skip).
- `docs/plan/server-hardening.md` — provenance: script ↔ catalog id (same
  change as Task 6).

**Exact req ids proven:** HARD-R1-TWO-POSTURES (hub vs target vs intake argv
differ; T1 FakeTransport). (ufw truth remains Phase 2.5.)

**Tests to write:**
- `tests/test_catalog.py` — `test_entry_version_bump_is_required_for_semantics`;
  `test_apply_twice_zero_mutating_calls`;
  `test_hub_posture_has_no_public_80_443`;
  `test_target_posture_allows_80_443_from_cf_ranges_only`;
  `test_intake_posture_is_tunnel_no_public_inbound`;
  `test_fix_and_check_are_argv_lists`.

**Dependencies:** Task 1, Task 2.

---

## Task 6 — scripts/ + static gates (HARD-Q8 host set)

**Title:** Four host scripts under `scripts/`; shellcheck/shfmt/`bash -n`.

**Files created/touched:**
- `scripts/harden-ubuntu.sh`, `scripts/update-cloudflare-ufw.sh`,
  `scripts/verify-hardening.sh`, `scripts/server-watch.sh` (sensitive).
  `hub-upgrade.sh` is Task 19; this task may land a `bash -n`-clean stub with a
  `# Task 19 fills C6` header, or omit it until 19 — HARD-Q8’s “five scripts”
  is proven when 19 lands.
- `docs/plan/server-hardening.md` — provenance block, versions, V2 order
  (mesh first), R3 `HUB_MESH_IP`.
- `Makefile` + `.github/workflows/push-checks.yml` (sensitive: CI) —
  `shellcheck`, `shfmt -d`, `bash -n` over `scripts/**`; wire as
  `review-round` prereq.
- `conformance/requirements.yaml` (sensitive) — add missing `text_hash` on
  `HARD-V2-MESH-BEFORE-FIREWALL` if still absent.

**Exact req ids proven:** HARD-Q8-SCRIPTS-TESTED (partial until Task 19);
HARD-R2-SSHD-VALIDATE-FIRST; HARD-R3-IGNOREIP; HARD-V2-MESH-BEFORE-FIREWALL.

**Tests to write:**
- `tests/test_scripts_hardening.py` — `test_dry_run_mutating_nothing`
  (DRY_RUN=1 + FakeTransport or script-level; assert no sshd reload / ufw
  enable);
  `test_harden_twice_second_run_no_mutating_transport` (T2 on
  hub-test-target, D6);
  `test_sshd_t_before_reload`;
  `test_refuses_disable_password_auth_without_authorized_keys`;
  `test_ignoreip_is_hub_mesh_ip_not_tailnet_slash10`;
  `test_refuses_tailscale0_posture_off_mesh`;
  `test_update_cloudflare_ufw_aborts_on_bad_fetch`.

**Dependencies:** Task 4 (T2 container), Task 5 (ids to map).

---

## Task 7 — Provisioner fresh-host guard

**Title:** Refuse occupied 80/443; import pre-hardened baselines.

**Files created/touched:**
- `provision/service.py`, `provision/tasks.py` (queue `deploys` or `control` —
  provision is not a probe). Probe via `transport.probe`; never interpolate
  hostnames into a shell string.
- Fresh = ports 80/443 free **and** no site containers. Occupied → refuse with
  an explanation string (operator-readable). Pre-hardened + empty → allow,
  `AppliedCatalogEntry` imported from `verify-hardening.sh` / script versions.
  When a Hub Beat job matching a script cron goes live, provisioner **deletes
  that cron** (FakeTransport `run` of crontab edit, argv list).

**Exact req ids proven:** PROV-E6-FRESH-HOST-GUARD.

**Tests to write:**
- `tests/test_provision_fresh_host.py` —
  `test_occupied_80_refuses_with_explanation`;
  `test_occupied_443_refuses`;
  `test_site_container_present_refuses`;
  `test_pre_hardened_empty_host_is_allowed_and_imports_catalog_versions`;
  `test_does_not_proceed_on_refuse` (zero mutating calls after refuse).

**Dependencies:** Task 5, Task 2. T2 path: Task 4, Task 6.

---

## Task 8 — Pipeline skeleton, locks, heartbeat

**Title:** Deployment state machine + Beat sweep.

**Files created/touched:**
- `deploys/pipeline.py` — load Manifest.body only; acquire `OperationLock`
  (site + target); set `running`; persist steps; on a new deploy while one
  runs, mark the old `superseded` at the lock boundary.
- `deploys/tasks.py` — Celery on queue `deploys`; heartbeat `last_heartbeat`
  every ~30s; env snapshot = vault get of `body["env_bundle_ref"]`, AAD already
  bound to manifest id; **never** put env files in the build context or in
  task kwargs.
- `deploys/heartbeat.py` + Beat schedule — sweep `running` with heartbeat
  older than 2 min → resume (first non-succeeded step) or abort.
- `HUB_TEST_CRASH_AFTER_STEP` env for the kill-matrix (hook now, exercised in
  Task 13).

**Exact req ids proven:** PIPE-D2-STATE-MACHINE; REL-P3-RESUMABLE-DEPLOYS
(skeleton: resume pointer + lock); REL-C1-HEARTBEAT-SWEEP; REL-A5-POSTGRES-LOCKS
(deploy path).

**Tests to write:**
- `tests/test_pipeline_state.py` — `test_statuses_match_pinned_enums`;
  `test_resume_is_first_non_succeeded_step`;
  `test_rollback_is_a_new_deployment_row` (row shape; execute in Task 13);
  `test_env_snapshot_goes_through_vault`;
  `test_lock_serializes_two_deploys_same_site`.
- `tests/test_heartbeat_sweep.py` — `test_stale_running_is_resumed_or_aborted`;
  `test_fresh_heartbeat_is_left_alone`.

**Dependencies:** Task 1, Task 2.

---

## Task 9 — ensure_build + ensure_ship (steps 1–2)

**Title:** Build on the target; ship by image inspect.

**Files created/touched:**
- `deploys/steps.py` — `ensure_build(desired)`, `ensure_ship(desired)`. Tag =
  `f(git sha + manifest hash)`; exists → skip. Hub clones, `put`s a vault-free
  context, `run(["docker", "build", ...])` on the target. Generated Dockerfiles:
  `npm ci` / hash-pinned pip — assert from Manifest.body template, do not
  invoke scanner. `ensure_ship`: `docker image inspect` via **probe**; load
  only on miss.

**Exact req ids proven:** SEC-B1-BUILD-OFFHUB; PIPE-D6-IDEMPOTENT-STEPS (these
two steps).

**Tests to write:**
- `tests/test_ensure_build.py` — `test_docker_build_argv_runs_on_target_not_hub`;
  `test_build_context_contains_no_env_file_or_vault_material`;
  `test_second_build_zero_mutating_calls`;
  `test_generated_dockerfile_uses_npm_ci_or_hashed_pip`.
- `tests/test_ensure_ship.py` — `test_inspect_is_probe_not_run`;
  `test_second_ship_zero_mutating_calls`.

**Dependencies:** Task 8, Task 2. T2: Task 4.

---

## Task 10 — ensure_migrate + ensure_volume

**Title:** Migrate (backup-guarded) and per-Site volumes.

**Files created/touched:**
- `deploys/steps.py` — `ensure_migrate`, `ensure_volume`. Volume name
  `site-{slug}-data` (and further names from Manifest `volumes`). Create if
  missing; never delete here. Migrate: backup guarded by the step record
  (crashed mid-step = fresh backup); generic pre-cutover hook from the
  manifest for non-Django.

**Exact req ids proven:** PIPE-N5-VOLUMES-MODELED (ensure_volume); PIPE-D6
(these steps).

**Tests to write:**
- `tests/test_ensure_volume.py` — `test_volume_is_per_site_not_per_deployment`;
  `test_second_ensure_volume_zero_mutating_calls`;
  `test_rollback_path_does_not_call_volume_rm` (hook / explicit refuse).
- `tests/test_ensure_migrate.py` — `test_migrate_is_rerunnable`;
  `test_backup_runs_if_step_did_not_succeed`;
  `test_second_migrate_zero_mutating_calls`.

**Dependencies:** Task 9.

---

## Task 11 — start_green / recreate + readiness gate (steps 4–5)

**Title:** Deploy strategy and `/healthz.ready`.

**Files created/touched:**
- `deploys/steps.py` — `ensure_start`, `ensure_health_check`.
  `blue_green`: start green alongside, deterministic name
  `site-{slug}-{deployment_id}`, exists+healthy = adopt, exists+dead = recreate.
  `recreate` (**mandatory** when Manifest `deploy_strategy=recreate`): stop old
  writer **before** new opens the volume/DB; `maintenance_until` / probe
  suppression during the window. Step 5: poll Manifest healthz `readiness_path`
  for `{live, ready, checks}`; wait while warming-and-progressing up to
  `warmup_timeout_s`; timeout → fail (rollback in Task 13). Traffic (Caddy)
  does not switch before `ready`.

**Exact req ids proven:** PIPE-N1-DEPLOY-STRATEGY; PIPE-S4-READINESS-GATE;
PIPE-D6 (these steps).

**Tests to write:**
- `tests/test_ensure_start.py` — `test_recreate_stops_old_before_new_opens_db`;
  `test_blue_green_starts_alongside`;
  `test_local_state_site_cannot_override_off_recreate`;
  `test_second_start_zero_mutating_calls`.
- `tests/test_ensure_health.py` — `test_cutover_waits_for_ready`;
  `test_warming_progress_waits`;
  `test_stuck_warm_fails_before_timeout_if_checks_frozen`;
  `test_liveness_is_not_the_cutover_gate`.

**Dependencies:** Task 10.

---

## Task 12 — DNS fake, Caddy route, smoke, cutover, artifacts, break-glass

**Title:** Steps 6–9 + P4 snapshots + P5 runbook.

**Files created/touched:**
- `deploys/steps.py` — `ensure_dns` (FakeDnsProvider; **skipped** if
  `exposure=mesh_only`), `ensure_route_tls` (Caddy PUT-by-id `site-{slug}`;
  mesh_only binds the mesh/test interface, no CF origin cert this phase),
  `ensure_smoke` (HTTPS is Phase 3; T2 smoke = curl the Caddy route /healthz
  ready, plus ws frame if Manifest declares ws), `ensure_cutover` (grace
  deadline on the step row; old container stopped, kept for rollback).
- `deploys/artifacts.py` — snapshot Dockerfile, Caddy route, DNS set, env
  **names** (not values), firewall argv into `DeploymentArtifact`.
- `deploys/breakglass.py` — per-site markdown on the target, mode 0400,
  root-owned, **no secrets**.

**Exact req ids proven:** REL-P4-ARTIFACT-SNAPSHOTS; SEC-P5-BREAK-GLASS;
PIPE-D6 (these steps). Convert SEC-P5 and VAL-45 to `verify: test` **or** add
`gate:` keys in the same registry edit (sensitive).

**Tests to write:**
- `tests/test_ensure_dns.py` — `test_mesh_only_skips_dns`;
  `test_public_list_then_diff_upsert`;
  `test_second_dns_zero_mutating_calls`.
- `tests/test_ensure_route.py` — `test_caddy_put_by_id`;
  `test_second_route_zero_mutating_calls`.
- `tests/test_ensure_smoke_cutover.py` — `test_smoke_sees_ready`;
  `test_cutover_after_ready_not_before`;
  `test_ws_smoke_when_manifest_declares_ws` (T1 fake).
- `tests/test_artifacts.py` — `test_every_generated_artifact_snapshotted`;
  `test_artifact_has_no_secret_values`.
- `tests/test_breakglass.py` — `test_runbook_mode_0400`;
  `test_runbook_contains_no_vault_plaintext`.

**Dependencies:** Task 11, Task 5. T2 Caddy: Task 4.

---

## Task 13 — Rollback, crash kill-matrix, run-twice on the fixture

**Title:** MUST-demo path: twice, resume, rollback; volumes survive.

**Files created/touched:**
- `deploys/pipeline.py` — rollback enqueues a **new** Deployment that
  re-applies the target deployment’s artifacts; does not `docker volume rm`.
- Kill-matrix: `HUB_TEST_CRASH_AFTER_STEP=n` SIGKILL, parametrized over steps
  1–9; resume from first non-succeeded.
- T2: deploy `sample-node-site/` to hub-test-target twice.

**Exact req ids proven:** REL-P3-RESUMABLE-DEPLOYS; REL-P4-ARTIFACT-SNAPSHOTS
(rollback); PIPE-D6-IDEMPOTENT-STEPS (full pipeline); PIPE-N5-VOLUMES-MODELED
(survive rollback); PIPE-N1 + PIPE-S4 on the fixture.

**Tests to write:**
- `tests/test_rollback.py` — `test_rollback_is_new_deployment_row`;
  `test_rollback_reapplies_artifact_set`;
  `test_rollback_does_not_remove_named_volume`.
- `tests/test_crash_kill_matrix.py` — `test_crash_after_step_n_resumes`
  (parametrize 1–9).
- `tests/test_pipeline_sample_node_site.py` — `test_deploy_twice_second_zero_mutating`;
  `test_volume_survives_second_deploy`;
  `test_recreate_old_writer_stopped_first`.

**Dependencies:** Task 12, Task 4. **D-020 MUST line is this task green.**

---

## Task 14 — Git polling + deploy_policy (Phase 2b-able)

**Title:** Beat poller; no webhook; windowed queue.

**Files created/touched:**
- `deploys/poller.py` — Beat 1–5 min, compare branch head to last deployed sha;
  enqueue `deploys.tasks` only. **No** Django URL for GitHub webhooks.
- Guard: `deploy_policy=confirm` → do not auto-enqueue; `windowed` → queue
  outside the cron window and emit a deploy-waiting notice (Finding or
  AuditEvent + realtime event). Manual deploy inside a blocked window: T2
  confirm is Phase 3 UI; this phase records the warning on the Deployment.

**Exact req ids proven:** PIPE-M2-GIT-POLLING; PIPE-N8-DEPLOY-POLICY.

**Tests to write:**
- `tests/test_git_poller.py` — `test_new_head_enqueues_deploy`;
  `test_same_head_does_not_enqueue`;
  `test_no_webhook_url_route_exists`;
  `test_non_tailnet_cannot_hit_a_deploy_trigger_route`.
- `tests/test_deploy_policy.py` — `test_confirm_does_not_auto_deploy`;
  `test_windowed_outside_window_queues_waiting_notice`;
  `test_auto_inside_window_enqueues`.

**Dependencies:** Task 8.

---

## Task 15 — DB provisioner + backup registry stub (Phase 2b-able)

**Title:** Ensure Postgres/role; BackupUnit; KEK never in dumps.

**Files created/touched:**
- `provision/db.py` — on first deploy, ensure Postgres container + role on the
  target; `vault.service.put` DATABASE_URL; inject via env bundle (not build
  context).
- `core/models.py` — `BackupUnit` (`kind ∈ {postgres, sqlite_file,
  directory_sync}`, site FK, schedule). Beat stub: `pg_dump | age` (or sqlite
  `.backup` / directory sync) with a **backup** key distinct from the KEK;
  alert-on-failure is a logged AuditEvent this phase (ntfy is Phase 3).
- Backup key in vault; Hub `pg_dump` fixtures used in tests must not contain
  the KEK.

**Exact req ids proven:** SEC-69-KEK-NEVER-IN-BACKUPS. (§E5/§N6 machinery;
no dedicated registry id beyond KEK.)

**Tests to write:**
- `tests/test_db_provisioner.py` — `test_ensures_postgres_role_and_vaults_url`;
  `test_second_ensure_zero_mutating_calls`;
  `test_database_url_not_in_build_context`.
- `tests/test_backup_registry.py` — `test_backup_unit_kinds`;
  `test_dump_is_age_encrypted_not_plaintext`;
  `test_kek_absent_from_hub_db_dump`;
  `test_kek_absent_from_site_backup_bytes`.

**Dependencies:** Task 10, Task 8.

---

## Task 16 — Env lifecycle (Phase 2b-able)

**Title:** Config-stale + apply same image (steps 4–9).

**Files created/touched:**
- `deploys/env.py` + DRF serializers/views for per-site env names (values
  write-only through vault). Add/edit/delete sets `Site.config_stale`. Apply
  enqueues a Deployment that skips build/ship and runs 4–9 with the existing
  image tag.
- Frontend can wait; T1 API + service are the phase gate. No secrets in
  GET bodies or logs.

**Exact req ids proven:** PIPE-D2-STATE-MACHINE (env through vault on this
path). SEC-69-NO-SECRETS-IN-EXHAUST remains phase 1 / waived — do not regress.

**Tests to write:**
- `tests/test_env_lifecycle.py` — `test_put_env_marks_config_stale`;
  `test_apply_skips_build_and_ship`;
  `test_get_lists_names_not_values`;
  `test_values_not_in_task_kwargs_or_logs`.

**Dependencies:** Task 12.

---

## Task 17 — Reconciler + brakes + staleness policy (Phase 2b-able)

**Title:** Desired vs observed; never restart on feed-stale.

**Files created/touched:**
- `reconcile/loop.py`, `reconcile/tasks.py` (queue `probes`) — Beat;
  `ensure_*` imported from `deploys.steps` (same primitives). Re-probe + lock
  re-check immediately before mutation.
- Brakes: `maintenance_until` (observe, do not act); per-resource backoff after
  3 failed convergences + one alert + manual re-arm; flap → pause; global
  budget + jitter; `reconcile_enabled` kill switch (step-up is Phase 4; a
  boolean + audit is enough now).
- Observed `unhealthy` → restart once then backoff; `warming` → do not count
  toward down-hysteresis. Data-staleness / `upstream-down` → **no** restart
  (§N3).

**Exact req ids proven:** REL-P1-RECONCILER; REL-C2-RECONCILER-BRAKES;
ALERT-N3-STALENESS-NEVER-RESTARTS.

**Tests to write:**
- `tests/test_reconciler.py` — `test_drift_container_converged`;
  `test_noop_on_converged_zero_mutating_calls`;
  `test_maintenance_until_does_not_mutate`;
  `test_backoff_after_three_failures`;
  `test_flap_pauses`;
  `test_kill_switch_stops_mutations`;
  `test_reprobe_before_mutate`.
- `tests/test_reconciler_staleness.py` —
  `test_data_stale_does_not_restart`;
  `test_upstream_down_never_restarts`;
  `test_unhealthy_live_restarts_once`.

**Dependencies:** Task 12, Task 8.

---

## Task 18 — Collector JSON contract (Phase 2b-able)

**Title:** One SSH session per target per minute.

**Files created/touched:**
- `monitor/collector.py` (queue `probes`) — one `probe`/`run` of a small
  on-target script returning the pinned JSON (design note §2). Per-target
  jitter `hash(target_id) mod 60`. Hub mesh IP already whitelisted by Task 6.
- Script content delivered with `put`, not a heredoc.

**Exact req ids proven:** REL-C3-ONE-COLLECTOR-SESSION.

**Tests to write:**
- `tests/test_collector.py` — `test_one_session_returns_full_contract`;
  `test_contract_has_metrics_containers_log_chunk_clock_healthz`;
  `test_jitter_is_stable_per_target`;
  `test_script_put_not_heredoc`;
  `test_two_collectors_do_not_open_three_ssh_sessions`.

**Dependencies:** Task 2, Task 4 (T2), Task 17 (healthz consumers share the
contract — can land just after Task 11 if 17 slips).

---

## Task 19 — hub-upgrade.sh (Phase 2b-able)

**Title:** Who deploys the deployer.

**Files created/touched:**
- `scripts/hub-upgrade.sh` (sensitive) — wait for no running Deployment;
  `pg_dump`; pull + build; migrate; SIGTERM Celery; smoke login + one probe
  cycle; previous image kept; `--rollback`.
- `docs/plan/server-hardening.md` — version bump, same change.

**Exact req ids proven:** HARD-Q8-SCRIPTS-TESTED (the fifth script).

**Tests to write:**
- `tests/test_hub_upgrade_script.py` — `test_bash_n_clean`;
  `test_refuses_when_deployment_running`;
  `test_rollback_flag_documented`;
  `test_dump_does_not_include_kek` (ties SEC-69-KEK-NEVER-IN-BACKUPS).

**Dependencies:** Task 6 (script layout + CI gates), Task 8 (Deployment
rows to wait on).

---

## Task 20 — Simulation states (Phase 2b-able)

**Title:** warming / data-stale / single-instance / recreate-down in the seed.

**Files created/touched:**
- `simulation/seed_v0.json` (or `seed_v1.json` if v0 must stay byte-stable —
  prefer extending v0 with new events).
- `realtime/simulation.py` if the replayer needs new topics
  (`site.{id}.status` warming, data-stale badge).
- UX-F8: convert to `verify: test` **or** add a `gate:` Makefile target in
  the same registry edit (sensitive).

**Exact req ids proven:** UX-F8-SIMULATION-STATES.

**Tests to write:**
- `tests/test_simulation.py` (extend) —
  `test_seed_includes_warming`;
  `test_seed_includes_data_stale`;
  `test_seed_includes_single_instance`;
  `test_seed_includes_recreate_site_down_impact`;
  `test_seed_includes_deploy_failure_at_a_named_step`.

**Dependencies:** Task 11 (states exist in the model).

---

## Task 21 — Acceptance, demos, phase gate

**Title:** `check.py --phase 2` can go green.

**Files created/touched:**
- `tests/acceptance/test_phase_2.py` — one test per milestone clause,
  `@pytest.mark.acceptance(phase=2)` + `@pytest.mark.req(...)`.
- `conformance/demos/phase-2.md` (+ artifacts dir) — TAKKO real-pipeline
  record; REL-P2 Hub-stopped-site-serves record (duration honest: T2 chaos
  now, 24h when a live site exists).
- `conformance/requirements.yaml` (sensitive) — add `P2-PIPELINE-DEMO`
  (`verify: demo`, `phase: 2`, `demo:` paths) mirroring `P1-SCAN-DEMO`.
  Any remaining `verify: checklist` phase-2 ids (`VAL-45`, `SEC-P5`, `UX-F8`)
  must have `gate:` keys that are `review-round` prereqs **or** be converted
  to `verify: test` in the task that wrote the tests.
- `conformance/paths.yaml` — map new modules to req ids.

**Exact req ids proven:** REL-P2-HUB-DOWN-SITES-UP (demo record);
all Task 13 reqs via acceptance transcription; P2-PIPELINE-DEMO once added.

**Tests to write:**
- `tests/acceptance/test_phase_2.py` —
  `test_sample_node_site_deploys_to_hub_test_target`;
  `test_second_deploy_zero_mutating_calls`;
  `test_resume_from_crash`;
  `test_rollback_reapplies_artifacts`;
  `test_named_volume_survives`;
  `test_build_not_on_hub`;
  `test_mesh_only_skips_dns`;
  `test_no_webhook_route`.

**Dependencies:** Task 13 (MUST). Tasks 14–20 as needed for full
`check.py --phase 2` without waivers. If D-020 is taken, this task files
`WAIVERS.md` lines (or phase bumps) for slipped ids instead of pretending
they shipped.
