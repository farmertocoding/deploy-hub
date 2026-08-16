// §F8 sim fixtures must match the GENERATED zod schemas. A fixture that drifts from
// the real API shape means review rounds are approving a fiction — so drift fails
// the build here instead.
import { test } from "node:test";
import assert from "node:assert/strict";
import { schemas } from "../src/api/zod.ts";
import { SIM_FIXTURES } from "../src/sim.js";

// window shim: sim.js is a browser module; the fixtures themselves are pure.
(globalThis as any).window = { location: { search: "" } };

const REQUIRED_STATES = ["empty", "loading", "live", "stale", "degraded", "error"];

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

test("the 409 refusal fixture carries the full problems list (round-1 F4 shape)", async () => {
  // legacy-shop's own refusal: blockers AND an unanswered required question, which is
  // what `preflight` gathers rather than the first problem it finds.
  const { status, data } = await (SIM_FIXTURES.live as any)("v1/sites/2/manifest/", {});
  assert.equal(status, 409);
  assert.ok(Array.isArray(data.problems) && data.problems.length >= 2);
});

test("the stale state refuses the POST the wizard said would succeed", async () => {
  // The §F8 state the 409 panel is reachable from with the button ENABLED: takko's
  // wizard says go, and the tree was re-scanned between the GET and the POST.
  const wizard = await (SIM_FIXTURES.stale as any)("v1/sites/1/wizard/");
  assert.equal(wizard.data.can_materialize, true);
  const { status, data } = await (SIM_FIXTURES.stale as any)("v1/sites/1/manifest/", {});
  assert.equal(status, 409);
  assert.equal(data.code, "blockers_present");
});

test("r8-4: every wizard/readiness pair the UI can reach parses against its schema", async () => {
  for (const state of ["live", "stale"]) {
    for (const id of [1, 2]) {
      const { data: report } = await (SIM_FIXTURES[state] as any)(`v1/projects/${id}/readiness/`);
      const parsedReport = schemas.Readiness.safeParse(report);
      assert.ok(parsedReport.success,
        `${state}/${id} readiness: ${JSON.stringify((parsedReport as any).error?.issues)}`);
      const { data: wizard } = await (SIM_FIXTURES[state] as any)(`v1/sites/${id}/wizard/`);
      const parsedWizard = schemas.WizardState.safeParse(wizard);
      assert.ok(parsedWizard.success,
        `${state}/${id} wizard: ${JSON.stringify((parsedWizard as any).error?.issues)}`);
    }
  }
});

// §4b.4 — THE ALARM THAT WOULD HAVE CAUGHT THE FICTION, RE-AIMED.
//
// Parsing proves nothing on its own here: `ReadinessSerializer.blockers` is a ListField
// of DictField and `blocking` is one too, so a fixture can hand the UI any refusal shape
// it likes and stay green. The first remedy for R8-1 did exactly that and was reviewed
// against it.
//
// r8's cross-check asserted the acceptance invariant — a blocker publishing an
// `acceptance` contract appears in `blocking` as an item carrying `awaiting_acceptance`
// if and only if its confirm is unanswered. D-012 left Phase 1, so no check publishes
// that contract and no `preflight` emits that item; the invariant now has NO instances,
// and a test that walks an empty set passes for the wrong reason forever. What replaces
// it is the same idea against what the server does send: every refusal item names a
// check the readiness report really reports as a blocker, and no fixture invents the
// acceptance shape the phase removed.
test("d012: no fixture carries an acceptance contract or an acceptance-pending refusal", async () => {
  for (const state of ["live", "stale", "degraded"]) {
    for (const id of [1, 2]) {
      const { data: report } = await (SIM_FIXTURES[state] as any)(`v1/projects/${id}/readiness/`);
      for (const tier of ["blockers", "warnings", "advice", "pending_sandbox"]) {
        for (const check of report[tier] || []) {
          assert.ok(!("acceptance" in check),
            `${state}/${id}: ${check.id} carries an acceptance contract, which no ` +
            "scanner in this phase emits");
        }
      }
      const { data: wizard } = await (SIM_FIXTURES[state] as any)(`v1/sites/${id}/wizard/`);
      for (const problem of wizard.blocking || []) {
        for (const item of problem.items || []) {
          assert.ok(!("awaiting_acceptance" in item),
            `${state}/${id}: a refusal item waits on an acceptance, which preflight ` +
            "cannot produce this phase");
        }
      }
      for (const question of wizard.questions || []) {
        assert.ok(!question.id.startsWith("scanner.test_material."),
          `${state}/${id}: the wizard asks a declaration confirm`);
      }
    }
  }
});

test("d012: every blocking refusal names a check the readiness report reports", async () => {
  for (const state of ["live", "stale"]) {
    for (const id of [1, 2]) {
      const { data: report } = await (SIM_FIXTURES[state] as any)(`v1/projects/${id}/readiness/`);
      const { data: wizard } = await (SIM_FIXTURES[state] as any)(`v1/sites/${id}/wizard/`);
      const reported = new Set((report.blockers || []).map((c: any) => c.id));
      for (const problem of wizard.blocking || []) {
        if (problem.code !== "blockers_present") continue;
        for (const item of problem.items || []) {
          assert.ok(reported.has(item.id),
            `${state}/${id}: the wizard refuses on ${item.id}, which the readiness ` +
            "report does not report as a blocker");
        }
      }
      // …and the other way: a blocker in the report and a wizard that says go is the
      // combination this phase must never show, because nothing clears a blocker.
      if (wizard.can_materialize)
        assert.equal(reported.size, 0,
          `${state}/${id}: the wizard says the deploy may proceed while the report ` +
          "still reports a blocker — no answer clears a blocker this phase");
    }
  }
});

test("d012: the legacy-shop report shows the drill tree at full tier", async () => {
  // The fixture repo carries a `deployhub.yaml` declaring `frontend/scripts/drill`.
  // What the operator must see is fifteen ordinary blocking lines — ten of them under
  // the declared path — with no header claiming a downgrade, and one warning saying the
  // file is not honored.
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/2/readiness/");
  const secretScan = report.blockers.find((c: any) => c.id === "core.secret-scan");
  assert.ok(secretScan, "the messy fixture lost its secret scan");
  const lines = secretScan.detail.split("\n\n")[0].split("\n");
  assert.equal(lines.length, 15, `expected 15 blocking lines, got ${lines.length}`);
  assert.equal(lines.filter((l: string) => l.startsWith("frontend/scripts/drill/")).length, 10);
  assert.ok(!/Downgrades claimed|declared:/.test(secretScan.detail),
    "the report still shows a declaration header or label");
  const notices = report.warnings.filter((c: any) => c.id === "core.declaration-file");
  assert.equal(notices.length, 1, "the presence notice is missing or duplicated");
});
