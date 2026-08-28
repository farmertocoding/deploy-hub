import React from "react";

export const STATUS_MAP = {
  live: { symbol: "●", word: "LIVE" },
  connecting: { symbol: "…", word: "connecting" },
  reconnecting: { symbol: "↻", word: "reconnecting" },
  degraded: { symbol: "⚠", word: "degraded" },
  "auth-required": { symbol: "⛔", word: "session expired" },
  pending: { symbol: "○", word: "pending" },
  queued: { symbol: "○", word: "queued" },
  running: { symbol: "▶", word: "running" },
  succeeded: { symbol: "✓", word: "succeeded" },
  failed: { symbol: "⛔", word: "failed" },
  cancelled: { symbol: "×", word: "cancelled" },
  rolled_back: { symbol: "↩", word: "rolled back" },
  healthy: { symbol: "✓", word: "healthy" },
  drift: { symbol: "⚠", word: "drift" },
  down: { symbol: "⛔", word: "down" },
  ready: { symbol: "✓", word: "ready" },
  error: { symbol: "⛔", word: "error" },
  p1: { symbol: "⛔", word: "P1" },
  p2: { symbol: "⚠", word: "P2" },
  p3: { symbol: "ℹ", word: "P3" },
  active: { symbol: "●", word: "active" },
  retired: { symbol: "×", word: "retired" },
  rotating: { symbol: "↻", word: "rotating" },
  warming: { symbol: "◎", word: "warming" },
  unhealthy: { symbol: "⛔", word: "unhealthy" },
  stale: { symbol: "⚠", word: "stale" },
  pressured: { symbol: "⚠", word: "pressured" },
  unreachable: { symbol: "⛔", word: "unreachable" },
  decommissioned: { symbol: "×", word: "decommissioned" },
  scanned: { symbol: "✓", word: "scanned" },
  held: { symbol: "●", word: "held" },
  open: { symbol: "●", word: "open" },
  connected: { symbol: "✓", word: "connected" },
  missing: { symbol: "⚠", word: "missing" },
};

export function statusParts(state) {
  const key = String(state || "").toLowerCase();
  return STATUS_MAP[key] || { symbol: "•", word: String(state || "unknown") };
}

export function Status({ state, asOf, className = "" }) {
  const { symbol, word } = statusParts(state);
  const stamp = asOf
    ? ` · data as of ${new Date(asOf).toLocaleTimeString([], { hour12: false })}`
    : "";
  return (
    <span className={`hud-status ${className}`.trim()} role="status">
      <span aria-hidden="true">{symbol}</span>
      <span>{word}{stamp}</span>
    </span>
  );
}
