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
  assert.match(text, /Connect AWS/);

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

function nodeText(node: any): string {
  if (node == null) return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (node.props?.children) return nodeText(node.props.children);
  if (node.children) return nodeText(node.children);
  return "";
}

function clickLabel(tree: any, label: string) {
  const btn = tree.root.findAllByType("button").find((b: any) => nodeText(b).includes(label));
  assert.ok(btn, `missing button ${label}`);
  assert.equal(btn.props.type, "button", `${label} must be type=button so a Settings form does not submit`);
  btn.props.onClick({ preventDefault() {}, stopPropagation() {} });
  return btn;
}

test("aws_connect_form_submit_and_click_do_not_post_until_t1_confirm", async () => {
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  (globalThis as any).window.location.search = "";
  (globalThis as any).window.location.hostname = "localhost";
  (globalThis as any).document.cookie = "csrftoken=test";
  if (!(globalThis as any).navigator) {
    Object.defineProperty(globalThis, "navigator", { value: {}, configurable: true });
  }
  Object.defineProperty((globalThis as any).navigator, "credentials", {
    configurable: true,
    value: { get: async () => ({ id: "cred", type: "public-key", response: {} }) },
  });

  const credentialPosts: any[] = [];
  (globalThis as any).fetch = async (url: string, opts: any = {}) => {
    const path = String(url);
    const method = opts.method || (opts.body !== undefined ? "POST" : "GET");
    if (path.includes("v1/aws/connect/") && method === "POST") {
      credentialPosts.push(JSON.parse(opts.body));
      return {
        status: 201,
        json: async () => ({ account_id_last4: "9012", region: "us-east-1" }),
      };
    }
    if (path.includes("authentication/begin")) {
      return { status: 200, json: async () => ({ challenge: "Y2hhbGxlbmdl" }) };
    }
    if (path.includes("auth/webauthn/touch")) {
      return { status: 200, json: async () => ({ touched: true }) };
    }
    return { status: 200, json: async () => ({ connected: false, reason: "set HUB_AWS_CREDENTIALS_REF" }) };
  };

  const { act, create } = await import("react-test-renderer");
  let tree: any;
  await act(async () => {
    tree = create(React.createElement(AwsPanel, { systemAdmin: true }));
    await Promise.resolve();
  });

  const passwords = tree.root.findAllByType("input").filter((n: any) => n.props.type === "password");
  assert.equal(passwords.length, 2);
  await act(() => {
    passwords[0].props.onChange({ target: { value: "AKIATEST", name: passwords[0].props.name } });
    passwords[1].props.onChange({ target: { value: "secret-test", name: passwords[1].props.name } });
  });

  const form = tree.root.findByType("form");
  await act(() => form.props.onSubmit({ preventDefault() {} }));
  assert.equal(credentialPosts.length, 0, "Enter/form submit must not POST AWS credentials");

  await act(() => { clickLabel(tree, "Connect AWS"); });
  assert.match(nodeText(tree.toJSON()), /type the name/i);
  assert.equal(credentialPosts.length, 0, "Connect click must open T1, not POST");

  await act(async () => {
    clickLabel(tree, "Touch security key");
    await Promise.resolve();
    await Promise.resolve();
  });
  const nameInput = tree.root.findAllByType("input")
    .find((n: any) => n.props["aria-label"] === "type the name");
  assert.ok(nameInput, "T1 overlay name field");
  await act(() => {
    nameInput.props.onChange({ target: { value: "aws" } });
  });
  await act(() => { clickLabel(tree, "Confirm — Connect AWS"); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
  assert.equal(credentialPosts.length, 1, "POST only after hardware touch + typed name");
  assert.equal(credentialPosts[0].access_key_id, "AKIATEST");
  assert.equal(credentialPosts[0].secret_access_key, "secret-test");
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
