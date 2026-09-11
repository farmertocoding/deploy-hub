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

import {
  SETTINGS_TABS,
  CloudflarePanel,
  connectCloudflare,
  connectedCloudflareAccounts,
  plantOriginCa,
} from "../src/screens/Settings.jsx";

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
  assert.match(text, /Connect Cloudflare/);
  assert.ok(!/t1-connect/i.test(markup));
  assert.ok(!/Bearer [A-Za-z0-9._-]{16,}/.test(markup),
    "must not echo a Bearer token value");

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
  assert.match(text, /SSL and Certificates/);
  assert.match(text, /Bearer/);
  assert.ok(!/Origin CA key/i.test(text) || /does not accept|not accept|vault|deprecated|Bearer/i.test(text),
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

async function completeT1(tree: any, act: any, confirmLabel: string, typedName: string) {
  await act(async () => {
    clickLabel(tree, "Touch security key");
    await Promise.resolve();
    await Promise.resolve();
  });
  const nameInput = tree.root.findAllByType("input")
    .find((n: any) => n.props["aria-label"] === "type the name");
  assert.ok(nameInput, "T1 overlay name field");
  await act(() => { nameInput.props.onChange({ target: { value: typedName } }); });
  await act(() => { clickLabel(tree, confirmLabel); });
  await act(async () => { await Promise.resolve(); await Promise.resolve(); });
}

test("cloudflare_and_origin_ca_form_submit_do_not_post_until_t1_confirm", async () => {
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

  const tokenPosts: any[] = [];
  const plantPosts: any[] = [];
  (globalThis as any).fetch = async (url: string, opts: any = {}) => {
    const path = String(url);
    const method = opts.method || (opts.body !== undefined ? "POST" : "GET");
    if (path.includes("cloudflare/connect/") && method === "POST") {
      tokenPosts.push(JSON.parse(opts.body));
      return {
        status: 201,
        json: async () => ({
          account: { id: 3, provider: "cloudflare", label: "connect.example" },
          zone: { id: 2, name: "connect.example", provider_zone_id: "zid", purpose: "prod" },
        }),
      };
    }
    if (path.includes("origin-ca-plant/") && method === "POST") {
      plantPosts.push({ url: path, body: JSON.parse(opts.body) });
      return { status: 200, json: async () => ({ planted: true }) };
    }
    if (path.includes("authentication/begin")) {
      return { status: 200, json: async () => ({ challenge: "Y2hhbGxlbmdl" }) };
    }
    if (path.includes("auth/webauthn/touch")) {
      return { status: 200, json: async () => ({ touched: true }) };
    }
    if (path.includes("v1/hud/integrations")) {
      return {
        status: 200,
        json: async () => ({
          dns: [{ id: 3, provider: "cloudflare", label: "connect.example" }],
        }),
      };
    }
    return { status: 200, json: async () => ({}) };
  };

  const { act, create } = await import("react-test-renderer");
  let tree: any;
  await act(async () => {
    tree = create(React.createElement(CloudflarePanel));
    await Promise.resolve();
    await Promise.resolve();
  });

  const tokenInput = tree.root.findAllByType("input").find((n: any) => n.props.type === "password");
  assert.ok(tokenInput);
  await act(() => {
    tokenInput.props.onChange({ target: { value: "cf-token-not-a-credential", name: tokenInput.props.name } });
  });
  const connectForm = tree.root.findAllByType("form")[0];
  await act(() => connectForm.props.onSubmit({ preventDefault() {} }));
  assert.equal(tokenPosts.length, 0, "Enter must not POST the Cloudflare token");

  await act(() => { clickLabel(tree, "Connect Cloudflare"); });
  assert.match(nodeText(tree.toJSON()), /type the name/i);
  assert.equal(tokenPosts.length, 0, "Connect click must open T1, not POST");
  await completeT1(tree, act, "Confirm — Connect Cloudflare", "cloudflare");
  assert.equal(tokenPosts.length, 1);
  assert.equal(tokenPosts[0].token, "cf-token-not-a-credential");

  const pathInput = tree.root.findAllByType("input").find((n: any) => n.props.type === "text");
  assert.ok(pathInput);
  await act(() => {
    pathInput.props.onChange({ target: { value: "/etc/deploy-hub/origin-ca/key", name: pathInput.props.name } });
  });
  const plantForm = tree.root.findAllByType("form")[1];
  await act(() => plantForm.props.onSubmit({ preventDefault() {} }));
  assert.equal(plantPosts.length, 0, "Enter must not plant Origin CA");

  await act(() => { clickLabel(tree, "Plant Origin CA"); });
  assert.equal(plantPosts.length, 0, "Plant click must open T1, not POST");
  await completeT1(tree, act, "Confirm — Plant Origin CA token", "origin-ca");
  assert.equal(plantPosts.length, 1);
  assert.deepEqual(plantPosts[0].body, { path: "/etc/deploy-hub/origin-ca/key" });
});

test("existing_cloudflare_accounts_can_be_selected_for_origin_ca_plant", () => {
  const accounts = connectedCloudflareAccounts({
    dns: [
      { id: 3, provider: "cloudflare", label: "saturdays-succulents.com" },
      { id: 4, provider: "cloudflare", label: "takko.market" },
      { id: 5, provider: "route53", label: "example.com" },
    ],
  });
  assert.deepEqual(accounts.map((row: any) => row.id), [3, 4]);

  const markup = render(CloudflarePanel);
  assert.match(markup, /aria-label="Origin-CA DNS account"/);
  assert.match(markup, /select an account/);
});

test("settings_add_passkey_runs_create_ceremony", async () => {
  // Security "Add a passkey" must use navigator.credentials.create, same as Enroll.
  const { readFileSync } = await import("node:fs");
  const { fileURLToPath } = await import("node:url");
  const { dirname, join } = await import("node:path");
  const src = join(dirname(fileURLToPath(import.meta.url)), "../src");
  const { registerPasskey } = await import("../src/webauthn.js");

  const calls: any[] = [];
  const result = await registerPasskey("phone", {
    apiFn: async (path: string, body: any) => {
      calls.push({ path, body });
      if (path.includes("registration/begin"))
        return { status: 200, data: { challenge: "Y2hhbGxlbmdl" } };
      return { status: 200, data: { webauthn_count: 2 } };
    },
    createCredential: async (opts: any) => {
      calls.push({ create: opts });
      return { id: "new-cred" };
    },
  });
  assert.equal(result.status, 200);
  assert.equal(calls[0].path, "auth/webauthn/registration/begin/");
  assert.equal(calls[1].create.challenge instanceof ArrayBuffer, true);
  assert.equal(calls[2].path, "auth/webauthn/registration/complete/");
  assert.equal(calls[2].body.name, "phone");
  assert.equal(calls[2].body.id, "new-cred");

  const settings = readFileSync(join(src, "screens/Settings.jsx"), "utf8");
  assert.match(settings, /registerPasskey/);
  assert.doesNotMatch(settings, /id: "phone"/);

  const enroll = readFileSync(join(src, "screens/Enroll.jsx"), "utf8");
  assert.match(enroll, /registerPasskey/);
});
