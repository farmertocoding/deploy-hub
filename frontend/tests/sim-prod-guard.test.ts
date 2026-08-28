import { test } from "node:test";
import assert from "node:assert/strict";

import { simAllowed, simState } from "../src/api.js";

test("production builds refuse ?sim=", () => {
  assert.equal(simAllowed({ PROD: true }), false);
  assert.equal(simAllowed({ PROD: false }), true);
  assert.equal(simAllowed({}), true);
});

test("unknown sim names do not fall through to live fetch", async () => {
  const original = globalThis.window;
  (globalThis as any).window = {
    location: { search: "?sim=not-a-fixture" },
  };
  (globalThis as any).document = { cookie: "" };
  const originalFetch = globalThis.fetch;
  let fetched = false;
  (globalThis as any).fetch = async () => {
    fetched = true;
    return { status: 200, json: async () => ({}) };
  };
  try {
    const { api } = await import("../src/api.js");
    const result = await api("v1/aws/connect/", { access_key_id: "AKIA" });
    assert.equal(fetched, false);
    assert.equal(result.status, 404);
  } finally {
    (globalThis as any).window = original;
    (globalThis as any).fetch = originalFetch;
  }
});

test("simState is null when production env is set", () => {
  assert.equal(simState("?sim=live", { PROD: true }), null);
  assert.equal(simState("?sim=live", { PROD: false }), "live");
});
