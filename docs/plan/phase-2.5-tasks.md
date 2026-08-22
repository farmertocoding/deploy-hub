# Phase 2.5 tasks — Test harness completion

SDD-ready work list for Implementers. Architect design note:
`docs/phase-2.5-design-note.md`. Do not start a task whose dependencies are open.
Do not start implementation from this design session.

**Branch:** cut `phase-2.5` from `phase-2` @ `2d6e99c` before the first product
commit. Never implement on `master`. Sensitive paths still wait for Joseph's
merge click; still write them on `phase-2.5`.

## Global constraints (every task)

- Assembly, not retrofit. Reuse Transport, `execute`, heartbeat sweep,
  `hub-test-target`, FakeDns, provisioner, catalog, `make review-round`.
- Every remote effect through Transport; argv lists never interpolated strings;
  file content via `put()` never heredocs.
- Cloud/DNS SDK imports only under `providers/`.
- `deploys/` never reaches `scanner/` even transitively.
- Env snapshots through the vault path; no secrets in logs/task-args/build
  contexts. Prod vault material never enters the harness (§B9).
- Locks in Postgres, not Redis (§A5).
- Builds on the target, never the Hub (§B1). Do not bind Hub docker.sock into
  any test target or Multipass VM.
- Reviewer never writes the code they review. Implementer `grok-4.6`; review
  seats follow D-014 / D-021.
- Sensitive paths (`scripts/**`, `catalog/`, `conformance/requirements.yaml`,
  `conformance/check.py`, CI, vault, SSH transport, `providers/`,
  `core/ssh.py` once Task 3 lands) wait for Joseph's merge click.
- Mockup-first: plain readable Python, no premature optimization.
- T1 = FakeTransport / no Multipass. T2 = `hub-test-target` (D-015, vfs).
  T3 = Multipass locally. T4 / WebAuthn is Phase 4 — do not require it.
- Cloudflare **product** adapter is Phase 3. This phase may add a **test-plane
  only** DnsProvider (D-028).
- GitHub Actions billing is broken (D-022). SHA pins already exist. Design
  around **local Multipass**. Optional dormant GHA QEMU recipe only. Do not
  require paid Actions for the phase gate.
- `make review-round` stays T1-fast (D-022 Cloud Agent). T3 is `make test-t3`
  / `make nightly` / `make conformance-2.5`.
- Skipped or xfailed T3 tests **never** verify a `tier: t3` req (D-024).
  `skipped-only` is red unless a dated `WAIVERS.md` line names the host.
  A T1 sibling pass must not make a `tier: t3` req `verified`.
- Do not edit `REVIEW_CHECKLIST.md` in the same round it judges. Registry
  edits are Task 0 (sensitive) and a later Scribe pass may follow.

Protective cut (**D-031**): MUST = Tasks 0–4, 6–11, 13–14, 16. Tasks 5, 12, 15
may slip with an honest waiver (alpine / LE-absent / drain-TOCTOU).

---

## Task 0 — Unblock `check.py --phase 2.5` (D-024, D-029)

**Title:** Float phases, `tier: t3`, review-round does not demand Multipass.

**Files created/touched:**
- `DECISIONS.md` — rows D-023…D-031 (text from the design note).
- `conformance/check.py` (sensitive) — `--phase` type `float` (today
  `type=int`, so `2.5` is impossible). Add `--exclude-tier` (repeatable).
  A req may carry `tier: t1|t2|t3` (default `t1`). **`tier: t3` is `verified`
  only if ≥1 `@pytest.mark.t3` marked test passed** and none failed. A T1
  test that carries a `tier: t3` req id is red (wrong marker). `skipped` /
  `xfailed` still never count as verified (existing rule 2).
- `conformance/requirements.yaml` (sensitive) — add the ids in design note
  §3 (`phase: 2.5`). Do not bump `REL-P2-HUB-DOWN-SITES-UP` off phase 2; do
  not retire the 24h waiver. Do not edit `REVIEW_CHECKLIST.md` here.
- `Makefile` — keep `conformance` as `--phase 2.5 --exclude-tier t3` so
  `review-round` stays T1. Add `conformance-2.5` (`--phase 2.5`, all tiers)
  and do **not** make it a `review-round` prerequisite.
- `tests/conftest.py` — T1 default markexpr becomes `not t2 and not t3`.
  Extend the T2 deselect bookkeeping to T3 so `-m "not t2 and not t3"` still
  writes `full_run: true` and records T2/T3 nodeids as `skipped`.
- `pyproject.toml` — register marker `t3: live Multipass / T3 e2e (Phase 2.5)`.
- `tests/test_conformance_gate.py` — extend the existing T2 skip cases.

**Exact req ids proven:** HARNESS-T3-SKIP-POLICY (the gate rule itself).

**Tests to write:**
- `tests/test_conformance_gate.py` —
  `test_phase_accepts_two_point_five`;
  `test_t3_tier_req_not_verified_by_t1_sibling`;
  `test_t3_tier_req_skipped_only_when_all_t3_skipped`;
  `test_t3_tier_req_verified_only_after_t3_pass`;
  `test_exclude_tier_t3_omits_t3_reqs_from_due_set`;
  `test_t1_default_markexpr_deselects_t3_and_stays_full_run`
  (update `test_t2_deselect_is_skipped_and_full_run` for the new markexpr).
- `tests/test_d023_actions_not_required.py` —
  `test_phase_2_5_gate_is_make_conformance_2_5_not_a_gha_check`
  (Makefile has `conformance-2.5`; no test asserts a green GitHub Check).

**Dependencies:** none.

---

## Task 1 — `HUB_TEST_MODE` credential wall (§B9)

**Title:** Refuse non-test zones; prod vault never in the harness.

**Files created/touched:**
- `hub/settings/base.py` — `HUB_TEST_MODE` (env, default `False`);
  `HUB_TEST_ZONE_SLUGS` (comma-separated env, default `hub-test`).
- `hub/settings/dev.py` / pytest — tests set `HUB_TEST_MODE=True` via
  `override_settings` or a pytest settings snippet; do not flip prod default.
- `core/models.py` + `core/migrations/` — `NetworkZone.purpose ∈ {prod, test}`,
  default `prod` (existing rows fail-closed under test mode).
- `core/test_mode.py` — `assert_test_zone(zone)` raises a named
  `TestModeError` if `HUB_TEST_MODE` and `zone.purpose != test` **or**
  `zone.slug not in HUB_TEST_ZONE_SLUGS`. Call from provision, `execute`,
  and any DnsProvider mutate (Task 12 adapter uses the same helper).
- `deploys/pipeline.py` — call `assert_test_zone(site.primary_target.zone)`
  at the start of `execute` when settings say so.
- `provision/service.py` — same guard before any mutating `run`/`put`.

**Exact req ids proven:** HARNESS-B9-TEST-MODE.

**Tests to write:**
- `tests/test_hub_test_mode.py` —
  `test_prod_zone_refused_when_test_mode`;
  `test_test_zone_off_allowlist_refused`;
  `test_test_zone_on_allowlist_allowed`;
  `test_execute_does_not_mutate_after_refuse`
  (`mutating_calls() == []`);
  `test_provision_does_not_mutate_after_refuse`;
  `test_test_mode_false_does_not_raise_on_prod_zone`
  (operator path still works when the flag is off);
  `test_no_prod_vault_env_names_in_harness_modules`
  (grep `tests/harness/**` + `providers/test_dns.py` for vault prod key
  names / `HUB_VAULT_KEYFILE` defaults — none).

**Dependencies:** Task 0 (can overlap; no registry coupling beyond the new id).

---

## Task 2 — `CheckRun` + missed-drill detector

**Title:** Drills write rows; a skipped drill is visible.

**Files created/touched:**
- `core/models.py` + `core/migrations/` — `CheckRun(kind, status ∈
  {scheduled, running, succeeded, failed, skipped}, started, finished,
  due_at, results JSON with schema_version)`. Kinds pinned:
  `hub_down`, `restore_clean`, `reaper`, `pager`.
- `monitor/drills.py` — `record_run(kind, status, results=None)`;
  `find_missed(now)` → kinds whose latest `due_at` is past and have no
  succeeded/failed row after that due.
- `monitor/tasks.py` — `detect_missed_drills` (queue `probes`): for each
  missed kind, `audit("drill-missed", …, severity="warning")`. ntfy is
  Phase 3 — do not add it.
- `hub/settings/base.py` — Beat entry `detect-missed-drills` every hour.

**Exact req ids proven:** HARNESS-DRILLS-BEAT (row + detector; job bodies
are Task 13).

**Tests to write:**
- `tests/test_checkrun.py` —
  `test_checkrun_statuses_match_pinned_enums`;
  `test_results_require_schema_version`;
  `test_missed_due_run_is_detected`;
  `test_fresh_succeeded_run_is_not_missed`;
  `test_skipped_status_is_still_a_written_row`
  (skip is recorded, not silent);
  `test_missed_drill_writes_audit_event`.

**Dependencies:** Task 0.

---

## Task 3 — `core/ssh.py` sensitive-path custody

**Title:** Adversarial Important leftover — SSH transport is human-merge.

**Files created/touched:**
- `conformance/paths.yaml` — add `core/ssh.py` next to `core/transport.py`
  (comment: SSH transport, host-key pin).
- `.github/CODEOWNERS` — `/core/ssh.py @farmertocoding`.
- Do not change `core/ssh.py` itself unless a test requires a comment.

**Exact req ids proven:** PROC-SENSITIVE-HUMAN-MERGE remains **waived**
(Actions billing / no branch-protection gate). This task makes the glob
honest; it does not retire the waiver by inventing a green GHA job.

**Tests to write:**
- `tests/test_proc_rules.py` (extend) —
  `test_core_ssh_py_is_on_sensitive_paths`;
  `test_codeowners_lists_core_ssh_py`.
  Reuse the existing paths.yaml / CODEOWNERS readers; do not add a fake
  `gate:` that only echoes.

**Dependencies:** none (parallel with Tasks 1–2).

---

## Task 4 — Shared T2 `hub_target` fixture

**Title:** One session fixture; stop copying the container launcher.

**Files created/touched:**
- `tests/harness/__init__.py`
- `tests/harness/target.py` — move `HubTarget`, `hub_target`, `_docker`,
  `_exec`, `_wait_tcp`, `_wait_exec`, `_docker_available`,
  `_presented_fingerprint` out of `tests/test_hub_test_target.py`. Keep
  the contract: privileged + `cgroupns=host`, publish `127.0.0.1::22`,
  **never** `-v /var/run/docker.sock`, image `hub-test-target:local`.
- `tests/conftest.py` — do **not** auto-import the fixture into every
  test (T1 must stay container-free). Export from `tests/harness/target.py`;
  T2 modules import it.
- `tests/test_hub_test_target.py` — import the shared fixture; keep the
  named tests.
- `tests/test_pipeline_sample_node_site.py` — delete the duplicated
  `hub_target` / helpers; import the shared one.
- `tests/test_scripts_hardening.py` — already imports helpers from
  `test_hub_test_target`; point at `tests.harness.target`.

**Exact req ids proven:** none new. SEC-B1 / SEC-68 existing T2 tests must
still collect and pass under `make test-t2`.

**Tests to write:**
- `tests/test_harness_target.py` —
  `test_hub_target_run_argv_never_binds_docker_sock`
  (inspect the launcher argv list);
  `test_t2_modules_share_one_hub_target_definition`
  (ast/import: `test_pipeline_sample_node_site` has no `docker run` helper
  of its own).

**Dependencies:** none. Needed before Tasks 6–7.

---

## Task 5 — `sample-site/` + T2 alpine vs real image (D-025, D-030)

**Title:** Django fixture exists; try real node image on vfs.

**Files created/touched:**
- `sample-site/` — **this tree does not have it.** Minimal Django/ASGI
  app: `/healthz` JSON `{live, ready, checks}`, delayed-ready optional,
  `uv.lock` or hash-pinned requirements, Dockerfile with `pip
  install --require-hashes` or `uv sync --frozen`. No secrets. Small
  enough for T3 overlay2 and, if possible, T2 vfs.
- `tests/test_pipeline_sample_node_site.py` — one session, try
  `dockerfile_template` from the fixture (or `NPM_CI_DOCKERFILE` in
  `tests/pipeline_fakes.py`) on `hub-test-target`. Timebox: if
  `docker build` fails on vfs or exceeds ~4 min, **keep** `T2_DOCKERFILE`
  alpine COPY stub and **keep**
  `WAIVED: tests.test_pipeline_sample_node_site+PIPE-S4-READINESS-GATE+t2-instant-ready-stub`.
  If it works: delete `T2_SERVE_PY` / `T2_DOCKERFILE`, retire that waiver
  line, and assert `/healthz.ready` is not instant-stub.
- `docs/plan/server-hardening.md` — no change unless a script version
  moves (it should not).

**Exact req ids proven:** PIPE-S4-READINESS-GATE on T2 **only if** the
real image lands. Q7-NODE-FIXTURE already phase 1. New fixture has no
registry id until Task 16 demo.

**Tests to write:**
- `tests/test_sample_site_fixture.py` —
  `test_sample_site_healthz_contract_on_disk`
  (a module-level GET handler or urls.py declares `{live, ready, checks}`);
  `test_sample_site_dockerfile_uses_npm_ci_or_hashed_pip`.
- `tests/test_pipeline_sample_node_site.py` —
  `test_t2_real_node_image_builds_on_vfs` **or**, if vfs refuses, a
  documented skip that does **not** carry PIPE-S4 (the waiver stays).
- `tests/test_pipeline_sample_site.py` —
  `test_t1_deploy_sample_site_twice_zero_mutating` (FakeTransport, same
  shape as the node-site T1).

**Dependencies:** Task 4 for the T2 attempt.

---

## Task 6 — SIGKILL / T2 worker-death kill-matrix

**Title:** Live process death, not in-process `RuntimeError`.

**Files created/touched:**
- `deploys/pipeline.py` — keep `HUB_TEST_CRASH_AFTER_STEP` → `RuntimeError`
  (Phase 2 T1). Add `HUB_TEST_CRASH_SIGNAL=SIGKILL`: after `ensure_*` for
  the named step, `os.kill(os.getpid(), signal.SIGKILL)`. Do not catch it.
- `deploys/management/commands/hub_execute.py` (or a `python -c` module
  `deploys/worker_entry.py`) — load one Deployment pk and call `execute`.
  The T2 test SIGKILLs **this child**, not the pytest process.
- `tests/test_crash_kill_matrix.py` — unchanged T1 matrix.
- `tests/test_crash_kill_matrix_sigkill.py` — new.

**Exact req ids proven:** REL-P3-WORKER-DEATH. Do not move REL-P3-RESUMABLE-DEPLOYS
off the T1 RuntimeError tests.

**Tests to write:**
- `tests/test_crash_kill_matrix_sigkill.py` —
  `test_sigkill_after_step_n_child_dies_parent_survives` (parametrize
  steps 1, 5, 9 — full 1–9 if T1-cheap via subprocess + FakeTransport;
  T2 live only needs one mid-pipeline step if the T1-subprocess matrix
  is complete);
  `test_heartbeat_sweep_resumes_sigkilled_child`
  (child SIGKILL → `last_heartbeat` stale → `sweep_stale_deployments` /
  second `execute` → `succeeded`);
  `test_runtimeerror_hook_still_raises_in_process`
  (do not break Task 13 Phase 2 tests).
- T2 (optional in the same file, `@pytest.mark.t2`):
  `test_t2_sigkill_worker_resumes_on_hub_test_target`
  — child uses `SshTransport` + `hub_target`; SIGKILL after step 4 or 5;
  sweep + second execute reaches succeeded. Skip only if docker missing
  (existing T2 pattern).

**Dependencies:** Task 4. T1-subprocess half does not need Task 4.

---

## Task 7 — toxiproxy SSH timeout → resume

**Title:** Fault on the SSH path; heartbeat sweep resumes.

**Files created/touched:**
- `tests/harness/toxiproxy.py` — start `ghcr.io/shopify/toxiproxy` (or
  `shopify/toxiproxy`) via argv `docker run`, never a shell string.
  Listen on `127.0.0.1:0` (or a fixed test port), forward to
  `hub_target.host:hub_target.port`. Helpers: `add_proxy`, `toxic_timeout`
  (downstream timeout), `reset`. Tear down in `finally`.
- `tests/test_toxiproxy_resume.py`
- `requirements-dev.txt` — only if a tiny HTTP client is not enough;
  prefer stdlib `urllib` against toxiproxy's API (`POST /proxies/.../toxics`).

**Exact req ids proven:** HARNESS-T3-TOXIPROXY (T2 is enough for MUST;
T3 Multipass leg is Task 11 reuse).

**Tests to write:**
- `tests/test_toxiproxy_resume.py` —
  `test_ssh_timeout_mid_deploy_resumes`
  (`@pytest.mark.t2`): `SshTransport` connects through the proxy;
  after step 2 or 4 inject timeout; in-flight `execute` fails or the
  child dies; clear toxic; heartbeat sweep / second `execute` →
  `succeeded`; no Hub docker.sock;
  `test_proxy_teardown_removes_container`;
  `test_argv_never_a_shell_string`.
- T1 (no docker toxiproxy): `test_timeout_on_transport_is_not_a_succeeded_step`
  — FakeTransport raises on a mid-step `run`; step stays non-succeeded
  (regression guard for the resume pointer).

**Dependencies:** Task 4, Task 6 (resume after death already exists).

---

## Task 8 — `--restart unless-stopped`

**Title:** REL-P2 leftover: site survives Hub stop and a target reboot later.

**Files created/touched:**
- `deploys/steps.py` — `_docker_run_argv` always inserts
  `--restart`, `unless-stopped` before the image tag (never via a
  interpolated string).
- Caddy unit on `hub-test-target` / Multipass already systemd-enabled;
  do not add a second restart policy on Caddy unless a T1 test shows
  the site route dies when Caddy is not in the image's unit.

**Exact req ids proven:** REL-P2-DRILL-STUB (dependency only). Does not
retire the REL-P2 24h waiver.

**Tests to write:**
- `tests/test_ensure_start.py` (extend) —
  `test_docker_run_argv_includes_restart_unless_stopped`;
  `test_restart_flag_is_literal_argv_not_shell`.
- `tests/test_rollback.py` (extend if needed) —
  `test_rollback_run_argv_still_has_unless_stopped`.

**Dependencies:** none (can land with Task 1). Needed before Task 13's
Hub-down stub.

---

## Task 9 — Multipass driver + anti-silent-green skip (D-023, D-024)

**Title:** T3 launcher; skip cannot green the phase gate.

**Files created/touched:**
- `tests/harness/multipass.py` — `multipass_available()` (`multipass
  version` argv, timeout 5s). `launch(name, cpus, mem, disk, image=
  "22.04")` → `MultipassVM(name, ipv4, user)`. `exec(vm, argv)` via
  `multipass exec <name> --` + argv list. `transfer` via `multipass
  transfer`. `delete_purge(name)` idempotent. Name prefix
  `hub-t3-` (reaper key). Cloud-init: sshd, a one-shot deploy user,
  **no** Hub docker.sock.
- `tests/harness/reaper.py` — `reap_test_plane()`: `multipass list` →
  delete+purge every `hub-t3-*` (and any name tagged in a local
  `.t3-lease` file under `tmp`). Never touch names outside the prefix.
- `tests/test_t3_skip_policy.py` — T1, always runs.

**Exact req ids proven:** HARNESS-T3-SKIP-POLICY (host probe);
HARNESS-REAPER-TEST-PLANE (prefix-only, T1 Fake/listing double).

**Tests to write:**
- `tests/test_t3_skip_policy.py` —
  `test_t3_marker_registered`;
  `test_make_test_deselects_t3`;
  `test_t3_only_req_is_skipped_only_not_verified`
  (throwaway tree like `test_conformance_gate.py`: a `tier: t3` req
  whose only test is skipped → `skipped-only`, check.py non-zero unless
  waived);
  `test_host_without_multipass_waiver_does_not_verify_when_multipass_present`
  (throwaway tree: plant the waiver fingerprint, mock
  `multipass_available() is True`, assert check.py still red / a helper
  `waiver_illegal_if(probe)` refuses). Do **not** require the real
  `WAIVERS.md` line until Task 16;
  `test_t3_skipif_does_not_use_pytest_skip_in_t1_modules`.
- `tests/test_t3_reaper.py` —
  `test_reaper_only_matches_hub_t3_prefix`;
  `test_reaper_idempotent_on_absent_name`;
  `test_reaper_refuses_bare_name_without_prefix`.

**Dependencies:** Task 0 (tier rule), Task 2 (CheckRun unused here but
reaper drill kind exists).

---

## Task 10 — T3 provision + ufw/fail2ban truth

**Title:** Real VM, real harden; container ufw is not this test.

**Files created/touched:**
- `tests/test_t3_ufw_truth.py` — `@pytest.mark.t3`. Launch Multipass
  (Task 9), copy `scripts/harden-ubuntu.sh` + `verify-hardening.sh` via
  `multipass transfer` (not a heredoc over ssh). `PROFILE=target`
  `HUB_MESH_IP` = a dummy mesh IP the script will whitelist **or** skip
  the mesh-before-firewall refuse by bringing up a loopback stand-in
  only if `harden-ubuntu.sh` allows a documented `HUB_T3_ALLOW_NO_MESH=1`
  **test-only** env that the script accepts when `HUB_TEST_MODE` equivalent
  is set — **prefer** installing tailscale in the VM if the image can;
  if it cannot, the test asserts `verify-hardening.sh` fail-closed on
  mesh-before-firewall and then applies the target ufw rules with a
  named `HUB_T3_UFW_ONLY=1` that still enables ufw and fail2ban.
  Assert: `ufw status` is `active` on a **VM** (not a container);
  fail2ban `is-active`; ignoreip is **not** `100.64.0.0/10`;
  `verify-hardening.sh` exits 0. `docker info` storage driver
  `overlay2`. Teardown + reaper in `finally`.
- Do **not** run this against `hub-test-target` (D-015 false-green).

**Exact req ids proven:** HARNESS-T3-UFW-TRUTH (`tier: t3`); HARD-R1 /
HARD-R3 **additional** T3 markers (T1 tests already verify argv).
HARD-V2: if mesh cannot come up, do not mark HARD-V2 on the skip path.

**Tests to write:**
- `tests/test_t3_ufw_truth.py` —
  `test_ufw_active_on_multipass_vm`;
  `test_fail2ban_active_on_multipass_vm`;
  `test_ignoreip_is_not_tailnet_slash10`;
  `test_verify_hardening_target_profile_passes`;
  `test_inner_docker_is_overlay2_not_vfs`;
  `test_not_running_inside_hub_test_target`
  (hostname / `systemd-detect-virt` is `kvm`/`qemu`/`multipass`, not
  `docker`).
- Skip decorator: `@pytest.mark.skipif(not multipass_available(),
  reason="multipass is not available")` **and** `@pytest.mark.t3`.
  That skip is `skipped-only` for HARNESS-T3-UFW-TRUTH — red unless
  waived (Task 16).

**Dependencies:** Task 9. Scripts already exist (Phase 2 Task 6).

---

## Task 11 — T3 dual-fixture HTTP deploy + v2 + rollback + reaper

**Title:** MUST nightly body without LE.

**Files created/touched:**
- `tests/harness/t3_deploy.py` — helpers: enroll VM as `Target` in a
  `purpose=test` zone (Task 1), generate SSH keypair, pin host key,
  `provision_host` (fresh-host), `execute` `sample-site/` then
  `sample-node-site/` (or parametrize two tests), HTTP GET ready,
  second deploy (v2), rollback, timing, `finally: reap`.
- `tests/test_t3_deploy.py` — `@pytest.mark.t3`.
- `deploys/pipeline.py` / steps — no product rewrite; wire
  `--restart` from Task 8. Node-site: assert readiness before Caddy
  cutover (existing step 5); named volume `site-{slug}-data` inspect
  after v2; open **one `ws://`** through on-VM Caddy (not Cloudflare)
  and receive one frame (Q7 local half).
- Rollback clock: `time.monotonic()` around `execute(rollback_pk)`
  `< 60` seconds (generous for first Multipass; fail if ≥ 60).

**Exact req ids proven:** HARNESS-T3-NIGHTLY (`tier: t3`);
HARNESS-REAPER-TEST-PLANE (live); PIPE-S4 / PIPE-N5 / PIPE-N1 T3
markers optional (T1 already proves). REL-P3 resume if combined with
Task 7 toxic on this VM — prefer a short extra test
`test_t3_toxiproxy_ssh_timeout_resumes` in this file or Task 7.

**Tests to write:**
- `tests/test_t3_deploy.py` —
  `test_provision_fresh_multipass_then_harden`;
  `test_deploy_sample_site_http_ready`;
  `test_deploy_sample_node_site_ready_before_cutover`;
  `test_sample_node_site_volume_survives_v2`;
  `test_sample_node_site_ws_frame_through_caddy`;
  `test_v2_deploy_then_rollback_under_60s`;
  `test_teardown_finally_reaper_leaves_no_hub_t3_vm`;
  `test_hub_docker_sock_not_on_vm`.
- All `@pytest.mark.t3` + skipif no Multipass.

**Dependencies:** Task 1, Task 5 (`sample-site/` must exist even if T2
alpine stayed), Task 8, Task 9, Task 10 (provision+harden can be a
fixture shared with Task 10 to avoid two VMs per nightly — **one VM
per session**, session-scoped `t3_vm` fixture).

---

## Task 12 — T3 HTTPS + LE staging + `wss://` via CF (credential-gated)

**Title:** Test-plane DNS only; skip is not a T1 green (D-028).

**Files created/touched:**
- `providers/test_dns.py` (sensitive: `providers/`) — `TestDnsProvider(DnsProvider)`
  constructs only when `HUB_TEST_MODE`. Every mutate calls
  `assert_test_zone` / allowlist. Talks to Cloudflare **test zone** with
  a zone-scoped token from env `HUB_TEST_CF_TOKEN` (never a prod token
  name). If the token is unset, `__init__` raises `TestModeError` —
  tests skip the **LE req**, they do not instantiate a prod client.
- `tests/test_t3_https.py` — `@pytest.mark.t3`. When
  `HUB_TEST_DNS_ZONE` + token set: upsert A/AAAA to the Multipass IPv4
  (or a documented tunnel), Caddy LE **staging** issuer, GET `https://`
  asserts status 200 + security headers (`Strict-Transport-Security` or
  the Caddy defaults you document), v2, rollback; if the node-site
  manifest declares ws, one `wss://` upgrade through CF+Caddy and one
  frame. When unset: `@pytest.mark.skipif` + `@pytest.mark.t3` only —
  HARNESS-T3-LE-STAGING becomes skipped-only.
- Do not implement Origin-cert / attack-playbook / prod zone list
  (Phase 3).

**Exact req ids proven:** HARNESS-T3-LE-STAGING (`tier: t3`);
HARNESS-B9-TEST-MODE (adapter refuse).

**Tests to write:**
- `tests/test_test_dns_provider.py` (T1) —
  `test_refuses_construct_when_not_test_mode`;
  `test_refuses_non_allowlisted_zone`;
  `test_refuses_prod_purpose_zone`;
  `test_no_import_of_test_dns_from_deploys`.
- `tests/test_t3_https.py` —
  `test_https_and_security_headers_le_staging`;
  `test_wss_one_frame_through_cf_caddy`;
  `test_dns_records_reaped_in_finally`.

**Dependencies:** Task 1, Task 11. **D-031 slip OK** with waiver
`HARNESS-T3-LE-STAGING+no-test-zone-credentials`.

---

## Task 13 — Drills as Beat jobs + REL-P2 nightly stub (D-026)

**Title:** Honest short Hub-down; 24h waiver stays.

**Files created/touched:**
- `monitor/drills.py` — `run_hub_down_drill(*, duration_s)` (default 60s
  nightly stub; monthly Beat uses 1800). Stop Hub-side workers (or the
  pytest-driven control plane) **without** stopping the site container;
  external prober = HTTP GET the site on the target. Write `CheckRun
  kind=hub_down`. `run_reaper_drill` calls `reap_test_plane` against a
  planted `hub-t3-orphan-*` (T1: Fake list; T3: a created-then-abandoned
  name). `run_restore_clean_drill` **stub**: write `CheckRun
  kind=restore_clean` with `results={"stub": true, "reason": "Phase 2.5
  body deferred"}` — do not fake a restore success.
- `monitor/tasks.py` + `CELERY_BEAT_SCHEDULE` —
  `drill-hub-down-monthly` (30 d), `drill-reaper-weekly` (7 d),
  `drill-restore-monthly` (30 d, stub). Nightly invokes the functions
  directly from `make nightly` (60s hub-down), not only Beat.
- `WAIVERS.md` — **do not delete**
  `REL-P2-HUB-DOWN-SITES-UP+verify-demo+24h-unproven`. Add a line only
  if the stub would otherwise claim 24h.

**Exact req ids proven:** REL-P2-DRILL-STUB; HARNESS-DRILLS-BEAT (bodies);
HARNESS-REAPER-TEST-PLANE (weekly drill T1).

**Tests to write:**
- `tests/test_drills.py` —
  `test_hub_down_stub_writes_checkrun_succeeded_when_site_serves`;
  `test_hub_down_does_not_claim_24h`
  (`results.duration_s < 86400` and no `24h` success flag);
  `test_missed_monthly_hub_down_is_detected` (Task 2 helper);
  `test_reaper_drill_removes_planted_orphan_prefix`;
  `test_restore_drill_is_honest_stub_not_green_fiction`;
  `test_beat_schedule_lists_three_drills`.
- T2 optional: `test_t2_hub_stopped_site_still_serves` already exists
  as demo text; if you add a test, mark it T2 and do not claim 24h.

**Dependencies:** Task 2, Task 8, Task 9 (reaper). T3 live hub-down can
reuse Task 11's site.

---

## Task 14 — Nightly / review-round tooling + optional GHA (D-023)

**Title:** Local nightly is the gate; Actions stay optional and dormant.

**Files created/touched:**
- `Makefile` — `test` stays `pytest -q -m "not t2 and not t3"`.
  `test-t3`: `pytest -q -m t3`. `nightly`: `lint log-scrub scripts-lint
  test test-t2 test-t3 conformance-2.5` then
  `@echo "nightly mechanical gates done"`. `review-round` unchanged
  except Task 0's `conformance --exclude-tier t3`. Do **not** add
  `test-t3` to `review-round`.
- `.github/workflows/nightly.yml` (sensitive: CI) — keep SHA-pinned
  actions. Replace the stub body with a comment + optional job
  `t3-qemu` gated by `if: ${{ vars.HUB_ENABLE_GHA_QEMU == 'true' }}`
  (default unset → job skipped). Skipped GHA must not be the phase
  gate. Recipe: udev kvm, QEMU/cloud-init equivalent of Multipass,
  `make test-t3`. **Do not** turn Actions billing back on.
- `scripts_dev/file_nightly_failure.py` — on non-zero `make nightly`,
  write `conformance/demos/phase-2.5/failures/<utc>.md` with the
  pytest summary + `run-report.json` sha. If `GITHUB_TOKEN` + `gh`
  exist, `gh issue create` with that bundle; otherwise print the path.
  Never runs on the Hub host (crown-jewel).
- `docs/plan/build-process.md` — Scribe may later note D-023; do not
  require it for MUST.

**Exact req ids proven:** HARNESS-T3-SKIP-POLICY (tooling);
P25-HARNESS-DEMO (paths exist once Task 16 writes the record).

**Tests to write:**
- `tests/test_makefile_nightly.py` —
  `test_review_round_prereqs_exclude_test_t3_and_conformance_2_5`;
  `test_nightly_prereqs_include_test_t3_and_conformance_2_5`;
  `test_test_target_markexpr_excludes_t2_and_t3`.
- `tests/test_nightly_failure_bundle.py` —
  `test_bundle_written_on_nonzero`;
  `test_bundle_contains_no_vault_plaintext`;
  `test_gh_issue_is_optional_when_token_absent`.
- `tests/test_gha_qemu_is_opt_in.py` —
  `test_nightly_workflow_qemu_job_is_vars_gated`
  (parse YAML; job has the `vars.HUB_ENABLE_GHA_QEMU` if).

**Dependencies:** Task 0.

---

## Task 15 — Optional `hub-upgrade.sh` hold-through-build (D-027)

**Title:** Drain waits; refuse-immediately stays.

**Files created/touched:**
- `scripts/hub-upgrade.sh` (sensitive) — optional loop: while
  `count_running_deployments > 0` and under `HUB_DRAIN_TIMEOUT_S`
  (default 600), sleep and re-check; then refuse if still running.
  Default path without the env keeps **refuse-immediately** (existing
  tests).
- `docs/plan/server-hardening.md` — version bump in the same change.
- `WAIVERS.md` — retire
  `scripts/hub-upgrade.sh+C6+drain-is-toctou` **only if** the hold
  lands and a test proves a running deploy that finishes during the
  wait lets the upgrade proceed, and one that does not still refuses
  before `pg_dump`.

**Exact req ids proven:** HARD-Q8-SCRIPTS-TESTED (additional). Slip
leaves the existing waiver.

**Tests to write:**
- `tests/test_hub_upgrade_script.py` (extend) —
  `test_refuses_when_deployment_running` **unchanged**;
  `test_hold_through_build_waits_then_proceeds`
  (`HUB_DRAIN_TIMEOUT_S=5`, `HUB_CHECK_RUNNING` prints `1` then `0`);
  `test_hold_through_build_still_refuses_after_timeout`
  (always `1` → non-zero, no `pg_dump`).

**Dependencies:** none. **Not on the D-031 MUST line.**

---

## Task 16 — Acceptance, demos, phase gate

**Title:** `make conformance-2.5` can go green honestly.

**Files created/touched:**
- `tests/acceptance/test_phase_2_5.py` — one test per milestone
  clause, `@pytest.mark.acceptance(phase="2.5")` (extend the mark if
  it only accepts int — Task 0 should allow `2.5`) + `@pytest.mark.req(...)`.
  T1 clauses run in `review-round`. T3 clauses carry `@pytest.mark.t3`.
- `conformance/demos/phase-2.5.md` + `conformance/demos/phase-2.5/` —
  local Multipass record (or the dated host-without-multipass waiver
  quoted, not a fake log). LE record or
  `HARNESS-T3-LE-STAGING+no-test-zone-credentials`. REL-P2 24h still
  named outstanding. SIGKILL matrix nodeids. toxiproxy nodeid.
- `conformance/requirements.yaml` (sensitive) — `P25-HARNESS-DEMO`
  (`verify: demo`, `phase: 2.5`, `demo:` those paths).
- `conformance/paths.yaml` — map `tests/harness/**`,
  `monitor/drills.py`, `core/test_mode.py`, `providers/test_dns.py`.
- `WAIVERS.md` — file **only** what is true:
  `HARNESS-T3-NIGHTLY+host-without-multipass` if Multipass cannot run
  **and** Task 9's probe test agrees; LE waiver if no test zone;
  alpine PIPE-S4 if Task 5 slipped; drain TOCTOU if Task 15 slipped;
  **keep** REL-P2 24h.

**Exact req ids proven:** P25-HARNESS-DEMO; all MUST ids via acceptance
transcription or honest waiver.

**Tests to write:**
- `tests/acceptance/test_phase_2_5.py` —
  `test_hub_test_mode_refuses_prod_zone`;
  `test_checkrun_missed_drill_audits`;
  `test_core_ssh_py_is_sensitive`;
  `test_sigkill_child_resumes`;
  `test_toxiproxy_or_t1_timeout_resume`;
  `test_docker_run_has_unless_stopped`;
  `test_t3_skip_cannot_verify_tier_t3`;
  `test_review_round_excludes_t3_tier`;
  `test_sample_site_and_sample_node_site_exist`;
  `test_t3_both_fixtures_ready_v2_rollback_reaper` (`@pytest.mark.t3`);
  `test_t3_ufw_truth` (`@pytest.mark.t3`);
  `test_rel_p2_24h_not_claimed`.

**Dependencies:** Task 11 (MUST). Tasks 5, 12, 15 as needed for a
waiver-free `conformance-2.5`. If D-031 is taken, this task files the
waiver lines instead of pretending those ids shipped.
