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
import { CheckBody, reportSummary } from "../src/Readiness.jsx";
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
