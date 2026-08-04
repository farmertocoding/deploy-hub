# Mutation set — negative cases for the `node-ts` scanner module

This fixture is engineered so every §S3 detection rule and every §S4 **static** check passes
(fires positively) on the pristine tree. Each mutation below is **one file edit** the module tests
apply to a temp copy; after the edit, exactly the named check must flip from `ok` to its failing
tier. Check ids follow the scanner-core slug convention (`node-ts.*` for module checks, `core.*`
for common-core checks); plan-level ids from the addendum are noted where one exists
(e.g. `SCAN-S4-READINESS-PATTERN`). The tests themselves live in the scanner test suite —
this table is the contract between fixture and tests.

| # | Mutation (one edit) | File | Check id that must flip | Plan ref |
|---|---------------------|------|-------------------------|----------|
| 1 | Set `"strict": false` in compilerOptions | `packages/server/tsconfig.json` | `node-ts.strict-build` | §S4 Build & runtime |
| 2 | Remove the `process.on("SIGTERM", ...)` handler block | `packages/server/src/index.ts` | `node-ts.graceful-shutdown` | §S4 Fastify serving |
| 3 | Remove the ready gating from `/healthz` (return `ready: true` unconditionally, i.e. drop the `backfillDone` term) | `packages/server/src/index.ts` | `node-ts.readiness-pattern` | §S4 Warm-up / readiness, `SCAN-S4-READINESS-PATTERN` |
| 4 | Remove the ping/pong heartbeat (`setInterval` block + `on("pong")` handler) | `packages/server/src/index.ts` | `node-ts.ws-heartbeat` | §S4 WebSocket specifics |
| 5 | Delete the file | `pnpm-lock.yaml` | `core.lockfile` | §S1 common core / §S4 frozen-lockfile |
| 6 | Add a `.env` file containing `ALPACA_SECRET=AKFAKEFAKEFAKEFAKE1234` | `.env` (new file) | `core.secret-scan` | §S1 common core, §S4 Config & secrets (entropy scan §4.5) |
| 7 | Remove the reconnect/backoff loop (drop the `catch` + `backoffMs` retry from `streamLoop`, let the error propagate) | `packages/server/src/ingest.ts` | `node-ts.ingest-reconnect` | §S4 Ingestion daemon |
| 8 | Change the start script to `"start": "ts-node src/index.ts"` | `packages/server/package.json` | `node-ts.compiled-js` | §S4 Build & runtime (prod runs compiled JS) |
| 9 | Remove the `"engines"` block | `packages/server/package.json` | `node-ts.engines-pin` | §S4 Build & runtime (engines pinned to Node 22) |

Rules for the tests consuming this table:

- Apply each mutation in isolation to a fresh copy of the fixture; assert the named check fails
  **and** every other check keeps its pristine-tree result (single-cause discipline).
- Mutation 6 is the only place the fake secret string exists — it is written by the test at
  runtime and must never be committed to the fixture tree.
- Mutation 5 (deleting a file) and mutation 6 (adding one) are still "one edit" for the purposes
  of this contract.

Positive-fire inventory (what the pristine tree exercises), for the detection/dispatch tests:

- **§S3 detection:** `pnpm-workspace.yaml` (monorepo, 2 packages) · root + server `engines.node: "22"` ·
  server `tsconfig.json` `strict: true` · deps fastify/ws/zod/ccxt (ingestion checks armed) ·
  `worker_threads` + `SharedArrayBuffer` + `Float64Array` in `src/engine.ts` · `pyproject.toml` with
  vectorbt/polars/duckdb (Python offline component → second module match, composition case) ·
  data-path heuristics: `data/bars-2026-01.parquet`, `data/app.sqlite3` + `-wal`, `data/levels.duckdb`.
- **§S4 static patterns:** `trustProxy: true` · `bodyLimit` · `0.0.0.0` + `process.env.PORT` listen ·
  `/healthz` pinned JSON `{live, ready, checks: {feed_age_s, backfill_pct}}` with ready gated on
  backfill · SIGTERM drain closing the ws server · ws server heartbeat · reconnect-with-backoff ·
  last-tick-age into healthz · `resumeFromCheckpoint` + bounded backfill concurrency ·
  `EXCLUSIVE_UPSTREAM = ["alpaca"]` (exclusive-upstream flag → recreate/handoff question) ·
  compiled-JS start script, bun as devDependency only · web package env-driven `VITE_WS_URL`.
