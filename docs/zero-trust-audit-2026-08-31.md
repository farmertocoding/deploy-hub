# Deploy Hub zero-trust and production-readiness audit

**Date:** 2026-08-31  
**Audited state:** branch `codex/origin-ca-bearer-token`, HEAD `bae4920edc839ed4f0428007ff44db36d80105b2`, plus the dirty working tree (`hub/settings/compose.py`, `frontend/src/screens/Settings.jsx`, matching tests).  
**Previous audit:** `docs/zero-trust-audit-2026-08-28.md` (HEAD `907305e`, **FAIL**).  
**Decision:** **FAIL — do not deploy this tree as a zero-trust production release.**

This is a go/no-go assessment, not a patch. The 2026-08-28 critical authorization bugs were largely remade. The remaining blockers are tenant-incident mis-attribution, worker isolation that is YAML theater, compose that cannot boot its own probe worker, optional off-host audit, unsigned deploy tasks, and a Phase-0 runtime that the README still presents as the real shape.

---

## Executive summary

Deploy Hub now has real identity bones: session + CSRF, mandatory 2FA, T1 WebAuthn touch, explicit workspace membership for ordinary users, capability-split finding transitions, and a superuser-only system-admin plane for the partner kill-switch and AWS connect. Vault AEAD, Origin-CA Bearer plant (no paste, no `v1.0-` service keys), partner Ed25519, and SSH argv + host-key pin are fail-closed where they run.

That is not enough to call the product production-ready.

1. **Multi-tenant isolation is still a leak at the producers.** Findings are stored as `(workspace, fingerprint)`, but uptime, topology, and several other engines still dump incidents into the default workspace. Default-workspace members can see other tenants’ host and site names; non-default tenants miss their own alerts.
2. **The compose stack cannot operate as documented.** `worker-probes` sets `HUB_VAULT_KEYFILE=""` which Django refuses at `vault.apps.ready()`. Probe Postgres/Redis env vars name principals that the images never create. Probe Redis “isolation” is a second password against a single `--requirepass`.
3. **Zero-trust process boundaries are still labels.** Web, deploys, and control share the KEK, primary DB role, Redis password, and `HUB_SECRET_KEY`. Mutating Celery (`run_deploy`, `run_adopt`) is still an unsigned integer id. HUD envelopes are signed but replay is process-local and consume does not bind `resource_id`/`task`.
4. **Off-host audit is skip-by-default.** Beat calls `ship()` every 60s; empty `HUB_AUDIT_S3_BUCKET` returns skipped. `S3AuditStore.put_object` does not set Object Lock retention. A Hub DB compromise can still rewrite the only durable trail.
5. **Mechanical release evidence is red on lint.** `ruff` fails 12 times in pager/digest tests after workspace became mandatory. Targeted zero-trust tests are green. Full `make test` / mutation / conformance were not re-run to completion in this session.

Single-tenant, Tailscale-loopback, operator-attended lab use is closer than it was on 28 August. Internet-facing, multi-workspace, unattended production is not.

---

## Scope and method

Six expert tracks ran in parallel against the live tree. The orchestrator independently re-read every High/Critical citation before accepting it.

| Track | Scope |
|---|---|
| Identity / tenancy | RBAC, membership, TOTP/WebAuthn, CSRF/session, WebSocket `authorize_topic`, findings/audit tenancy |
| Secrets / crypto | Vault/KEK, cookies, Celery args, audit ship, exhaust, Origin-CA plant |
| Isolation / deploy | Compose, workers, SSRF, SSH, partner intake, HUD envelopes, `local_path` |
| Frontend | XSS, CSRF, T1 overlay, Settings Cloudflare dirty diff, CSP, generated API |
| SRE / operations | Boot fail-closed, backups, pager/deadman, HA, hardening, compose vs prod |
| Mechanical gates | lint, log-scrub, scripts-lint, Django check, pip/npm/pnpm audit, targeted pytest |

Read-only except this report. No live cloud credentials were invented or used. Uncommitted files were included.

---

## Gate scoreboard

| Gate / check | Result | Evidence |
|---|---|---|
| `make lint` | **FAIL** | `ruff check .`: 12 errors (2× I001 unsorted imports, 10× E501) in `tests/test_delivery_behaviors.py` and `tests/test_pager.py` after `workspace=` became required. Bandit and pip-audit were not reached by `make lint`. |
| Bandit (direct) | PASS | No findings on package roots. |
| `pip-audit -r requirements.txt` | PASS | No known vulnerabilities. |
| `pip-audit -r requirements-dev.txt` | PASS | No known vulnerabilities. |
| `make log-scrub` | PASS | No prohibited `SECRET_KEY =` in configured Python roots. |
| `make scripts-lint` | PASS | ShellCheck + `shfmt -d` on the five host scripts. |
| Django `hub.settings.dev` `check` | PASS | No issues. |
| Targeted ZT pytest | PASS | 89 passed, 1 skipped in 10.50 s: `test_zero_trust_authz`, `test_auth_throttle`, `test_task_envelope`, `test_local_sources`, `test_settings_boot`, `test_findings_tenancy`, `test_audit`, `test_audit_ship`, `test_origin_ca_plant`. |
| Dirty Settings tests (`node:test`) | PASS | 5/5 Cloudflare / Origin-CA plant tests. |
| Frontend `npm audit --audit-level=high` | PASS | 0 vulnerabilities (lockfile now `vite@6.4.3`, `esbuild@0.25.12`, `js-yaml@4.3.1`, `nanoid@3.3.18`). |
| Sample workspace `pnpm audit --audit-level high` | PASS | No known vulnerabilities. |
| `make test` (full T1) | **NOT RUN** | Previous audit: 2,490 passed, 1 mutation-cache-watch failure. Not re-executed to completion here. |
| `make mutation` | **NOT RUN** | Scope now includes `core/rbac.py`, `core/permissions.py`, `core/findings.py`, `core/audit.py` (QG-02 floor widened). No cold verdict this round. |
| `make check-generated` | **NOT RUN** | Process is gated; HEAD freshness not proven. |
| `make conformance` / `conformance-7` | **NOT RUN** | `PART-U1-NAMED-PARTNER` remains waived. |
| Frontend `npm run quality` / Playwright | **NOT RUN** | `frontend-quality` and `js-audit` are now `review-round` prerequisites. Playwright a11y is still not a blocker. |

Environment: local Python 3.13.14 / Django 5.2, Node 26.5.0. CI still declares Python 3.12 / Node 22. That remains a reproducibility limit.

`Makefile` now rejects `--jobs`/`-j` and marks `review-round` `.NOTPARALLEL` (QG-01 addressed in source).

---

## Previous findings — re-verification

Status is against **current** code, not the 28 August report.

| ID | Was | Now | Notes |
|---|---|---|---|
| **ZT-01** Critical implicit owner for membership-free users | OPEN | **FIXED** | `workspace_membership()` returns persisted rows only, plus staff bootstrap on `default`. Ordinary users with zero memberships get empty caps and 403 (`core/rbac.py:116-135`, `tests/test_zero_trust_authz.py`). T1 delete now creates an explicit owner (`tests/test_webauthn_t1.py`). |
| **ZT-02** High `local_path` host read | OPEN | **MOSTLY FIXED** | Default `HUB_ALLOW_LOCAL_SOURCES` off. Serializer refuses; scan/archive re-resolve, denylist `vault.key`/`.env*`, size caps, TOCTOU inode check. Residual: opt-in without `HUB_LOCAL_SOURCE_ROOT` is still host-wide except `/` and `/etc`; adopt/provision copy stored paths without `resolve_local_source`. |
| **ZT-03** High findings globally keyed | OPEN | **PARTIAL** | Schema is `(workspace, fingerprint)`; `finding()` requires `workspace`. Producers still fall back to `default_workspace()` (new **ZT-13**). |
| **ZT-04** High audit defaulted to default workspace | OPEN | **FIXED** | Omitted workspace is inferred or `AuditWorkspaceRequired`; no-obj calls are `scope="system"`. Chain hash includes `workspace_id` / `partner_id`. |
| **ZT-05** High viewer can suppress findings | OPEN | **FIXED** | `findings.manage` / `findings.accept_risk`. Viewer has neither. Transition view audits 403s. |
| **ZT-06** High tenant role mutates globals | OPEN | **FIXED** | `RequireSystemAdmin` on partner kill-switch POST and AWS connect POST. Residual: AWS GET and partner `api_enabled` leak global status to any workspace member. |
| **ZT-07** High shared worker identity | OPEN | **PARTIAL** | Probes drop the vault mount and rename env vars. Redis still one `requirepass`. Postgres image still creates only `hub`. Deploy/control/web still share KEK + `HUB_SECRET_KEY`. |
| **ZT-08** High no off-host audit | OPEN | **PARTIAL** | Beat `ship-audit-trail` every 60s; `S3AuditStore` exists. Skip if bucket empty; Object Lock is a local boolean, not an S3 header. |
| **ZT-09** sample Node vulns | OPEN | **FIXED** (this lockfile) | `pnpm audit --audit-level high` clean. |
| **ZT-10** audit chain fork / CASCADE | OPEN | **FIXED** | `AuditChainHead.select_for_update()`; `AuditEvent.workspace` is `PROTECT`. |
| **ZT-11** intake plaintext / unbounded | OPEN | **PARTIAL** | Prod requires HTTPS + `INTAKE_SERVICE_TOKEN`, body cap, no redirects. `intake/app.py` still reads the full WSGI body. Git-push HMAC binds job id only. |
| **ZT-12** no login throttle / unaudited denials | OPEN | **PARTIAL** | Custom 10/min cache throttle; `authz_denied` audit; trusted-hop `client_ip`. No `DEFAULT_THROTTLE_CLASSES`. OTP failures do not increment the bucket. Cache is LocMem unless configured. |
| **QG-01** Make `-j` | OPEN | **FIXED** in Makefile | `--jobs` filtered; `.NOTPARALLEL: review-round nightly-gates`. |
| **QG-02** mutation scope | OPEN | **PARTIAL** | Floor now includes rbac/permissions/findings/audit. No cold mutation verdict this round. |
| **QG-03** frontend quality not gated | OPEN | **MOSTLY FIXED** | `frontend-quality` + `js-audit` are `review-round` prereqs. Playwright a11y still policy-exempt. |
| **QG-04** JS/dev dep audit | OPEN | **MOSTLY FIXED** | `js-audit` gated; this run’s npm/pnpm/pip audits were clean. Secret scanner still allowlists any path containing `settings`. |
| **QG-05** stale generated API | OPEN | **UNKNOWN** | Gate exists; not re-run. Dirty Settings work did not regenerate OpenAPI. |

---

## Findings (current, independently traced)

### ZT-13 — High — Tenant incidents still land in the default workspace

**Evidence:** `finding()` is workspace-mandatory, but callers still default:

```35:40:monitor/antinoise.py
def observe(fingerprint, ok, *, workspace=None, now=None):
    from core.models import default_workspace
    workspace = workspace or default_workspace()
```

```116:123:monitor/uptime.py
def _observe(fingerprint, ok):
    ...
    return observe(fingerprint, ok)
```

```251:258:monitor/topology.py
def _file(fingerprint, **fields):
    workspace = fields.pop("workspace", None) or workspace_of(fields.get("site"))
    return finding(..., workspace=workspace or default_workspace(), **fields)
```

HTTP list/detail then filter by selected workspace, so the bug looks like isolation.

**Impact:** Default-workspace viewers see other tenants’ hostnames and site names. Two tenants with the same `site.name` share one `site-down:{name}` row. The owning tenant’s inbox stays empty for those engines.

**Remediation:** Pass `workspace_of(site|target|partner)` at every `observe()` / `raise_alert()` / `_file()`. Delete `or default_workspace()`. Fail closed. Test: site in workspace B down → finding only in B.

### ZT-14 — High — Probe “isolation” is non-functional and likely cannot boot

**Evidence:**

- Compose sets `HUB_VAULT_KEYFILE: ""` on `worker-probes` (`docker-compose.yml:49-61`).
- `VAULT_KEYFILE = os.environ.get("HUB_VAULT_KEYFILE", ...)` therefore becomes `""`.
- `get_backend()` raises `KEKError("VAULT_KEYFILE is not set")` (`vault/kek.py:157-159`).
- `vault.apps.ready()` calls `get_backend().check()` whenever `DEBUG` is false (`vault/apps.py:16-20`). Compose is prod-derived, `DEBUG=False`.
- Redis has a single `--requirepass ${REDIS_PASSWORD}` (`docker-compose.yml:16`). `REDIS_PASSWORD_PROBES` cannot be a different secret unless probes cannot connect.
- Postgres image creates only `POSTGRES_USER: hub`. There is no `hub_probes` role.

**Impact:** Uptime, deadman, collector, git poll, and cert/token audits live on `probes`. If that worker dies, the Hub is blind. If operators set the probe passwords equal to the primary ones, the “split” is cosmetic and any probe compromise still reaches the broker.

**Remediation:** Either give probes a real no-KEK settings path (`VAULT_SKIP_STARTUP_CHECK` plus a KEK-free backend), or do not pretend. Create Postgres roles and Redis ACL users in an init script. Prove probes cannot `GET` vault tables or `LPUSH` to the deploys queue.

### ZT-15 — High — Mutating Celery is still unsigned; HUD envelopes are incomplete

**Evidence:**

```12:16:deploys/tasks.py
@shared_task
def run_deploy(deployment_id):
    from deploys.pipeline import execute
    return execute(deployment_id)
```

`deploys/hud_workers.py` enqueues `run_deploy.delay(int(operation.object_id))` with no envelope. `run_adopt` / `cancel_adopt` are the same shape.

HUD outbox *is* signed (`core/tasks.py:5-18`, `core/task_envelope.py`). Consume checks HMAC, TTL, in-memory nonce, and **workspace only**. It does not bind `task` or `resource_id`. `_SEEN_NONCES` is a process-local `set()`. Nonce is `sha256(task:workspace:resource:issued)[:16]`, not random. Secret falls back to `SECRET_KEY`.

**Impact:** A process that can publish to Redis can start deploys by primary key. A captured HUD envelope can be replayed on another worker within TTL, or pointed at a different outbox row in the same workspace.

**Remediation:** Sign every mutating task. Bind `task` + `resource_id` at consume. Persist nonces in Redis/DB with TTL. Require `HUB_TASK_ENVELOPE_SECRET` at prod boot.

### ZT-16 — High — Off-host audit is optional and not Object-Lock-real

**Evidence:** `ship()` returns `skipped` when `HUB_AUDIT_S3_BUCKET` is empty (`core/audit_ship.py:66-70`). Compose does not set a bucket. `S3AuditStore.put` calls bare `put_object` (`providers/audit_store.py:38-53`). Settings default `AUDIT_S3_OBJECT_LOCK=True` even when the bucket is unlocked. `verify_shipped()` walks `store.objects`, which S3 does not populate.

**Impact:** Same as original ZT-08. Beat can “succeed” every minute while shipping nothing.

**Remediation:** Prod/compose boot-fail without a lock-verified bucket. `GetObjectLockConfiguration` at construct. `PutObject` with retention / `If-None-Match`. Independent download verifier. Vault the S3 secret.

### ZT-17 — High — WebSocket `findings` / `map.graph` subscribe is membership-blind

**Evidence:**

```38:40:realtime/authorize.py
    if topic in ("findings", "map.graph") or topic.startswith("demo."):
        return True
```

Delivery filter exists only for `findings` and only if `event.workspace_id` is truthy (`realtime/consumers.py:103-108`). Tests encode “any enrolled user may subscribe to `findings`” as required. `map.graph` change events have no workspace filter (`monitor/map_graph.py:37`). Combined with ZT-13, default-workspace incidents (including other tenants’ data) fan out to default members.

**Remediation:** Require membership, or workspace-qualify the topic. Fail closed on missing `workspace_id`. Test that workspace A does not receive B’s finding events.

### OPS-01 — High — Compose is not a production runtime, but README calls it the real shape

**Evidence:** `docker-compose.yml` has no `restart`, no healthcheck, no memory limits, no logging driver, no migrate sidecar, no Caddy/Tailscale sidecar. Image is labeled “dev-grade”, unpinned `python:3.12-slim`. `hub.settings.compose` turns off Secure cookies and SSL redirect, and the dirty tree pins WebAuthn RP to `localhost` plus Vite CSRF origins.

Pager default is `fake`. Deadman is skip-unless-configured. Hub Postgres is **not** on the nightly `provision.backup` path (that path is per-site SSH `pg_dump`). T1 restore unseals into a tempfile and checks `len(plaintext) > 0`; it does not `pg_restore`.

**Impact:** Crash stays down. Loopback HTTP cookies on a host that later publishes 8000 are session theft. There is no practiced Hub DR.

**Remediation:** Treat compose as lab-only. Production must boot `hub.settings.prod` behind HTTPS + Tailscale/Caddy, with healthchecks, Hub `pg_dump` off-box, KEK offline and not on the dump volume, real pager/deadman, and a restore drill that actually restores.

### ZT-18 — Medium — Staff/superuser still implies default-workspace admin/owner

`core/rbac.py:125-134` and `workspace_payload`. Creating `is_staff=True` in Django admin grants Hub admin on `default` without a `WorkspaceMembership`. `/admin/` is excluded from Hub 2FA middleware (OTP admin site is separate).

**Remediation:** Persist owners only via `bootstrap_owner`. Superuser ≠ tenant owner.

### ZT-19 — Medium — Login throttle does not count second-factor failures; cache is LocMem

`_login_failure` runs only on password miss (`core/views.py:79-83`). OTP/WebAuthn failures are audited, not counted. No `CACHES` setting → LocMem → per-process 10/min.

### ZT-20 — Medium — Default workspace can list unclaimed / global secret metadata

`core/hud/common.py` `workspace_secrets()` ORs in non-resource owners and unclaimed resource ids for slug `default`. Not plaintext, but owner graph leak.

### ZT-21 — Medium — Settings T1 secret binds skip the T1 overlay

`dns.cloudflare_connect`, `dns.origin_ca_plant`, and `aws.connect` are T1 in `frontend/src/api/action_tiers.js`. Backend still has `RequireRecentTouch`. Settings POSTs from ordinary forms (`Settings.jsx` Cloudflare/AWS panels). Partners correctly use `ActionButton`. A stolen session already inside the 5-minute window, or a raw 403 with no step-up UI, is the gap. Server authz is not bypassed.

**Dirty tree note:** Origin-CA plant now has a DNS-account select and still posts `{path}` only. That is the right shape. It still does not run the hardware-touch overlay.

### ZT-22 — Medium — Opt-in local sources without a root, and adopt path skip

`refuse_api_local_path` requires the root only when `HUB_LOCAL_SOURCE_ROOT` is set. Adopt copies `project.local_path` into `source_dir` without re-running `resolve_local_source`.

### FE-01 — Medium — No CSP on the SPA origin

`frontend/index.html` has no CSP. Prod Django sets HSTS/nosniff/DENY frames only. Compose has no edge in front of the UI. XSS would inherit `credentials: "include"` plus a readable CSRF cookie. Practical HTML sinks are almost only the TOTP QR `dangerouslySetInnerHTML`.

### FE-02 — Medium — Logout and idle

HUD logout POSTs then only changes `location.hash`; React user state remains until the 15s `/api/auth/me/` poll. That poll also stamps idle timeout, so an open tab never idles.

### INT-01 — Medium — Intake WSGI unbounded; git-push HMAC is id-only

`intake/app.py` `wsgi.input.read(length)`. Git-push MAC covers `job["id"]`, not url/ref/sha. Hub re-resolves git head, so SHA injection is constrained; metadata/DoS remain.

### ZT-23 — Low — KMS DEK wrap has no EncryptionContext; recovery codes are unsalted SHA-256

`providers/kms.py` encrypt/decrypt are blob-only. `core/otp.py` hashes recovery codes with SHA-256.

### ZT-24 — Low — `ensure_keyfile` chmods a world-readable KEK instead of refusing

Silent repair of a briefly exposed keyfile.

---

## Dirty working tree (this audit)

| File | Effect on the verdict |
|---|---|
| `hub/settings/compose.py` | Trusts Vite `http://localhost:5173` / `127.0.0.1:5173` for CSRF; WebAuthn RP `localhost`, origins `5173` and `:8000` only. Needed for local login. Confirms compose is not `hub.settings.prod`. Matches `docs/known-issues.md` (`127.0.0.1:5173` is an invalid WebAuthn domain). |
| `tests/test_settings_boot.py` | Pins the Vite origin split. 9/9 passed. |
| `frontend/src/screens/Settings.jsx` | Origin-CA account picker; path-only plant preserved; Connect/Plant still not T1 overlay. |
| `frontend/tests/settings-cloudflare.test.ts` | 5/5 `node:test` passed. |

Untracked `p35-bind/`, `p35-none/`, `tmp/`, `package-lock.json` at repo root were not treated as product surface.

---

## Strengths (do not regress)

- Prod refuses missing `HUB_SECRET_KEY`, FakeKEK, loopback WebAuthn origin, and `HUB_TEST_MODE`.
- Session auth, login CSRF, Secure cookies/HSTS under `hub.settings.prod`, mandatory HTTP 2FA.
- T1: two confirmed passkeys, 5-minute hardware touch, typed confirmation on HUD commands that use `ActionButton`.
- WebSockets: origin/session/OTP at connect; object topics check membership (global topics do not).
- Partner Ed25519: method, path, body hash, freshness, replay nonce, idempotency, Hub re-verify. HMAC/bearer inbound remains evaluation-only (`docs/hmac-bearer-evaluation.md`).
- Origin-CA plant: confined roots, 0600, no symlink, refuses vault.key and `v1.0-` service keys, `RequireRecentTouch`.
- Signed downloads: TTL, actor, workspace, deployment bound.
- Celery JSON only. Redis unpublished + `requirepass`.
- Workspace queryset helpers fail closed on `workspace=None`.
- Mutation wrapper still fails closed on unchecked mutants; floor now includes RBAC/audit/findings.

---

## Production-readiness verdict by plane

| Plane | Ready? |
|---|---|
| Identity (single default workspace, staff-attended) | Conditional — ZT-01/05/06/12 largely closed |
| Multi-workspace tenancy | **No** — ZT-13, ZT-17 |
| Secrets at rest | Conditional — vault AEAD yes; KEK is disk-equivalent; audit not immutable |
| Worker isolation | **No** — ZT-14, ZT-15, ZT-07 residual |
| Deploy/SSH | Conditional — SSH/build-off-host hygiene is good; unsigned `run_deploy` is not |
| Frontend operator UI | Conditional — cookie session/CSRF good; T1 overlay + CSP + logout not |
| Operations / DR | **No** — OPS-01, fake pager, no Hub backup, probes likely unbootable |
| Release evidence | **No** — `make lint` red; full T1/mutation/conformance not green this round |

**Overall: no.**

---

## Fix order (do not combine into one deploy)

1. **Containment:** fix probes boot vs KEK; require `HUB_LOCAL_SOURCE_ROOT` whenever local sources are on; keep compose off the public internet.
2. **Tenant truth:** delete `default_workspace()` fallbacks in producers; membership-gate WS `findings`/`map.graph`.
3. **Worker truth:** real Redis ACL + Postgres grants, or stop claiming a split; sign `run_deploy`/`run_adopt`; durable envelope nonces.
4. **Audit durability:** boot-fail without Object-Lock shipping; verify independently of the Hub DB.
5. **Ops:** `hub.settings.prod` + HTTPS terminator + Tailscale-only 8000; Hub `pg_dump` off-box; real pager/deadman; healthchecks/restart/limits.
6. **Evidence:** ruff-clean pager tests; serial `make review-round` on Python 3.12 / Node 22; mutation cold run; `check-generated`.

---

## Reproduction

```bash
source .venv/bin/activate
make lint                 # currently red: ruff in tests/test_delivery_behaviors.py, tests/test_pager.py
make log-scrub
make scripts-lint
pytest tests/test_zero_trust_authz.py tests/test_task_envelope.py \
       tests/test_local_sources.py tests/test_findings_tenancy.py \
       tests/test_audit.py tests/test_audit_ship.py tests/test_settings_boot.py
(cd frontend && npm audit --audit-level=high)
```

Compare with `docs/zero-trust-audit-2026-08-28.md`. Do not treat a green subset as `review-round`.

---

## What would change this to PASS

All of:

1. ZT-13 and ZT-17 closed with multi-workspace tests.
2. Probes worker boots without a KEK and cannot publish to deploys/control or read vault.
3. Every mutating Celery task is enveloped; replay is durable; envelope secret is required.
4. Prod refuses to boot without a verified Object-Lock audit store.
5. Production runtime is `hub.settings.prod` with HTTPS, Hub backups, pager, deadman, healthchecks — not loopback compose.
6. `make lint` and serial `make review-round` green on the declared CI toolchain.

Until then: **do not merge or deploy as a zero-trust-ready release.**
