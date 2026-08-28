// Settings AWS tab: peer of Cloudflare, write-only paste, degraded empty/error.
// Markup is pinned the way settings-cloudflare.test.ts pins the CF tab;
// the post is pinned through connectAws (api() → fetch).
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };
(globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

import { SETTINGS_TABS, AwsPanel, AwsStatusBanner, connectAws } from "../src/screens/Settings.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

test("aws_tab_exists_paste_is_write_only_degraded_empty_and_error", async () => {
  assert.ok(SETTINGS_TABS.some((t) => t.id === "aws"),
    "AWS must be a Settings tab, not a top-level page");
  assert.equal(SETTINGS_TABS.find((t) => t.id === "aws")?.label, "AWS");
  const cf = SETTINGS_TABS.findIndex((t) => t.id === "cloudflare");
  const aws = SETTINGS_TABS.findIndex((t) => t.id === "aws");
  assert.equal(aws, cf + 1, "AWS sits beside Cloudflare");

  const tenant = render(AwsPanel);
  assert.doesNotMatch(tenant, /type="password"/);
  assert.match(visibleText(tenant), /system-administrator/);

  const markup = render(AwsPanel, { systemAdmin: true });
  const text = visibleText(markup);
  assert.match(text, /not connected/i, text);
  assert.ok(!/\bConnected\b/.test(text), text);
  const passwords = markup.match(/type="password"/g) || [];
  assert.equal(passwords.length, 2, "access key id and secret are write-only");
  assert.match(text, /HUB_AWS_CREDENTIALS_REF/);

  const pastedId = "t1-aws-access-key-id-not-a-credential";
  const pastedSecret = "t1-aws-secret-access-key-not-a-credential";

  const okCalls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    okCalls.push({ url, body: JSON.parse(opts.body) });
    return {
      status: 201,
      json: async () => ({ account_id_last4: "9012", region: "us-east-1" }),
    };
  };
  const { status, data } = await connectAws(pastedId, pastedSecret);
  assert.equal(status, 201);
  assert.equal(okCalls.length, 1);
  assert.equal(okCalls[0].url, "/api/v1/aws/connect/");
  assert.equal(okCalls[0].body.access_key_id, pastedId);
  assert.equal(okCalls[0].body.secret_access_key, pastedSecret);
  assert.equal(data.account_id_last4, "9012");
  const dumped = JSON.stringify(data);
  assert.ok(!dumped.includes(pastedId), "201 must not echo the access key id");
  assert.ok(!dumped.includes(pastedSecret), "201 must not echo the secret");

  (globalThis as any).fetch = async () => ({
    status: 409,
    json: async () => ({
      connected: false,
      reason: "set HUB_AWS_CREDENTIALS_REF",
      detail: "set HUB_AWS_CREDENTIALS_REF",
    }),
  });
  const err = await connectAws(pastedId, pastedSecret);
  assert.equal(err.status, 409);
  assert.equal(err.data.connected, false);
  assert.match(err.data.reason, /HUB_AWS_CREDENTIALS_REF/);
  assert.ok(!/\bConnected\b/.test(JSON.stringify(err.data)));
});

test("aws_status_banner_hides_empty_ref_lie_after_connect", () => {
  const empty = visibleText(render(AwsStatusBanner, {
    connected: false, reason: "set HUB_AWS_CREDENTIALS_REF",
  }));
  assert.match(empty, /not connected/i, empty);
  assert.match(empty, /HUB_AWS_CREDENTIALS_REF/, empty);
  assert.ok(!/\bConnected\b/.test(empty), empty);

  const configured = visibleText(render(AwsStatusBanner, {
    connected: true, accountLast4: "9012", region: "us-east-1",
  }));
  assert.doesNotMatch(configured, /AWS is not connected/i);
  assert.match(configured, /Account ···9012 in us-east-1/);
  assert.ok(!/\bConnected\b/.test(configured), configured);

  const after201 = visibleText(render(AwsStatusBanner, {
    connected: false, accountLast4: "9012", region: "us-east-1",
  }));
  assert.doesNotMatch(after201, /AWS is not connected/i);
  assert.match(after201, /Account ···9012 in us-east-1/);
  assert.ok(!/\bConnected\b/.test(after201), after201);
});
