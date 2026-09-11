/**
 * S/R level service — Fastify HTTP (history, health) + native ws (live push).
 *
 * Deploy-relevant contracts (scanner addendum §S4):
 *   - binds 0.0.0.0:$PORT behind Caddy, trustProxy on
 *   - /healthz splits liveness from readiness; ready flips only after backfill
 *   - SIGTERM = graceful shutdown: stop intake, close ws server, drain in-flight
 *   - server-side ws heartbeat (ping/pong) so half-open sockets are reaped
 */
import Fastify from "fastify";
import { WebSocketServer, WebSocket } from "ws";
import { z } from "zod";
import { startIngestion, feedStatus } from "./ingest.js";
import { Engine } from "./engine.js";

const PORT = Number(process.env.PORT ?? 8080);
const HEARTBEAT_MS = 15_000;

const app = Fastify({
  trustProxy: true, // TLS terminates at Caddy; honor X-Forwarded-* from it only
  bodyLimit: 64 * 1024, // history queries are tiny; reject anything bigger
  requestTimeout: 10_000,
  connectionTimeout: 5_000,
  logger: true,
});

const engine = new Engine(Number(process.env.WORKER_THREADS ?? 2));

// ---------------------------------------------------------------------------
// Warm-up state. The ring-buffer engine is meaningless until history backfill
// completes — readiness gates traffic cutover on it (deliberate warm-up).
// ---------------------------------------------------------------------------
let backfillDone = false;
let backfillPct = 0;

startIngestion({
  onBackfillProgress: (pct) => {
    backfillPct = pct;
    if (pct >= 100) backfillDone = true; // ready flips here, never before
  },
  onBar: (bar) => engine.push(bar),
});

// ---------------------------------------------------------------------------
// Health. Pinned JSON contract: { live, ready, checks: { feed_age_s, ... } }.
// live   = process up, event loop responsive (uptime probe / reconciler)
// ready  = warm engine, safe to receive cut-over traffic (pipeline gate only)
// feed_age_s = staleness metric, its own Finding class — never a restart trigger
// ---------------------------------------------------------------------------
app.get("/healthz", async () => {
  const feed = feedStatus();
  return {
    live: true,
    ready: backfillDone,
    checks: {
      feed_age_s: feed.lastTickAgeS,
      backfill_pct: backfillPct,
      upstream: feed.connected ? "upstream-connected" : "upstream-down",
      ws_clients: wss.clients.size,
    },
  };
});

const LevelsQuery = z.object({
  symbol: z.string().min(1).max(32),
  limit: z.coerce.number().int().min(1).max(500).default(100),
});

app.get("/api/levels", async (req, reply) => {
  if (!backfillDone) {
    return reply.code(503).send({ error: "warming_up", backfill_pct: backfillPct });
  }
  const q = LevelsQuery.parse(req.query);
  return { symbol: q.symbol, levels: engine.levels(q.symbol, q.limit) };
});

// ---------------------------------------------------------------------------
// Live push: native ws sharing Fastify's HTTP server. Server-side heartbeat —
// ping every HEARTBEAT_MS, terminate peers that missed the previous ping.
// Clients reconnect with snapshot-then-stream (§3.5 pattern).
// ---------------------------------------------------------------------------
type LiveSocket = WebSocket & { isAlive?: boolean };

const wss = new WebSocketServer({ server: app.server, path: "/ws/levels" });

wss.on("connection", (ws: LiveSocket) => {
  ws.isAlive = true;
  ws.on("pong", () => {
    ws.isAlive = true;
  });
  // snapshot first, then incremental stream
  ws.send(JSON.stringify({ type: "snapshot", levels: engine.snapshot() }));
});

const heartbeat = setInterval(() => {
  for (const client of wss.clients as Set<LiveSocket>) {
    if (client.isAlive === false) {
      client.terminate();
      continue;
    }
    client.isAlive = false;
    client.ping();
  }
}, HEARTBEAT_MS);

engine.onLevelChange((update) => {
  const frame = JSON.stringify({ type: "delta", update });
  for (const client of wss.clients) {
    if (client.readyState === WebSocket.OPEN) client.send(frame);
  }
});

// ---------------------------------------------------------------------------
// Graceful shutdown — required for blue-green cutover to be clean. Close the
// ws server (stops new sockets, notifies peers), let in-flight HTTP drain via
// fastify.close(), then exit. The pipeline's per-site grace period covers this.
// ---------------------------------------------------------------------------
let shuttingDown = false;

process.on("SIGTERM", () => {
  if (shuttingDown) return;
  shuttingDown = true;
  app.log.info("SIGTERM: draining");

  clearInterval(heartbeat);
  for (const client of wss.clients) {
    client.close(1001, "server shutting down");
  }
  wss.close(() => {
    app.log.info("ws server closed");
  });

  void engine
    .stop()
    .then(() => app.close()) // waits for in-flight requests to drain
    .then(() => process.exit(0));

  // hard deadline in case a socket refuses to die
  setTimeout(() => process.exit(1), 20_000).unref();
});

app
  .listen({ host: "0.0.0.0", port: PORT })
  .then(() => app.log.info(`listening on 0.0.0.0:${PORT}`))
  .catch((err) => {
    app.log.error(err);
    process.exit(1);
  });
