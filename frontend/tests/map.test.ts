// MAP-96-GRAPH-V1 / D-041: list-view toggle, status as icon+label, empty hint.
// renderToStaticMarkup — no effects — so MapView takes the snapshot `data` as a
// prop. The fetch lives on MapPanel; these pin what the operator actually sees.
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };

import { MapView } from "../src/Map.jsx";

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
