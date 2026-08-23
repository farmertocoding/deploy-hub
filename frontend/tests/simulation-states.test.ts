// UX-F8-SIMULATION-STATES: every state the v1 seed enumerates must have a
// rendering assertion against a real product component. A seed row with no
// renderer here is a fail — that is how the demo-pane waiver stays retired
// only for states that actually painted, not for a promise.
import { test } from "node:test";
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };

import { StatusPill } from "../src/Chrome.jsx";
import { FindingDetail, FindingsView } from "../src/screens/Findings.jsx";
import { DeployStatus } from "../src/screens/Deploys.jsx";
import { CertState, SiteObserved, SiteStatus } from "../src/screens/Sites.jsx";
import { MapPanel } from "../src/screens/Home.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

const ROOT = join(dirname(fileURLToPath(import.meta.url)), "../..");
const SEED_PATH = join(ROOT, "simulation/seed_v1.json");

// The brief's "every new state" list. The seed may add more; it may not omit
// these, and every id it does carry must have a renderer below.
const REQUIRED_STATE_IDS = [
  "finding-p1-open",
  "finding-p2-open",
  "finding-p3-open",
  "finding-p2-acked",
  "finding-p3-accepted",
  "finding-p1-resolved",
  "degraded-polling",
  "deploy-failure-blue-green",
  "deploy-failure-recreate",
  "warming",
  "data-stale",
  "single-instance",
  "cert-expiring",
  "unproxied-cert-refusal",
  "alert-storm",
  "host-down-suppression",
  "map-empty",
  "map-populated",
];

function loadSeed() {
  assert.ok(existsSync(SEED_PATH),
    "simulation/seed_v1.json must exist so UX-F8 states are reviewable");
  return JSON.parse(readFileSync(SEED_PATH, "utf8"));
}

function findingFrom(state: any) {
  return state.finding || state.event || state;
}

const RENDER: Record<string, (state: any) => string> = {
  "finding-p1-open": (s) => render(FindingsView, {
    phase: "live", findings: [findingFrom(s)], onNav: () => {},
  }),
  "finding-p2-open": (s) => render(FindingsView, {
    phase: "live", findings: [findingFrom(s)], onNav: () => {},
  }),
  "finding-p3-open": (s) => render(FindingsView, {
    phase: "live", findings: [findingFrom(s)], onNav: () => {},
  }),
  "finding-p2-acked": (s) => render(FindingsView, {
    phase: "live", findings: [findingFrom(s)], onNav: () => {},
  }),
  "finding-p3-accepted": (s) => render(FindingsView, {
    phase: "live", findings: [findingFrom(s)], onNav: () => {},
  }),
  "finding-p1-resolved": (s) => render(FindingsView, {
    phase: "live", findings: [findingFrom(s)], onNav: () => {},
  }),
  "degraded-polling": () => render(StatusPill, {
    status: "degraded", asOf: new Date(2026, 7, 22, 2, 3, 4),
  }),
  "deploy-failure-blue-green": (s) => render(DeployStatus, { deploy: s.deploy }),
  "deploy-failure-recreate": (s) => render(DeployStatus, { deploy: s.deploy }),
  warming: (s) => render(SiteObserved, { site: s.site }),
  "data-stale": (s) => render(SiteObserved, { site: s.site }),
  "single-instance": (s) => render(SiteObserved, { site: s.site }),
  "cert-expiring": (s) => render(FindingsView, {
    phase: "live", findings: [findingFrom(s)], onNav: () => {},
  }),
  "unproxied-cert-refusal": (s) =>
    render(CertState, { site: s.site }) + render(FindingDetail, {
      finding: findingFrom(s), onBack: () => {},
    }),
  "alert-storm": (s) => render(FindingsView, {
    phase: "live", findings: [findingFrom(s)], onNav: () => {},
  }),
  "host-down-suppression": (s) => render(FindingsView, {
    phase: "live", findings: [findingFrom(s)], onNav: () => {},
  }),
  "map-empty": (s) => render(MapPanel, { width: 1280, sites: s.sites || [] }),
  "map-populated": (s) => render(MapPanel, {
    width: 1280, sites: s.sites || [{ domain: "shop.example.com" }],
  }),
};

test("every_new_state_renders_in_simulation_mode", () => {
  // What would make this fail: a seed state with no renderer, a required id
  // missing from the seed, or a must_render token that never appears in markup.
  const seed = loadSeed();
  const states: any[] = seed.states;
  assert.ok(Array.isArray(states) && states.length > 0,
    "seed_v1 must enumerate states (not only scripted_events)");

  const ids = new Set(states.map((s) => s.id));
  const missingRequired = REQUIRED_STATE_IDS.filter((id) => !ids.has(id));
  assert.deepEqual(missingRequired, [],
    `seed is missing required states: ${missingRequired.join(", ")}`);

  const noRenderer = states.filter((s) => !RENDER[s.id]).map((s) => s.id);
  assert.deepEqual(noRenderer, [],
    `states with no rendering assertion: ${noRenderer.join(", ")}`);

  for (const state of states) {
    const markup = RENDER[state.id](state);
    const text = visibleText(markup);
    assert.ok(text.length > 0, `${state.id} rendered nothing`);
    for (const token of state.must_render || []) {
      assert.ok(text.includes(token),
        `${state.id} did not render ${JSON.stringify(token)}: ${text}`);
    }
  }

  // The two waiver lines: warming must show elapsed/expected, and site/deploy
  // topics must paint on product screens (not only the demo pane).
  const warming = states.find((s) => s.id === "warming");
  const warmingText = visibleText(RENDER.warming(warming));
  assert.match(warmingText, /elapsed|expected|\d+s/i, warmingText);

  const bg = visibleText(RENDER["deploy-failure-blue-green"](
    states.find((s) => s.id === "deploy-failure-blue-green")));
  assert.match(bg, /Old version still serving|site unaffected/i, bg);

  const rec = visibleText(RENDER["deploy-failure-recreate"](
    states.find((s) => s.id === "deploy-failure-recreate")));
  assert.match(rec, /down|unreachable/i, rec);
  assert.doesNotMatch(rec, /old version still serving/i);

  const site = states.find((s) => s.id === "unproxied-cert-refusal");
  assert.ok(visibleText(render(SiteStatus, { site: site.site })).length > 0);
});

test("every_seed_state_has_a_scripted_event", () => {
  // What would make this fail: states[] enumerating a topic the replayer
  // never publishes (P3 / acked / accepted / resolved / degraded-polling /
  // single-instance were the first holes).
  const seed = loadSeed();
  const covered = new Set(
    (seed.scripted_events || [])
      .map((e: any) => e.state_id)
      .filter(Boolean),
  );
  const missing = (seed.states || [])
    .map((s: any) => s.id)
    .filter((id: string) => !covered.has(id));
  assert.deepEqual(missing, [],
    `scripted_events omit states: ${missing.join(", ")}`);
});

test("sim_shell_mounts_login_enroll_t1_overlay", async () => {
  // C9: ?sim= mounts Shell; Login/Enroll are extracted so F8 can see them;
  // the T1 overlay is in the 390 px phone set.
  (globalThis as any).window.location = {
    search: "?sim=login", hash: "", protocol: "http:", host: "localhost",
    href: "http://localhost/?sim=login",
  };
  (globalThis as any).window.innerWidth = 390;
  (globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

  const { Login } = await import("../src/screens/Login.jsx");
  const { Enroll } = await import("../src/screens/Enroll.jsx");
  const { T1Overlay } = await import("../src/Tiers.jsx");
  const { PHONE_SCOPE } = await import("../src/Chrome.jsx");
  const { default: App, Shell } = await import("../src/App.jsx");

  const login = visibleText(render(Login, { onLogin: () => {} }));
  assert.match(login, /passkey|WebAuthn|security key/i, login);
  assert.match(login, /authenticator code instead/i, login);

  const enroll = visibleText(render(Enroll, { onDone: () => {} }));
  assert.match(enroll, /passkey|WebAuthn/i, enroll);
  assert.match(enroll, /phone/i, enroll);

  const overlay = visibleText(render(T1Overlay, {
    label: "Delete target", expected: "box-1",
    onTouch: () => {}, onConfirm: () => {}, onDismiss: () => {},
  }));
  assert.match(overlay, /Delete target/);
  assert.match(overlay, /touch|passkey|security key/i, overlay);
  assert.ok(PHONE_SCOPE.includes("t1-overlay"),
    "T1 overlay belongs in the 390 px phone set (C9)");

  assert.ok(Shell, "Shell must be exported so ?sim= can mount it");
  (globalThis as any).window.location.search = "?sim=live";
  const shell = render(App, {});
  assert.ok(visibleText(shell).length > 0, " ?sim= must not skip the operator chrome");
  assert.match(shell, /Home|Sites|Settings/,
    "?sim= mounts Shell, not a bare ReadinessScreen");
});
