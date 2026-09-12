/**
 * Ingestion daemon — CCXT websocket streams normalized to one Zod Bar schema.
 * Background loop, not a request handler: a dead feed fails no HTTP check, so
 * last-tick age is tracked here and surfaced through /healthz (§S4 ingestion).
 */
import ccxt from "ccxt";
import { z } from "zod";

export const Bar = z.object({
  symbol: z.string(),
  ts: z.number().int(),
  open: z.number(),
  high: z.number(),
  low: z.number(),
  close: z.number(),
  volume: z.number().nonnegative(),
});
export type Bar = z.infer<typeof Bar>;

// Feeds that permit only ONE concurrent connection per account (Alpaca standard
// plan). During a blue-green overlap two daemons would fight over the socket —
// the Hub flags these and requires recreate or an ingestion-handoff pre-stop hook.
export const EXCLUSIVE_UPSTREAM = ["alpaca"];

const BACKFILL_CONCURRENCY = 2; // bounded: FinMind/Alpaca rate limits (§N4)
const CHECKPOINT_FILE = `${process.env.DATA_DIR ?? "./data"}/backfill.checkpoint`;

interface IngestHooks {
  onBackfillProgress: (pct: number) => void;
  onBar: (bar: Bar) => void;
}

let lastTickMs = 0;
let connected = false;

export function feedStatus() {
  return {
    connected,
    lastTickAgeS: lastTickMs === 0 ? null : Math.round((Date.now() - lastTickMs) / 1000),
  };
}

export function startIngestion(hooks: IngestHooks): void {
  // Ready flips on backfillDone; starting ccxt.pro.binance in parallel lets
  // watchTrades starve checkpoint writes so /healthz checks freeze mid-warm.
  void (async () => {
    await backfill(hooks);
    void streamLoop(hooks);
  })();
}

/**
 * Backfill resumes from the last durable checkpoint rather than re-pulling the
 * whole history on every restart — a full re-backfill after a crash would burn
 * the FinMind quota and trip Alpaca rate limits.
 */
async function backfill(hooks: IngestHooks): Promise<void> {
  const start = await resumeFromCheckpoint(CHECKPOINT_FILE);
  const chunks = planChunks(start, Date.now());
  let done = 0;

  // bounded concurrency: never more than BACKFILL_CONCURRENCY requests in flight
  const queue = [...chunks];
  await Promise.all(
    Array.from({ length: BACKFILL_CONCURRENCY }, async () => {
      for (let chunk = queue.shift(); chunk; chunk = queue.shift()) {
        const bars = await fetchHistoricalChunk(chunk);
        for (const raw of bars) hooks.onBar(Bar.parse(raw));
        await writeCheckpoint(CHECKPOINT_FILE, chunk.until);
        done += 1;
        hooks.onBackfillProgress(Math.min(100, Math.round((done / chunks.length) * 100)));
      }
    }),
  );
  hooks.onBackfillProgress(100);
}

/**
 * Live stream with reconnect-with-backoff: exponential from 1s to 60s cap,
 * reset after a healthy tick. The loop never gives up — upstream silence is
 * normal (closed markets); process restarts fix nothing here.
 */
async function streamLoop(hooks: IngestHooks): Promise<void> {
  const exchange = new ccxt.pro.binance({ enableRateLimit: true }); // keyless public ws
  let backoffMs = 1_000;

  for (;;) {
    try {
      connected = true;
      for (;;) {
        const trades = await exchange.watchTrades("BTC/USDT");
        lastTickMs = Date.now();
        backoffMs = 1_000; // healthy tick resets the backoff
        for (const t of trades) hooks.onBar(tradeToBar(t));
      }
    } catch (err) {
      connected = false;
      await sleep(backoffMs + Math.floor(Math.random() * 250)); // jitter
      backoffMs = Math.min(backoffMs * 2, 60_000); // exponential, capped
    }
  }
}

// --- small helpers (fixture stubs — realistic shape, no live I/O) -----------

interface Chunk {
  since: number;
  until: number;
}

function planChunks(since: number, until: number): Chunk[] {
  const step = 6 * 60 * 60 * 1000;
  const out: Chunk[] = [];
  for (let t = since; t < until; t += step) out.push({ since: t, until: Math.min(t + step, until) });
  return out;
}

async function resumeFromCheckpoint(path: string): Promise<number> {
  const { readFile } = await import("node:fs/promises");
  try {
    return Number(await readFile(path, "utf8"));
  } catch {
    return Date.now() - 7 * 24 * 60 * 60 * 1000; // cold start: one week
  }
}

async function writeCheckpoint(path: string, ts: number): Promise<void> {
  const { mkdir, writeFile } = await import("node:fs/promises");
  const slash = path.lastIndexOf("/");
  if (slash > 0) await mkdir(path.slice(0, slash), { recursive: true });
  await writeFile(path, String(ts), "utf8");
}

async function fetchHistoricalChunk(chunk: Chunk): Promise<unknown[]> {
  void chunk;
  return []; // fixture: shape only
}

function tradeToBar(t: { symbol?: string; timestamp?: number; price?: number; amount?: number }): Bar {
  const price = t.price ?? 0;
  return Bar.parse({
    symbol: t.symbol ?? "BTC/USDT",
    ts: t.timestamp ?? Date.now(),
    open: price,
    high: price,
    low: price,
    close: price,
    volume: t.amount ?? 0,
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}
