// Task 12b: the Settings Cloudflare tab exists and POSTs the pasted token
// to the connect endpoint. Markup is pinned the way nav.test.ts pins tabs;
// the post is pinned through connectCloudflare (api() → fetch), because
// this tree has no react-testing-library for a click-driven form.
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };
(globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

import { SETTINGS_TABS, CloudflarePanel, connectCloudflare, plantOriginCa } from "../src/screens/Settings.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

test("cloudflare_tab_exists_and_posts_the_token", async () => {
  assert.ok(SETTINGS_TABS.some((t) => t.id === "cloudflare"),
    "Cloudflare must be a Settings tab, not a top-level page");
  assert.equal(SETTINGS_TABS.find((t) => t.id === "cloudflare")?.label, "Cloudflare");

  const markup = render(CloudflarePanel);
  const text = visibleText(markup);
  assert.match(markup, /type="password"/, "the token field must not echo in the clear");
  assert.ok(text.includes("Connect"), text);
  assert.ok(!/t1-connect|Bearer /i.test(markup));

  const calls: Array<{ url: string; body: any }> = [];
  const pasted = "t1-connect-dummy-token-not-a-credential";
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: JSON.parse(opts.body) });
    return {
      status: 201,
      json: async () => ({
        account: { id: 1, provider: "cloudflare", label: "connect.example" },
        zone: {
          id: 2, name: "connect.example",
          provider_zone_id: "zid-connect", purpose: "prod",
        },
      }),
    };
  };

  const { status, data } = await connectCloudflare(pasted);
  assert.equal(status, 201);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/v1/cloudflare/connect/");
  assert.equal(calls[0].body.token, pasted);
  assert.equal(data.zone.name, "connect.example");
  assert.ok(!JSON.stringify(data).includes(pasted),
    "the success body the panel renders must not echo the token");
});

test("connect_names_the_missing_origin_ca_key_ref_and_has_no_paste_for_it", () => {
  // 12b is DNS-token only. After connect, Origin certs fail closed by name —
  // this screen must say origin_ca_key_ref is missing, never offer a second paste.
  const markup = render(CloudflarePanel);
  const text = visibleText(markup);
  assert.match(text, /origin_ca_key_ref/);
  assert.ok(!/Origin CA key/i.test(text) || /does not accept|not accept|vault/i.test(text),
    text);
  const passwords = markup.match(/type="password"/g) || [];
  assert.equal(passwords.length, 1, "only the DNS token field is a paste surface");
});

test("plant_posts_path_only_and_connect_stays_token_only", async () => {
  const markup = render(CloudflarePanel);
  const text = visibleText(markup);
  assert.match(text, /Plant/);
  assert.match(text, /path/i);
  assert.ok(!/type="password"[^>]*path/i.test(markup));
  const passwords = markup.match(/type="password"/g) || [];
  assert.equal(passwords.length, 1, "Plant is a path field, not a second key paste");

  const calls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: JSON.parse(opts.body) });
    return { status: 200, json: async () => ({ planted: true }) };
  };
  const plantedPath = "/etc/deploy-hub/origin-ca/key";
  const { status, data } = await plantOriginCa(3, plantedPath);
  assert.equal(status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/v1/dns-accounts/3/origin-ca-plant/");
  assert.deepEqual(calls[0].body, { path: plantedPath });
  assert.equal(data.planted, true);
  assert.ok(!("origin_ca_key" in calls[0].body));
});
