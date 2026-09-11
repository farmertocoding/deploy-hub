# Deploy Hub security audit (experts + red team)

**Date:** 2026-09-11  
**Audited state:** branch `codex/origin-ca-bearer-token`.  
**Previous audit:** `docs/zero-trust-audit-2026-09-03.md` (FAIL for unattended production).  
**Method:** six expert tracks plus an independent red team against the live tree. High citations were re-read on current source. Findings were fixed in the same session with failing-first tests, except operator-owned DR.

**Decision after the fix wave:** **FAIL for unattended multi-tenant internet-facing production.** Single-tenant, Tailscale-loopback, operator-attended lab use is acceptable. Compose remains lab. Hub off-box DB backup is waived (operator-owned destination).

---

## Executive summary

The 2026-09-03 probes→fleet-deploy kill-chain stays closed: Redis `hub_probes` is a single `--user` string, Postgres `hub_probes` is SELECT-default with fleet DML revoked, probes cannot HMAC deploys envelopes, and `poll_git` / rotate / backup refuse unsigned Celery.

This session closed the residuals 09-03 left OPEN for a production go, plus new defects the live-tree review found:

1. Staff/superuser no longer mint a synthetic owner on workspace `default` (`ZT-18`).
2. Settings Cloudflare / AWS / Origin-CA and HUD `secret.create` go through T1 (`ZT-21`, `FE-03`).
3. ConfirmAction / T1Overlay lock after the first Confirm so Enter-spam cannot enqueue a second HUD command (`FE-HUD-CONFIRM-BUSY`).
4. Vite production/preview origin ships `Content-Security-Policy` with `script-src 'self'`; theme boot is an external file (`FE-01`).
5. S3 audit store calls `GetObjectLockConfiguration` (`ZT-08/16`).
6. Prod refuses `HUB_PAGER_BACKEND=fake`, empty local vault keyfile, and missing `HUB_PUBLIC_URL`.
7. `collect_all` / `tick_all` / `poll_git` refuse unsigned envelopes; Beat points at signed dispatchers.
8. git ls-remote re-resolves before connect; `docker_run_extra` is allowlisted; `hub_root` refuses path `ssh_user`; adopt `source_dir` goes through `resolve_local_source`.
9. Redis default user loses `@admin` / `FLUSHALL` / `CONFIG`. secret-scan is git-tracked + line-level.

Still not a production go: compose is lab, Hub `pg_dump` off-box is operator-owned (`OPS-DR-HUB-DB`), HMAC/bearer inbound stays off, named-partner evidence is not synthesized (`PART-U1`).

---

## Tracks

| Track | Result |
|---|---|
| Identity / tenancy | ZT-18 staff bootstrap removed. ZT-20 platform secret OR removed. Tenant GET of `api_enabled` / AWS status gated. |
| Secrets / crypto | Object Lock verified via `GetObjectLockConfiguration`. Prod refuses empty local keyfile and fake pager. |
| Isolation / deploy / SSRF | Probes Postgres is SELECT-default + fleet DML revoke. monitor/reconcile moved to `control`. `docker_run_extra` allowlisted. git ls-remote re-resolves before connect. |
| Frontend | ConfirmAction/T1Overlay busy lock. Settings Cloudflare/AWS/Origin-CA and secret.create use T1 overlay. SPA CSP + external theme boot. QR is an img, not innerHTML. |
| SRE / ops | Prod refuse fake pager / missing PUBLIC_URL. Redis default user loses FLUSHALL/CONFIG. verify-hardening checks daemon.json keys. |
| Red team | Chain B reconstituted as B2 (Postgres DML) and closed in this wave. FE abort Enter-spam closed. |
| Mechanical | secret-scan is git-tracked + line-level. check-generated refuses untracked generated files. `manage.py check` is a pytest. |

---

## Previous findings — re-verification (pre-fix → after this wave)

| ID | 2026-09-03 | After this wave |
|---|---|---|
| ZT-01 implicit owner | FIXED | FIXED |
| ZT-03 findings key | FIXED | FIXED |
| ZT-05 viewer suppress | FIXED | FIXED |
| ZT-06 tenant→global POST | FIXED POST; GET leak | **FIXED** GET `api_enabled` / AWS status are system-admin |
| ZT-07/14 probe isolation | MOSTLY FIXED | **FIXED** probes DML revoke + monitor/reconcile on `control` |
| ZT-08/16 audit ship | OPEN | **FIXED** `GetObjectLockConfiguration` |
| ZT-11/INT-01 intake | FIXED | FIXED |
| ZT-12/19 throttle | FIXED | FIXED |
| ZT-13 default-workspace dumps | FIXED engines | FIXED; partner-aggregate passes workspace |
| ZT-15 unsigned Celery | rotate/backup FIXED | **FIXED** collect/tick/poll_git too |
| ZT-17 WS findings | FIXED | FIXED |
| ZT-18 staff bootstrap | OPEN | **FIXED** — membership required, including `default` |
| ZT-20 default secret metadata | FIXED resource-owner OR | **FIXED** remaining platform-secret OR |
| ZT-21 Settings overlay | OPEN | **FIXED** T1 overlay on CF/AWS/Origin-CA |
| ZT-22 local root | FIXED | FIXED |
| FE-01 CSP | OPEN | **FIXED** on `vite preview` / build (not `npm run dev` HMR) |
| FE-02 logout/idle | FIXED | FIXED |
| FE-03 secret.create T1 | FIXED server | **FIXED** HUD overlay |
| FE-HUD-CONFIRM-BUSY | (new) | **FIXED** Confirm busy lock |
| OPS-01 compose as prod | OPEN as lab | unchanged (lab) |
| OPS-PAGER fake default | OPEN | **FIXED** prod refuse |
| OPS-DR-HUB-DB | OPEN | **WAIVED** operator-owned destination |
| PART-U1 | waived | waived |

---

## Red team kill-chains (at HEAD, then fix)

| Chain | At HEAD | After this wave |
|---|---|---|
| A. Stolen workspace-B viewer cookie | CLOSED | CLOSED |
| B. Redis / probes worker | CLOSED for probes user; default user still broker-admin | **CLOSED** default user `-@admin -flushall -config` |
| B2. Postgres `hub_probes` DML | OPEN — GRANT ALL then denylist; fleet DML on deploys/core | **CLOSED** SELECT-default + fleet DML revoke; missing-table safe |
| C. Compromised intake | CLOSED | CLOSED |
| D. Zero memberships | CLOSED for non-staff; staff bootstrap OPEN | **CLOSED** staff without membership is not default owner |
| E. local_path / Origin-CA / adopt | CLOSED | CLOSED; adopt `source_dir` resolved |
| F. SSRF / git ls-remote TOCTOU | residual TOCTOU | **CLOSED** re-resolve before connect |
| G. CSRF | CLOSED | CLOSED |
| H. Viewer→operator / tenant→system admin POST | CLOSED | CLOSED; GET leak closed |
| I. Unsigned deploy/HUD | CLOSED for named tasks; collect/tick/poll_git OPEN | **CLOSED** those three refuse unsigned |
| N1. `/admin/` 2FA-free | OPEN (OTPAdminSite wraps HTML) | pin OTPAdminSite; Enrollment stays `/api/`-only |
| N2. `docker_run_extra` | loaded gun | **CLOSED** 127.0.0.1 `-p` allowlist |
| FE abort Enter-spam | OPEN | **CLOSED** Confirm `aria-disabled` / `aria-busy` / `disabled` |

---

## What this wave did not take

- Synthesizing `PART-U1` named-partner evidence, invented `HUB_TEST_*` / HMAC tokens, or live Let’s Encrypt.
- An off-box Hub Postgres backup destination (`OPS-DR-HUB-DB` — operator-owned).
- Declaring unattended multi-tenant production PASS. Compose stays lab.
- Re-enabling paid GitHub Actions billing or treating `nightly.yml` `t3-qemu` as a required Check.
- CSP on `npm run dev` / Vite HMR (Playwright uses the dev server; production CSP is `vite preview` / build).

---

## Production-readiness

| Plane | Ready? |
|---|---|
| Identity (single default workspace) | Conditional — membership required, including staff |
| Multi-workspace HTTP/WS | Conditional — producers fail-closed |
| Worker isolation | Conditional — probes cannot sign deploys or DML fleet tables |
| Secrets at rest | Conditional — vault AEAD + Object Lock verify; HMAC inbound off |
| Frontend | Conditional — Confirm lock + T1 overlay + prod CSP; Vite HMR has no CSP |
| Operations / DR | **No** — compose lab; Hub restore operator-owned |

**Overall: no** for internet-facing unattended production. **Yes** for the 09-03 residuals this review still rated as defects, except operator-owned DR.

Compare with `docs/zero-trust-audit-2026-09-03.md`.

---

## Gate scoreboard (this session)

| Gate | Evidence |
|---|---|
| Finding tests (`tests/test_zero_trust_*.py`, Confirm unit, secret-scan) | in-repo; first run captured during the fix wave |
| Playwright `test:e2e` / `test:functional` | Enter-spam spec kept; two local runs 59 / 46 passed |
| `make review-round` | first full run failed mutation on spent/stale waivers + untested `finding()` / dead `resolve_workspace` fallback; those are fixed in source/tests. Subsequent consecutive greens are the bar. |
| `make test-t2` | Docker has `hub-test-target:local`; run after review-round |
| `make test-t3` | Multipass 1.16.3 present, no instances; try after T2 |
| GitHub Actions `push-checks` | observe on push; local make is evidence only |
