// RT-35-DEGRADED-POLLING, client half: when the socket is unavailable the panels
// degrade to VISIBLE 10 s REST polling, never silently stale, and reconnect resumes
// snapshot-then-stream. The state machine is createEventsClient (useEvents.js) with
// injected socket + timers — a hook-shaped client is a state machine no
// renderToStaticMarkup test can reach, which is why it is a factory.
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { createEventsClient } from "../src/useEvents.js";
import { StatusPill } from "../src/Chrome.jsx";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };

const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");
const flush = () => new Promise<void>((r) => setImmediate(r));

class FakeSocket {
  onopen: any; onmessage: any; onclose: any;
  readyState = 0;
  sent: string[] = [];
  send(s: string) { this.sent.push(s); }
  close() { this.readyState = 3; }
  open() { this.readyState = 1; this.onopen(); }
  fail(code = 1006) { this.readyState = 3; this.onclose({ code }); }
  message(msg: any) { this.onmessage({ data: JSON.stringify(msg) }); }
}

// Deterministic timers: schedule/cancel/now injected into the client, advance() fires
// due callbacks in time order (chained schedules included) and flushes microtasks so
// awaited snapshots inside a tick settle before the next one fires.
function fakeTimers() {
  let t = 0;
  let nextId = 1;
  const pending = new Map<number, { fn: () => void; at: number }>();
  return {
    schedule: (fn: any, ms: number) => {
      const id = nextId++;
      pending.set(id, { fn, at: t + ms });
      return id;
    },
    cancel: (id: number) => pending.delete(id),
    advance: async (ms: number) => {
      const target = t + ms;
      for (;;) {
        const due = [...pending.entries()]
          .filter(([, p]) => p.at <= target)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!due) break;
        t = due[1].at;
        pending.delete(due[0]);
        due[1].fn();
        await flush();
      }
      t = target;
    },
    now: () => new Date(2026, 7, 22, 12, 0, 0, t),
  };
}

function harness() {
  const sockets: FakeSocket[] = [];
  const timers = fakeTimers();
  const statuses: string[] = [];
  const client = createEventsClient({
    makeSocket: () => { const s = new FakeSocket(); sockets.push(s); return s; },
    schedule: timers.schedule, cancel: timers.cancel, now: timers.now,
    onChange: (c: any) => statuses.push(c.status),
  });
  return { sockets, timers, statuses, client };
}

test("socket_failure_switches_to_ten_second_polling", async () => {
  const { sockets, timers, statuses, client } = harness();
  let snapshots = 0;
  const events: any[] = [];
  client.subscribe("alerts", (e: any) => events.push(e),
    async () => ({ seq: ++snapshots, data: [] }));
  await flush();
  assert.equal(snapshots, 1, "subscribe itself snapshots once");

  client.start();
  sockets[0].fail();
  await flush();

  // The INITIAL connect failing is not a blip — there was never a live socket — so
  // the client is degraded immediately and polls on entry, not 10 s later.
  assert.ok(statuses.includes("degraded"), statuses.join(","));
  assert.equal(snapshots, 2, "entering degraded polls every subscribed topic once");

  // …then every 10 s, exactly once per tick, even though the 1.5 s reconnect timer
  // keeps making sockets that go nowhere.
  await timers.advance(10_000);
  assert.equal(snapshots, 3);
  await timers.advance(10_000);
  assert.equal(snapshots, 4);

  // A reconnect attempt failing AGAIN must not stack a second poll loop.
  sockets[sockets.length - 1].fail();
  await flush();
  await timers.advance(10_000);
  assert.equal(snapshots, 5,
    "a repeated failure must not stack a second poll loop — one tick per 10 s");

  // A live socket that drops reads "reconnecting" first (a blip is not unavailability);
  // the NEXT failure is what re-enters degraded.
  sockets[sockets.length - 1].open();
  await flush();
  assert.equal(statuses[statuses.length - 1], "live");
  sockets[sockets.length - 1].fail();
  await flush();
  assert.equal(statuses[statuses.length - 1], "reconnecting");
});

test("degraded_mode_is_visible_not_silent", () => {
  // The pill NAMES the mode and stamps the data. This is the whole difference
  // between "degraded" and "silently stale" (RT-35): an operator reading the screen
  // knows it is a 10 s poll and knows how old the data is.
  const markup = renderToStaticMarkup(React.createElement(StatusPill, {
    status: "degraded", asOf: new Date(2026, 7, 22, 2, 3, 4),
  }));
  const text = visibleText(markup);
  assert.match(text, /degraded/);
  assert.match(text, /polling every 10 s/);
  assert.match(text, /data as of \d{1,2}:\d{2}:\d{2}/);
  assert.match(markup, /role="status"/, "the mode change is announced, not only drawn");

  // Live renders NOTHING — a pill that is always present is a pill nobody reads —
  // and the other non-live states are visible too.
  assert.equal(renderToStaticMarkup(React.createElement(StatusPill,
    { status: "live", asOf: null })), "");
  for (const status of ["connecting", "reconnecting", "auth-required"]) {
    assert.ok(visibleText(renderToStaticMarkup(React.createElement(StatusPill,
      { status, asOf: null }))).length > 0, status);
  }
});

test("reconnect_resnapshots_before_streaming", async () => {
  const { sockets, timers, client } = harness();
  const events: any[] = [];
  let snapshots = 0;
  client.subscribe("alerts", (e: any) => events.push(e), async () => {
    snapshots += 1;
    return { seq: 5, data: [{ seq: 5, event: { line: "history" } }] };
  });
  await flush();
  client.start();
  sockets[0].fail();
  await flush(); // degraded; entry poll ran (snapshots = 2)
  await timers.advance(1_500); // the reconnect timer makes the next socket

  const s = sockets[sockets.length - 1];
  events.length = 0;
  s.open();
  // The subscribe frame must not be on the wire before the snapshot has landed:
  // snapshot-THEN-stream is the reconnect contract (§D7), and polling is over.
  assert.equal(s.sent.length, 0,
    "the subscribe frame must wait for the snapshot to resolve (snapshot-THEN-stream)");
  await flush();
  assert.equal(snapshots, 3, "reconnect must refetch the snapshot before streaming");
  assert.ok(s.sent.some((f) => JSON.parse(f).action === "subscribe"));
  assert.equal(events[0]?.__snapshot, true, "the repaint precedes any stream event");

  // Events at or below the snapshot's seq are pre-snapshot history and are dropped;
  // the one after it streams through.
  s.message({ topic: "alerts", seq: 5, event: { line: "stale" } });
  s.message({ topic: "alerts", seq: 6, event: { line: "fresh" } });
  assert.deepEqual(events.slice(1).map((e) => e.line), ["fresh"]);

  // …and the poll loop is genuinely gone: ten more seconds fetch nothing.
  await timers.advance(10_000);
  assert.equal(snapshots, 3,
    "the poll loop should be stopped after reconnect, but a tick still fired");
});
