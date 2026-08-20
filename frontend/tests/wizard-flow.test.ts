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
import { readFileSync } from "node:fs";
import { makeWizardHandlers, materializeGate, materializeOutcome,
  wizardSaveBody }
  from "../src/Readiness.jsx";
import { schemas } from "../src/api/zod.ts";
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
    { answers: { "site.domain": "staging.takko.market" } }, "PATCH");
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
  await live("v1/sites/4/wizard/", { answers: { "site.exposure": "public" } }, "PATCH");
  const { data } = await live("v1/sites/4/wizard/");
  assert.deepEqual(data.blocking.map((p: any) => p.code), ["answers_missing"]);
});

test("r10-ux-f4: an answered site's POST is not refused for the answer it has", async () => {
  reset();
  await live("v1/sites/4/wizard/",
    { answers: { "site.domain": "staging.takko.market" } }, "PATCH");

  const { status, data } = await live("v1/sites/4/manifest/", {});
  assert.equal(status, 201, "a wizard saying can_materialize must not meet answers_missing");

  const row = siteIn(rowFor((await live("v1/projects/")).data, "takko"), 4);
  assert.equal(row.latest_manifest_version, data.version);
});

test("r10-ux-f4: reset forgets the answer too", async () => {
  reset();
  await live("v1/sites/4/wizard/",
    { answers: { "site.domain": "staging.takko.market" } }, "PATCH");
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

// ── R11-Q1: the handlers, which no test could reach ──────────────────────────
//
// Everything above drives the FIXTURES: it asserts what the server answers, given the
// request the test makes. What none of it touches is the request the CLIENT makes — and
// that is where the ack checkbox turns into a body key and the outcome turns into a
// re-read. Two mutations of the shipped `SiteWizard`, both surviving all 79 tests:
//
//     -      { confirm_warnings: !!state.warnings?.length && ack });
//     +      { ack: !!state.warnings?.length && ack });
//
//     -    if (outcome.reloadWizard) load();
//
// The first makes the warnings gate's one control unreachable; the second deletes the
// R9-4 convergence. The fixtures cannot see either, because a fixture answers what it is
// asked and never learns what it was not asked for. `makeWizardHandlers` puts the two
// handlers where a spy can stand in for `api`.

type Call = { path: string; body?: any; method?: string };

function harness(state: any, ack: boolean, responses: Array<any>, draft: any = {}) {
  const calls: Call[] = [];
  const events: string[] = [];
  const api = async (path: string, body?: any, method?: string) => {
    calls.push({ path, body, method });
    return responses.shift() ?? { status: 500, data: { detail: "no response queued" } };
  };
  const msgs: any[] = [];
  const busy: boolean[] = [];
  const drafts: any[] = [];
  const handlers = makeWizardHandlers({
    siteId: 7, state, draft, ack, api,
    load: () => { events.push("load"); },
    onChanged: () => { events.push("onChanged"); },
    setBusy: (b: boolean) => busy.push(b),
    setMsg: (m: any) => msgs.push(m),
    setDraft: (d: any) => drafts.push(d),
  });
  return { handlers, calls, events, msgs, busy, drafts };
}

const WITH_WARNINGS = { warnings: [{ id: "node-ts.symlinked-files", title: "w" }],
                        blocking: [], can_materialize: true, questions: [] };
const NO_WARNINGS = { warnings: [], blocking: [], can_materialize: true, questions: [] };
const CREATED = { status: 201, data: { version: 4 } };

test("f1: save PATCHes {answers: draft}, not a qid map", async () => {
  const draft = { "site.domain": "app.example.com" };
  assert.deepEqual(wizardSaveBody(draft), { answers: draft });
  const h = harness(NO_WARNINGS, false, [{ status: 200, data: { answered: draft } }], draft);
  await h.handlers.save();
  assert.deepEqual(h.calls, [{
    path: "v1/sites/7/wizard/",
    body: { answers: draft },
    method: "PATCH",
  }]);
  assert.equal(schemas.PatchedAnswers.safeParse(h.calls[0].body).success, true);
});

test("r11-q1: the ack reaches the server as confirm_warnings, and only when it applies",
  async () => {
    // Warnings on screen and the box ticked: the one case that may confirm.
    let h = harness(WITH_WARNINGS, true, [CREATED]);
    await h.handlers.materialize();
    assert.deepEqual(h.calls, [{ path: "v1/sites/7/manifest/",
                                 body: { confirm_warnings: true }, method: undefined }],
      "the ack must reach the server under the key materialize.py reads");

    // Warnings on screen, box not ticked: this is the 409 the gate exists for.
    h = harness(WITH_WARNINGS, false, [{ status: 409, data: { code: "x" } }]);
    await h.handlers.materialize();
    assert.deepEqual(h.calls[0].body, { confirm_warnings: false });

    // R10-UX-F6: no warnings, no consent — whatever `ack` happens to hold. Ticked and
    // then the server's warnings went away is the only way to get here, and confirming
    // a set that no longer exists is not a thing to send.
    h = harness(NO_WARNINGS, true, [CREATED]);
    await h.handlers.materialize();
    assert.deepEqual(h.calls[0].body, { confirm_warnings: false });
  });

test("r11-q1: what each status re-reads — 201 both, 409 both, 500 neither", async () => {
  let h = harness(NO_WARNINGS, false, [CREATED]);
  await h.handlers.materialize();
  assert.deepEqual(h.events, ["load", "onChanged"],
    "a 201 re-reads the wizard and the project list");
  assert.deepEqual(h.msgs, [null, { ok: true, text: "Manifest v4 created." }]);

  // R9-4: a 409 is the server telling this client its copy is stale, and the only
  // correct response is to go and read the current one. Deleting this re-read is the
  // mutation that survived every test in this file.
  h = harness(WITH_WARNINGS, false,
              [{ status: 409, data: { code: "warnings_unconfirmed", detail: "d" } }]);
  await h.handlers.materialize();
  assert.deepEqual(h.events, ["load", "onChanged"],
    "a 409 re-reads too — the refusal exists because the screen is out of date");
  assert.ok(h.msgs[1].problems, "the refusal panel gets the problems list");

  // A 500 or a dead socket re-reads nothing on purpose: the server said nothing about
  // this site's state, so there is nothing to converge ON.
  h = harness(NO_WARNINGS, false, [{ status: 500, data: { detail: "boom" } }]);
  await h.handlers.materialize();
  assert.deepEqual(h.events, [], "nothing to converge on — a refetch would loop");
  assert.deepEqual(h.msgs[1], { ok: false, text: "boom" });
});

test("r11-q1: the busy flag brackets the request, both ways", async () => {
  const h = harness(NO_WARNINGS, false, [CREATED]);
  await h.handlers.materialize();
  assert.deepEqual(h.busy, [true, false],
    "a button that never re-enables is a screen the operator has to reload");
});

test("r11-q1: save PATCHes the draft, clears it on 200, and re-reads", async () => {
  const draft = { "site.domain": "takko.market" };
  let h = harness(NO_WARNINGS, false, [{ status: 200, data: {} }], draft);
  await h.handlers.save();

  const body = h.calls[0].body;
  // AnswersSerializer requires `{answers: {qid: value}}`; a qid map 400s.
  const parsed = schemas.PatchedAnswers.safeParse(body);
  assert.ok(parsed.success, JSON.stringify((parsed as any).error?.issues));
  assert.deepEqual(parsed.data.answers, draft);
  assert.equal("site.domain" in body, false);
  assert.deepEqual(h.calls, [{ path: "v1/sites/7/wizard/", body,
                               method: "PATCH" }]);
  assert.deepEqual(h.drafts, [{}], "the typed answers are the server's now");
  assert.deepEqual(h.events, ["load"], "…and the form shows what the server kept");
  assert.deepEqual(h.msgs[1], { ok: true, text: "Saved." });

  // A rejected answer keeps the draft — retyping a domain because the server said it was
  // malformed is the round-1 error-proofing property. P0-VALIDATION shape:
  // `{errors: {field: [{code, message, hint}]}}`.
  h = harness(NO_WARNINGS, false,
              [{ status: 400, data: { errors: {
                  "site.domain": [{ code: "invalid", message: "not a domain", hint: "" }],
                } } }],
              draft);
  await h.handlers.save();
  assert.deepEqual(h.drafts, []);
  assert.deepEqual(h.events, []);
  assert.deepEqual(h.msgs[1], { ok: false, text: "site.domain: not a domain" });

  // F-2 pointed save() at the field-map renderer for every non-200. Status 0
  // (api.js dead-socket) and sim 501 only carry `data.detail`. An empty red
  // line is not an error — materializeOutcome already keeps the detail.
  h = harness(NO_WARNINGS, false,
              [{ status: 0, data: { detail:
                  "Cannot reach server — check your connection and retry." } }],
              draft);
  await h.handlers.save();
  assert.deepEqual(h.drafts, []);
  assert.deepEqual(h.events, []);
  assert.deepEqual(h.msgs[1], { ok: false, text:
    "Cannot reach server — check your connection and retry." });

  h = harness(NO_WARNINGS, false,
              [{ status: 501, data: { detail: "[sim] NOT COVERED: PATCH /wizard/" } }],
              draft);
  await h.handlers.save();
  assert.deepEqual(h.msgs[1],
    { ok: false, text: "[sim] NOT COVERED: PATCH /wizard/" });
});

// ── R11-UX-F3: the sibling wizard that never re-read ─────────────────────────
//
// `refreshKey` is bumped whenever a write (or a refusal) means this screen's data is out
// of date. `ReadinessPanel` has taken it since R9-4 and re-reads the report; `SiteWizard`
// did not take it at all, so on a project with two sites the panel converged on the
// re-scanned truth while the OTHER site's wizard went on showing preflight answers
// computed against the report from before it moved — a blocker list and a gate saying the
// deploy may proceed, on one screen.
//
// The behavioural half of this pin is in sim-contract.test.ts, where the fixtures can
// actually move a sibling's payload. What is asserted here is the wiring, because
// `useEffect` does not run under `renderToStaticMarkup` and there is no DOM test runner
// on this tree: a dependency array is not observable, so it is read.

test("r11-ux-f3: SiteWizard takes refreshKey and re-reads on it", () => {
  const source = readFileSync(new URL("../src/Readiness.jsx", import.meta.url), "utf-8");

  assert.match(source, /function SiteWizard\(\{ site, refreshKey, onChanged \}\)/,
    "SiteWizard does not receive the key that says its data is stale");
  assert.match(source, /useEffect\(\(\) => \{ if \(open\) load\(\); \}, \[open, refreshKey\]\)/,
    "the wizard's load effect does not depend on refreshKey — a sibling's 409 " +
    "converges the panel and leaves this form showing the report from before it");
  assert.match(source, /<SiteWizard key=\{s\.id\} site=\{s\} refreshKey=\{refreshKey\}/,
    "the panel renders its wizards without passing the key down");
});

test("r11-ux-f3: after a sibling's 409 the OTHER site's gate shows the new truth",
  async () => {
    // The behavioural half of the wiring pin above, and the screen it is about: takko has
    // two sites, the operator opens both, presses Materialize on `prod`, and the server
    // refuses because the report moved. `prod`'s form converges (R9-4). `staging`'s form
    // is the one nobody touched — and its gate is computed from a payload that predates
    // the re-scan, so the screen showed a blocker list beside a sibling button reading
    // "Answers needed", which is a refusal an answer clears.
    reset();
    const before = await stale("v1/sites/4/wizard/");
    assert.equal(materializeGate(before.data).label, "Answers needed");

    const refused = await stale("v1/sites/1/manifest/", {});
    assert.equal(refused.status, 409);

    // `refreshKey` is what makes the sibling re-read; this is what it re-reads.
    const after = await stale("v1/sites/4/wizard/");
    assert.equal(materializeGate(after.data).label, "⛔ Blocked",
      "the sibling gate still offers a refusal the operator can type their way out of");
    assert.ok(materializeGate(after.data).title.includes("blockers"),
      "…and the reason on screen is the server's own sentence");
  });

// ── R12-F12-1: where the keyboard is after the thing it was on disappears ────
//
// Two swaps on this screen unmount the element that has focus: "Configure & materialize"
// replaces itself with the form, and Retry replaces the error panel with the spinner. In
// both cases focus falls to `<body>` — the press is announced by nothing, and the next Tab
// starts again at the top of the document.
//
// THE BOUNDARY, stated as R11-UX-F3's pin states it rather than left for the next reader
// to discover: `renderToStaticMarkup` runs no effects and this tree has no DOM runner, so
// "focus moved" is not observable here. What IS observable is the markup that makes it
// possible — a focusable container, on every branch that can render after the swap — and
// the effect that asks for it. The first is rendered and asserted; the second is read.

test("f12-1: the opened wizard is focusable, on every branch the swap can land on", () => {
  const source = readFileSync(new URL("../src/Readiness.jsx", import.meta.url), "utf-8");
  const wizard = source.slice(source.indexOf("function SiteWizard("));

  // The fetch is in flight when the click lands, so which of these three renders at that
  // moment depends on the network. A ref on only the happy one focuses nothing exactly
  // when the operator has least information.
  assert.equal((wizard.match(/ref=\{openedRef\} tabIndex=\{-1\}/g) || []).length, 3,
    "the form, the spinner and the error line must all be able to receive focus");
  assert.match(wizard,
    /useEffect\(\(\) => \{ if \(open\) openedRef\.current\?\.focus\(\); \}/,
    "nothing asks for focus when the wizard opens");
});

test("f12-1: Retry's swap target is focusable, and first paint is not", () => {
  const source = readFileSync(new URL("../src/Readiness.jsx", import.meta.url), "utf-8");
  const screen = source.slice(source.indexOf("export default function ReadinessScreen"));

  assert.equal((screen.match(/ref=\{statusRef\} tabIndex=\{-1\}/g) || []).length, 2,
    "the error line and the spinner are the two things Retry can swap to");
  assert.match(screen, /onClick=\{\(\) => \{ setRetried\(true\); load\(\); \}\}/,
    "Retry does not record that a person pressed something");
  assert.match(screen, /if \(retried\) statusRef\.current\?\.focus\(\);/,
    "…and nothing acts on it");
  // The gate matters as much as the focus call: moving focus on FIRST paint, when nobody
  // has pressed anything, is its own defect — the operator is dropped into a region they
  // did not ask for, on a screen they have not read yet.
  assert.ok(!/useEffect\(\(\) => \{\s*statusRef\.current\?\.focus\(\)/.test(screen),
    "focus is taken on every render, first paint included");
});
