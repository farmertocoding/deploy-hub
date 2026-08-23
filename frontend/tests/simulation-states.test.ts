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
(globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

import { NAV, StatusPill } from "../src/Chrome.jsx";
import { FindingDetail, FindingsView } from "../src/screens/Findings.jsx";
import { DeployStatus } from "../src/screens/Deploys.jsx";
import { CertState, SiteObserved, SiteStatus } from "../src/screens/Sites.jsx";
import { MapPanel } from "../src/screens/Home.jsx";
import { TargetsView } from "../src/screens/Targets.jsx";
import { AwsPanel, PartnersPanel } from "../src/screens/Settings.jsx";
import { ConfirmDialog, T1Overlay } from "../src/Tiers.jsx";
import { SitesView } from "../src/screens/Sites.jsx";

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
  "enroll-empty",
  "enroll-error",
  "enroll-degraded",
  "partner-intake-empty",
  "partner-intake-error",
  "partner-intake-degraded",
  "partner-site",
  "partner-kill-switch-overlay",
  "partner-destination-order-confirm",
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
  "enroll-empty": () =>
    render(TargetsView, {
      phase: "live", targets: [], awsCredentialsRef: "hub-aws",
      cost: "$0.05/h", onCopy: () => {}, onCreate: () => {},
    }) + render(T1Overlay, {
      label: "Create target", cost: "$0.05/h",
      onTouch: () => {}, onConfirm: () => {}, onDismiss: () => {},
    }),
  "enroll-error": () => render(TargetsView, {
    phase: "error",
    onError: { text: "Target create failed", retry: () => {} },
  }),
  "enroll-degraded": () => render(AwsPanel),
  "partner-intake-empty": (s) =>
    render(PartnersPanel, {
      partners: [],
      intake: s.intake || { status: "degraded", mode: "fake", configured: false },
    }) + render(T1Overlay, {
      label: "Create partner",
      onTouch: () => {}, onConfirm: () => {}, onDismiss: () => {},
    }),
  "partner-intake-error": (s) =>
    render(PartnersPanel, {
      partners: [],
      intake: s.intake || {
        status: "error", mode: "fake", configured: false,
        as_of: "2026-08-24T02:03:04Z",
      },
    }) + render(FindingDetail, {
      finding: findingFrom(s), onBack: () => {},
    }),
  "partner-intake-degraded": (s) =>
    render(PartnersPanel, {
      partners: s.partners || [{
        id: 1, slug: "fixture-partner", destination_order: [],
      }],
      intake: s.intake || { status: "degraded", mode: "fake", configured: false },
    }),
  "partner-site": (s) => render(SitesView, {
    phase: "live", sites: [s.site], onSelect: () => {}, onNav: () => {},
  }),
  "partner-kill-switch-overlay": (s) =>
    render(T1Overlay, {
      label: "Suspend partner",
      summary: s.summary
        || "Stop containers, detach routes, revoke the Hub-side key.",
      onTouch: () => {}, onConfirm: () => {}, onDismiss: () => {},
    }) + render(PartnersPanel, {
      partners: s.partners || [{
        id: 1, slug: "fixture-partner", destination_order: [],
      }],
      intake: { status: "degraded", mode: "fake", configured: false },
      apiEnabled: false,
    }),
  "partner-destination-order-confirm": (s) =>
    render(ConfirmDialog, {
      label: "Rank partner destination",
      summary: s.summary
        || "abuse takedowns and IP-reputation damage land on hardware and residential/office connections you cannot dispose of",
      onConfirm: () => {}, onDismiss: () => {},
    }) + render(PartnersPanel, {
      partners: s.partners || [{
        id: 1, slug: "fixture-partner", destination_order: [1],
        destinations: [{ id: 1, host: "home.fixture.test", kind: "ssh" }],
      }],
      intake: { status: "degraded", mode: "fake", configured: false },
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

  const enrollEmpty = visibleText(RENDER["enroll-empty"](
    states.find((s) => s.id === "enroll-empty") || {}));
  assert.match(enrollEmpty, /Create target/);
  assert.match(enrollEmpty, /\$0\.05\/h/);
  assert.match(enrollEmpty, /five cents per hour/i);
  assert.doesNotMatch(enrollEmpty, /\binstance\b/i);

  const enrollDegraded = visibleText(RENDER["enroll-degraded"](
    states.find((s) => s.id === "enroll-degraded") || {}));
  assert.match(enrollDegraded, /not connected/i);
  assert.ok(!/\bConnected\b/.test(enrollDegraded), enrollDegraded);
  assert.match(enrollDegraded, /HUB_AWS_CREDENTIALS_REF/);

  assert.equal(NAV.length, 6, "NAV stays six — no 7th AWS/Instances item");

  const partnerEmpty = visibleText(RENDER["partner-intake-empty"](
    states.find((s) => s.id === "partner-intake-empty") || {}));
  assert.match(partnerEmpty, /Create partner/);
  assert.match(partnerEmpty, /Fake/);
  assert.doesNotMatch(partnerEmpty, /\bConnected\b/);
  assert.doesNotMatch(partnerEmpty, /\$0\.05/);
  assert.doesNotMatch(partnerEmpty, /\binstance\b/i);

  const partnerDegraded = visibleText(RENDER["partner-intake-degraded"](
    states.find((s) => s.id === "partner-intake-degraded") || {}));
  assert.doesNotMatch(partnerDegraded, /\bConnected\b/);
  assert.doesNotMatch(partnerDegraded, /hubk_/);
  assert.doesNotMatch(partnerDegraded, /whsec_/);

  const partnerSite = visibleText(RENDER["partner-site"](
    states.find((s) => s.id === "partner-site") || {}));
  assert.match(partnerSite, /◆ partner/);
  assert.match(partnerSite, /All/);

  const killOverlay = visibleText(RENDER["partner-kill-switch-overlay"](
    states.find((s) => s.id === "partner-kill-switch-overlay") || {}));
  assert.match(killOverlay, /Stop containers/i);
  assert.match(killOverlay, /detach routes/i);
  assert.match(killOverlay, /revoke/i);
  assert.doesNotMatch(killOverlay, /\bConnected\b/);
  assert.doesNotMatch(killOverlay, /\$0\.05/);
  assert.doesNotMatch(killOverlay, /\binstance\b/i);

  const rankConfirm = visibleText(RENDER["partner-destination-order-confirm"](
    states.find((s) => s.id === "partner-destination-order-confirm") || {}));
  assert.match(rankConfirm, /abuse takedowns/);
  assert.match(rankConfirm, /IP-reputation/);
  assert.doesNotMatch(rankConfirm, /\bConnected\b/);
  assert.doesNotMatch(rankConfirm, /\binstance\b/i);
});

test("live_create_failure_and_cost_only_from_get_200", async () => {
  const {
    TargetsView, runCreateTarget, TARGET_CREATE_FAILED, costFromCreateGet,
  } = await import("../src/screens/Targets.jsx");

  const failed409 = await runCreateTarget(
    async () => ({ status: 409, data: { detail: "unconfigured hourly cost estimate" } }),
    "100.64.0.10",
  );
  assert.equal(failed409.ok, false);
  assert.equal(failed409.text, "Target create failed");
  assert.equal(failed409.status, 409);
  assert.ok(failed409.data);

  const failed400 = await runCreateTarget(
    async () => ({ status: 400, data: { detail: "create_instance failed" } }),
    "100.64.0.10",
  );
  assert.equal(failed400.ok, false);
  assert.equal(failed400.text, TARGET_CREATE_FAILED);

  const errorText = visibleText(render(TargetsView, {
    phase: "error",
    onError: { text: failed409.text, retry: () => {} },
  }));
  assert.equal(errorText.includes("Target create failed"), true, errorText);
  assert.match(errorText, /Retry/);

  const ok = await runCreateTarget(
    async () => ({ status: 201, data: { host: "100.64.0.10", id: 1, kind: "aws_ec2" } }),
    "100.64.0.10",
  );
  assert.equal(ok.ok, true);
  assert.equal(ok.host, "100.64.0.10");
  assert.doesNotMatch(String(ok.host), /instance/i);

  const noCost = visibleText(render(TargetsView, {
    phase: "live", targets: [], awsCredentialsRef: "hub-aws",
    onCopy: () => {}, onCreate: () => {}, onRetryCost: () => {},
  }));
  assert.doesNotMatch(noCost, /\$0\.05\/h/);
  assert.doesNotMatch(noCost, /Create target/);
  assert.doesNotMatch(noCost, /\$0(?:\.00)?(?:\/h)?/);
  assert.match(noCost, /Retry cost/);

  assert.equal(costFromCreateGet(409, {}), null);
  assert.equal(costFromCreateGet(200, { cost_display: "$0.05/h" }), "$0.05/h");
  assert.equal(costFromCreateGet(200, {}), null);
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
