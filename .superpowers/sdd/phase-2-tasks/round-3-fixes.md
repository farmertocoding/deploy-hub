# Phase 2 — review round 3 fixes

Status: implemented on `phase-2`. Not pushed. HEAD was `a7999f0`.

## Mechanical

- `REVIEW_CHECKLIST.md` and `conformance/requirements.yaml` untouched.
- Waived fingerprints not re-opened.

## Specialist regressions (`tests/test_review_round3.py`)

1. **Security Important** `catalog/apply.py+HARD-R3+jail-rewrite-collapses-live-dest` — `_jail_pin_paths` rewrites only hub staging (`/.hub/jail.local` / `hub_join`). `/etc/fail2ban/jail.local` is never a pin. `apply_entry` with `ssh_user=root` installs `/home/root/.hub/jail.local` onto `/etc/fail2ban/jail.local`; put body has substituted `HUB_MESH_IP`. If dest collapses, no `AppliedCatalogEntry`.
2. **SRE P1** `monitor/collect_once.py+REL-C2+healthz-fallback-not-n2-json` — empty Docker Health falls through to `_curl_healthz`, which curls the listen port from `HostConfig.PortBindings` / `Config.ExposedPorts` / `$PORT` (not implicit :80) and parses N2 JSON `{live, ready, checks}` like `_healthz_payload`. `checks.upstream` / feed-stale become per-container `reason`. `_read_observed` no longer forces `reason: ""` on collector JSON. Empty Health + `{live: true, ready: false, checks: {upstream: "upstream-down"}}` on `$PORT` → tick without `observe=` is warming or the upstream-down brake, zero `docker restart`.

## Waive / leftover (not expanded)

- Kill-matrix RuntimeError vs SIGKILL (waived)
- Acceptance T1 name vs hub-test-target (waived)
- T2 alpine S4 stub (waived)
- Hub-upgrade drain TOCTOU (waived)
- UX demo pane / seed elapsed / runbook impact-DNS (waived)
- T2 live image not executed this round (`-m not t2`)
- Inspect fallback `_probe_container_state` is still `{{.State.Running}}` when collector JSON is stale (>60s)
- Probe fallback (no fresh collect payload) still uses `reason: ""`
- Same-version fail2ban skip still does not fail the check argv (CIDR already applied stays a skip if the row exists)
