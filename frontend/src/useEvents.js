// The one multiplexed socket (§3.5/§D7): subscribe/unsubscribe by topic,
// snapshot-then-stream on connect AND reconnect, per-topic seq gap detection —
// and RT-35's degraded mode: when the socket is UNAVAILABLE (not merely blinking),
// every subscribed topic's REST snapshot is re-fetched every 10 s so the panels are
// visibly polled rather than silently stale, and reconnect resumes
// snapshot-then-stream through the same syncTopic path polling uses.
//
// Contract: subscribe(topic, handler, snapshotFn?)
//  - snapshotFn (optional) fetches `${topic}` snapshot -> {seq, data}; called before
//    the stream is trusted, again after every reconnect, and on every degraded-mode
//    poll tick. Events with seq <= snapshot.seq are discarded (§D7: exactly one code
//    path for load+resume — and now for the poll, which is the same fetch).
//
// The client is a plain factory, extracted from the hook so the state machine is
// testable under node --test with an injected socket and injected timers
// (tests/degraded.test.ts): renderToStaticMarkup runs no effects, so a hook-shaped
// socket client is a state machine no test in this tree can reach.
import { useEffect, useRef, useState } from "react";

// Status ladder: connecting → live ⇄ reconnecting → degraded → live; auth-required
// is terminal. ONE failed (re)connect is a blip and reads "reconnecting"; the next
// failure means the socket is unavailable in RT-35's sense, and that is when the
// 10 s polling starts. The initial connect failing goes straight to degraded — there
// was never a live socket to be optimistic about.
export function createEventsClient({
  makeSocket,
  schedule = (fn, ms) => setTimeout(fn, ms),
  cancel = (id) => clearTimeout(id),
  now = () => new Date(),
  onChange = () => {},
  retryMs = 1500,
  pollMs = 10_000,
}) {
  let ws = null;
  let closed = false;
  let status = "connecting";
  let asOf = null; // when the data on screen was last confirmed against the server
  let pollTimer = null;
  let retryTimer = null;
  const subs = new Map(); // topic -> {handler, snapshotFn}
  const seqs = new Map(); // topic -> last seen seq

  const emit = () => onChange({ status, asOf });
  const set = (s) => { if (status !== s) { status = s; emit(); } };

  async function syncTopic(topic) {
    const sub = subs.get(topic);
    if (!sub) return;
    if (sub.snapshotFn) {
      // The catch must wrap ONLY the fetch: a handler exception misreported as a
      // "snapshot failed" both hides the bug and skips the repaint (live-demo
      // finding, 2026-08-03 — intermittent lost-lines after reconnect).
      let snap = null;
      try {
        snap = await sub.snapshotFn(topic); // {seq, data}
      } catch (err) {
        sub.handler({ __snapshot_failed: true, status: err?.status },
          seqs.get(topic) ?? 0);
      }
      if (snap) {
        seqs.set(topic, snap.seq ?? 0);
        // The "data as of" stamp is the poll's honesty line (RT-35): it moves only
        // on a CONFIRMED snapshot, never on the tick that merely tried.
        asOf = now();
        emit();
        sub.handler({ __snapshot: true, data: snap.data ?? [] }, snap.seq ?? 0);
      }
    }
    if (ws?.readyState === 1) {
      ws.send(JSON.stringify({ action: "subscribe", topics: [topic] }));
    }
  }

  // In degraded mode the socket is not open, so syncTopic is a pure REST snapshot —
  // the SAME function reconnect runs, which is what keeps §D7's "one code path"
  // claim true with polling added.
  function pollAll() {
    for (const topic of subs.keys()) syncTopic(topic);
  }

  function startPolling() {
    if (pollTimer !== null) return; // repeated failed reconnects must not stack ticks
    pollAll();
    const tick = () => { pollAll(); pollTimer = schedule(tick, pollMs); };
    pollTimer = schedule(tick, pollMs);
  }

  function stopPolling() {
    if (pollTimer !== null) { cancel(pollTimer); pollTimer = null; }
  }

  function connect() {
    const s = makeSocket();
    ws = s;
    s.onopen = () => {
      if (closed) return;
      stopPolling();
      set("live");
      // Snapshot-then-stream for every subscribed topic — same path as initial load.
      for (const topic of subs.keys()) syncTopic(topic);
    };
    s.onmessage = (e) => {
      const msg = JSON.parse(e.data);
      if (!msg.topic) return;
      const sub = subs.get(msg.topic);
      if (!sub) return;
      const last = seqs.get(msg.topic) ?? 0;
      if (msg.seq <= last) return; // duplicate or pre-snapshot
      if (msg.seq > last + 1 && last !== 0) {
        // Gap detected: refetch snapshot rather than pretend continuity (§D7).
        syncTopic(msg.topic);
        return;
      }
      seqs.set(msg.topic, msg.seq);
      sub.handler(msg.event, msg.seq);
    };
    s.onclose = (e) => {
      if (closed) return;
      // 4401/4403 are terminal (unauthenticated / enrollment required): retrying
      // can never succeed and would grind out a security AuditEvent every 1.5s
      // (round-3 finding). Surface auth-required instead — and stop the poll, which
      // would grind out the same AuditEvent through REST.
      if (e.code === 4401 || e.code === 4403) {
        stopPolling();
        set("auth-required");
        return;
      }
      if (status === "live") {
        set("reconnecting");
      } else {
        // connecting/reconnecting/degraded and the socket failed AGAIN: the socket
        // is unavailable, not blinking. Visible 10 s polling from here (RT-35) —
        // status first, so the entry poll's "data as of" stamp lands on a pill that
        // already says degraded.
        set("degraded");
        startPolling();
      }
      retryTimer = schedule(connect, retryMs);
    };
  }

  return {
    start() { closed = false; connect(); },
    close() {
      closed = true;
      stopPolling();
      if (retryTimer !== null) { cancel(retryTimer); retryTimer = null; }
      ws?.close();
    },
    subscribe(topic, handler, snapshotFn) {
      subs.set(topic, { handler, snapshotFn });
      seqs.delete(topic);
      syncTopic(topic);
    },
    unsubscribe(topic) {
      subs.delete(topic);
      seqs.delete(topic);
      if (ws?.readyState === 1) {
        ws.send(JSON.stringify({ action: "unsubscribe", topics: [topic] }));
      }
    },
  };
}

export function useEvents() {
  const [conn, setConn] = useState({ status: "connecting", asOf: null });
  const clientRef = useRef(null);
  if (!clientRef.current) {
    // Created during render but SIDE-EFFECT-FREE until start(): the socket exists
    // only once the effect below runs, so a render that never commits opens nothing.
    clientRef.current = createEventsClient({
      makeSocket: () => {
        const proto = location.protocol === "https:" ? "wss" : "ws";
        return new WebSocket(`${proto}://${location.host}/ws/events/`);
      },
      onChange: (c) => setConn(c),
    });
  }
  useEffect(() => {
    const client = clientRef.current;
    client.start();
    return () => client.close();
  }, []);
  const client = clientRef.current;
  return { status: conn.status, asOf: conn.asOf,
           subscribe: client.subscribe, unsubscribe: client.unsubscribe };
}
