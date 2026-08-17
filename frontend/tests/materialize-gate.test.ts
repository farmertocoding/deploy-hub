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
// PROVENANCE, AND WHAT D-012 LEAVING PHASE 1 DID TO IT (2026-08-16). Every `blocking`
// payload below was copied verbatim from a real `preflight` run at the time it was
// written. Two of them — the ones carrying `awaiting_acceptance` — are now HISTORICAL:
// no scanner emits an acceptance contract and no `preflight` emits that item this
// phase, so those payloads record a shape the server produced before the cap decision
// and will produce again when the mechanism returns with its threat model. The spec
// keeps `materializeGate` unchanged on that basis, so its reading of them is kept
// exercised rather than deleted and re-derived later.
//
// The payloads that are live today — `blockers_present` with no awaiting list,
// `answers_missing`, `scan_required` — are what `preflight` sends now, and
// frontend/src/sim.js carries the current ones spliced from a fresh run.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { materializeGate, materializeOutcome } from "../src/Readiness.jsx";
import { SIM_FIXTURES } from "../src/sim.js";

// window shim: sim.js is a browser module, and two tests below drive the real §F8
// fixtures through the same two functions the screen calls.
(globalThis as any).window = { location: { search: "" } };

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
  // R10-UX-F5 moved `scan_required` to its own label, so the code here is one no
  // version of this gate has met — which is what the test was always about.
  const gate = materializeGate({
    can_materialize: false,
    blocking: [{ code: "schema_skew", detail: "this report predates the current schema", items: [] }],
  });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "⛔ Blocked");
  assert.equal(gate.title, "this report predates the current schema");
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

// R9-9: AND THE COPY IS DERIVED TOO, from the module that sends it.
//
// The file set has been walked since r8 for a stated reason — a hand-typed list is
// R4-12's class — and then the two strings decided the verdict were hand-typed, in the
// test whose own header says that is the defect. It cost what it always costs:
// `warnings_unconfirmed` ("the readiness report has warnings; confirm to proceed") was
// outside a pin that greps for `re-scanned` and `readiness report has blockers`, so a
// client could author the warnings gate's copy — the one control round-9 item 2 is
// about — and stay green.
//
// So the forbidden copy is read out of `wizard/materialize.py` at test time. Two anchors,
// because the module raises refusals in two shapes: the `"detail":` key of a `problems`
// entry, and the message argument of a direct `MaterializeRefused(...)` — the second is
// how the warnings gate raises, which is exactly the one the typed list missed. Adjacent
// string literals are joined, because that is what Python does with them.
//
// READ-ONLY, and no backend file is touched: this is a test reading a source file, the
// same way `clientSources` reads the client's.
const MATERIALIZE_PY = fileURLToPath(new URL("../../wizard/materialize.py", import.meta.url));

function serverRefusalCopy(): string[] {
  const source = readFileSync(MATERIALIZE_PY, "utf8");
  const anchor = /"detail":|MaterializeRefused\(\s*"(?:[^"\\]|\\.)*",/g;
  const literal = /\s*"((?:[^"\\]|\\.)*)"/y;
  const found = new Set<string>();
  for (const match of source.matchAll(anchor)) {
    let at = match.index! + match[0].length;
    const parts: string[] = [];
    for (;;) {
      literal.lastIndex = at;
      const piece = literal.exec(source);
      if (!piece) break;                    // e.g. `"detail": self.message`
      parts.push(piece[1]);
      at = literal.lastIndex;
    }
    if (parts.length) found.add(parts.join(""));
  }
  return [...found];
}

// Whole strings are not enough on their own: R8-1's actual defect was a PARAPHRASE
// ("Blockers must be fixed and rescanned first"), which no literal match catches. So the
// unit is a run of words. Normalising away hyphens and punctuation is what makes
// `rescanned` and `re-scanned` the same word, which is the case the typed pin had to
// spell out twice and this one gets for nothing.
const words = (text: string) =>
  text.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim().split(" ");
const RUN = 5;

test("r9-9: the forbidden copy is the server's own literals, not a list typed here", () => {
  const copy = serverRefusalCopy();
  // The extraction is load-bearing: a regex that matched nothing would make the pin below
  // pass forever, which is this test's own failure mode and the one it must not have.
  assert.ok(copy.length >= 5, `only extracted ${copy.length} refusal strings`);
  assert.ok(copy.some((s) => s === "required questions are unanswered"), copy);
  assert.ok(copy.some((s) => s.includes("has blockers")), copy);
  // The second anchor, named: this is the one a `"detail":`-only regex would miss, and it
  // is the copy behind the ack checkbox.
  assert.ok(copy.some((s) => s === "the readiness report has warnings; confirm to proceed"),
    `the MaterializeRefused(...) shape was not extracted: ${JSON.stringify(copy)}`);
  // …and the multi-line implicit concatenation Python joins for it.
  assert.ok(copy.some((s) => s.includes("must be fixed and the project re-scanned")), copy);
});

test("r8-1/r9-9: no client module authors a refusal the server already sends", () => {
  const sources = clientSources();
  // The walk itself is load-bearing: an empty or truncated one would pass silently.
  assert.ok(sources.length >= 4, `only walked ${sources.length} client modules`);
  assert.ok(sources.some(([name]) => name === "Readiness.jsx"),
    "the walk missed Readiness.jsx, which is the file this rule is about");

  const forbidden: Array<[string, string]> = [];
  for (const copy of serverRefusalCopy()) {
    const w = words(copy);
    for (let i = 0; i + RUN <= w.length; i++)
      forbidden.push([w.slice(i, i + RUN).join(" "), copy]);
  }
  assert.ok(forbidden.length >= 20, `only ${forbidden.length} phrases to check`);

  for (const [name, src] of sources) {
    const haystack = ` ${words(src).join(" ")} `;
    for (const [phrase, copy] of forbidden)
      assert.ok(!haystack.includes(` ${phrase} `),
        `${name} reproduces the server's refusal copy ("…${phrase}…", from ` +
        `"${copy}") — render state.blocking's own detail instead`);
  }
});

// ── round-9 item 3: the arm between "go" and "⛔ Blocked" ──────────────────────
//
// `preflight` refuses a fresh site for one reason: nobody has typed the domain. That is
// EVERY clean project's first screen, and the gate called it "⛔ Blocked" — the glyph
// this UI reserves for a blocker-tier finding, on a project whose report has none. The
// operator is told the repository is in trouble when the form is simply empty.
//
// `answers_need_reentry` joins it: preflight emits that when a stored plaintext answer
// has been reclassified as a secret and scrubbed, and the operator's action is the same
// one — type it here. Neither refusal is about the code, and neither survives a re-scan.
const REENTRY_DETAIL =
  "these values are now handled as secrets and must be entered again; the previously " +
  "stored plaintext has been deleted and should be rotated at the source";

test("r9-3: an unanswered question is not a blocker, and does not wear the glyph", () => {
  const gate = materializeGate({
    can_materialize: false,
    blocking: [{ code: "answers_missing", detail: MISSING_DETAIL,
                 items: [{ id: "site.domain", prompt: "Public domain for this site" }] }],
  });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "Answers needed");
  assert.ok(!gate.label.includes("⛔"),
    "the blocker glyph on a project with no blocker is the finding");
  assert.equal(gate.title, MISSING_DETAIL);
});

test("r9-3: a scrubbed answer is the same kind of refusal", () => {
  const gate = materializeGate({
    can_materialize: false,
    blocking: [
      { code: "answers_need_reentry", detail: REENTRY_DETAIL,
        items: [{ id: "django.env.DB_PASSWORD", prompt: "Value for DB_PASSWORD" }] },
      { code: "answers_missing", detail: MISSING_DETAIL,
        items: [{ id: "site.domain", prompt: "Public domain for this site" }] },
    ],
  });
  assert.equal(gate.label, "Answers needed");
  assert.equal(gate.title, `${REENTRY_DETAIL} · ${MISSING_DETAIL}`);
});

test("r9-3: one blocker beside the missing answer and it is Blocked again", () => {
  const gate = materializeGate({
    can_materialize: false,
    blocking: [
      { code: "blockers_present", detail: PLAIN_DETAIL, items: HARD_ITEMS },
      { code: "answers_missing", detail: MISSING_DETAIL,
        items: [{ id: "site.domain", prompt: "Public domain for this site" }] },
    ],
  });
  assert.equal(gate.label, "⛔ Blocked");
});

test("r9-3: an unknown refusal code is still Blocked — the arm is not a fallback", () => {
  // Whatever the next code turns out to be, it is not something the operator answers in
  // this form. The arm names its two codes; anything else keeps the conservative label.
  const gate = materializeGate({
    can_materialize: false,
    blocking: [{ code: "schema_skew", detail: "report predates the schema", items: [] }],
  });
  assert.equal(gate.label, "⛔ Blocked");
});

// ── R10-UX-F5: ⛔ on a project with nothing to report ─────────────────────────
//
// R9-3 reserved ⛔ for "a blocker-tier finding in the report" and then left
// `scan_required` wearing it. A project nobody has scanned has no findings at all, and
// the panel directly above the button says so — so the screen announced a blockage the
// report it is showing does not contain, and pointed the operator at nothing to look at.

test("r10-ux-f5: scan_required gets its own neutral label", () => {
  const gate = materializeGate({
    can_materialize: false,
    blocking: [{ code: "scan_required", detail: "this project has not been scanned yet",
                 items: [] }],
  });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "Scan required");
  assert.ok(!gate.label.includes("⛔"), "the glyph means a finding in the report");
  // …and the reason is still the server's own sentence, verbatim (§4b).
  assert.equal(gate.title, "this project has not been scanned yet");
});

test("r10-ux-f5: scan_required beside a real blocker is Blocked again", () => {
  const gate = materializeGate({
    can_materialize: false,
    blocking: [
      { code: "scan_required", detail: "not scanned", items: [] },
      { code: "blockers_present", detail: PLAIN_DETAIL,
        items: [{ id: "core.secret-scan", title: "Committed secrets detected" }] },
    ],
  });
  assert.equal(gate.label, "⛔ Blocked");
});

test("r10-ux-f5: the real never-scanned fixture renders the new label", async () => {
  // orders-api/prod out of ?sim=degraded: a real `_state()` run on a project with an
  // empty scan_report, not a payload written to suit this test.
  const { data } = await (SIM_FIXTURES.degraded as any)("v1/sites/5/wizard/");
  assert.deepEqual(data.blocking.map((p: any) => p.code), ["scan_required"]);
  assert.equal(materializeGate(data).label, "Scan required");
});

test("r9-3: the real fixture for that screen renders the new arm", async () => {
  // takko/staging out of ?sim=live: a real `_state()` run on a clean project's fresh
  // site (scripts_dev/sim_fixture_payloads.py), not a payload written to suit this test.
  const { data } = await (SIM_FIXTURES.live as any)("v1/sites/4/wizard/");
  assert.deepEqual(data.blocking.map((p: any) => p.code), ["answers_missing"]);
  assert.equal(materializeGate(data).label, "Answers needed");
});

// ── round-9 item 4: what the client does with a 409 ───────────────────────────
//
// The 409 branch set a message and re-read nothing. In ?sim=stale that left the operator
// under a refusal naming a committed Stripe key, above a panel reading "✓ No findings"
// and a Materialize button still enabled — the screen contradicting itself, with the
// server's answer already in hand. `onChanged` fired only on 201, so neither the report
// nor the project list nor the wizard state was re-read.
//
// The decision is a pure function for the same reason `materializeGate` is: what the
// client does with a response is reviewable if you can call it.

test("r9-4: a 409 sends the client back to the server, not just to a message", () => {
  const body = {
    code: "blockers_present", detail: PLAIN_DETAIL, items: HARD_ITEMS,
    problems: [{ code: "blockers_present", detail: PLAIN_DETAIL, items: HARD_ITEMS }],
  };
  const outcome = materializeOutcome(409, body);
  assert.deepEqual(outcome.msg.problems, body.problems);
  assert.equal(outcome.reloadWizard, true, "the wizard state that said go is stale");
  assert.equal(outcome.refreshProject, true, "…and so is the report above it");
});

test("r9-4: a 409 with no problems list still shows the one reason it carries", () => {
  const outcome = materializeOutcome(409, { code: "scan_required", detail: "no scan" });
  assert.deepEqual(outcome.msg.problems, [{ code: "scan_required", detail: "no scan" }]);
  assert.equal(outcome.reloadWizard, true);
});

test("r9-4: a 201 re-reads too — the site now has a manifest it did not have", () => {
  const outcome = materializeOutcome(201, { version: 4 });
  assert.equal(outcome.msg.ok, true);
  assert.match(outcome.msg.text, /v4/);
  assert.equal(outcome.reloadWizard, true);
  assert.equal(outcome.refreshProject, true);
});

test("r9-4: a 500 or a dead socket re-reads NOTHING", () => {
  // The server said nothing about this site's state, so there is nothing to converge on
  // and a refetch loop is the only thing a retry here could add.
  for (const [status, data] of [[500, { detail: "boom" }], [0, { detail: "offline" }]]) {
    const outcome = materializeOutcome(status as number, data as any);
    assert.equal(outcome.msg.ok, false);
    assert.equal(outcome.reloadWizard, false);
    assert.equal(outcome.refreshProject, false);
  }
});

test("r9-4: driving ?sim=stale through both functions converges the screen", async () => {
  // The whole finding in six lines: the gate says go, the POST refuses, the client
  // re-reads because the outcome says to, and the gate that said go now says Blocked in
  // the server's own words.
  const stale = SIM_FIXTURES.stale as any;
  stale.reset();
  const before = await stale("v1/sites/1/wizard/");
  assert.equal(materializeGate(before.data).disabled, false);

  const { status, data } = await stale("v1/sites/1/manifest/", { confirm_warnings: false });
  const outcome = materializeOutcome(status, data);
  assert.equal(outcome.reloadWizard, true);

  const after = await stale("v1/sites/1/wizard/");   // what reloadWizard makes the UI do
  const gate = materializeGate(after.data);
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "⛔ Blocked");
  assert.equal(gate.title, data.problems[0].detail);
});
