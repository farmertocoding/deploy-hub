# Phase 2 round-1 leftovers

Controller-scoped leftovers after mechanical `make review-round` was green
(`ce12b5b`) and in-bounds findings were waived (`04249c3` / `WAIVERS.md`).
This round **fixes** the non-waived items. Do not re-open waived fingerprints.

## Waived (leave in WAIVERS.md; not this commit)

| Fingerprint | Why it stays waived |
| --- | --- |
| `tests.test_crash_kill_matrix+REL-P3+t1-runtimeerror-not-t2-crash` | SIGKILL is Phase 2.5; T1 1–9 matrix stays |
| `tests.acceptance.test_phase_2+Q4-transcription+hub-test-target-is-t1` | T1 FakeTransport acceptance allowed |
| `tests.test_pipeline_sample_node_site+PIPE-S4-READINESS-GATE+t2-instant-ready-stub` | T2 alpine COPY-from-tree vfs exception |
| `scripts/hub-upgrade.sh+C6+drain-is-toctou` | named test is refuse-immediately |
| `frontend/src/App.jsx \| UX-F8-SIMULATION-STATES \| demo pane…` | Task 20 seed-only; screens Phase 3 |
| `simulation/seed_v0.json \| review3-N2 \| warming event omits elapsed…` | elapsed/expected waits for site-card UI |
| `deploys/breakglass.py \| SEC-P5 \| runbook lacks impact line…` | impact/DNS copy is Phase 3 |

## Fixed this round

1. **QE F4** `ensure_cutover` probes `docker inspect` Running and skips `docker stop` when already stopped. Second cutover of the same desired has `mutating_calls()==[]`.
   - Test: `tests/test_ensure_smoke_cutover.py::test_second_cutover_skips_stop_when_old_already_stopped`
2. **QE F5** Literal `@pytest.mark.req("PIPE-S4-READINESS-GATE")` on `test_ws_smoke_when_manifest_declares_ws`.
3. **Security minor #7** Backup seal AAD is `Secret.build_aad(BACKUP_KEY, "site", site_id)`, threaded from `provision/backup.py`. Swap onto another site's key/AAD raises `InvalidTag`.
   - Test: `tests/test_backup_registry.py::test_backup_aad_is_site_bound_swap_fails_closed`
4. **SRE F7** Collector persists `(inode, offset)` on the Target (or in-memory double) and passes offset as argv[2]. Second collect of the same file sends the previous offset.
   - Test: `tests/test_collector.py::test_second_collect_passes_persisted_log_offset`
5. **SRE F6+F8** Tick drives observed state from the latest collector JSON when `collect_at` is ≤60s (containers + healthz → running/stopped/absent/unhealthy/warming). Fresh payload skips `docker inspect`. `observe=` injection unchanged. A repair invalidates `collect_at`.
   - Test: `tests/test_reconciler.py::test_tick_uses_fresh_collector_json_not_inspect`
6. **SRE F9** `HUB_RECONCILE_ENABLED` (default True) is checked before per-site `reconcile_enabled`. Global off → zero mutating calls; one `reconcile_globally_disabled` audit.
   - Test: `tests/test_reconciler.py::test_global_kill_switch_stops_mutations`
7. **SRE F10** `execute` `try/finally` releases deploy locks on terminal statuses (succeeded/failed/cancelled/superseded/rolled_back). Raise after SUCCEEDED save → lock row gone. Mid-step crash stays RUNNING and keeps the lock.
   - Test: `tests/test_pipeline_state.py::test_execute_releases_lock_if_post_success_save_raises`
8. **fail2ban rollback** `rollback_entry` substitutes `HUB_MESH_IP` into `delignoreip` argv (refuses if unset). Catalog pin still contains the `100.64.1.1` placeholder; live jail.local was already substituted on apply.
   - Test: `tests/test_catalog.py::test_fail2ban_rollback_substitutes_mesh_ip`

## Not in this round (explicit do-not)

- Kill-matrix still T1 `RuntimeError`, not SIGKILL
- T1 acceptance test not renamed
- UX demo pane / hub-upgrade drain not expanded
- `REVIEW_CHECKLIST.md` and `conformance/requirements.yaml` untouched
