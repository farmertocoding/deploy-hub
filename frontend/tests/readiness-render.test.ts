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
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { Badge, CheckBody, MaterializeControl, reportSummary } from "../src/Readiness.jsx";
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

test("r9-8: the aria-label is what the badge says", () => {
  // It used to be the singular for every count — a screen reader heard "3 Blocker"
  // while the screen read "3 Blockers", which is §F9's rule broken in the one direction
  // that rule exists to prevent.
  for (const tier of ["blocker", "warning", "advice", "pending_sandbox"]) {
    for (const n of [1, 2, 3]) {
      const markup = render(Badge, { tier, n });
      const label = markup.match(/aria-label="([^"]*)"/)?.[1];
      assert.equal(label, visibleText(markup).trim().replace(/^\S+\s/, ""),
        `${tier} n=${n}: the label and the text disagree`);
    }
  }
});
