// The shell's shared chrome (§F1/§F6/RT-35): the nav table, the hash router, the
// connection pill and the designed empty state. Exported constants over clever
// components, so tests/nav.test.ts pins the IA as data rather than by screenscraping.
import React, { useEffect, useState } from "react";
import { POLL_MS } from "./useEvents.js";
import { box, danger, warning, muted } from "./ui/surface.js";

// §F1 object-centric nav — these six, exactly, in this order. Advisors are TABS on
// their objects (Settings carries Developer/Vault; readiness lives inside Home's
// fleet), never entries here: adding one to this list is the reviewable act
// UX-F1-IA-NAV forbids.
export const NAV = [
  { id: "home", label: "Home" },
  { id: "sites", label: "Sites" },
  { id: "targets", label: "Targets" },
  { id: "deploys", label: "Deploys" },
  { id: "findings", label: "Findings" },
  { id: "settings", label: "Settings" },
];

// §F6: exactly three screens are designed for phone width (390 px). The map is
// explicitly desktop-only and no alert deep link routes through it — an alert links
// to the finding detail (#/findings/<id>), which IS in this list.
export const PHONE_SCOPE = ["finding-detail", "site-status", "deploy-status", "t1-overlay"];
export const DESKTOP_MIN_PX = 768;

// Hash routes, no router library: "#/sites/3" → {screen:"sites", id:"3"}. An unknown
// or empty hash is Home — a deep link must never strand the operator on a blank shell.
export function parseRoute(hash) {
  const raw = (hash || "").replace(/^#\/?/, "");
  const qIndex = raw.indexOf("?");
  const path = qIndex >= 0 ? raw.slice(0, qIndex) : raw;
  const query = Object.fromEntries(new URLSearchParams(qIndex >= 0 ? raw.slice(qIndex + 1) : ""));
  const extra = Object.keys(query).length ? { query } : {};
  const [screenPart, ...rest] = path.split("/");
  const screen = screenPart || "";
  if (screen === "admin") {
    return { screen: "admin", id: rest.filter(Boolean).join("/") || undefined, ...extra };
  }
  if (!NAV.some((n) => n.id === screen)) return { screen: "home", id: undefined, ...extra };
  return { screen, id: rest[0] || undefined, ...extra };
}

export function routeHash(screen, id) {
  if (screen === "admin") return id ? `#/admin/${id}` : "#/admin";
  return id === undefined ? `#/${screen}` : `#/${screen}/${id}`;
}

export function useRoute() {
  const [route, setRoute] = useState(() => parseRoute(window.location.hash));
  useEffect(() => {
    const onHash = () => setRoute(parseRoute(window.location.hash));
    window.addEventListener("hashchange", onHash);
    return () => window.removeEventListener("hashchange", onHash);
  }, []);
  const nav = (screen, id) => { window.location.hash = routeHash(screen, id); };
  return [route, nav];
}

export function useWidth() {
  const [width, setWidth] = useState(() => window.innerWidth);
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);
  return width;
}

// RT-35's visibility half: the pill NAMES the mode, and degraded carries the
// "data as of HH:MM:SS" stamp — the time of the last CONFIRMED snapshot, which is
// what "never silently stale" means on a screen. Live renders nothing: a pill that is
// always present is a pill nobody reads. Symbol + words, never color-only (§F9).
export function StatusPill({ status, asOf }) {
  if (status === "live") return null;
  const stamp = asOf
    ? ` · data as of ${new Date(asOf).toLocaleTimeString([], { hour12: false })}`
    : "";
  const text =
    status === "degraded"
      ? `⚠ degraded — polling every ${POLL_MS / 1000} s${stamp}`
      : status === "reconnecting" ? "↻ reconnecting…"
      : status === "auth-required" ? "⛔ session expired — reload and log in again"
      : "… connecting";
  const color = status === "auth-required" ? danger
    : status === "degraded" ? warning : muted;
  return (
    <span role="status" style={{ ...box, color, borderColor: color,
      borderRadius: 12, padding: "4px 10px" }}>{text}</span>
  );
}

// The designed empty state (§F1 brief): one sentence and THE single button that
// populates the screen — not a paragraph of options, not zero affordances.
export function EmptyState({ sentence, button, onAction }) {
  return (
    <div style={{ margin: "10vh auto", width: "fit-content", textAlign: "center" }}>
      <p>{sentence}</p>
      <button style={box} onClick={onAction}>{button}</button>
    </div>
  );
}

// The four fetch phases every screen renders (loading / live / error / degraded is
// the pill's job; this is loading/error). Shared so the wording cannot drift
// per-screen.
export function LoadingLine({ what }) {
  return <p style={{ padding: 16 }}>Loading {what}…</p>;
}

export function ErrorLine({ text, onRetry }) {
  return (
    <div style={{ padding: 16 }}>
      <p style={{ color: danger }}>{text}</p>
      <button style={box} onClick={onRetry}>Retry</button>
    </div>
  );
}
