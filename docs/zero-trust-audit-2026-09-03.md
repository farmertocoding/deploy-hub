# Deploy Hub security audit (experts + red team)

**Date:** 2026-09-03  
**Audited state:** branch `codex/origin-ca-bearer-token`, HEAD `36f0d484a6ef71cfade301ab4a6bdd698aa3cbd1`.  
**Previous audit:** `docs/zero-trust-audit-2026-08-31.md` (FAIL).  
**Method:** six expert tracks plus an independent red team against the live tree. The orchestrator re-read every High citation before accepting it. High findings that were still open were fixed in this same session with failing-first tests.

**Decision after the fix wave:** **FAIL for unattended multi-tenant production.** Single-tenant, Tailscale-loopback, operator-attended lab use is acceptable. Do not treat compose as a zero-trust production runtime.

---

## Executive summary

The 2026-08-31 critical authorization bugs stay closed: membership-free users no longer inherit owner, findings are workspace-keyed, viewers cannot suppress, tenant roles cannot POST the partner kill-switch or AWS connect, `run_deploy` / `run_adopt` / `provision_host` / HUD outbox require signed envelopes, Origin-CA plant is path-only, and HMAC/bearer inbound remains off.

The remaining compromise was **probe/broker isolation theater**. Redis `--user` was split across argv so ACL never applied as written; even the intended rule was `~*` plus `@write`, so a probes worker could `LPUSH` the deploys queue, `DEL` envelope nonces, and inherit `HUB_TASK_ENVELOPE_SECRET`. Postgres `hub_probes` had DML on every table, including `vault_secret` and memberships. Beat SSH rotate and nightly backup took unsigned Celery.

This session closed that kill-chain in source:

1. Redis `hub_probes` is a **single** `--user` string confined to `~probes*` / `~_kombu.binding.probes*`.
2. Postgres `REVOKE`s vault, membership writes, `auth_user` writes, and sessions.
3. Probes overlay `HUB_TASK_ENVELOPE_SECRET: probes-cannot-sign` so they cannot HMAC deploys envelopes.
4. `poll_git` moved to queue `control`.
5. `rotate_ssh_keys` and `run_backup_nightly` refuse `envelope=None`; Beat calls signed dispatchers.
6. Archive/adopt always `require_root=True`; OTP failures count toward login throttle; `/api/auth/me/` no longer refreshes idle; intake bodies are capped; git-push MAC binds `id|type|git_url|ref`; HUD secret create is T1; logout clears React auth immediately.
7. Same wave also closed: default-workspace unclaimed secret metadata (ZT-20); partner `tenant_ref` Caddy-route injection; enroll/overflow/idle-pick workspace scoping; `hub_join` `..` traversal; HUD live topic `deploy.{id}`.

Still open for a production go: fake pager default, skip-by-default compose audit ship, no Hub DB backup/restore, GOVERNANCE Object Lock without `GetObjectLockConfiguration`, Settings Cloudflare/AWS/Origin-CA skip the T1 overlay (server still `RequireRecentTouch`), staff bootstrap on `default`, SPA origin CSP.

---

## Tracks

| Track | Result |
|---|---|
| Identity / tenancy | ZT-01/03/05/06/17/20 closed. Residuals: ZT-18 staff bootstrap, ZT-21 Settings overlay. |
| Secrets / crypto | Envelopes hold for named tasks. HMAC/bearer still disabled. Origin-CA plant holds. Audit ship still name-required, not lock-verified. |
| Isolation / deploy / SSRF | Probe Redis/Postgres/envelope-secret kill-chain was OPEN; fixed this wave. Git ls-remote DNS-rebind TOCTOU remains Medium. |
| Frontend | XSS sinks almost only TOTP QR. CSRF double-submit holds. Logout and secret.create T1 fixed this wave. CSP on Vite origin still absent. |
| SRE / ops | Prod fail-closed for SECRET_KEY / FakeKEK / TEST_MODE / PUBLIC_URL. Compose is lab. Fake pager default and Hub DR still OPEN. |
| Red team | Chains A, C, D, E, G, H closed. Chain B (probes → fleet deploy / RBAC rewrite) was the only full compromise; fixed this wave. |
| Mechanical | ruff on security roots clean; bandit no findings; pip-audit clean; Django check clean (2026-09-03 session). |

---

## Previous findings — re-verification (pre-fix)

| ID | 2026-08-31 | At HEAD `36f0d48` | After this wave |
|---|---|---|---|
| ZT-01 implicit owner | FIXED | FIXED | FIXED |
| ZT-02 local_path | MOSTLY | PARTIAL (archive/adopt skip root) | **FIXED** archive/adopt `require_root=True` |
| ZT-03 findings key | PARTIAL | FIXED schema | FIXED |
| ZT-05 viewer suppress | FIXED | FIXED | FIXED |
| ZT-06 tenant→global POST | FIXED | FIXED (GET residual) | FIXED POST; GET status still leaks |
| ZT-07/14 probe isolation | PARTIAL | **OPEN** write-all Redis/Postgres + envelope secret | **MOSTLY FIXED** ACL + REVOKE + dummy envelope secret. KEK-bearing collect still scheduled on probes. |
| ZT-08/16 audit ship | PARTIAL | PARTIAL | OPEN (not this wave) |
| ZT-11/INT-01 intake | PARTIAL | OPEN body + id-only MAC | **FIXED** cap + bound MAC |
| ZT-12/19 throttle | PARTIAL | OTP uncounted | **FIXED** OTP increments bucket |
| ZT-13 default-workspace dumps | PARTIAL | engines closed; antinoise helper still defaulted | **FIXED** `_workspace()` fail-closed; storm/push-log pass default explicitly |
| ZT-15 unsigned Celery | MOSTLY | rotate/backup unsigned | **FIXED** those two + dispatchers |
| ZT-17 WS findings | MOSTLY | subscribe membership; delivery filtered | FIXED |
| ZT-18 staff bootstrap | OPEN | OPEN | OPEN |
| ZT-20 default secret metadata | OPEN | OPEN | **FIXED** — default no longer ORs unclaimed resource owners |
| ZT-21 Settings overlay | OPEN | OPEN | OPEN (server still gated) |
| ZT-22 local root | PARTIAL | archive skip | **FIXED** |
| FE-01 CSP | OPEN | OPEN | OPEN |
| FE-02 logout/idle | OPEN | OPEN | **FIXED** |
| FE-03 secret.create T1 | (new) | OPEN | **FIXED** |
| OPS-01 compose as prod | OPEN | README now lab | OPEN as lab-only |
| OPS-PAGER fake default | OPEN | OPEN | OPEN |

---

## Red team kill-chains (at HEAD, then fix)

| Chain | At HEAD | After this wave |
|---|---|---|
| A. Stolen workspace-B viewer cookie | CLOSED | CLOSED |
| B. Redis / probes worker | **OPEN** — LPUSH deploys, forge envelope, rewrite membership | **CLOSED** for probes user (ACL + dummy secret + unsigned rotate refuse). Default Redis password remains broker-admin. |
| C. Compromised intake | CLOSED for SHA rollback / impersonation | CLOSED; body DoS and id-only MAC fixed |
| D. Zero memberships | CLOSED | CLOSED |
| E. local_path / Origin-CA / adopt | CLOSED for vault.key /etc; archive residual | CLOSED |
| F. SSRF | CLOSED as clean IMDS; DNS-rebind TOCTOU | residual TOCTOU |
| G. CSRF | CLOSED | CLOSED |
| H. Viewer→operator / tenant→system admin POST | CLOSED | CLOSED |
| I. Unsigned deploy/HUD | CLOSED for four tasks; rotate/backup OPEN | those two CLOSED |
| N1. `/admin/` 2FA-free | OPEN (OTPAdminSite wraps HTML; Enrollment middleware is `/api/` only) | OPEN |
| N2. `docker_run_extra` | loaded gun, not an API today | unchanged |

---

## What this wave did not take

- Real Redis ACL integration test against a running `redis:7` (T1 parses compose).
- Moving `monitor.*` / `reconcile.*` off probes (collect/SSH still crash without KEK).
- Prod refuse of fake pager; Object Lock `GetObjectLockConfiguration`; Hub `pg_dump` off-box.
- Settings Cloudflare/AWS/Origin-CA T1 overlay (server already `RequireRecentTouch`).
- SPA CSP (Vite inline theme boot script).
- Staff ≠ default-workspace owner.

---

## Production-readiness

| Plane | Ready? |
|---|---|
| Identity (single default workspace) | Conditional |
| Multi-workspace HTTP/WS | Conditional — producers mostly fail-closed |
| Worker isolation | Conditional — probes can no longer sign deploys; collect still mis-queued |
| Secrets at rest | Conditional — vault AEAD yes; audit not immutable |
| Frontend | Conditional — cookie/CSRF good; CSP still missing |
| Operations / DR | **No** — fake pager, compose lab, no Hub restore |

**Overall: no** for internet-facing unattended production. **Yes** for the probes→fleet-deploy kill-chain that was open this morning.

Compare with `docs/zero-trust-audit-2026-08-31.md`.
