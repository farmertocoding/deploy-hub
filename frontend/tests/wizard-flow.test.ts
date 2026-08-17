// The SEQUENCE SiteWizard performs, driven through the §F8 fixtures.
//
// readiness-render.test.ts pins markup and materialize-gate.test.ts pins the two pure
// decisions. Neither covers the third thing this screen does, which is a CONVERSATION:
// GET the wizard, PATCH an answer, re-read, POST the manifest, re-read again. Round
// 10's UX review found three defects that live entirely in that sequence and are
// invisible to any single response — a 201 whose re-read returns the pre-POST row, a
// refusal whose re-read shows the version it refused to create, and a PATCH whose
// re-read undoes the answer.
//
// NOT a DOM test: there is no react-testing-library on this tree and `SiteWizard` is
// effects and fetches. What is asserted is the exchange the component makes, in the
// order it makes it — `api()` calls the fixture, so the fixture is the server for this
// purpose and every convergence defect above is a property of what it returns.
import { test } from "node:test";
import assert from "node:assert/strict";
import { materializeGate, materializeOutcome } from "../src/Readiness.jsx";
import { SIM_FIXTURES } from "../src/sim.js";

(globalThis as any).window = { location: { search: "" } };

const live = (path: string, body?: any, method?: string) =>
  (SIM_FIXTURES.live as any)(path, body, method);
const stale = (path: string, body?: any, method?: string) =>
  (SIM_FIXTURES.stale as any)(path, body, method);
const rowFor = (projects: any[], name: string) =>
  projects.find((p: any) => p.name === name);
const siteIn = (project: any, id: number) =>
  project.sites.find((s: any) => s.id === id);

const reset = () => {
  (SIM_FIXTURES.live as any).reset();
  (SIM_FIXTURES.stale as any).reset();
};

// ── R10-UX-F2: the 201 that never arrived on screen ──────────────────────────

test("r10-ux-f2: atlas-edge's list row converges after the ack-confirmed 201", async () => {
  reset();
  // Before: the site the ack checkbox exists for has no manifest at all.
  const before = siteIn(rowFor((await live("v1/projects/")).data, "atlas-edge"), 3);
  assert.equal(before.latest_manifest_version, null);

  // The wizard says go; the POST without the ack is the real 409, with it the real 201.
  const refused = await live("v1/sites/3/manifest/", { confirm_warnings: false });
  assert.equal(refused.status, 409);
  const { status, data } = await live("v1/sites/3/manifest/", { confirm_warnings: true });
  assert.equal(status, 201);

  const outcome = materializeOutcome(status, data);
  assert.equal(outcome.refreshProject, true, "the client re-reads the list after a 201");

  const after = siteIn(rowFor((await live("v1/projects/")).data, "atlas-edge"), 3);
  assert.equal(after.latest_manifest_version, data.version);
  assert.equal(after.manifest_current, true,
    `"${outcome.msg.text}" beside "no manifest yet" is the screen this closes`);
});

test("r10-ux-f2: takko/prod's row moves from v3 to the version it just created", async () => {
  reset();
  const before = siteIn(rowFor((await live("v1/projects/")).data, "takko"), 1);
  assert.equal(before.latest_manifest_version, 3);

  const { status, data } = await live("v1/sites/1/manifest/", { confirm_warnings: false });
  assert.equal(status, 201);
  assert.equal(data.version, 4);

  const after = siteIn(rowFor((await live("v1/projects/")).data, "takko"), 1);
  assert.equal(after.latest_manifest_version, 4);
});

test("r10-ux-f2: reset puts the live state back before any POST", async () => {
  reset();
  await live("v1/sites/3/manifest/", { confirm_warnings: true });
  (SIM_FIXTURES.live as any).reset();

  const row = siteIn(rowFor((await live("v1/projects/")).data, "atlas-edge"), 3);
  assert.equal(row.latest_manifest_version, null,
    "a fixture with a memory nobody can clear is a fixture nobody can review twice");
});

test("r10-ux-f2: a refused POST creates nothing", async () => {
  reset();
  const refused = await live("v1/sites/2/manifest/", {});
  assert.equal(refused.status, 409);

  const row = siteIn(rowFor((await live("v1/projects/")).data, "legacy-shop"), 2);
  assert.equal(row.latest_manifest_version, null);
});

// ── R10-UX-F3: a refusal that appeared to have incremented the version ───────

test("r10-ux-f3: the stale convergence does not create a manifest", async () => {
  reset();
  const before = siteIn(rowFor((await stale("v1/projects/")).data, "takko"), 1);
  assert.equal(before.latest_manifest_version, 3);
  assert.equal(before.manifest_current, true);

  const { status } = await stale("v1/sites/1/manifest/", {});
  assert.equal(status, 409);

  const after = siteIn(rowFor((await stale("v1/projects/")).data, "takko"), 1);
  assert.equal(after.latest_manifest_version, 3,
    "a refusal creates no manifest — this row used to read v4");
  assert.equal(after.manifest_current, false,
    "…and the re-scan is what makes the manifest it does have stale");
});

test("r10-ux-f3: and the report and wizard converge with it", async () => {
  reset();
  await stale("v1/sites/1/manifest/", {});

  const { data: report } = await stale("v1/projects/1/readiness/");
  assert.ok(report.blockers.some((c: any) => c.id === "core.secret-scan"),
    "the panel above the refusal must stop reading ✓ No findings");
  const { data: wizard } = await stale("v1/sites/1/wizard/");
  assert.equal(wizard.can_materialize, false);
  assert.equal(materializeGate(wizard).label, "⛔ Blocked");
});

// ── R10-UX-F4: the answer that went in and came straight back out ────────────

test("r10-ux-f4: typing the domain and saving clears Answers needed", async () => {
  reset();
  const { data: before } = await live("v1/sites/4/wizard/");
  assert.deepEqual(before.blocking.map((p: any) => p.code), ["answers_missing"]);
  assert.equal(materializeGate(before).label, "Answers needed");

  // What `save()` sends, and what it does with the answer: PATCH, then re-read.
  const patched = await live("v1/sites/4/wizard/",
    { "site.domain": "staging.takko.market" }, "PATCH");
  assert.equal(patched.status, 200);

  const { data: after } = await live("v1/sites/4/wizard/");
  assert.equal(after.answered["site.domain"], "staging.takko.market");
  assert.deepEqual(after.blocking, []);
  assert.equal(after.can_materialize, true);
  assert.equal(materializeGate(after).label, "Materialize manifest");
});

test("r10-ux-f4: the PATCH is body-driven, not a counter", async () => {
  reset();
  // A PATCH carrying some other answer does not clear the refusal the domain clears.
  await live("v1/sites/4/wizard/", { "site.exposure": "public" }, "PATCH");
  const { data } = await live("v1/sites/4/wizard/");
  assert.deepEqual(data.blocking.map((p: any) => p.code), ["answers_missing"]);
});

test("r10-ux-f4: an answered site's POST is not refused for the answer it has", async () => {
  reset();
  await live("v1/sites/4/wizard/", { "site.domain": "staging.takko.market" }, "PATCH");

  const { status, data } = await live("v1/sites/4/manifest/", {});
  assert.equal(status, 201, "a wizard saying can_materialize must not meet answers_missing");

  const row = siteIn(rowFor((await live("v1/projects/")).data, "takko"), 4);
  assert.equal(row.latest_manifest_version, data.version);
});

test("r10-ux-f4: reset forgets the answer too", async () => {
  reset();
  await live("v1/sites/4/wizard/", { "site.domain": "staging.takko.market" }, "PATCH");
  (SIM_FIXTURES.live as any).reset();

  const { data } = await live("v1/sites/4/wizard/");
  assert.deepEqual(data.blocking.map((p: any) => p.code), ["answers_missing"]);
});

// ── the ack flow end to end, which no test drove before ─────────────────────

test("r10: the ack checkbox is the only difference between the 409 and the 201", async () => {
  reset();
  const { data: wizard } = await live("v1/sites/3/wizard/");
  assert.ok(wizard.warnings.length >= 1, "no warnings, nothing to acknowledge");
  assert.equal(materializeGate(wizard).disabled, false,
    "the warnings gate is only reachable from a site that clears preflight");

  const refused = await live("v1/sites/3/manifest/", { confirm_warnings: false });
  assert.equal(refused.status, 409);
  assert.equal(refused.data.code, "warnings_unconfirmed");
  // Every warning the refusal names is one the wizard offered for acknowledgement.
  const offered = new Set(wizard.warnings.map((w: any) => w.id));
  for (const item of refused.data.items || []) assert.ok(offered.has(item.id), item.id);

  const created = await live("v1/sites/3/manifest/", { confirm_warnings: true });
  assert.equal(created.status, 201);
});
