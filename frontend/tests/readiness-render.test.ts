// What the readiness screen RENDERS, as opposed to what it decides.
//
// materialize-gate.test.ts pins the decisions, which are pure functions and easy to
// look at. The round-9 UX queue was mostly the other half: a detail rendered into a
// <p> that collapses its newlines, a success sentence shown for a project nobody has
// scanned, a refusal delivered only through the `title=` of a disabled button, and a
// plural formed by adding "s" to "Deferred to sandbox". None of those are decisions —
// they are markup, and the only way to assert markup is to render it.
//
// react-dom/server, not a browser: these are presentational components with no effects
// and no fetches, and `renderToStaticMarkup` gives the exact string a reviewer would be
// looking at. The components are exported for this reason and used only here and in
// Readiness.jsx itself.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Badge, CheckBody, MaterializeControl, OutcomeRegion, ProjectRow,
  ProjectRowSelector, QuestionField, ReportScope, SaveButton, WarningsAck,
  busyClickGuard, questionFieldId, reportSummary, rowKeyHandler }
  from "../src/Readiness.jsx";
import { SIM_FIXTURES } from "../src/sim.js";

(globalThis as any).window = { location: { search: "" } };

const render = (component: any, props: any) =>
  renderToStaticMarkup(React.createElement(component, props));
// Attribute values live inside the angle brackets; stripping tags leaves only what the
// operator can actually read on the screen.
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

// ── item 1: multi-line details rendered as one paragraph ─────────────────────

test("r9-1: a multi-line detail keeps its lines", () => {
  const markup = render(CheckBody, {
    check: { detail: "a.py:1: first\nb.py:2: second", fix_hint: "one\ntwo" },
  });
  assert.match(markup, /white-space:pre-line/,
    "a \\n-joined finding list in a <p> is one run-on paragraph");
  assert.equal(markup.match(/white-space:pre-line/g)?.length, 2,
    "the fix hint is written the same way and needs the same handling");
  assert.ok(visibleText(markup).includes("first\nb.py:2: second"));
});

test("r9-1: the fixture that produced the finding", async () => {
  // legacy-shop's `core.secret-scan`: fifteen file:line findings joined with \n, then a
  // blank line and two paragraphs of fix hint. Rendered without white-space handling it
  // is a single wall of text with the filenames run together.
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/2/readiness/");
  const check = report.blockers.find((c: any) => c.id === "core.secret-scan");
  const lines = check.detail.split("\n\n")[0].split("\n");
  assert.ok(lines.length >= 15, `the fixture lost its lines: ${lines.length}`);

  const text = visibleText(render(CheckBody, { check }));
  for (const line of lines) assert.ok(text.includes(line), line);
  assert.match(render(CheckBody, { check }), /white-space:pre-line/);
});

// ── item 5: "✓ No findings" for a project nobody has scanned ─────────────────

test("r9-5: an empty report with no scan is not a clean report", async () => {
  const { data: report } = await (SIM_FIXTURES.degraded as any)("v1/projects/4/readiness/");
  assert.equal(report.scanned_at, null);
  assert.equal(reportSummary(report).kind, "never-scanned");
});

test("r9-5: an empty report WITH a scan still reads as clean", async () => {
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/1/readiness/");
  assert.ok(report.scanned_at);
  assert.equal(reportSummary(report).kind, "clean");
});

test("r9-5: a report with findings is neither", async () => {
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/2/readiness/");
  assert.equal(reportSummary(report).kind, "findings");
  // …and the sections come back with it, so the panel has one definition of them.
  const summary = reportSummary(report);
  assert.deepEqual(summary.sections.map(([tier]: any) => tier),
    ["blocker", "warning", "advice", "pending_sandbox"]);
});

// ── item 7: the refusal that only a mouse could find ─────────────────────────

test("r9-7: the refusal detail is visible text, not only a tooltip", () => {
  const detail = "this project has not been scanned yet";
  const markup = render(MaterializeControl, {
    gate: { disabled: true, label: "⛔ Blocked", title: detail },
    busy: false, onClick: () => {},
  });
  assert.ok(markup.includes(`title="${detail}"`), "the tooltip stays for the pointer");
  assert.ok(visibleText(markup).includes(detail),
    "a disabled button cannot be focused, so its title= reaches nobody who is not " +
    "hovering it — for scan_required and the schema-skew refusal that was the only " +
    "carrier of the reason");
});

test("r9-7: an enabled control has no refusal to show", () => {
  const markup = render(MaterializeControl, {
    gate: { disabled: false, label: "Materialize manifest", title: "" },
    busy: false, onClick: () => {},
  });
  assert.equal(visibleText(markup).trim(), "Materialize manifest");
});

// ── item 8: "3 Deferred to sandboxs" ─────────────────────────────────────────

test("r9-8: every tier pluralizes as English rather than by appending s", () => {
  const plurals = ["blocker", "warning", "advice", "pending_sandbox"]
    .map((tier) => visibleText(render(Badge, { tier, n: 3 })).trim());
  for (const text of plurals) {
    assert.ok(!/sandboxs|Advices/.test(text), text);
    assert.match(text, /^\S+ 3 /, text);
  }
  assert.deepEqual(plurals, ["⛔ 3 Blockers", "⚠ 3 Warnings", "ℹ 3 Advice",
                             "⏳ 3 Deferred to sandbox"]);
});

test("r9-8: singulars are unchanged", () => {
  const singulars = ["blocker", "warning", "advice", "pending_sandbox"]
    .map((tier) => visibleText(render(Badge, { tier, n: 1 })).trim());
  assert.deepEqual(singulars, ["⛔ 1 Blocker", "⚠ 1 Warning", "ℹ 1 Advice",
                               "⏳ 1 Deferred to sandbox"]);
});

test("r10-ux-f7: the badge has no aria-label — the text IS the label", () => {
  // R9-8's version of this test asserted the aria-label EQUALLED the visible text,
  // because it used to be the singular at every count ("3 Blocker" heard, "3 Blockers"
  // read). Deriving one from the other stopped them disagreeing and left the real
  // problem: on a plain <span> whose text already reads correctly, an aria-label is not
  // a clarification, it REPLACES the text for the reader that uses it. Two spellings of
  // one fact, which is §F9's rule broken in a quieter way; the fix for two spellings is
  // one spelling.
  for (const tier of ["blocker", "warning", "advice", "pending_sandbox"]) {
    for (const n of [1, 2, 3]) {
      const markup = render(Badge, { tier, n });
      assert.ok(!/aria-label/.test(markup), `${tier} n=${n}: ${markup}`);
      // …and what remains still carries the count and the correctly-formed word, which
      // is the property R9-8 was defending.
      assert.match(visibleText(markup).trim(), new RegExp(`^\\S+ ${n} \\S`));
    }
  }
});

// ── R10-UX-F1: "✓ clean" for a project nobody has scanned ────────────────────
//
// The project LIST row had no render pin at all — this file covered the panel and the
// badges and stopped at the left column. And the left column carries the same defect
// R9-5 fixed in the panel: `Object.values(p.tiers).every((n) => n === 0)` is true for a
// project whose `scan_report` is `{}`, so `orders-api` rendered
//
//     orders-api  ✓ clean  never scanned
//
// one column away from a panel reading "⏳ Not scanned yet — this project has no
// readiness report, which is not the same as having nothing to report." Two panels, one
// screen, opposite claims — R9-5's own sentence, in the half of the screen it did not
// reach.
//
// `scanned_at` is the discriminator here for R9-5's reason: it is the one field that
// says a scan happened, and zero tiers cannot tell "nothing found" from "nothing
// looked".

test("r10-ux-f1: an unscanned project's row does not read as clean", async () => {
  const { data: projects } = await (SIM_FIXTURES.degraded as any)("v1/projects/");
  const orders = projects.find((p: any) => p.name === "orders-api");
  assert.equal(orders.scanned_at, null);
  assert.ok(Object.values(orders.tiers).every((n) => n === 0));

  const text = visibleText(render(ProjectRow, { project: orders }));

  assert.ok(!text.includes("clean"),
    `a project no scanner has read is not clean: ${text}`);
  assert.ok(text.includes("not scanned"), text);
});

test("r10-ux-f1: a scanned project with nothing to report still reads as clean", async () => {
  const { data: projects } = await (SIM_FIXTURES.live as any)("v1/projects/");
  const takko = projects.find((p: any) => p.name === "takko");
  assert.ok(takko.scanned_at);

  const text = visibleText(render(ProjectRow, { project: takko }));

  assert.ok(text.includes("✓ clean"), text);
});

test("r10-ux-f1: a project with findings shows its badges and no clean tick", async () => {
  const { data: projects } = await (SIM_FIXTURES.live as any)("v1/projects/");
  const legacy = projects.find((p: any) => p.name === "legacy-shop");

  const text = visibleText(render(ProjectRow, { project: legacy }));

  assert.ok(!text.includes("clean"), text);
  assert.match(text, /⛔ \d+ Blocker/, text);
});

test("r10-ux-f1: the row renders each site's manifest currency", async () => {
  const { data: projects } = await (SIM_FIXTURES.live as any)("v1/projects/");
  const takko = projects.find((p: any) => p.name === "takko");

  const text = visibleText(render(ProjectRow, { project: takko }));

  for (const site of takko.sites) {
    assert.ok(text.includes(site.name), site.name);
    assert.ok(site.latest_manifest_version == null
      ? text.includes("no manifest yet")
      : text.includes(`manifest v${site.latest_manifest_version}`), text);
  }
});

// ── R10-UX-F6: consent to an empty set ───────────────────────────────────────
//
// The ack checkbox rendered whatever `state.warnings` held. On a clean project it read
// "I have read the warnings above and accept them" with no warnings anywhere on screen,
// and ticking it sent `confirm_warnings: true` to a server that had asked for nothing —
// training the operator to tick it, which is precisely the habit the one screen that
// DOES gate on it needs them not to have.

test("r10-ux-f6: no warnings, no checkbox", async () => {
  const { data: wizard } = await (SIM_FIXTURES.live as any)("v1/sites/1/wizard/");
  assert.deepEqual(wizard.warnings, []);

  assert.equal(render(WarningsAck, { warnings: wizard.warnings, checked: false }), "");
});

test("r10-ux-f6: with warnings, the checkbox names them", async () => {
  // atlas-edge/prod: the only §F8 site that clears preflight and still carries
  // warnings, which is the whole reason this control exists.
  const { data: wizard } = await (SIM_FIXTURES.live as any)("v1/sites/3/wizard/");
  assert.ok(wizard.warnings.length >= 1, JSON.stringify(wizard.warnings));

  const text = visibleText(render(WarningsAck,
    { warnings: wizard.warnings, checked: false }));

  for (const w of wizard.warnings) {
    assert.ok(text.includes(w.title), `${w.title} is not named beside the consent`);
  }
  assert.ok(text.includes("accept"), text);
});

test("r10-ux-f6: one warning is not addressed as several", () => {
  const text = visibleText(render(WarningsAck, {
    warnings: [{ id: "node-ts.symlinked-files", title: "Symlinked files were not read" }],
    checked: false,
  }));
  assert.ok(text.includes("this warning") && text.includes("accept it"), text);
});

// ── R10-UX-F7 / F8: a refusal nobody is told about, worded for the wrong cause ─

test("r10-ux-f7: the disabled button points at its own visible reason", () => {
  const detail = "this project has not been scanned yet";
  const markup = render(MaterializeControl, {
    gate: { disabled: true, label: "Scan required", title: detail },
    busy: false, onClick: () => {}, id: "site-5-materialize",
  });

  const describedBy = markup.match(/aria-describedby="([^"]*)"/)?.[1];
  assert.ok(describedBy, "the reason is a paragraph after a button and nothing says so");
  assert.ok(markup.includes(`id="${describedBy}"`),
    "aria-describedby names an element that is not on the page");
  // …and the reason it points AT is the server's sentence, still rendered visibly.
  assert.ok(visibleText(markup).includes(detail));
});

test("r10-ux-f7: an enabled control describes nothing", () => {
  const markup = render(MaterializeControl, {
    gate: { disabled: false, label: "Materialize manifest", title: "" },
    busy: false, onClick: () => {}, id: "site-1-materialize",
  });
  assert.ok(!/aria-describedby/.test(markup), markup);
});

test("r10-ux-f7: two sites' controls do not point at one reason", () => {
  const gate = { disabled: true, label: "⛔ Blocked", title: "blockers present" };
  const ids = ["site-1-materialize", "site-2-materialize"].map((id) =>
    render(MaterializeControl, { gate, busy: false, onClick: () => {}, id })
      .match(/aria-describedby="([^"]*)"/)?.[1]);

  assert.equal(new Set(ids).size, 2,
    "one id for every site's control points every button at the first one's reason");
});

test("r10-ux-f7: the outcome region is a live region that is always present", () => {
  // Always present, not mounted with its message: screen readers announce CHANGES to an
  // existing live region, so a region that appears carrying its text announces nothing.
  const empty = render(OutcomeRegion, { msg: null });
  assert.match(empty, /role="status"/);
  assert.match(empty, /aria-live="polite"/);
  assert.equal(visibleText(empty), "");

  for (const msg of [{ ok: true, text: "Saved." },
                     { ok: false, text: "site.domain: not a domain" },
                     { problems: [{ code: "warnings_unconfirmed", detail: "d" }] }]) {
    const markup = render(OutcomeRegion, { msg });
    assert.match(markup, /role="status"/, JSON.stringify(msg));
    assert.ok(visibleText(markup).length > 0, JSON.stringify(msg));
  }
});

test("r10-ux-f8: the re-read sentence does not claim an answer was given", async () => {
  // atlas-edge's real `warnings_unconfirmed` refusal: the operator pressed Materialize
  // and answered nothing, and the panel told them the form had been re-read "after this
  // answer".
  const { status, data } = await (SIM_FIXTURES.live as any)("v1/sites/3/manifest/", {});
  assert.equal(status, 409);
  assert.equal(data.code, "warnings_unconfirmed");

  const text = visibleText(render(OutcomeRegion,
    { msg: { problems: data.problems || [data] } }));

  assert.ok(text.includes("re-read from the server"), text);
  assert.ok(!text.includes("after this answer"),
    "this refusal is reachable with no answer given at all");
});

// ── R11-UX-F2: two wizards on one page, one set of DOM ids ───────────────────

test("r11-ux-f2: a question's input id is per SITE, and the label points at its own",
  () => {
    const question = { id: "site.domain", prompt: "Public domain for this site",
                       kind: "domain", default: null, choices: [], secret: false };
    const markups = [1, 4].map((siteId) =>
      render(QuestionField, { siteId, question, prior: undefined,
                              drafted: undefined, onChange: () => {} }));

    const ids = markups.map((m) => m.match(/ id="([^"]+)"/)![1]);
    assert.deepEqual(ids, ["site-1-site.domain", "site-4-site.domain"]);
    for (const markup of markups) {
      const forAttr = markup.match(/for="([^"]+)"/)![1];
      const idAttr = markup.match(/ id="([^"]+)"/)![1];
      assert.equal(forAttr, idAttr,
        "the label points somewhere other than its own field");
    }
  });

test("r11-ux-f2: a two-site project page has no duplicate ids at all", async () => {
  // The page that produced the defect: takko, whose two sites are asked the same
  // questions, so every id in one wizard had a twin in the other. `getElementById` and
  // every `<label for>` resolve to the FIRST match, so clicking staging's domain label
  // focused prod's box and the typing went into the wrong site's form.
  const { data: prod } = await (SIM_FIXTURES.live as any)("v1/sites/1/wizard/");
  const { data: staging } = await (SIM_FIXTURES.live as any)("v1/sites/4/wizard/");

  const ids: string[] = [];
  for (const [siteId, state] of [[1, prod], [4, staging]] as Array<[number, any]>) {
    for (const question of state.questions) {
      const markup = render(QuestionField, { siteId, question,
                                             prior: state.answered?.[question.id],
                                             drafted: undefined, onChange: () => {} });
      ids.push(...[...markup.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]));
    }
    // The other id-bearing control in the same wizard, rendered the way `SiteWizard`
    // renders it — the `aria-describedby` target R10-UX-F7 added, which was already
    // per-site and is where the naming rule this fix follows came from.
    const control = render(MaterializeControl, {
      gate: { disabled: true, label: "⛔ Blocked", title: "the report has blockers" },
      busy: false, onClick: () => {}, id: questionFieldId(siteId, "materialize"),
    });
    ids.push(...[...control.matchAll(/ id="([^"]+)"/g)].map((m) => m[1]));
  }
  assert.ok(ids.length >= 8, `the fixture stopped asking questions: ${ids.length}`);
  assert.equal(new Set(ids).size, ids.length,
    `duplicate ids on one page: ${ids.filter((v, i) => ids.indexOf(v) !== i)}`);
});

// ── R11-UX-F4: a row that called itself a button ─────────────────────────────

test("r11-ux-f4: Enter and Space both activate the row, and Space does not scroll", () => {
  const pressed: string[] = [];
  let prevented = 0;
  const handler = rowKeyHandler(() => pressed.push("selected"));
  const press = (key: string) =>
    handler({ key, preventDefault: () => { prevented += 1; } } as any);

  press("Enter");
  press(" ");
  assert.deepEqual(pressed, ["selected", "selected"],
    "Space is the key most people press on something that says role=button");
  assert.equal(prevented, 2,
    "Space scrolls the page unless the handler says otherwise — which is what it did");

  press("a");
  press("Tab");
  assert.equal(pressed.length, 2, "typing must not select a project");
});

test("r11-ux-f4: the selected row says so in aria and in something other than colour",
  async () => {
    const { data: projects } = await (SIM_FIXTURES.live as any)("v1/projects/");
    const on = render(ProjectRowSelector,
      { project: projects[0], selected: true, onSelect: () => {} });
    const off = render(ProjectRowSelector,
      { project: projects[0], selected: false, onSelect: () => {} });

    assert.match(on, /aria-pressed="true"/);
    assert.match(off, /aria-pressed="false"/,
      "a role=button with no pressed state tells a screen reader nothing about selection");
    assert.match(on, /role="button"/);
    assert.match(on, /tabindex="0"/);

    // The non-colour half. `outline` was the whole signal, which is a colour, and §F9's
    // rule is that status is never colour-only — state is no different.
    const marker = /▸/;
    assert.match(on, marker);
    assert.ok(!marker.test(off), "the unselected row carries the selection marker");
    assert.equal(visibleText(on).replace("▸", "").trim(), visibleText(off).trim(),
      "the marker is the ONLY text the selection adds — anything else here would be a " +
      "second signal, and the row's content is the project's own row");
  });

// ── R11-UX-F5: a disabled button that looked exactly like a live one ─────────

test("r11-ux-f5: a disabled control is visibly disabled", () => {
  const blocked = { disabled: true, label: "⛔ Blocked", title: "the report has blockers" };
  const ready = { disabled: false, label: "Materialize manifest", title: "" };

  const off = render(MaterializeControl, { gate: blocked, busy: false, onClick: () => {} });
  const on = render(MaterializeControl, { gate: ready, busy: false, onClick: () => {} });

  const style = (markup: string) => markup.match(/style="([^"]*)"/)![1];
  assert.notEqual(style(off), style(on),
    "an inline style= overrides the browser's :disabled rendering, so a disabled " +
    "button drawn from the same object is pixel-identical to a live one");
  assert.match(style(off), /cursor:not-allowed/);
  assert.match(style(off), /color:#6e7681/);
  assert.match(off, /disabled=""/);

  // …and `busy` disables it too — a request in flight is the other way this button
  // stops taking clicks, and it wore the live styling for the whole round trip.
  const busy = render(MaterializeControl,
    { gate: ready, busy: true, onClick: () => {} });
  assert.equal(style(busy), style(off),
    "a button disabled because a request is in flight still looks pressable");
});

// ── R12-F12-2: what the report is a report OF ────────────────────────────────

test("f12-2: the scope line names the modules that ran and counts every tier", async () => {
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/2/readiness/");
  const text = visibleText(render(ReportScope, { report }));

  for (const module of report.modules) assert.ok(text.includes(module), module);
  // Every tier the payload counted, in reading order, with the singular/plural this
  // screen already uses for its section headings.
  assert.ok(text.includes(`${report.summary.blocker} Blockers`), text);
  assert.ok(text.includes(`${report.summary.warning} Warnings`), text);
  assert.ok(text.includes(`${report.summary.advice} Advice`), text);
  assert.ok(text.includes(`${report.summary.pending_sandbox} Deferred to sandbox`), text);
  assert.ok(text.includes(`${report.summary.ok} OK`), text);
  assert.equal(text.indexOf("Blockers") < text.indexOf("OK"), true,
    "the tiers read in tier order, not in whatever order the payload's keys arrive in");
});

test("f12-2: the CLEAN report says how much passed, which was the point", async () => {
  // "✓ No findings" over a suite that barely ran looks exactly like one that ran fully.
  // takko's report is ten `ok` checks and nothing else, and the panel showed neither
  // number nor module before this line existed.
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/1/readiness/");
  assert.deepEqual(report.blockers, []);

  const text = visibleText(render(ReportScope, { report }));

  assert.ok(text.includes(`${report.summary.ok} OK`), text);
  assert.ok(text.includes(report.modules[0]), text);
  for (const absent of ["Blockers", "Warnings", "Deferred"])
    assert.ok(!text.includes(absent), `a zero count is not a fact worth a word: ${text}`);
});

test("f12-2: a never-scanned report renders no scope line at all", async () => {
  // `modules: []` and `summary: {}` — there is nothing to say, and R9-5's whole finding
  // is that this screen must not imply a scan happened.
  const { data: report } = await (SIM_FIXTURES.degraded as any)("v1/projects/4/readiness/");
  assert.equal(render(ReportScope, { report }), "");
  assert.equal(render(ReportScope, { report: undefined }), "");
});

test("f12-2: the scope line claims nothing the payload does not say", async () => {
  // §4b applied to a line that is not a refusal: every word in it is either a payload
  // value or the tier vocabulary this screen already owns (TIER_BADGE, R9-8).
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/3/readiness/");
  const text = visibleText(render(ReportScope, { report }));
  const vocabulary = ["Scanned by", "·", ",", "Blocker", "Blockers", "Warning",
                      "Warnings", "Advice", "Deferred to sandbox", "OK"];

  // Longest first, or stripping "Warning" leaves the "s" of "Warnings" behind and the
  // test reports a defect it invented.
  const known = [...report.modules, ...Object.values(report.summary).map(String),
                 ...vocabulary].sort((a, b) => b.length - a.length);
  let residue = text;
  for (const word of known) residue = residue.split(word).join("");
  assert.equal(residue.trim(), "",
    `the line contains text from neither the payload nor TIER_BADGE: ${residue}`);
});

test("f12-2: and the panel actually renders it, under the heading", () => {
  // The component tests above prove the line is right; this one proves it is ON the
  // screen. `ReadinessPanel` fetches, so it cannot be rendered here — the same boundary
  // the F12-1 pins state, and the same remedy: read the source rather than pretend a
  // component test covers a wiring question.
  const source = readFileSync(new URL("../src/Readiness.jsx", import.meta.url), "utf-8");
  const panel = source.slice(source.indexOf("function ReadinessPanel("));
  const heading = panel.indexOf("Readiness — {project?.name}");
  const scope = panel.indexOf("<ReportScope report={report} />");

  assert.ok(scope > 0, "the panel renders no scope line at all");
  assert.ok(heading < scope && scope < panel.indexOf('kind === "clean"'),
    "the scope line belongs under the heading, above the findings it is the scope of");
});

// ── R12-F12-3 / F12-4: two controls that moved under the operator ────────────

test("f12-3: Save keeps its label while busy and says so with aria-busy", () => {
  const markup = render(SaveButton, { busy: true, disabled: true, onClick: () => {} });
  assert.match(markup, /aria-busy="true"/);
  assert.ok(visibleText(markup).includes("Save answers"),
    "the button lost its accessible name mid-action — it read “…”");
});

test("f12-3: Materialize announces busy the same way", () => {
  const ready = { disabled: false, label: "Materialize manifest", title: "" };
  assert.match(render(MaterializeControl, { gate: ready, busy: true, onClick: () => {} }),
    /aria-busy="true"/);
  assert.match(render(MaterializeControl, { gate: ready, busy: false, onClick: () => {} }),
    /aria-busy="false"/);
});

test("f12-4: the selection marker reserves its width in both states", async () => {
  const { data: projects } = await (SIM_FIXTURES.live as any)("v1/projects/");
  const on = render(ProjectRowSelector,
    { project: projects[0], selected: true, onSelect: () => {} });
  const off = render(ProjectRowSelector,
    { project: projects[0], selected: false, onSelect: () => {} });

  const marker = /<span aria-hidden="true" style="([^"]*)">/;
  assert.match(on, marker);
  assert.match(off, marker,
    "added only when selected, the marker shoves the project's name sideways on click");
  assert.equal(on.match(marker)![1], off.match(marker)![1],
    "the reserved box must be the same in both states or it reserves nothing");
  assert.match(on.match(marker)![1], /width:1.1em/);
});

// ── R12-ARCH-1: the guarded fact, on the screen ──────────────────────────────

test("arch-1: a check's refused_paths are rendered under it", () => {
  const markup = render(CheckBody, {
    check: { detail: "3 symlinked files resolve outside the scanned repository:",
             fix_hint: "commit the file itself",
             refused_paths: ["src/a.ts", "src/b.ts", "src/c.ts"] },
  });
  const text = visibleText(markup);

  assert.ok(text.includes("Did not read:"), text);
  for (const path of ["src/a.ts", "src/b.ts", "src/c.ts"])
    assert.ok(text.includes(path), `${path} is guarded and rendered nowhere: ${text}`);
  // One element per path: a filename may contain a comma or a newline, and a delimiter a
  // name can contain is a name that can forge two entries.
  assert.equal((markup.match(/<li>/g) || []).length, 3);
});

test("arch-1: a check with no refusals renders no list and no label", () => {
  const markup = render(CheckBody, { check: { detail: "d", fix_hint: "f" } });
  assert.ok(!visibleText(markup).includes("Did not read"), markup);
  assert.ok(!markup.includes("<ul"), markup);
});

test("arch-1: the rendered list composes no copy beyond its label", () => {
  // The F12-2 strip: everything on screen is a payload value or the one label this
  // component owns.
  const refused = ["packages/server/src/metrics.ts", "src/metri\\cs.ts"];
  const text = visibleText(render(CheckBody, { check: { refused_paths: refused } }));

  assert.ok(text.includes("Did not read:"), "nothing rendered — this strip is vacuous");
  let residue = text;
  for (const word of [...refused, "Did not read:"]) residue = residue.split(word).join("");
  assert.equal(residue.trim(), "", `the list says something the payload does not: ${text}`);
});

test("arch-1: the edge fixture's refusal renders the path the scanner guarded", async () => {
  // The real payload, through the real component: `node-ts.symlinked-files` on
  // atlas-edge carries the file its module took out of `core.symlinked-files`.
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/3/readiness/");
  const check = report.warnings.find((c: any) => c.id === "node-ts.symlinked-files");

  assert.ok(check.refused_paths?.length, "the fixture lost the field");
  const markup = render(CheckBody, { check });

  // Asserted on the LIST, not on the text: this module's detail quotes the same path
  // through `repr`, so a text search passes off the prose and proves nothing about the
  // field — which is the whole finding one layer down.
  assert.equal((markup.match(/<li>/g) || []).length, check.refused_paths.length);
  for (const path of check.refused_paths)
    assert.ok(markup.includes(`<li>${path}</li>`), path);
});

test("arch-a: refusals render from any tier, which is wider than the vouching rule", () => {
  // `scanner.core.ANNOUNCEMENT_TIERS` lets only a blocker or a warning VOUCH for a
  // refusal, because vouching deletes another check's line. Rendering deletes nothing, so
  // it is deliberately permissive: a stored report from another version — or a check
  // family that grows the field later — shows its refusals here whatever tier it chose.
  // A screen that dropped the list because the tier was not one of two would be hiding
  // something the report contains.
  for (const tier of ["ok", "advice", "pending_sandbox"]) {
    const text = visibleText(render(CheckBody, {
      check: { tier, detail: "everything looks fine",
               refused_paths: ["src/unread.ts"] },
    }));
    assert.ok(text.includes("src/unread.ts"), `${tier}: ${text}`);
  }
});

// ── R13-F13-1: repo-controlled text that cannot be broken ────────────────────

test("f13-1: a check body wraps the repository's own unbreakable tokens", () => {
  // The panel renders three kinds of repo-controlled text with no spaces in them: a
  // detail's `file:line` findings, a fix hint quoting a path, and the `refused_paths`
  // list — which is unbounded by design, because a machine-readable list that truncated
  // would be the prose it exists to replace. One deep monorepo path is one token wider
  // than the box.
  const deep = "packages/a-rather-long-package-name/src/features/telemetry/collectors/"
    + "runtime/metrics.ts";
  assert.ok(deep.length > 80, deep.length);

  const markup = render(CheckBody, {
    check: { detail: `${deep}:14: hardcoded secret`, fix_hint: `edit ${deep}`,
             refused_paths: [deep] },
  });

  // Every element that can contain one of those tokens says how to break it.
  assert.equal((markup.match(/overflow-wrap:anywhere/g) || []).length, 3,
    "detail, fix hint and the refusal list each carry repo-controlled text");
  assert.ok(visibleText(markup).includes(deep));
});

test("f13-1: the wrap rule travels with PRE_LINE, so both paragraphs have it", () => {
  const markup = render(CheckBody, { check: { detail: "d", fix_hint: "f" } });
  assert.equal((markup.match(/white-space:pre-line/g) || []).length, 2);
  assert.equal((markup.match(/overflow-wrap:anywhere/g) || []).length, 2,
    "a paragraph that honours the server's newlines must also break its long tokens");
});

// ── R13-F13-2: a button that disables itself under the operator's finger ─────

test("f13-2: while busy the control stays focusable and says aria-disabled", () => {
  const ready = { disabled: false, label: "Materialize manifest", title: "" };
  const markup = render(MaterializeControl, { gate: ready, busy: true,
                                              onClick: () => {} });

  assert.ok(!markup.includes("disabled=\"\""),
    "a disabled element cannot hold focus, so the press evicts the keyboard from the " +
    "button that was pressed and nothing puts it back");
  assert.match(markup, /aria-disabled="true"/);
  assert.match(markup, /aria-busy="true"/,
    "…and the busy state is announced on an element the reader is still on");
});

test("f13-2: a gate refusal is still hard-disabled", () => {
  // The other reason to be dead, and it keeps the old treatment: nothing was pressed, no
  // focus is being held, and an action the server refuses belongs out of the tab order.
  const blocked = { disabled: true, label: "⛔ Blocked", title: "the report has blockers" };
  const markup = render(MaterializeControl, { gate: blocked, busy: false,
                                              onClick: () => {} });

  assert.match(markup, /disabled=""/);
  assert.ok(!markup.includes("aria-disabled"),
    "aria-disabled beside a real disabled attribute is two spellings of one fact");
});

test("f13-2: Save splits the same two reasons the same way", () => {
  const busy = render(SaveButton, { busy: true, disabled: false, onClick: () => {} });
  assert.ok(!busy.includes("disabled=\"\""), busy);
  assert.match(busy, /aria-disabled="true"/);

  // Nothing typed yet: there is nothing to save and nobody pressed anything.
  const empty = render(SaveButton, { busy: false, disabled: true, onClick: () => {} });
  assert.match(empty, /disabled=""/);
  assert.ok(!empty.includes("aria-disabled"), empty);
});

test("f13-2: an aria-disabled button is still clickable, so the click is guarded", () => {
  // That is the whole cost of the pattern: the browser stops enforcing the refusal, so
  // the component has to. A second press mid-request would send a second POST — and the
  // simulation's own answer to that is "[sim] NOT COVERED: a second materialize".
  const pressed: string[] = [];
  let prevented = 0;
  const event = { preventDefault: () => { prevented += 1; } } as any;

  busyClickGuard(true, () => pressed.push("sent"))(event);
  assert.deepEqual(pressed, [], "the request in flight was joined by a second one");
  assert.equal(prevented, 1);

  busyClickGuard(false, () => pressed.push("sent"))(event);
  assert.deepEqual(pressed, ["sent"], "…and an idle button still works");
  assert.equal(prevented, 1);
});

test("f13-2: the busy styling is unchanged by the swap", () => {
  // R11-UX-F5's pin, re-asserted through the new arrangement: whichever attribute carries
  // the refusal, a control that cannot be used must not look pressable.
  const ready = { disabled: false, label: "Materialize manifest", title: "" };
  const style = (markup: string) => markup.match(/style="([^"]*)"/)![1];

  assert.equal(
    style(render(MaterializeControl, { gate: ready, busy: true, onClick: () => {} })),
    style(render(MaterializeControl, {
      gate: { disabled: true, label: "⛔ Blocked", title: "t" }, busy: false,
      onClick: () => {} })));
});
