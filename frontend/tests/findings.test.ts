// UX-F2-FINDING-MODEL, UI half: the inbox is a filtered view of the Finding
// model Task 4 already serves at /api/v1/findings/. Severity is never colour
// alone; accept-risk will not POST without a reason; ack does not drop the
// row; FindingDetail stays one of the three §F6 phone-width screens.
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };
(globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

import {
  FindingDetail, FindingsView, SeverityChip,
  acceptRisk, ackFinding, reasonIsValid,
} from "../src/screens/Findings.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

const OPEN = {
  id: 7,
  source_engine: "uptime",
  severity: "p1",
  entity: "site:takko/prod",
  title: "takko/prod is down",
  body: "Three consecutive probes failed; visitors see connection errors.",
  fix_action: "Check docker ps on the target; restart the container.",
  state: "open",
  fingerprint: "fp-takko-down",
  accepted_reason: "",
  first_seen: "2026-08-22T00:00:00Z",
  last_seen: "2026-08-22T01:00:00Z",
};

test("accept_risk_requires_a_reason", async () => {
  // What would make this fail: the Accept-risk control POSTing with a blank
  // reason, or an accepted row rendering without the reason on the grey chip.
  assert.equal(reasonIsValid(""), false);
  assert.equal(reasonIsValid("   \t"), false);
  assert.equal(reasonIsValid("dev-only; downtime is acceptable"), true);

  const markup = render(FindingsView, {
    phase: "live", findings: [OPEN], onNav: () => {},
  });
  const text = visibleText(markup);
  assert.match(text, /Accept risk/i, text);
  assert.match(markup, /disabled/,
    "accept-risk must be unusable until a reason is typed");

  const calls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: JSON.parse(opts.body) });
    return { status: 200, json: async () => ({ seq: 1, data: OPEN }) };
  };

  const refused = await acceptRisk(OPEN.id, "  ");
  assert.equal(calls.length, 0, "a blank reason must never hit the transition API");
  assert.equal(refused.status, 400);
  assert.ok(refused.data.errors?.reason, refused);

  const reason = "dev-only; downtime is acceptable";
  await acceptRisk(OPEN.id, reason);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/v1/findings/7/transition/");
  assert.equal(calls[0].body.action, "accept_risk");
  assert.equal(calls[0].body.reason, reason);

  const accepted = { ...OPEN, state: "accepted", accepted_reason: reason };
  const chip = visibleText(render(FindingsView, {
    phase: "live", findings: [accepted], onNav: () => {},
  }));
  assert.match(chip, /accepted/i, chip);
  assert.ok(chip.includes(reason), chip);
});

test("severity_is_never_colour_only", () => {
  // What would make this fail: a chip that is only a coloured box / swatch,
  // with no symbol and no "p1"/"p2"/"p3" word the operator can read.
  for (const severity of ["p1", "p2", "p3"] as const) {
    const markup = render(SeverityChip, { severity });
    const text = visibleText(markup);
    assert.match(text, new RegExp(severity, "i"),
      `${severity} chip has no readable label: ${text}`);
    assert.match(markup, /aria-label|⛔|⚠|ℹ|●|◆|■/,
      `${severity} chip has no icon/symbol — colour alone is not enough`);
  }

  const inbox = visibleText(render(FindingsView, {
    phase: "live",
    findings: [
      { ...OPEN, id: 1, severity: "p1", title: "P1 row" },
      { ...OPEN, id: 2, severity: "p2", title: "P2 row" },
      { ...OPEN, id: 3, severity: "p3", title: "P3 row" },
    ],
    onNav: () => {},
  }));
  assert.match(inbox, /p1/i);
  assert.match(inbox, /p2/i);
  assert.match(inbox, /p3/i);
});

test("ack_does_not_remove_the_finding_from_the_inbox", async () => {
  // What would make this fail: ack filtering the row out of the default inbox,
  // or the helper issuing delete / resolve instead of ack.
  const acked = { ...OPEN, state: "acked" };
  const markup = render(FindingsView, {
    phase: "live", findings: [acked], onNav: () => {},
  });
  const text = visibleText(markup);
  assert.ok(text.includes(OPEN.title),
    `acked finding vanished from the inbox: ${text}`);
  assert.match(text, /acked/i, text);

  const calls: Array<{ url: string; body: any }> = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    calls.push({ url, body: JSON.parse(opts.body) });
    return { status: 200, json: async () => ({ seq: 2, data: acked }) };
  };
  await ackFinding(OPEN.id);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "/api/v1/findings/7/transition/");
  assert.equal(calls[0].body.action, "ack");
});

test("finding_detail_renders_at_phone_width", () => {
  // What would make this fail: a min/width wider than 390 px, no max-width
  // yield, or the §6.6 what/why/exact-fix fields not actually on screen.
  const finding = {
    id: 7,
    title: "Unproxied site cannot be issued a certificate",
    severity: "p1",
    entity: "site:takko/prod",
    body: "takko/prod is public and unproxied; Hub-central DNS-01 is not built.",
    fix_action: "Proxy the site through Cloudflare, or wait for Phase 4's DNS-01.",
    state: "open",
    fingerprint: "fp-unproxied",
  };
  const markup = render(FindingDetail, { finding, onBack: () => {} });
  const text = visibleText(markup);
  assert.ok(text.includes(finding.title), text);
  assert.ok(text.includes(finding.body), text);
  assert.ok(text.includes("Proxy the site through Cloudflare"), text);
  assert.ok(text.includes("DNS-01"), text);
  for (const m of markup.matchAll(/(?:min-)?width:(\d+)px/g)) {
    assert.ok(Number(m[1]) <= 390,
      `finding-detail claims a ${m[0]} — wider than the phone it is scoped to`);
  }
  assert.match(markup, /max-width:100%/,
    "finding-detail does not yield to a narrow viewport");
});
