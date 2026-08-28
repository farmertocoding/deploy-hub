// Shared fetch wrapper (extracted from App.jsx, gaining a method argument for the
// wizard's PATCH) + the §F8 simulation harness.
//
// ?sim=empty|loading|loading-report|loading-wizard|live|stale|degraded|error serves
// canned responses instead of the network, so every review round can walk every §F8
// state with no backend at all. The fixtures live in sim.js and are pinned to the
// GENERATED zod schemas by frontend/tests/sim-contract.test.ts — a sim state that drifts
// from the real API shape fails the build rather than silently reviewing a fiction.
//
// The three `loading` states are one per spinner (round-9 item 10): the screen makes
// three fetches in a chain, so a state that hangs the first one leaves the other two
// spinners on screens the reviewer cannot get to.
import { SIM_FIXTURES } from "./sim.js";
import { hudSim } from "./hud-sim.js";

function getCookie(name) {
  const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return m ? m[2] : "";
}

export function simAllowed(env) {
  const resolved = env ?? (typeof import.meta !== "undefined" ? import.meta.env : undefined);
  return !(resolved && resolved.PROD);
}

export function simState(search, env) {
  if (!simAllowed(env)) return null;
  const raw = search ?? (typeof window !== "undefined" ? window.location.search : "");
  return new URLSearchParams(raw || "").get("sim");
}

export async function api(path, body, method) {
  const sim = simState();
  if (sim) {
    if (String(path).startsWith("v1/hud/")) {
      const hud = hudSim(sim, path, body, method);
      if (hud) return hud;
    }
    const fx = SIM_FIXTURES[sim];
    if (fx) return fx(path, body, method);
    return { status: 404, data: { detail: "unknown simulation" } };
  }
  // A down/unreachable server must surface, never reject unhandled (Phase-0 round-1
  // UX finding): status 0 routes into every existing error branch via data.detail.
  try {
    const res = await fetch(`/api/${path}`, {
      method: method || (body !== undefined ? "POST" : "GET"),
      headers: { "Content-Type": "application/json", "X-CSRFToken": getCookie("csrftoken") },
      credentials: "include",
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    return { status: res.status, data: await res.json().catch(() => ({})) };
  } catch {
    return { status: 0, data: { detail: "Cannot reach server — check your connection and retry." } };
  }
}
