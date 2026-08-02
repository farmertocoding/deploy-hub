// The one multiplexed socket (§3.5/§D7): subscribe/unsubscribe by topic,
// snapshot-then-stream on reconnect, per-topic seq gap detection.
import { useEffect, useRef, useState } from "react";

export function useEvents() {
  const wsRef = useRef(null);
  const topicsRef = useRef(new Set());
  const handlersRef = useRef(new Map()); // topic -> fn(event, seq)
  const seqRef = useRef(new Map());
  const [status, setStatus] = useState("connecting");

  useEffect(() => {
    let closed = false;
    function connect() {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      const ws = new WebSocket(`${proto}://${location.host}/ws/events/`);
      wsRef.current = ws;
      ws.onopen = () => {
        setStatus("live");
        if (topicsRef.current.size) {
          ws.send(JSON.stringify({ action: "subscribe", topics: [...topicsRef.current] }));
        }
      };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data);
        if (!msg.topic) return;
        const last = seqRef.current.get(msg.topic) ?? 0;
        if (msg.seq <= last) return; // duplicate
        if (msg.seq > last + 1 && last !== 0) {
          // Gap: caller should refetch snapshot; v0 surfaces it via handler flag.
          handlersRef.current.get(msg.topic)?.({ __gap: true }, msg.seq);
        }
        seqRef.current.set(msg.topic, msg.seq);
        handlersRef.current.get(msg.topic)?.(msg.event, msg.seq);
      };
      ws.onclose = () => {
        setStatus("reconnecting");
        if (!closed) setTimeout(connect, 1500); // then snapshot-then-stream
      };
    }
    connect();
    return () => {
      closed = true;
      wsRef.current?.close();
    };
  }, []);

  function subscribe(topic, handler) {
    topicsRef.current.add(topic);
    handlersRef.current.set(topic, handler);
    if (wsRef.current?.readyState === 1) {
      wsRef.current.send(JSON.stringify({ action: "subscribe", topics: [topic] }));
    }
  }

  return { status, subscribe };
}
