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
// sim-contract.test.ts pins the fixtures; this file pins the decision. It is the
// regression test for R8-1: the first case below fails on ffec190, where
// `materializeGate` does not exist and the disabled expression lives inside JSX.
import { test } from "node:test";
import assert from "node:assert/strict";
import { materializeGate } from "../src/Readiness.jsx";

// Verbatim from wizard/materialize.py::preflight — the strings the server really sends.
const BLOCKERS_PRESENT = {
  code: "blockers_present",
  detail: "the readiness report has blockers; these must be fixed and the project " +
    "re-scanned — except where a declaration is awaiting acceptance, which you clear " +
    "by answering its confirm in this wizard, not by changing the repo",
  items: [{ id: "core.secret-scan", title: "Secrets in a declared tree — your acceptance is required" }],
};
const ANSWERS_MISSING = {
  code: "answers_missing",
  detail: "required questions are unanswered",
  items: [{ id: "scanner.test_material.frontend-scripts-drill--a38574e34e643d90",
            prompt: "This repo declares `frontend/scripts/drill` as test material…" }],
};
const ANSWERS_NEED_REENTRY = {
  code: "answers_need_reentry",
  detail: "these values are now handled as secrets and must be entered again; the " +
    "previously stored plaintext has been deleted and should be rotated at the source",
  items: [{ id: "django.env.SECRET_KEY", prompt: "Value for SECRET_KEY" }],
};

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

test("r8-1: an unanswered declaration confirm asks for an answer and never says re-scan", () => {
  const gate = materializeGate({ can_materialize: false, blocking: [ANSWERS_MISSING] });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "Answer required");
  // The whole point: re-scanning cannot clear this one, so the copy must not send the
  // operator there. Checked on the lowercased tooltip so no casing slips through.
  assert.ok(!/rescan|rescanned/.test(gate.title.toLowerCase()), gate.title);
  assert.match(gate.title, /Answering them here is what clears them/);
});

test("r8-1: a real blocker still says blocked, with the fix-and-rescan instruction that is true for it", () => {
  const gate = materializeGate({ can_materialize: false, blocking: [BLOCKERS_PRESENT] });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "⛔ Blocked");
  assert.equal(gate.title,
    "Blockers must be fixed and rescanned first — materialization will refuse.");
});

test("r8-1: a mixed refusal names every reason, not just the first", () => {
  const gate = materializeGate({
    can_materialize: false, blocking: [ANSWERS_NEED_REENTRY, ANSWERS_MISSING],
  });
  assert.equal(gate.disabled, true);
  assert.equal(gate.label, "⛔ Blocked");
  assert.equal(gate.title, `${ANSWERS_NEED_REENTRY.detail} · ${ANSWERS_MISSING.detail}`);
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
