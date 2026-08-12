// §F8 sim fixtures must match the GENERATED zod schemas. A fixture that drifts from
// the real API shape means review rounds are approving a fiction — so drift fails
// the build here instead.
import { test } from "node:test";
import assert from "node:assert/strict";
import { schemas } from "../src/api/zod.ts";
import { SIM_FIXTURES } from "../src/sim.js";

// window shim: sim.js is a browser module; the fixtures themselves are pure.
(globalThis as any).window = { location: { search: "" } };

const REQUIRED_STATES = ["empty", "loading", "live", "accepted", "degraded", "error"];

test("all §F8 states exist", () => {
  for (const state of REQUIRED_STATES) {
    assert.ok(SIM_FIXTURES[state], `missing sim state: ${state}`);
  }
});

test("live project list parses against the generated ProjectSummary schema", async () => {
  const { status, data } = await (SIM_FIXTURES.live as any)("v1/projects/");
  assert.equal(status, 200);
  for (const row of data) {
    const parsed = schemas.ProjectSummary.safeParse(row);
    assert.ok(parsed.success, JSON.stringify((parsed as any).error?.issues));
  }
});

test("degraded + empty project lists parse too", async () => {
  for (const state of ["degraded", "empty"]) {
    const { data } = await (SIM_FIXTURES[state] as any)("v1/projects/");
    for (const row of data) {
      assert.ok(schemas.ProjectSummary.safeParse(row).success,
        `${state} fixture drifted from ProjectSummary`);
    }
  }
});

test("live readiness report parses against the generated Readiness schema", async () => {
  const { data } = await (SIM_FIXTURES.live as any)("v1/projects/2/readiness/");
  const parsed = schemas.Readiness.safeParse(data);
  assert.ok(parsed.success, JSON.stringify((parsed as any).error?.issues));
});

test("live wizard state parses against the generated WizardState schema", async () => {
  const { data } = await (SIM_FIXTURES.live as any)("v1/sites/2/wizard/");
  const parsed = schemas.WizardState.safeParse(data);
  assert.ok(parsed.success, JSON.stringify((parsed as any).error?.issues));
});

test("r8-4: the accepted state parses against WizardState and Readiness too", async () => {
  const { data: state } = await (SIM_FIXTURES.accepted as any)("v1/sites/2/wizard/");
  const parsedState = schemas.WizardState.safeParse(state);
  assert.ok(parsedState.success, JSON.stringify((parsedState as any).error?.issues));
  const { data: report } = await (SIM_FIXTURES.accepted as any)("v1/projects/2/readiness/");
  const parsedReport = schemas.Readiness.safeParse(report);
  assert.ok(parsedReport.success, JSON.stringify((parsedReport as any).error?.issues));
});

// Parsing is not enough here. `ReadinessSerializer.blockers` is a ListField of
// DictField, so `acceptance` passes through UNTYPED — a fixture that dropped the field
// entirely would still parse green, and the UI state R8-4 is about would be reviewable
// nowhere again. These three assertions are about presence and agreement, not shape.
test("r8-4: the live report carries an acceptance-pending blocker", async () => {
  const { data } = await (SIM_FIXTURES.live as any)("v1/projects/2/readiness/");
  const pending = data.blockers.filter((b: any) => b.acceptance?.blocking_only_declared === true);
  assert.ok(pending.length >= 1, "no blocker awaiting acceptance in the live fixture");
  for (const b of pending) {
    assert.ok(Array.isArray(b.acceptance.questions) && b.acceptance.questions.length >= 1,
      `${b.id}: acceptance.questions is empty — nothing to answer`);
  }
});

// The drift alarm. The check's `acceptance.questions`, the wizard's question set and
// (on a real server) the manifest record all carry the SAME content-keyed confirm id;
// edit one and the gate would open for a question nobody was asked. Edit either id in
// sim.js apart from the other and this goes red.
test("r8-4: every confirm the live report waits on is a bool question in the live wizard", async () => {
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/2/readiness/");
  const { data: state } = await (SIM_FIXTURES.live as any)("v1/sites/2/wizard/");
  for (const b of report.blockers.filter((b: any) => b.acceptance)) {
    for (const qid of b.acceptance.questions) {
      const q = state.questions.find((q: any) => q.id === qid);
      assert.ok(q, `${b.id} waits on ${qid}, which the wizard never asks`);
      assert.equal(q.kind, "bool", `${qid} must be a confirm`);
      assert.ok(!(qid in (state.answered || {})),
        `${qid} is answered — the live fixture is meant to be the pending state`);
    }
  }
});

test("r8-4: accepted can materialize while the report still carries the blocker", async () => {
  const { data: state } = await (SIM_FIXTURES.accepted as any)("v1/sites/2/wizard/");
  assert.equal(state.can_materialize, true);
  const { data: report } = await (SIM_FIXTURES.accepted as any)("v1/projects/2/readiness/");
  assert.ok(report.blockers.some((b: any) => b.acceptance?.blocking_only_declared === true),
    "the accepted state lost the blocker it is supposed to be reviewed against");
});

test("the 409 refusal fixture carries the full problems list (round-1 F4 shape)", async () => {
  const { status, data } = await (SIM_FIXTURES.live as any)("v1/sites/2/manifest/", {});
  assert.equal(status, 409);
  assert.ok(Array.isArray(data.problems) && data.problems.length >= 2);
});
