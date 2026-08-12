// R8-1: the Materialize control's decision, as a pure function you can look at.
//
// The defect this pins: the button was gated on `hasBlockers` — derived from the
// stored scan report — while the server gates the POST on `preflight`. A declaration
// accepted in the wizard clears preflight and never rewrites the report (that is
// pinned by test_issue_r7_1r_a_re_scan_that_changes_nothing_keeps_the_acceptance), so
// the report kept a blocker-tier check forever and the only control that can reach
// `POST v1/sites/{id}/manifest/` stayed disabled, under a tooltip telling the operator
// to re-scan — the one operation proven to change nothing.
//
// SPEC §4b, the second half of the same defect: the FIRST remedy keyed "answer this"
// on `answers_missing`, a shape preflight never produces for a pending declaration —
// it emits `blockers_present` with an `awaiting_acceptance` list, and appends the true
// clause to its own detail ("…which you clear by answering its confirm in this wizard,
// not by changing the repo"). The correct copy was in the payload and the client threw
// it away for a hardcoded string. Hence the rule these tests enforce: NEVER HARDCODE A
// REFUSAL STRING THE SERVER ALREADY SENDS. Both disabled rows take their tooltip from
// `state.blocking`; only the label is the client's.
//
// Every `blocking` payload below is copied verbatim from a real `preflight` run — see
// the commit message for the command that produced each one.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { materializeGate } from "../src/Readiness.jsx";

const CONFIRM = "scanner.test_material.frontend-scripts-drill--a38574e34e643d90";
const CONFIRM_PROMPT =
  "This repo declares `frontend/scripts/drill` as test material — \"red-team / QA " +
  "drill scripts; deliberate fake credentials\". Accept that claim? Until you do, the " +
  "heuristic secret findings under that path BLOCK the deploy like any other; " +
  "accepting reports them without blocking. Published credential formats and .env " +
  "files there block either way; refusing is recorded in the manifest, and editing " +
  "the path or the reason brings this question back.";

// preflight's detail when at least one blocking check is awaiting an acceptance. The
// clause after the dash is the server telling the operator the truth the old client
// tooltip denied.
const AWAITING_DETAIL =
  "the readiness report has blockers; these must be fixed and the project re-scanned " +
  "— except where a declaration is awaiting acceptance, which you clear by answering " +
  "its confirm in this wizard, not by changing the repo";
const PLAIN_DETAIL =
  "the readiness report has blockers; these must be fixed and the project re-scanned";
const MISSING_DETAIL = "required questions are unanswered";

const PENDING_ITEM = {
  id: "core.secret-scan",
  title: "Secrets in a declared tree — your acceptance is required",
  awaiting_acceptance: [{ id: CONFIRM, prompt: CONFIRM_PROMPT }],
};
const HARD_ITEMS = [
  { id: "django.secret-key-literal", title: "Secret material is a literal in source" },
  { id: "django.debug-on", title: "DEBUG is on in prod settings" },
];

test("r8-1: can_materialize enables the button even though the report still carries a blocker-tier check", () => {
  // The wizard state the server returns once the declaration confirm is answered true:
  // preflight is empty, so the POST would succeed — while `readiness.blockers` still
  // holds `core.secret-scan`, because an answer never rewrites a scan report. On
  // ffec190 the button read that report and stayed disabled forever.
  const gate = materializeGate({ can_materialize: true, blocking: [] });
  assert.equal(gate.disabled, false);
  assert.equal(gate.label, "Materialize manifest");
  assert.equal(gate.title, "");
});

// §4b's regression case. This is the shape preflight really returns for a declaration
// the operator has answered but not accepted: `blockers_present` carrying
// `awaiting_acceptance`, and NO `answers_missing` — the question is answered, the claim
// is refused. The first remedy keyed on `answers_missing` and so rendered "⛔ Blocked /
// Blockers must be fixed and rescanned first" here: false, and false in exactly the
// case R8-1 exists to remove.
test("r8-1: a blocker that only an answer can clear says Answer required, in the server's own words", () => {
  const gate = materializeGate({
    can_materialize: false,
    blocking: [{ code: "blockers_present", detail: AWAITING_DETAIL, items: [PENDING_ITEM] }],
  });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "Answer required");
  assert.match(gate.title, /not by changing the repo/);
  // The whole tooltip is the server's, character for character.
  assert.equal(gate.title, AWAITING_DETAIL);
});

test("r8-1: the same blocker before the question is answered at all", () => {
  // preflight adds `answers_missing` for the unanswered confirm; still nothing hard.
  const gate = materializeGate({
    can_materialize: false,
    blocking: [
      { code: "blockers_present", detail: AWAITING_DETAIL, items: [PENDING_ITEM] },
      { code: "answers_missing", detail: MISSING_DETAIL,
        items: [{ id: CONFIRM, prompt: CONFIRM_PROMPT }] },
    ],
  });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "Answer required");
  assert.equal(gate.title, `${AWAITING_DETAIL} · ${MISSING_DETAIL}`);
});

test("r8-1: mixed — one blocker an answer clears, two it never will — is blocked", () => {
  const gate = materializeGate({
    can_materialize: false,
    blocking: [
      { code: "blockers_present", detail: AWAITING_DETAIL,
        items: [...HARD_ITEMS, PENDING_ITEM] },
      { code: "answers_missing", detail: MISSING_DETAIL,
        items: [{ id: CONFIRM, prompt: CONFIRM_PROMPT },
                { id: "site.domain", prompt: "Public domain for this site (e.g. app.example.com)" }] },
    ],
  });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "⛔ Blocked");
  assert.equal(gate.title, `${AWAITING_DETAIL} · ${MISSING_DETAIL}`);
});

test("r8-1: a blocker no answer can clear is blocked, in the server's own words", () => {
  const gate = materializeGate({
    can_materialize: false,
    blocking: [{ code: "blockers_present", detail: PLAIN_DETAIL, items: HARD_ITEMS }],
  });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "⛔ Blocked");
  assert.equal(gate.title, PLAIN_DETAIL);
});

test("r8-1: a refusal code this UI has never seen still disables and shows its detail", () => {
  const gate = materializeGate({
    can_materialize: false,
    blocking: [{ code: "scan_required", detail: "this project has not been scanned yet", items: [] }],
  });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "⛔ Blocked");
  assert.equal(gate.title, "this project has not been scanned yet");
});

// §4b.4. The rule, enforced rather than remembered: the client authors no refusal copy.
//
// THE FILE SET IS DERIVED, NOT TYPED. A hand-typed list is R4-12's class — the Makefile
// says so in as many words above `PY_ROOTS`, which exists because `wizard/` landed and
// two hand-typed gate lists both missed it. A reviewer defeated the typed version of
// this pin in one move: a new `src/Deploys.jsx` carrying the verbatim old tooltip passed
// all seven tests. Walking the tree means the next module is inside the pin the moment
// it exists, which is the only version of this rule worth having.
//
// Two exclusions, both narrow and both for a stated reason:
//   src/sim.js  — a TRANSCRIPT of server responses, not client copy. Its refusal strings
//                 are `preflight`'s own, copied verbatim on purpose; a fixture that
//                 dodged the server's wording to satisfy a grep would be the exact
//                 fiction §4b was filed about.
//   src/api/    — generated from the serializers by `make generate-client`; nothing is
//                 authored there and `make check-generated` owns it.
function clientSources(dir = fileURLToPath(new URL("../src", import.meta.url)), rel = "") {
  const found: Array<[string, string]> = [];
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    const here = rel ? `${rel}/${entry.name}` : entry.name;
    if (here === "sim.js" || here === "api") continue;
    if (entry.isDirectory()) found.push(...clientSources(join(dir, entry.name), here));
    else if (/\.(jsx?|tsx?)$/.test(entry.name))
      found.push([here, readFileSync(join(dir, entry.name), "utf8")]);
  }
  return found;
}

test("r8-1: no client module authors a refusal string the server already sends", () => {
  const sources = clientSources();
  // The walk itself is load-bearing: an empty or truncated one would pass silently.
  assert.ok(sources.length >= 4, `only walked ${sources.length} client modules`);
  assert.ok(sources.some(([name]) => name === "Readiness.jsx"),
    "the walk missed Readiness.jsx, which is the file this rule is about");
  for (const [name, src] of sources) {
    assert.ok(!/rescanned|re-scanned/.test(src),
      `${name} spells out a refusal the server sends — take the tooltip from state.blocking`);
    assert.ok(!/readiness report has blockers/.test(src), `${name}: same`);
  }
});
