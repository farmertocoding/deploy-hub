// The one multiplexed socket (§3.5/§D7): subscribe/unsubscribe by topic,
// snapshot-then-stream on connect AND reconnect, per-topic seq gap detection.
//
// Contract: subscribe(topic, handler, snapshotFn?)
//  - snapshotFn (optional) fetches `${topic}` snapshot -> {seq, data}; called before
//    the stream is trusted, and again after every reconnect. Events with
//    seq <= snapshot.seq are discarded (§D7: exactly one code path for load+resume).
import { useEffect, useRef, useState } from "react";

export function useEvents() {
  const wsRef = useRef(null);
  const subsRef = useRef(new Map()); // topic -> {handler, snapshotFn}
  const seqRef = useRef(new Map());  // topic -> last seen seq
  const [status, setStatus] = useState("connecting");

  async function syncTopic(topic) {
    const sub = subsRef.current.get(topic);
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
          seqRef.current.get(topic) ?? 0);
      }
      if (snap) {
        seqRef.current.set(topic, snap.seq ?? 0);
        sub.handler({ __snapshot: true, data: snap.data ?? [] }, snap.seq ?? 0);
      }
    }
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ action: "subscribe", topics: [topic] }));
    }
  }

  useEffect(() => {
    let closed = false;
    function connect() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws/events/`);
      wsRef.current = ws;
      ws.onopen = () => {
        setStatus("live");
        // Snapshot-then-stream for every subscribed topic — same path as initial load.
        for (const topic of subsRef.current.keys()) syncTopic(topic);
      };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (!msg.topic) return;
        const sub = subsRef.current.get(msg.topic);
        if (!sub) return;
        const last = seqRef.current.get(msg.topic) ?? 0;
        if (msg.seq <= last) return; // duplicate or pre-snapshot
        if (msg.seq > last + 1 && last !== 0) {
          // Gap detected: refetch snapshot rather than pretend continuity (§D7).
          syncTopic(msg.topic);
          return;
        }
        seqRef.current.set(msg.topic, msg.seq);
        sub.handler(msg.event, msg.seq);
      };
      ws.onclose = (e) => {
        // 4401/4403 are terminal (unauthenticated / enrollment required): retrying
        // can never succeed and would grind out a security AuditEvent every 1.5s
        // (round-3 finding). Surface auth-required instead.
        if (e.code === 4401 || e.code === 4403) {
          setStatus("auth-required");
          return;
        }
        setStatus("reconnecting");
        if (!closed) setTimeout(connect, 1500);
      };
    }
    connect();
    return () => {
      closed = true;
      wsRef.current?.close();
    };
  }, []);

  function subscribe(topic, handler, snapshotFn) {
    subsRef.current.set(topic, { handler, snapshotFn });
    seqRef.current.delete(topic);
    syncTopic(topic);
  }

  function unsubscribe(topic) {
    subsRef.current.delete(topic);
    seqRef.current.delete(topic);
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ action: "unsubscribe", topics: [topic] }));
    }
  }

  return { status, subscribe, unsubscribe };
}
