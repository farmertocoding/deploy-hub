# Phase 2 — review round 4 fixes

Status: implemented on `phase-2`. Not pushed. HEAD was `0637fe6`.

QE + SRE: Hub `_docker_run_argv` never set `-p`, `-e PORT`, or EXPOSE.
`collect_once._curl_healthz` then saw empty Health, empty PortBindings/ExposedPorts,
and no `$PORT` → `{live:false}` → reconciler `docker restart` of a live site.
Round-3 planted `PORT=18080` in inspect Env, which Hub never emitted.

## Mechanical

- `REVIEW_CHECKLIST.md` and `conformance/requirements.yaml` untouched.
- Waived fingerprints not re-opened. `WAIVERS.md` untouched.
- Not pushed.

## Production

1. **`deploys/steps.py` `_docker_run_argv`** always appends `-e PORT=<listen>` after
   `--env-file` / volumes / `docker_run_extra`. Listen is `desired.internal_port`
   (SiteInstance), else Manifest.body `port` / `PORT`, else `8080`. Secrets stay
   in the env file, not on argv. Still no `-p` / EXPOSE from Hub.
2. **`monitor/collect_once.py`** Hub-shaped inspect (empty Health / PortBindings /
   ExposedPorts) curls `/healthz` on `Config.Env` `PORT=<n>` once docker run sets it.
   If inspect still has no port, return `{live:true, ready:false, reason:listen-port-unknown}`
   instead of `{live:false}`.
3. **`reconcile/loop.py`** maps `listen-port-unknown` to `WARMING`. `_plan` will not
   `docker restart` that reason (restart-only skip; STOPPED still starts).

## Tests (TDD)

RED on `0637fe6`: argv had no `-e PORT=`; empty inspect → `docker restart`.

GREEN: `CONFORMANCE_RUN_REPORT=off .venv/bin/pytest -m "not t2"` on touched tests.

- `tests/test_review_round4.py`
  - `test_docker_run_argv_sets_numeric_port_env` (internal_port / body port / `PORT` / 8080)
  - `test_docker_run_keeps_env_file_and_omits_secrets`
  - `test_fake_transport_docker_run_records_port_flag`
  - `test_hub_shaped_inspect_curls_env_port_from_docker_run` (Env `PORT=21000`, not 18080)
  - `test_tick_skips_restart_when_inspect_has_no_port`
- `tests/test_review_round3.py` plants `PORT=<SiteInstance.internal_port>`, not 18080.

Related still green: `test_ensure_start`, `test_review_round{1,2,3}`, `test_collector`,
`test_reconciler`, `test_reconciler_staleness`, `test_env_lifecycle`. `make lint` green
(`PATH=.venv/bin:/opt/homebrew/bin`).

## Leftover

- Hub still does not publish `-p` / EXPOSE. Caddy dials `127.0.0.1:internal_port`;
  that host mapping is a separate finding from this PORT/healthz restart loop.
- T2 alpine stub (`tests/test_pipeline_sample_node_site.py`) still listens on
  container `:80` with `docker_run_extra -p 127.0.0.1:20000:80` and ignores `$PORT`.
  Existing waiver `tests.test_pipeline_sample_node_site+PIPE-S4-READINESS-GATE+t2-instant-ready-stub`
  is unchanged.
- `--restart unless-stopped` still absent (REL-P2 24h / reboot, already in the
  demo record).
