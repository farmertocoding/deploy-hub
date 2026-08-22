// UX-F1-IA-NAV, client half: object-centric nav — Home (map + fleet), Sites,
// Targets, Deploys, Findings, Settings — advisors are TABS on their objects, never
// top-level pages, and the demo pane is a Settings/Developer tab, not the product
// surface. Plus the §F6 phone scope: exactly three screens render usably at 390 px
// and the map is explicitly not one of them. (The pytest marker for the req id lands
// with the Python half in Tasks 4/13; these pin the markup and the IA data.)
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };

import { NAV, PHONE_SCOPE, parseRoute, routeHash } from "../src/Chrome.jsx";
import { NavBar } from "../src/App.jsx";
import { SETTINGS_TABS } from "../src/screens/Settings.jsx";
import { MapPanel } from "../src/screens/Home.jsx";
import { CertState, SiteStatus, SitesView, flattenSites } from "../src/screens/Sites.jsx";
import { TargetsView } from "../src/screens/Targets.jsx";
import { DeployStatus, DeploysView } from "../src/screens/Deploys.jsx";
import { FindingDetail, FindingsView } from "../src/screens/Findings.jsx";
import { SIM_FIXTURES } from "../src/sim.js";

const render = (component: any, props: any) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

// Sites come from the §F8 fixtures — real ProjectListView output, the same payload
// the screen fetches. Deploys and findings have no serializer this side of Tasks
// 4/13, so their fixtures are typed HERE as the interface contract those tasks fill;
// they are the only typed payloads in this file, on purpose.
const liveSites = async () => {
  const { data } = await (SIM_FIXTURES.live as any)("v1/projects/");
  return flattenSites(data);
};
const DEPLOY = { id: 1, site: "takko/prod", version: 4, state: "running",
  headline: "Old version still serving.",
  steps: [{ name: "build", state: "done" }, { name: "migrate", state: "running" }] };
const FINDING = { id: 7, title: "Unproxied site cannot be issued a certificate",
  severity: "blocker", site: "takko/prod",
  detail: "takko/prod is public and unproxied; Hub-central DNS-01 is not built.\nThe pipeline refused rather than improvise.",
  fix_hint: "Proxy the site through Cloudflare, or wait for Phase 4's DNS-01." };

test("advisors_are_tabs_not_top_level_pages", () => {
  // The IA as data: exactly these six objects, in this order. No advisor, no demo
  // pane, no readiness entry — those are tabs/regions ON their objects.
  assert.deepEqual(NAV.map((n) => n.id),
    ["home", "sites", "targets", "deploys", "findings", "settings"]);

  const markup = render(NavBar, { route: { screen: "home" }, onNav: () => {},
    status: "live", asOf: null, username: "j" });
  const text = visibleText(markup);
  for (const n of NAV) assert.ok(text.includes(n.label), n.label);
  assert.ok(!/demo/i.test(text), "the demo pane is a Settings tab, not nav");
  assert.ok(!/advisor/i.test(text));
  assert.match(markup, /aria-current="page"/, "the current screen is not announced");

  // …and the demo pane's actual home is the Settings tab bar.
  assert.deepEqual(SETTINGS_TABS.map((t) => t.id), ["cloudflare", "developer", "vault"]);
});

test("every_list_screen_has_an_empty_state", () => {
  // The designed empty state (§F1): one sentence + THE single button that populates
  // the screen. Exactly one button — zero is a dead end, two is a menu.
  const screens: Array<[string, string]> = [
    ["Sites", render(SitesView, { phase: "live", sites: [], onNav: () => {},
      onSelect: () => {} })],
    ["Targets", render(TargetsView, { phase: "live", targets: [], onCopy: () => {} })],
    ["Deploys", render(DeploysView, { phase: "live", deploys: [], onNav: () => {} })],
    ["Findings", render(FindingsView, { phase: "live", findings: [], onNav: () => {} })],
  ];
  for (const [name, markup] of screens) {
    assert.equal((markup.match(/<button/g) || []).length, 1,
      `${name}: the empty state has more (or fewer) affordances than THE one button`);
    const sentence = visibleText(markup);
    assert.ok(sentence.includes("No "), `${name}: ${sentence}`);
    assert.ok(sentence.includes("—"),
      `${name}: the sentence must say what populates the screen: ${sentence}`);
  }

  // …and the same views render their loading and error states, so a screen is never
  // blank while it fetches or fails.
  for (const View of [SitesView, TargetsView, DeploysView, FindingsView]) {
    assert.ok(visibleText(render(View, { phase: "loading" })).includes("Loading"));
    assert.ok(visibleText(render(View,
      { phase: "error", onError: { text: "HTTP 500", retry: () => {} } }))
      .includes("HTTP 500"));
  }
});

test("three_named_screens_render_at_phone_width", async () => {
  // §F6: finding detail, site status (with its T3 actions), deploy status. "Usable
  // at 390 px" for an inline-styled tree means: nothing in the markup claims a fixed
  // or minimum width wider than the phone, and the container yields (max-width 100%).
  assert.deepEqual(PHONE_SCOPE, ["finding-detail", "site-status", "deploy-status"]);

  const sites = await liveSites();
  const phoneScreens: Array<[string, string]> = [
    ["finding-detail", render(FindingDetail, { finding: FINDING, onBack: () => {} })],
    ["site-status", render(SiteStatus, { site: sites[0],
      actions: ["site.rollback", "site.restart", "check.rerun"], onRun: () => {} })],
    ["deploy-status", render(DeployStatus, { deploy: DEPLOY })],
  ];
  for (const [name, markup] of phoneScreens) {
    assert.ok(visibleText(markup).length > 0, name);
    for (const m of markup.matchAll(/(?:min-)?width:(\d+)px/g)) {
      assert.ok(Number(m[1]) <= 390,
        `${name} claims a ${m[0]} — wider than the phone it is scoped to`);
    }
    assert.match(markup, /max-width:100%/, `${name} does not yield to a narrow viewport`);
  }

  // The site status carries its T3 actions (that is the §F6 wording), and they are
  // the one-click kind — no dialog markup in the resting state.
  const [, siteMarkup] = phoneScreens[1];
  for (const label of ["Roll back", "Restart", "Re-run check"])
    assert.ok(visibleText(siteMarkup).includes(label), label);
  assert.ok(!/role="dialog"/.test(siteMarkup));
});

test("map_is_not_in_the_phone_scope", () => {
  // The map is explicitly desktop-only (§F6): at phone width it renders a pointer to
  // Sites, not a squashed map — and it is not in the phone scope list.
  assert.ok(!PHONE_SCOPE.some((s) => /map/.test(s)));

  const phone = visibleText(render(MapPanel, { width: 390 }));
  assert.ok(phone.includes("desktop-only"), phone);
  assert.ok(!phone.includes("Fleet map"), "the map rendered at phone width anyway");
  assert.ok(visibleText(render(MapPanel, { width: 1280 })).includes("Fleet map"));

  // No alert deep link routes through the map: the cert-refusal state links straight
  // to the finding detail — a phone-scope screen — by hash route.
  const site = { name: "prod", cert_refusal: { detail: "unproxied public site",
    finding_id: 7 } };
  const link = render(CertState, { site });
  assert.ok(link.includes(`href="${routeHash("findings", 7)}"`), link);
  assert.deepEqual(parseRoute("#/findings/7"), { screen: "findings", id: "7" });
  // …and an unknown hash lands Home, never a blank shell.
  assert.deepEqual(parseRoute("#/map/3"), { screen: "home", id: undefined });
});
