# Phase 2 Design Note — Deploy to own machine

**Phase:** 2 per §I as amended (review3 §M2/§N1–N3/§N5–N6/§N8/§Q8/§V2/§V10)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-20 · **Seat:** Fable (D-021; fallback Grok 4.6)
**Estimate:** 2–3 wk incl. review rounds. Protective cut: D-020.

## 1. What lands this phase

1. **Core tables** the pipeline needs: `NetworkZone`, `Target` (host-key fingerprint,
   vaulted SSH key), `SiteInstance` (desired/observed, including `warming`/`unhealthy`),
   `OperationLock` (Postgres, §A5), `Deployment` / `DeploymentStep` / `DeploymentArtifact`
   (§D2/§D3), `AppliedCatalogEntry` (§D8), `DnsRecord`, `SiteVolume`, `BackupUnit` stub.
   `Site` gains `exposure`, `deploy_strategy`, `deploy_policy`, `maintenance_until`,
   healthz fields, `config_stale`. **D-005 closed:** the dedicated `Manifest` row is the
   frozen input; `deploys/` never imports `scanner/` (§V6).
2. **Transport seam (D-018)** — `probe(argv)` vs `run(argv)` / `put`. Real
   `SshTransport` (Fabric) with strict host-key pin (§6.8). T1 uses `FakeTransport`
   from the first commit.
3. **Catalog + `scripts/`** — Python dataclass entries (`catalog/entries.py`); the five
   scripts live under `scripts/` as the pre-Hub interim of those ids (§Q8). Catalog-first:
   provisioner executes entries through Transport; when the matching Beat job goes live it
   **removes the script cron**. `harden-ubuntu.sh` encodes R1–R3, `sshd -t` first (R2),
   mesh-before-firewall (V2), `HUB_MESH_IP` ignoreip (V1).
4. **Provisioner, fresh-host only (§E6)** — occupied 80/443 or non-fresh app state
   **refuses with an explanation**. Pre-hardened but empty (scripts already applied, ports
   free, no site containers) is allowed: probe-and-import versions into
   `AppliedCatalogEntry`. Adopt-existing-site is Phase 3.
5. **Pipeline as `ensure_*` in `deploys/steps.py`**, shared with the reconciler (§D6).
   Steps 1–9; `mesh_only` skips DNS/edge. Builds **on the target** (§B1): Hub clones the
   commit (§A4), ships a vault-free context via `put`, `docker build` argv on the target.
   Recreate vs blue-green (§N1); per-Site volumes (§N5); step 5 gates on `/healthz.ready`
   with `warmup_timeout_s` (§N2). Env snapshots through the vault path (§D2). Rollback =
   a **new** Deployment re-applying artifacts; volumes never touched without T1 confirm.
6. **Liveness:** `last_heartbeat` ~30s + sweep resume-or-abort (§C1). Crash kill-matrix
   `HUB_TEST_CRASH_AFTER_STEP=n`. Git **polling** Beat job, no webhook (§M2 / E1 patched).
   `deploy_policy` auto|confirm|windowed (§N8).
7. **DB provisioner + backup registry stub (§E5/§N6)** — ensure Postgres container/role
   on the target, credentials in vault as `DATABASE_URL`; `BackupUnit kind ∈ {postgres,
   sqlite_file, directory_sync}` registered; dumps `| age` with a **backup** key, never
   the KEK. Env lifecycle: names listed, values write-only, Apply = steps 4–9 same image
   (§E4).
8. **Reconciler v1 with brakes (§C2)** on queue `probes`; collector JSON contract (§C3)
   — one SSH session per target per minute. Staleness never restarts (§N3).
9. **`hub-upgrade.sh` (§C6)** and **`hub-test-target`** per D-015 (Ubuntu, systemd PID 1,
   sshd, inner docker **vfs**, privileged + cgroupns=host; **do not** bind Hub docker.sock).
   Caddy is installed so step 7 is T2-real; ufw/fail2ban **truth** stays Phase 2.5.
10. **CI-runnable demo fixture** is in-repo `sample-node-site/` (TAKKO-shaped: recreate,
    volumes, warmup `/healthz`). Real-world half: TAKKO through the real pipeline
    (`verify: demo`). REL-P2 is a demo, not a T1 test.

## 2. Interfaces / tables that change

**New tables:** `NetworkZone`, `Target`, `SiteInstance`, `OperationLock`, `Deployment`,
`DeploymentStep`, `DeploymentArtifact`, `AppliedCatalogEntry`, `DnsRecord`, `SiteVolume`,
`BackupUnit`. **Site** columns as §4. **Transport** gains `probe()`. **SshTransport** is
the first real Transport. **Catalog** dataclasses + `AppliedCatalogEntry`. **Collector
JSON** (pinned): `{schema_version, target_id, ts, metrics, containers, log_chunk:
{file, inode, offset, bytes}, clock, healthz: {live, ready, checks}}`. **DnsProvider**
stays the Phase-0 fake in CI (Cloudflare adapter is Phase 3). Celery: pipeline on
`deploys`; reconciler, collector, git poller Beat on `probes`.

## 3. Applicable registry reqs (phase ≤ 2 due at exit)

REL-P1-RECONCILER · REL-P2-HUB-DOWN-SITES-UP · REL-P3-RESUMABLE-DEPLOYS ·
REL-P4-ARTIFACT-SNAPSHOTS · SEC-P5-BREAK-GLASS · VAL-45-SHELL-ARGLISTS ·
PIPE-S4-READINESS-GATE · SEC-B1-BUILD-OFFHUB · PIPE-D2-STATE-MACHINE ·
PIPE-D6-IDEMPOTENT-STEPS · PIPE-N1-DEPLOY-STRATEGY · PIPE-N5-VOLUMES-MODELED ·
PIPE-M2-GIT-POLLING · PIPE-N8-DEPLOY-POLICY · REL-C1-HEARTBEAT-SWEEP ·
REL-C2-RECONCILER-BRAKES · REL-A5-POSTGRES-LOCKS · REL-C3-ONE-COLLECTOR-SESSION ·
SEC-68-HOSTKEY-PINNING · SEC-69-KEK-NEVER-IN-BACKUPS · ALERT-N3-STALENESS-NEVER-RESTARTS ·
HARD-R1-TWO-POSTURES · HARD-R2-SSHD-VALIDATE-FIRST · HARD-R3-IGNOREIP ·
HARD-Q8-SCRIPTS-TESTED · HARD-V2-MESH-BEFORE-FIREWALL · PROV-E6-FRESH-HOST-GUARD ·
UX-F8-SIMULATION-STATES.

**Not due:** `SCAN-DECLARED-TEST-MATERIAL` / `SCAN-DECLARED-GUARDS` (D-017 → phase 4).

## 4. Exit demo

**CI half:** `sample-node-site/` → real pipeline → `hub-test-target`, **twice** (second
run: `mutating_calls() == []`), plus resume-from-crash and rollback; volumes survive.
**Real-world half:** TAKKO through the same pipeline; record in
`conformance/demos/phase-2.md`. **REL-P2:** Hub stopped, site still serves (demo record;
24h drill is the live form, not a T1). `check.py --phase 2` green; two consecutive
clean rounds.

## 5. DECISION markers opened

- **D-017** D-012 is **not** re-landed in Phase 2. Joseph parked the mechanism “as its
  own phase with a threat model written first.” Option (a) (Task 0 = threat model +
  re-import) would mix scanner-trust work into the deploy wave and contradict that
  parking. Option (b): bump the two reqs to **phase 4** (security suite; threat model
  is the first page of that design note). Registry edit is sensitive-path; parked
  `tests/test_scanner_declarations.py` keep their markers. This is what makes
  `check.py --phase 2` not blocked by parked scanner work.
- **D-018** `Transport.probe(argv)` is the read-only seam. `run` / `put` stay mutating;
  `get` / `probe` do not. `FakeTransport.mutating_calls()` is **unchanged** (`run` and
  `put` only). Using `run` for an inspect is fail-closed: run-twice goes red.
- **D-019** Task order vs the brief’s sketch: pull **`hub-test-target` forward** (SSH
  and pipeline T2 need it); land **heartbeat with the pipeline skeleton**; land
  **volumes/recreate/readiness with steps 4–5**, not after 1–9. Remainder follows the
  brief. See `docs/plan/phase-2-tasks.md`.
- **D-020** Protective cut — see §6 and the task plan. Milestone that MUST ship is
  unchanged from the brief.

## 6. Out of scope (explicitly)

T3 Multipass / ufw-truth / overlay2 / reboot (Phase 2.5) · Cloudflare DNS adapter
(Phase 3; fakes only) · WebAuthn (Phase 4) · adopt-existing-site (Phase 3) · webhook
ingress (Phase 5.5; Phase 2 is git polling) · executing-check sandbox runner (Phase 1
named it here; no phase-2 registry id; Hub path already has zero subprocess) · D-012
live scan/wizard path (D-017).

**Phase 2b** (slips without failing the MUST demo): git polling, windowed
`deploy_policy`, reconciler brakes, collector, `hub-upgrade.sh`, env-lifecycle UI,
DB/backup Beat jobs, UX-F8 seed polish, REL-P2 24h duration. Those ids stay phase 2;
taking the cut means a waiver or a phase bump before `check.py --phase 2` can close.

## 7. Round-6 design reset

One listen port for `docker run`, `collect_once`, and `ensure_health_check`.
`_docker_run_argv` sets `-e PORT=<listen>` where `listen` is `_listen_port(desired)`
(internal_port else Manifest body `port`/`PORT` else 8080). Step 5 curls
`http://{container_ip}:{listen}{path}` (or `127.0.0.1:{listen}` when inspect IP is
empty). Never implicit `:80` when PORT is 20000–29999.
