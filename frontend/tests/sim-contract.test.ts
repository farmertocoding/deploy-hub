// §F8 sim fixtures must match the GENERATED zod schemas. A fixture that drifts from
// the real API shape means review rounds are approving a fiction — so drift fails
// the build here instead.
import { test } from "node:test";
import assert from "node:assert/strict";
import { schemas } from "../src/api/zod.ts";
import { SIM_FIXTURES } from "../src/sim.js";

// window shim: sim.js is a browser module; the fixtures themselves are pure.
(globalThis as any).window = { location: { search: "" } };

const REQUIRED_STATES = ["empty", "loading", "live", "degraded", "error"];

test("all five §F8 states exist", () => {
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

test("the 409 refusal fixture carries the full problems list (round-1 F4 shape)", async () => {
  const { status, data } = await (SIM_FIXTURES.live as any)("v1/sites/2/manifest/", {});
  assert.equal(status, 409);
  assert.ok(Array.isArray(data.problems) && data.problems.length >= 2);
});
