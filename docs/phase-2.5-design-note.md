# Phase 2.5 Design Note — Test harness completion

**Phase:** 2.5 per §I (addendum 2026-07-30) · **Nightly** per build-process.md §3 · **§B9** credential wall
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-21 · **Seat:** Grok 4.6
**Estimate:** 1 wk incl. review rounds. Protective cut: D-031. Phase 2 closed (adversarial SIGN-OFF at `2d6e99c`).
**Branch:** Implementer cuts **`phase-2.5`** from `phase-2` @ `2d6e99c` before the first product commit. These two docs may sit untracked on `phase-2`. **Never implement on `master`.**

## 1. What lands this phase

Seams already exist (Transport, FakeDns, `hub-test-target`, pipeline `execute`, heartbeat sweep, `make review-round`, SHA-pinned workflow *recipes*). This phase **assembles** them. It does not rewrite the pipeline.

1. **Credential wall (§B9).** `HUB_TEST_MODE` + `NetworkZone.purpose ∈ {prod, test}`. Test-plane code refuses non-test zones and refuses to construct a DNS client for any zone not in `HUB_TEST_ZONE_SLUGS`. Prod vault material never enters the harness. Per-run SSH keys, destroyed with the target.
2. **T2 completion.** Shared `hub_target` fixture (today duplicated). **SIGKILL worker-death** kill-matrix (the Phase 2 `RuntimeError` hook stays; that waiver is not a pass for this). Alpine-vs-real `sample-node-site` image: try vfs `npm ci` / the fixture Dockerfile; keep the alpine waiver if vfs cannot. `--restart unless-stopped` on `_docker_run_argv` (REL-P2 leftover).
3. **`sample-site/`** — **missing on this tree.** Land a minimal Django/ASGI healthz fixture (Q7 first leg). T3 deploys **both** `sample-site/` and `sample-node-site/`.
4. **T3 nightly (local Multipass is the host of record).** Real Ubuntu VM, overlay2 (not vfs), real provision, both fixtures, HTTP ready, v2 deploy, rollback-within-60s, teardown-in-`finally` + reaper (`purpose:test` / name prefix) leaves nothing. **ufw/fail2ban truth** via `harden-ubuntu.sh` + `verify-hardening.sh` on the VM (container ufw is a known false-green). toxiproxy on the SSH path: timeout mid-deploy → heartbeat sweep resumes.
5. **HTTPS + LE staging + `wss://` through CF+Caddy** only when the test-zone token is present. Absent credentials → `tier: t3` skipped-only, **not** verified. Local Multipass still proves HTTP + one `ws://` frame through on-VM Caddy.
6. **Drills as Beat jobs** writing `CheckRun`. Monthly Hub-down (short nightly stub; **24h stays waived**), weekly reaper, monthly restore stub. A skipped/missed drill is an AuditEvent (ntfy is Phase 3).
7. **Review-round tooling.** `make review-round` stays T1 (D-022 Cloud Agent; Darwin may lack Multipass). New `make test-t3` / `make nightly` / `make conformance-2.5`. Optional GHA QEMU recipe stays dormant — **do not require paid Actions** (D-022; Joseph already SHA-pinned). Auto-file = local bundle + optional `gh issue` when a token exists.
8. **Custody leftover:** `core/ssh.py` joins `conformance/paths.yaml` + CODEOWNERS (adversarial Important). Sensitive paths still wait for Joseph's merge click.

## 2. Interfaces / tables that change

**`NetworkZone.purpose`** (`prod` default — fail-closed under test mode). **`CheckRun`** (`kind`, `status ∈ {scheduled, running, succeeded, failed, skipped}`, `due_at`, `results` JSON `schema_version`). **Settings:** `HUB_TEST_MODE`, `HUB_TEST_ZONE_SLUGS`. **`core/test_mode.py`:** `assert_test_zone(zone)`. **`providers/test_dns.py`:** test-plane `DnsProvider` only (D-028 — not the Phase 3 Cloudflare product adapter). **`_docker_run_argv`:** `--restart unless-stopped`. **`check.py`:** `--phase` accepts `2.5` (today `type=int`); `tier: t3` + `--exclude-tier t3`. **Pytest:** mark `t3`; T1 markexpr becomes `not t2 and not t3`. Celery Beat: drill + reaper + missed-drill detector on queue `probes`.

## 3. Applicable registry reqs (phase ≤ 2.5 due at exit)

**New (Task 0 adds):** HARNESS-B9-TEST-MODE · HARNESS-T3-SKIP-POLICY · HARNESS-T3-NIGHTLY (`tier: t3`) · HARNESS-T3-UFW-TRUTH (`tier: t3`) · HARNESS-T3-TOXIPROXY · HARNESS-T3-LE-STAGING (`tier: t3`) · HARNESS-DRILLS-BEAT · HARNESS-REAPER-TEST-PLANE · REL-P3-WORKER-DEATH · REL-P2-DRILL-STUB · P25-HARNESS-DEMO (`verify: demo`).

**Already due, leftover proof:** REL-P3 (T1 stays; SIGKILL is the new id) · REL-P2-HUB-DOWN-SITES-UP (**phase 2, waiver stays** — 24h unproven) · PIPE-S4 alpine waiver (Task 5 tries to retire) · HARD-R1/R3 on a real VM (T3 truth) · PROC-SENSITIVE-HUMAN-MERGE / PROC-REGRESSION-TEST **stay waived** (Actions billing broken).

**Not due:** SEC-A2-WEBAUTHN / T4 Playwright (Phase 4) · Cloudflare product adapter / Origin certs (Phase 3) · adopt-existing-site (Phase 3) · ntfy pager (Phase 3; CheckRun only).

## 4. Exit demo

**Local Multipass:** provision a throwaway VM → harden+verify (ufw/fail2ban real) → deploy `sample-site/` and `sample-node-site/` → HTTP ready (node-site: traffic after `ready`, volume survives, one `ws://` frame) → v2 → rollback-within-60s → toxiproxy SSH timeout → resume → teardown + reaper empty. **LE/HTTPS/wss-via-CF** when `HUB_TEST_DNS_ZONE` is set; otherwise that req is skipped-only + named waiver, never a T1-sibling green. Host without Multipass: dated `WAIVERS.md` line; a T1 probe fails if Multipass is present and T3 was skipped. Record: `conformance/demos/phase-2.5.md`. `make conformance-2.5` green; two consecutive clean T1 rounds.

## 5. DECISION markers opened

- **D-023** Host of record = **local Multipass** + `make test-t3` / `make nightly`. GHA QEMU is an optional dormant recipe. Phase exit must not require paid Actions (D-022).
- **D-024** A `tier: t3` req is verified only by a **passed `@pytest.mark.t3` test**. T1 siblings, skips, and xfails never verify it. `check.py --phase 2.5` is the phase gate; `make review-round` uses `--exclude-tier t3`.
- **D-025** T2 tries the real `sample-node-site` image on vfs; alpine COPY stub + existing PIPE-S4 waiver stay if vfs cannot. Do not silently drop the waiver.
- **D-026** REL-P2 24h waiver **stays**. 2.5 ships a Beat drill + short nightly Hub-down stub. `--restart unless-stopped` lands so a later 24h is possible.
- **D-027** `hub-upgrade.sh` hold-through-build drain is **optional**. Named refuse-immediately remains the HARD-Q8 proof; existing TOCTOU waiver may stay.
- **D-028** Test-plane DNS client ≠ Phase 3 Cloudflare adapter. Test-mode-only; refuse non-allowlisted zones.
- **D-029** `check.py --phase` becomes float (`2.5`). Review-round conformance does not demand a Multipass run.
- **D-030** `sample-site/` is absent; 2.5 lands a minimal Django/ASGI fixture so the T3 first leg is not fiction.
- **D-031** Protective cut — §6.

## 6. Out of scope (explicitly)

WebAuthn / T4 Playwright (Phase 4) · product Cloudflare adapter, Origin certs, ntfy (Phase 3) · TAKKO real-pipeline (Phase 2 real-world half, still outstanding; not a harness item) · AWS/Azure T3 parametrization (Phase 5) · partner T3 (Phase 5.5) · executing-check sandbox · D-012 declaration threat model (Phase 4) · paid GitHub Actions as a gate.

**May slip (D-031) without failing the MUST demo:** real T2 fixture image (alpine waiver stays) · LE/HTTPS/wss-via-CF (named waiver) · restore-to-clean-container drill body (CheckRun stub is enough) · hub-upgrade hold-through-build · Multipass reboot smoke · GHA QEMU actually running.

**MUST:** B9 wall · ssh.py custody · shared T2 fixture · SIGKILL matrix · toxiproxy resume (T2) · `--restart unless-stopped` · Multipass driver + anti-silent-green · T3 provision + ufw truth + both fixtures HTTP + v2 + rollback-60s + reaper · CheckRun + Hub-down stub · `make nightly` / `conformance-2.5` · demo record.
