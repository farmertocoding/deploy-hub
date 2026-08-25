// MAP-96-GRAPH-V1 / D-041: list-view toggle, status as icon+label, empty hint.
// renderToStaticMarkup — no effects — so MapView takes the snapshot `data` as a
// prop. The fetch lives on MapPanel; these pin what the operator actually sees.
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };

import { readFileSync } from "node:fs";
import { attachMapGraph, mapGraphSnapshot, MapView } from "../src/Map.jsx";
import Home from "../src/screens/Home.jsx";

const render = (component: any, props: any) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

const GRAPH = {
  nodes: [
    { id: "hub", kind: "hub", label: "Hub", status: "ok" },
    { id: "edge", kind: "edge", label: "Cloudflare", status: "ok" },
    { id: "zone:1", kind: "zone", label: "prod-vlan", status: "ok" },
    { id: "host:1", kind: "host", label: "web-1", status: "ready", parent: "zone:1" },
    { id: "container:1", kind: "container", label: "shop", status: "unhealthy",
      parent: "host:1" },
  ],
  edges: [
    { a: "edge", b: "host:1", path: "public" },
  ],
};

test("list_view_toggle_shows_the_same_nodes", () => {
  const svg = visibleText(render(MapView, { graph: GRAPH, listView: false }));
  const list = visibleText(render(MapView, { graph: GRAPH, listView: true }));
  for (const label of ["Hub", "Cloudflare", "prod-vlan", "web-1", "shop"]) {
    assert.ok(svg.includes(label), `svg missing ${label}: ${svg}`);
    assert.ok(list.includes(label), `list missing ${label}: ${list}`);
  }
  const svgMarkup = render(MapView, { graph: GRAPH, listView: false });
  assert.ok(svgMarkup.includes("<svg"), "map view must be plain SVG, not a canvas lib");
  const listMarkup = render(MapView, { graph: GRAPH, listView: true });
  assert.ok(!listMarkup.includes("<svg"), "list view must not draw the SVG");
  assert.match(svgMarkup, /data-path="public"/);
});

test("status_is_icon_plus_label_not_colour", () => {
  const markup = render(MapView, { graph: GRAPH, listView: true });
  const text = visibleText(markup);
  assert.ok(text.includes("ready"), text);
  assert.ok(text.includes("unhealthy"), text);
  // Icon characters travel with the words — a coloured rect alone fails this.
  assert.ok(/✓|✔|▶|⚠|⛔/.test(text), `no status icon in: ${text}`);
  assert.match(markup, /data-status="ready"/);
  assert.match(markup, /data-status="unhealthy"/);
});

test("optional_finding_chips_link_hash_findings", () => {
  // Topology advisor chips are optional on the existing SVG (D-041): they
  // must deep-link the hash inbox, never a path router the SPA does not mount.
  const graph = {
    nodes: [
      {
        id: "hub", kind: "hub", label: "Hub", status: "ok",
        findings: [{ id: 42, severity: "p1" }],
      },
      { id: "edge", kind: "edge", label: "Cloudflare", status: "ok" },
      { id: "zone:1", kind: "zone", label: "prod-vlan", status: "ok" },
      { id: "host:1", kind: "host", label: "web-1", status: "ready", parent: "zone:1" },
    ],
    edges: [],
  };
  const svg = render(MapView, { graph, listView: false });
  assert.match(svg, /#\/findings\/42/);
  assert.match(svg, /data-finding-id="42"/);
  assert.match(svg, /P1/);
  const list = render(MapView, { graph, listView: true });
  assert.ok(!list.includes("#/findings/42"), "chips are SVG-only");
});

const GHOST_GRAPH = {
  nodes: [
    { id: "hub", kind: "hub", label: "Hub", status: "ok" },
    { id: "edge", kind: "edge", label: "Cloudflare", status: "ok" },
    { id: "zone:1", kind: "zone", label: "prod-vlan", status: "ok" },
    { id: "host:1", kind: "host", label: "web-1", status: "ready", parent: "zone:1" },
    { id: "ghost:printer.lan", kind: "ghost", label: "printer.lan", status: "ghost",
      parent: "zone:1" },
    { id: "ghost:orphan.lan", kind: "ghost", label: "orphan.lan", status: "ghost" },
  ],
  edges: [],
};

test("ghost_nodes_render_in_list_and_svg_with_icon_label", () => {
  const svgMarkup = render(MapView, { graph: GHOST_GRAPH, listView: false });
  const listMarkup = render(MapView, { graph: GHOST_GRAPH, listView: true });
  const svg = visibleText(svgMarkup);
  const list = visibleText(listMarkup);
  assert.ok(svg.includes("printer.lan"), `svg missing printer.lan: ${svg}`);
  assert.ok(list.includes("printer.lan"), `list missing printer.lan: ${list}`);
  assert.ok(svg.includes("orphan.lan"), `svg missing parentless ghost: ${svg}`);
  assert.ok(/◌/.test(svg) || /ghost/.test(svg), `svg status not icon+label: ${svg}`);
  assert.ok(/◌/.test(list) || /ghost/.test(list), `list status not icon+label: ${list}`);
  assert.ok(svg.includes("◌") && svg.includes("ghost"), `svg must show ◌ ghost: ${svg}`);
  assert.ok(list.includes("◌") && list.includes("ghost"), `list must show ◌ ghost: ${list}`);
  assert.match(svgMarkup, /data-kind="ghost"/);
  assert.match(svgMarkup, /data-status="ghost"/);
  assert.match(listMarkup, /data-status="ghost"/);
  const chromeSrc = readFileSync(new URL("../src/Chrome.jsx", import.meta.url), "utf8");
  assert.equal(
    [...chromeSrc.matchAll(/id: "(home|sites|targets|deploys|findings|settings)"/g)].length,
    6,
  );
});

test("empty_fleet_shows_the_onboarding_hint", () => {
  const empty = {
    nodes: [
      { id: "hub", kind: "hub", label: "Hub", status: "ok" },
      { id: "edge", kind: "edge", label: "Cloudflare", status: "ok" },
    ],
    edges: [],
  };
  const text = visibleText(render(MapView, { graph: empty, listView: false }));
  assert.ok(/provision|target|enroll/i.test(text), text);
  assert.ok(text.includes("—"), `hint must say what populates the map: ${text}`);
  assert.ok(!text.includes("prod-vlan"));
});

const flush = () => new Promise<void>((r) => setImmediate(r));

function fakeEvents() {
  const calls: Array<any> = [];
  return {
    calls,
    subscribe(topic: string, handler: Function, snapshotFn: Function) {
      calls.push({ topic, handler, snapshotFn });
    },
    unsubscribe(topic: string) {
      calls.push({ unsubscribe: topic });
    },
  };
}

test("home_fleet_map_subscribes_to_map_graph", async () => {
  // renderToStaticMarkup runs no effects — the bind is attachMapGraph, which
  // FleetMap calls with the shell client Home threads through. Fake events;
  // do not rely on a mount-only GET.
  const events = fakeEvents();
  let applied: any = null;
  const detach = attachMapGraph(events, (data: any) => { applied = data; });
  assert.equal(events.calls[0].topic, "map.graph");
  assert.equal(events.calls[0].snapshotFn, mapGraphSnapshot);

  events.calls[0].handler({ __snapshot: true, data: GRAPH });
  assert.deepEqual(applied, GRAPH);

  const updated = {
    ...GRAPH,
    nodes: [...GRAPH.nodes,
      { id: "host:2", kind: "host", label: "web-2", status: "ready", parent: "zone:1" }],
  };
  const prevFetch = (globalThis as any).fetch;
  const prevDoc = (globalThis as any).document;
  const urls: string[] = [];
  (globalThis as any).document = { cookie: "" };
  (globalThis as any).fetch = async (url: string) => {
    urls.push(String(url));
    return { status: 200, json: async () => ({ seq: 8, data: updated }) };
  };
  try {
    events.calls[0].handler({ kind: "changed" });
    await flush();
    assert.ok(urls.some((u) => /\/api\/v1\/map\/$/.test(u)), `refetch urls: ${urls}`);
    assert.deepEqual(applied, updated);
    const snap = await mapGraphSnapshot();
    assert.equal(snap.seq, 8);
    assert.deepEqual(snap.data, updated);
  } finally {
    (globalThis as any).fetch = prevFetch;
    (globalThis as any).document = prevDoc;
  }

  detach();
  assert.deepEqual(events.calls[1], { unsubscribe: "map.graph" });

  // Home threads the shell client into FleetMap (effects do not run here).
  render(Home, { width: 1280, events: fakeEvents() });
  render(Home, { width: 390, events: fakeEvents() });
  const homeSrc = readFileSync(new URL("../src/screens/Home.jsx", import.meta.url), "utf8");
  assert.match(homeSrc, /<MapPanel width=\{width\} events=\{events\} \/>/);
  assert.match(homeSrc, /<FleetMap graph=\{graph\} events=\{events\} \/>/);
  const appSrc = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(appSrc, /<Home width=\{width\} events=\{events\} onNav=\{onNav\} \/>/);
});
