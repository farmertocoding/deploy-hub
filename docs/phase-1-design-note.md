# Phase 1 Design Note — Scanner & Wizard (modules: django + node-ts)

**Phase:** 1 per §I as amended (scanner addendum §S1–S5, review3 §M1/§N2/§Q7/§V4–V7/§V10)
**Role:** Architect design note per build-process.md §2① · **Date:** 2026-08-04
**Estimate:** ~1 week incl. review rounds (V10). Protective cut pre-approved: readiness
report on the real repos ships even if wizard polish slips.

## 1. What lands this phase

1. **`scanner/core.py`** — module registry + dispatch: `detect_modules(path) → [module]`
   (multiple matches merge into ONE manifest, §V5), `scan(path) → ScanReport`
   (schema_version'd per §D8), report persistence on `Project`, diff vs previous run.
2. **Module interface (§S1 + §M1)** — `detect() → checks[] → wizard_questions[] →
   dockerfile_template`, where every check carries `execution: static | executing`.
   **Hub-side scan runs static checks ONLY** (SEC-SCAN-NOEXEC: T1 test asserts the
   Hub path invokes zero subprocess/npm/pip/pnpm entry points). Executing checks are
   *emitted as a sandbox job spec* this phase (the sandbox runner itself is Phase 2
   machinery); the report marks them "pending sandbox" honestly rather than faking.
3. **`scanner/modules/django.py`** — §5.1 list as static checks (AST/file/manifest
   reads): settings split/env-driven, DEBUG, SECRET_KEY source + git-history leak scan
   (gitleaks), ALLOWED_HOSTS, DB engine, static config, security settings, CSRF/CORS,
   migrations state (read-only), pinned deps, server present. **Per §J7 inventory
   (SCAN-DJANGO-UV / SCAN-DJANGO-ASGI):** reads `pyproject.toml`+`uv.lock` as well as
   requirements.txt (uv is the fleet norm); tolerates Py 3.12–3.14 / Django 5.2–6;
   detects ASGI-only serving (daphne/uvicorn, Channels) and preserves the ASGI command
   instead of assuming gunicorn; detects sidecar processes in compose files (worker/
   beat/scheduler/one-shot migrate) and records them as manifest components (§V5).
4. **`scanner/modules/node_ts.py`** — §S3 detection + §S4 static checks: pnpm
   workspace, engines pin, tsconfig strict, prod-runs-compiled-JS, Bun-dev-only,
   trustProxy/body-limits/SIGTERM patterns, ws heartbeat + reconnect advice,
   readiness-gate pattern (SCAN-S4-READINESS-PATTERN), ingestion daemon checks,
   exclusive-upstream flag (§N4), local-state findings → single-instance + recreate
   strategy + named-volume + backup-registry manifest fields (§N1/§N5/§N6),
   `jobs_image` stub (§N7), days-to-full forecast (static: data-dir growth heuristic).
5. **Fallback modules (§V4)** — `dockerfile.py` + `static.py`, lowest precedence;
   existing Dockerfile validated (EXPOSE/non-root patterns; Trivy is a pipeline gate),
   never a bypass.
6. **Common core** — gitleaks scan, lockfile pinned, .gitignore sanity, tests-exist
   advisory, healthz per §E9 fallback, digest-pin check on FROM lines, exposure-mode
   auth warning (SCAN-M4-EXPOSURE-AUTH).
7. **`sample-node-site/` fixture (Q7-NODE-FIXTURE)** — minimal pnpm monorepo (Fastify+ws
   fake tick feed, worker_threads, delayed-ready /healthz, stub pyproject with
   vectorbt, sample .parquet/.sqlite3) engineered so every S3 rule and S4 check fires,
   plus a mutation set for each check's negative case. `sample-site/` (Django) gains
   uv + ASGI + sidecar variants per the J7 findings.
8. **Wizard (F7-lite)** + manifest materialization (§V6): DRF endpoints through the
   §4.5 pipeline (serializer → generated zod → RHF), module-contributed questions,
   answers persist on blur, output = stored deployment manifest (deploys/ will read
   only this). UI: readiness report in three collapsible tiers.
9. **CLI parity:** `python -m hub scan <path>` renders the same report as text.
10. **Milestone demos (verify: demo):** readiness report on the real trading repo AND
    on TAKKO/E-invoice/hr-saas/SATURDAYS (the J7 four validate the django module
    against reality; records in conformance/demos/phase-1.md).
    **UPDATE 2026-08-20 (D-016):** real-repo demos are **SATURDAYS_site and TAKKO
    only.** J7 inventory of the other two stands; they are not demo artifacts.
    `sample-node-site/` remains the Q7 in-repo fixture.

## 2. Interfaces / tables that change

`Project` gains `scan_report` JSON (schema_version 1) — already stubbed. **No other
product tables** (Site/Target stay Phase 2). New code interfaces: `ScannerModule`
protocol, `Check` dataclass (id, tier, execution, result), `Manifest` pydantic model
(components list per §V5: service, static_route, jobs, volumes, deploy_strategy,
exposure, healthz contract fields per §N2). The /healthz JSON contract
`{live, ready, checks:{...}}` is pinned this phase as a Phase-1 interface (§N2).

## 3. Applicable registry reqs (phase ≤ 1 due at exit)

SCAN-S1-MODULAR-DISPATCH · SEC-SCAN-NOEXEC · SCAN-S3-DETECTION-RULES ·
SCAN-S4-READINESS-PATTERN · SCAN-V4-FALLBACK-PRECEDENCE · SCAN-DJANGO-UV ·
SCAN-DJANGO-ASGI · SCAN-M4-EXPOSURE-AUTH · Q7-NODE-FIXTURE · ARCH-V6-DEPLOYS-NO-SCANNER-IMPORT ·
SEC-69-ENVELOPE-ENCRYPTION (wizard env answers write through the vault path) ·
VAL-45-REJECTED-INPUT-AUDITED · SEC-B10-SSRF-GUARD (git-URL validator) ·
SEC-69-NO-SECRETS-IN-EXHAUST (static-gate).

## 4. Exit demo

`python -m hub scan` against sample-node-site → report fires every check; against the
four inventoried real repos → honest reports (uv/ASGI/sidecars recognized, no false
Blockers); wizard walk on sample-node-site → manifest stored with recreate strategy,
volumes, warmup fields; conformance `check.py --phase 1` green; review rounds to
convergence per §4.

## 5. DECISION markers opened

- **D-004** gitleaks invocation: vendored binary vs pip `detect-secrets` (static-check
  classification requires no network at scan time) — Researcher decides.
- **D-005** manifest storage: JSONField on Project vs dedicated Manifest model —
  Architect leans JSONField (pydantic-validated, schema_version'd) until Phase 2
  tables exist; revisit at Phase 2 design note.
- **J-1** (carried from Phase 0): **closed 2026-08-20, D-015.** T2 = sshd+systemd
  container with inner docker on vfs; Multipass is not needed sooner. Record:
  `docs/j1-t2-fidelity-spike.md`.

## 6. Out of scope (explicitly)

The sandbox runner for executing checks (Phase 2; this phase only classifies and
emits job specs) · any SSH/provisioning · deploy pipeline changes (§N1 work is
Phase 2) · WebAuthn · Site/Target models · auto-fix diffs beyond the settings-split
template (§E9 honest scoping).
