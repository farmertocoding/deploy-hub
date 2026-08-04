# sample-node-site

CI fixture for the deploy-hub scanner's `node-ts` module (review3 §Q7, scanner addendum §S2–S4). A
minimal pnpm monorepo shaped like the reference trading stack: a Fastify + `ws` service with a fake
CCXT-style tick feed, worker_threads + SharedArrayBuffer S/R engine, a readiness-gated `/healthz`
with a deliberate warm-up delay, a static Vite frontend, a stub Python 3.12 backtesting component
(vectorbt/polars/duckdb), and sample on-disk state (`.parquet` / `.sqlite3` WAL / `.duckdb`). It is
**scanned, never executed** — every S3 detection rule and S4 STATIC check must fire positively
against this tree, and `MUTATIONS.md` documents the single-edit negative case for each check.
