// ROUTER-ADVICE-TARGET-TAB — Target detail Hardening | Router tabs and T3 Probe router.
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };
(globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

import {
  TargetDetail, TargetsView, probeAndRefresh, probeRouter,
} from "../src/screens/Targets.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

const TARGET = {
  id: 3,
  host: "tun.lan",
  kind: "ssh",
  tunnel: true,
  router_advice: {
    mode: "tunnel",
    forwarded: true,
    finding_id: 9,
    title: "Tunnel target has a WAN forward",
    body: "WAN forward 443/tcp is mapped. A forwarded port bypasses Cloudflare Tunnel.",
  },
};

test("router_tab_renders_advice_and_probe_router_label", () => {
  const markup = render(TargetDetail, { target: TARGET, tab: "router" });
  const text = visibleText(markup);
  assert.match(markup, /data-tab="router"/);
  assert.match(text, /Probe router/);
  assert.match(text, /Tunnel target has a WAN forward/);
  assert.match(text, /443\/tcp/);
  assert.match(markup, /href="#\/findings\/9"/);
  assert.match(text, /⚠|✓|⛔|ℹ|forwarded|nothing forwarded|WAN/i);
  assert.doesNotMatch(markup, /role="dialog"/);
});

test("router_status_is_icon_or_words_not_color_only", () => {
  const markup = render(TargetDetail, { target: TARGET, tab: "router" });
  const text = visibleText(markup);
  assert.ok(/⚠|✓|⛔|ℹ|forwarded|nothing forwarded/i.test(text), text);
  assert.match(text, /forwarded|Tunnel target has a WAN forward/i);
});

test("hardening_tab_copy_is_honest", () => {
  const markup = render(TargetDetail, { target: TARGET, tab: "hardening" });
  const text = visibleText(markup);
  assert.match(markup, /data-tab="hardening"/);
  assert.match(text, /Hardening/);
  assert.match(text, /Findings inbox/i);
  assert.doesNotMatch(text, /\binstance\b/i);
});

test("targets_view_shows_hardening_and_router_tabs", () => {
  const markup = render(TargetsView, {
    phase: "live",
    targets: [TARGET],
    selectedId: 3,
    selected: TARGET,
    tab: "router",
    onSelect: () => {},
    onNav: () => {},
  });
  const text = visibleText(markup);
  assert.match(text, /Hardening/);
  assert.match(text, /Router/);
  assert.match(text, /Probe router/);
});

test("probeAndRefresh_refetches_target_detail_after_probe", async () => {
  const calls: string[] = [];
  (globalThis as any).fetch = async (url: string) => {
    calls.push(String(url));
    if (String(url).includes("router-probe")) {
      return {
        status: 201,
        json: async () => ({ ok: true, target_id: 3, forwarded: false, finding_id: null }),
      };
    }
    return {
      status: 200,
      json: async () => ({
        id: 3,
        host: "tun.lan",
        kind: "ssh",
        tunnel: true,
        router_advice: {
          mode: "tunnel",
          forwarded: false,
          finding_id: null,
          title: "",
          body: "",
        },
      }),
    };
  };
  const { status, data } = await probeAndRefresh(3);
  assert.equal(status, 201);
  assert.equal(data.router_advice.finding_id, null);
  assert.equal(data.router_advice.forwarded, false);
  assert.equal(calls[0], "/api/v1/targets/3/router-probe/");
  assert.equal(calls[1], "/api/v1/targets/3/");
});

test("probeRouter_posts_the_router_probe_route", async () => {
  const calls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: opts?.body ? JSON.parse(opts.body) : undefined });
    return { status: 201, json: async () => ({ ok: true, target_id: 3, forwarded: false, finding_id: null }) };
  };
  const { status } = await probeRouter(3);
  assert.equal(status, 201);
  assert.equal(calls[0].url, "/api/v1/targets/3/router-probe/");
});

test("app_passes_route_and_onNav_into_targets", () => {
  const app = readFileSync(new URL("../src/App.jsx", import.meta.url), "utf8");
  assert.match(app, /<Targets route=\{route\} onNav=\{onNav\} \/>/);
  const src = readFileSync(new URL("../src/screens/Targets.jsx", import.meta.url), "utf8");
  assert.match(src, /v1\/targets\//);
  assert.match(src, /onNav\("targets"/);
  assert.match(src, /target\.router_probe/);
  assert.match(src, /probeRouter/);
  assert.match(src, /probeAndRefresh/);
  assert.match(src, /setSelected\(result\.data\)/);
});
