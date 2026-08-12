// Shared fetch wrapper (extracted from App.jsx, gaining a method argument for the
// wizard's PATCH) + the §F8 simulation harness.
//
// ?sim=empty|loading|live|accepted|degraded|error serves canned responses instead of
// the network, so every review round can walk every §F8 state with no backend at
// all. The fixtures live in sim.js and are pinned to the GENERATED zod schemas by
// frontend/tests/sim-contract.test.ts — a sim state that drifts from the real API
// shape fails the build rather than silently reviewing a fiction.
import { SIM_FIXTURES } from "./sim.js";

function getCookie(name) {
  const m = document.cookie.match(new RegExp("(^| )" + name + "=([^;]+)"));
  return m ? m[2] : "";
}

export function simState() {
  return new URLSearchParams(window.location.search).get("sim");
}

export async function api(path, body, method) {
  const sim = simState();
  if (sim) {
    const fx = SIM_FIXTURES[sim];
    if (fx) return fx(path, body, method);
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
