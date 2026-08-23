// Task 8 — adopt plan + T2 start/cancel on Sites, and every new adopt state
// in sim.js. Flip / decommission are T2 because they write the operator's
// DnsZone and take down the old path; edge_owner is a Site column, not a
// per-run prompt; live_compose_path is an explicit argument or it is absent.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };
(globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

import { presentation, tierFor } from "../src/actions.js";
import { AdoptPlan, adoptDiff, startAdopt } from "../src/screens/Sites.jsx";
import { SIM_FIXTURES } from "../src/sim.js";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

const ADOPT_STATES = ["plan", "verify", "flipped", "abandoned", "unplanted"] as const;

async function adoptProjects(state: string) {
  const fx = (SIM_FIXTURES as any)[state];
  assert.ok(fx, `missing sim fixture ${state}`);
  const { status, data } = await fx("v1/projects/");
  assert.equal(status, 200, state);
  assert.ok(Array.isArray(data) && data.length > 0, `${state} must list a project`);
  return data;
}

function publicSites(projects: any[]) {
  return projects.flatMap((p: any) =>
    (p.sites || []).filter((s: any) => s.exposure !== "mesh_only"));
}

test("adopt_actions_are_t2_with_a_diff", async () => {
  // What would make this fail: start/cancel as T3 one-click (flip writes the
  // operator's zone; decommission stops the old path), or a confirm that does
  // not name that diff.
  for (const id of ["site.adopt.start", "site.adopt.cancel"]) {
    const row = tierFor(id);
    assert.equal(row.tier, "T2", id);
    assert.deepEqual(presentation(row), { confirm: true, undo: false, stepUp: "none" },
      `${id} is flip/decommission-adjacent and must confirm with a diff`);
  }

  const projects = await adoptProjects("plan");
  const site = publicSites(projects)[0];
  assert.ok(site, "plan fixture must carry a public site");
  const startDiff = adoptDiff(site, "site.adopt.start");
  const cancelDiff = adoptDiff(site, "site.adopt.cancel");
  assert.match(startDiff, /flip/i);
  assert.match(startDiff, /decommission/i);
  assert.match(cancelDiff, /abandon|temp/i);

  const markup = render(AdoptPlan, { site });
  const text = visibleText(markup);
  assert.match(text, /Start adopt|Cancel adopt/);
  assert.match(markup, /role="dialog"|Start adopt|Cancel adopt/);

  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const { act, create } = await import("react-test-renderer");
  const { ActionButton } = await import("../src/Tiers.jsx");
  let tree: any;
  act(() => {
    tree = create(React.createElement(ActionButton, {
      row: tierFor("site.adopt.start"),
      summary: startDiff,
      onRun: () => {},
    }));
  });
  act(() => { tree.root.findAllByType("button")[0].props.onClick(); });
  const dialog = tree.root.findAll(
    (n: any) => n.props && n.props.role === "dialog",
  );
  assert.equal(dialog.length, 1, "T2 start must open a confirm, not run");
  const dialogText = JSON.stringify(tree.toJSON());
  assert.match(dialogText, /flip/i);
  assert.match(dialogText, /decommission/i);
  act(() => { tree.unmount(); });
});

test("edge_owner_is_displayed_not_prompted_per_run", async () => {
  // What would make this fail: a <select> / "choose edge owner" prompt on
  // each start, or a file picker that walks /srv/sites/{slug} instead of an
  // explicit live_compose_path field.
  const projects = await adoptProjects("plan");
  const site = publicSites(projects)[0];
  assert.ok(site.edge_owner === "host_caddy" || site.edge_owner === "site_caddy",
    `edge_owner must be the closed pair, got ${site.edge_owner}`);

  const markup = render(AdoptPlan, { site, liveComposePath: "" });
  const text = visibleText(markup);
  assert.match(text, new RegExp(site.edge_owner));
  assert.doesNotMatch(markup, /<select\b/i);
  assert.doesNotMatch(text, /choose edge|pick edge|set edge owner|which caddy/i);
  assert.doesNotMatch(markup, /type="file"/i);
  assert.doesNotMatch(text, /\/srv\/sites\//);
  assert.match(markup, /name="live_compose_path"/);

  const src = readFileSync(new URL("../src/screens/Sites.jsx", import.meta.url), "utf8");
  assert.doesNotMatch(src, /\/srv\/sites\//);
  assert.match(src, /live_compose_path/);
});

test("sim_covers_plan_verify_flip_abandon", async () => {
  // What would make this fail: a new adopt stage with no ?sim= fixture, a
  // public site that omits cert_refusal, or an unbound public Site (illegal
  // under site_public_requires_dns_zone).
  const stages: Record<string, string> = {
    plan: "plan",
    verify: "verify",
    flipped: "flip",
    abandoned: "abandoned",
  };

  for (const state of ADOPT_STATES) {
    const projects = await adoptProjects(state);
    for (const site of projects.flatMap((p: any) => p.sites || [])) {
      assert.ok(Object.prototype.hasOwnProperty.call(site, "cert_refusal"),
        `${state}: ${site.name} omitted cert_refusal`);
      if (site.exposure === "public" || site.exposure == null) {
        assert.ok(site.dns_zone,
          `${state}: public ${site.name} is unbound — that row cannot exist`);
        assert.notEqual(site.dns_zone, null);
      }
    }
    const site = publicSites(projects)[0];
    const markup = render(AdoptPlan, { site });
    const text = visibleText(markup);
    assert.ok(text.length > 0, `${state} AdoptPlan rendered nothing`);
    assert.match(text, new RegExp(site.edge_owner));
    if (stages[state]) {
      assert.equal(site.adopt?.stage, stages[state], state);
    }
  }

  const unplanted = publicSites(await adoptProjects("unplanted"))[0];
  assert.equal(unplanted.origin_ca_planted, false);
  assert.ok(unplanted.dns_zone, "unplanted is not unbound");
  assert.ok(unplanted.cert_refusal === null || unplanted.cert_refusal.detail,
    "unplanted must emit cert_refusal (null when unused)");

  const simSrc = readFileSync(new URL("../src/sim.js", import.meta.url), "utf8");
  assert.doesNotMatch(simSrc, /site-dns-unbound/);
  assert.doesNotMatch(simSrc, /"dns_zone":\s*null/);

  const calls: Array<{ url: string; body: any }> = [];
  const prevFetch = (globalThis as any).fetch;
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: opts?.body ? JSON.parse(opts.body) : undefined });
    return { status: 202, json: async () => ({ slipped: true }) };
  };
  try {
    await startAdopt(11, { live_compose_path: "/explicit/compose.yml" });
    assert.equal(calls[0].url, "/api/v1/sites/11/adopt/");
    assert.deepEqual(calls[0].body, { live_compose_path: "/explicit/compose.yml" });
    assert.ok(!JSON.stringify(calls[0].body).includes("/srv/sites/"),
      "start must not invent /srv/sites/{slug}");
  } finally {
    (globalThis as any).fetch = prevFetch;
  }
});
