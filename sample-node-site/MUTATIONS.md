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
| 10 | Rename the feed-age metric out of the `/healthz` payload (`feed_age`→`tick_gap`, `lastTickAgeS`→`tickGapS`, at its definition and its call site) | `packages/server/src/ingest.ts` + `index.ts` | `node-ts.ingest-staleness` | §S4 Ingestion daemon (§N2/§N3 staleness metric) |
| 11 | Rename the bounded-concurrency const and its comment (`CONCURRENCY`→`PARALLELISM`) so no bounded-concurrency pattern remains | `packages/server/src/ingest.ts` | `node-ts.ingest-backfill` | §S4 Ingestion daemon (§N4 rate-limit guidance) |
| 12 | Change the start script to `"start": "bun src/index.ts"` | `packages/server/package.json` | `node-ts.bun-dev-only` | §S4 Build & runtime (bun is dev-only) |
| 13 | Remove `trustProxy: true` from the Fastify constructor | `packages/server/src/index.ts` | `node-ts.fastify-serving` | §S4 Fastify serving |

Rules for the tests consuming this table:

- Apply each mutation in isolation to a fresh copy of the fixture; assert the named check fails
  **and** every other check keeps its pristine-tree result (single-cause discipline).
- Mutation 6 is the only place the fake secret string exists — it is written by the test at
  runtime and must never be committed to the fixture tree.
- Mutation 5 (deleting a file) and mutation 6 (adding one) are still "one edit" for the purposes
  of this contract. So is **renaming one identifier at its definition and its call sites**
  (mutations 10 and 11): renaming a producer without its consumers would leave the fixture
  failing `tsc`, and a fixture that does not compile is not a fixture. Mutation 10 spans two
  files for exactly that reason — and because `node-ts.ingest-staleness` greps the concatenated
  text of *every* service file mentioning `healthz`, so editing only the `/healthz` payload
  leaves `ingest.ts` still matching.
- Mutations 12 and 13 are asserted by their own named tests rather than the parametrized matrix
  (they predate it); they carry the `Q7-NODE-FIXTURE` marker like every other row.

**Checks whose negative case is a branch, not a tier flip.** `node-ts.monorepo`,
`node-ts.recognized-deps` and `node-ts.worker-threads` are §S3 *recording* results: they are
always `ok` and report what was found, so no mutation can flip their tier. `node-ts.offline-component`
is emitted only when a Python offline component exists, so its negative is the check's absence, and
`node-ts.service-package` warns on a tree with no deployable package — which the pristine fixture
cannot be. Their negatives are therefore asserted on a minimal single-package tree by
`tests/test_scanner_node_ts.py::test_issue_r4_11_detection_recordings_have_their_negative_branch`,
not by a row above. Every `node-ts.*` check now has a negative case in one form or the other
(R4-11 WI-8).

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
