// UX-F3-FIRST-RUN-CHECKLIST: Home is a checklist until the applicable first-run
// items are done (target + CF/plant if public + project), then today's map + fleet.
// Checklist completion is derived fleet state. Topic stays `findings`.
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { readFileSync } from "node:fs";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };
(globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

import { HomeView, attachFirstRun, addProject, firstRunSnapshot } from "../src/screens/Home.jsx";
import { remainingItems } from "../src/checklist.js";
import { SIM_FIXTURES } from "../src/sim.js";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

async function firstRun(state: string) {
  const fx = (SIM_FIXTURES as any)[state];
  assert.ok(fx, `missing sim fixture ${state}`);
  const { status, data } = await fx("v1/first-run/");
  assert.equal(status, 200, state);
  assert.ok(data?.data, `${state} first-run must be {seq, data}`);
  return data.data;
}

test("checklist_owns_home_until_items_are_done", async () => {
  // What would make this fail: Home rendering map + fleet while enroll / CF /
  // add-project are still open, or inventing a checklist websocket topic.
  const progress = await firstRun("empty");
  assert.equal(progress.owns_home, true);
  const left = remainingItems(progress);
  assert.deepEqual(left.map((i: any) => i.id),
    ["enroll_target", "connect_cloudflare", "add_project"]);
  assert.ok(!left.some((i: any) => i.id === "plant_origin_ca"),
    "plant waits until a proxied public site exists");

  const markup = render(HomeView, { width: 1280, progress, onNav: () => {} });
  const text = visibleText(markup);
  assert.match(text, /Enroll the first target/);
  assert.match(text, /Connect Cloudflare/);
  assert.match(text, /Add a project/);
  assert.doesNotMatch(text, /Plant the Origin-CA/);
  assert.doesNotMatch(text, /Fleet map/);
  assert.doesNotMatch(text, /Loading projects/);
  assert.equal((markup.match(/<button/g) || []).length, 3,
    "each remaining item is one sentence + the one button that populates it");

  const mid = await firstRun("mid-checklist");
  assert.equal(mid.owns_home, true);
  assert.ok(remainingItems(mid).length > 0);

  const calls: Array<any> = [];
  const events = {
    subscribe(topic: string, handler: Function, snapshotFn: Function) {
      calls.push({ topic, handler, snapshotFn });
    },
    unsubscribe(topic: string) {
      calls.push({ unsubscribe: topic });
    },
  };
  const detach = attachFirstRun(events, () => {});
  assert.equal(calls[0].topic, "findings",
    "checklist completion is derived state; topic stays findings");
  detach();
  assert.deepEqual(calls[1], { unsubscribe: "findings" });

  const authz = readFileSync(new URL("../../realtime/authorize.py", import.meta.url), "utf8");
  assert.doesNotMatch(authz, /checklist|first-run|first_run/,
    "do not add a checklist / first-run topic");
});

test("mesh_only_first_site_skips_cloudflare_and_plant", async () => {
  // What would make this fail: still requiring CF connect or Origin-CA plant
  // when the first site is mesh_only (review3 §M4).
  const progress = {
    owns_home: false,
    items: [
      { id: "enroll_target", applicable: true, done: true },
      { id: "connect_cloudflare", applicable: false, done: false },
      { id: "plant_origin_ca", applicable: false, done: false },
      { id: "add_project", applicable: true, done: true },
    ],
  };
  const byId = Object.fromEntries(progress.items.map((i: any) => [i.id, i]));
  assert.equal(byId.connect_cloudflare.applicable, false);
  assert.equal(byId.plant_origin_ca.applicable, false);
  assert.equal(byId.enroll_target.done, true);
  assert.equal(byId.add_project.done, true);
  assert.equal(progress.owns_home, false);

  const markup = render(HomeView, { width: 1280, progress, onNav: () => {} });
  const text = visibleText(markup);
  assert.doesNotMatch(text, /Connect Cloudflare/);
  assert.doesNotMatch(text, /Plant the Origin-CA/);
  assert.match(text, /Fleet map|Loading projects/);
});

test("proxied_public_path_requires_plant_before_done", async () => {
  // What would make this fail: treating a proxied public Site as first-run
  // complete before origin_ca_key_ref is planted.
  const progress = await firstRun("empty");
  // mid-public is the empty→bound public path with plant still open. The
  // dedicated fixture is `done` minus plant; reuse the named public-pending
  // shape served as part of empty's sibling `mid-checklist` is mesh-only, so
  // the public-needs-plant fixture is `done` only after plant. Drive the
  // derived card directly from the snapshot the public path must keep open.
  const pendingPlant = {
    owns_home: true,
    items: [
      { id: "enroll_target", applicable: true, done: true },
      { id: "connect_cloudflare", applicable: true, done: true },
      { id: "plant_origin_ca", applicable: true, done: false },
      { id: "add_project", applicable: true, done: true },
    ],
  };
  assert.deepEqual(remainingItems(pendingPlant).map((i: any) => i.id),
    ["plant_origin_ca"]);
  const markup = render(HomeView, { width: 1280, progress: pendingPlant, onNav: () => {} });
  const text = visibleText(markup);
  assert.match(text, /Plant the Origin-CA/);
  assert.match(text, /Plant Origin-CA/);
  assert.match(text, /SSL and Certificates/);
  assert.match(text, /service key/i);
  assert.doesNotMatch(text, /Fleet map/);
  assert.doesNotMatch(text, /Loading projects/);
  assert.ok(progress.owns_home, "empty fixture must still own Home");
});

test("done_checklist_reveals_map_and_fleet", async () => {
  // What would make this fail: the card staying on Home after every applicable
  // item is done, or revealing map/fleet while the card still owns the screen.
  const progress = await firstRun("done");
  assert.equal(progress.owns_home, false);
  assert.deepEqual(remainingItems(progress), []);

  const markup = render(HomeView, { width: 1280, progress, onNav: () => {} });
  const text = visibleText(markup);
  assert.doesNotMatch(text, /Enroll the first target/);
  assert.doesNotMatch(text, /Connect Cloudflare/);
  assert.doesNotMatch(text, /Plant the Origin-CA/);
  assert.doesNotMatch(text, /Add a project/);
  assert.match(text, /Fleet map/);
  assert.match(text, /Loading projects/);

  const snapCalls: string[] = [];
  const prevFetch = (globalThis as any).fetch;
  (globalThis as any).fetch = async (url: string) => {
    snapCalls.push(String(url));
    return { status: 200, json: async () => ({ seq: 1, data: progress }) };
  };
  try {
    const snap = await firstRunSnapshot();
    assert.equal(snapCalls[0], "/api/v1/first-run/");
    assert.deepEqual(snap.data, progress);
  } finally {
    (globalThis as any).fetch = prevFetch;
  }
});

test("successful_add_project_refetches_first_run_without_a_findings_event", async () => {
  // What would make this fail: AddProjectForm clearing fields after 201 and
  // waiting for a findings event that project create never publishes, so the
  // card stays on Home until remount.
  const done = await firstRun("done");
  assert.equal(done.owns_home, false);

  const urls: string[] = [];
  const prevFetch = (globalThis as any).fetch;
  (globalThis as any).fetch = async (url: string) => {
    urls.push(String(url));
    if (String(url).includes("/api/v1/findings/")) {
      return { status: 200, json: async () => ({ seq: 1, data: [] }) };
    }
    if (String(url).includes("/api/v1/projects/")) {
      return { status: 201, json: async () => ({ id: 9, name: "f3-mesh", sites: [] }) };
    }
    if (String(url).includes("/api/v1/first-run/")) {
      return { status: 200, json: async () => ({ seq: 1, data: done }) };
    }
    return { status: 404, json: async () => ({}) };
  };
  try {
    const result = await addProject({
      name: "f3-mesh", local_path: "/tmp/f3-mesh", exposure: "mesh_only", proxied: true,
    });
    assert.equal(result.status, 201);
    assert.equal(result.progress?.owns_home, false,
      "201 must return the refetched first-run progress so owns_home can clear");
    assert.ok(urls.some((u) => /\/api\/v1\/projects\/$/.test(u)), `urls: ${urls}`);
    assert.ok(urls.some((u) => /\/api\/v1\/first-run\/$/.test(u)),
      `201 must refetch first-run; urls: ${urls}`);
    assert.ok(!urls.some((u) => /\/api\/v1\/findings\//.test(u)),
      "project create does not publish findings; do not wait on that topic");
  } finally {
    (globalThis as any).fetch = prevFetch;
  }

  const markup = render(HomeView, { width: 1280, progress: done, onNav: () => {} });
  const text = visibleText(markup);
  assert.match(text, /Fleet map/);
  assert.match(text, /Loading projects/);
  assert.doesNotMatch(text, /Add a project/);
});
