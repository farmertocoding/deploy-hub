// §F8 sim fixtures must match the GENERATED zod schemas. A fixture that drifts from
// the real API shape means review rounds are approving a fiction — so drift fails
// the build here instead.
import { test } from "node:test";
import assert from "node:assert/strict";
import { schemas } from "../src/api/zod.ts";
import { SIM_FIXTURES } from "../src/sim.js";

// window shim: sim.js is a browser module; the fixtures themselves are pure.
(globalThis as any).window = { location: { search: "" } };

const REQUIRED_STATES = ["empty", "loading", "live", "accepted", "stale", "degraded", "error"];

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
  const { status, data } = await (SIM_FIXTURES.stale as any)("v1/sites/3/manifest/", {});
  assert.equal(status, 409);
  assert.ok(Array.isArray(data.problems) && data.problems.length >= 2);
});

test("r8-4: every wizard/readiness pair the UI can reach parses against its schema", async () => {
  for (const state of ["live", "accepted", "stale"]) {
    for (const id of [1, 2, 3]) {
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

// §4b.4 — THE ALARM THAT WOULD HAVE CAUGHT THE FICTION.
//
// Parsing proves nothing here: `ReadinessSerializer.blockers` is a ListField of
// DictField, so `acceptance` passes through untyped, and `blocking` is a ListField of
// DictField too — a fixture can hand the UI any refusal shape it likes and stay green.
// The first remedy for R8-1 did exactly that and was reviewed against it.
//
// The invariant, which is `wizard/materialize.py::_pending_acceptance` restated: a
// blocker check publishing `acceptance` appears in that state's wizard `blocking` as a
// `blockers_present` item carrying `awaiting_acceptance` IF AND ONLY IF its confirm is
// not answered `true` — and every id in that list is a `bool` question the same wizard
// asks. Edit either side alone and this goes red.
test("r8-4: report and wizard agree about which declaration is pending", async () => {
  for (const state of ["live", "accepted", "stale"]) {
    for (const id of [1, 2, 3]) {
      const { data: report } = await (SIM_FIXTURES[state] as any)(`v1/projects/${id}/readiness/`);
      const { data: wizard } = await (SIM_FIXTURES[state] as any)(`v1/sites/${id}/wizard/`);
      const where = `${state}/${id}`;
      const awaiting = new Map();   // check id -> awaiting_acceptance question ids
      for (const problem of wizard.blocking || []) {
        if (problem.code !== "blockers_present") continue;
        for (const item of problem.items || []) {
          if (!(item.awaiting_acceptance || []).length) continue;
          awaiting.set(item.id, item.awaiting_acceptance.map((q: any) => q.id));
        }
      }

      // report → wizard
      for (const check of report.blockers || []) {
        if (!check.acceptance) continue;
        const pending = (check.acceptance.questions || [])
          .filter((qid: string) => (wizard.answered || {})[qid] !== true);
        if (pending.length && check.acceptance.blocking_only_declared === true) {
          assert.deepEqual(awaiting.get(check.id), pending,
            `${where}: ${check.id} waits on ${pending} but the wizard's blocking says ` +
            `${JSON.stringify(awaiting.get(check.id))}`);
        } else {
          assert.equal(awaiting.get(check.id), undefined,
            `${where}: ${check.id} has nothing pending, yet the wizard still lists it ` +
            "as awaiting an acceptance");
        }
      }

      // wizard → report
      for (const [checkId, qids] of awaiting) {
        const check = (report.blockers || []).find((c: any) => c.id === checkId);
        assert.ok(check, `${where}: the wizard waits on ${checkId}, which the readiness ` +
          "report does not report as a blocker");
        assert.ok(check.acceptance, `${where}: ${checkId} is awaited but publishes no ` +
          "acceptance contract — no answer could clear it");
        for (const qid of qids) {
          assert.ok((check.acceptance.questions || []).includes(qid),
            `${where}: the wizard waits on ${qid}, which ${checkId} never asked for`);
          const question = (wizard.questions || []).find((q: any) => q.id === qid);
          assert.ok(question, `${where}: ${qid} is awaited and the wizard never asks it`);
          assert.equal(question.kind, "bool", `${where}: ${qid} must be a confirm`);
        }
      }
    }
  }
});

test("r8-4: the acceptance-pending blocker and its accepted twin are both reachable", async () => {
  const pending = await (SIM_FIXTURES.live as any)("v1/sites/3/wizard/");
  assert.equal(pending.data.can_materialize, false);
  assert.ok(pending.data.blocking.some((p: any) => p.code === "blockers_present"),
    "the pending state must refuse with blockers_present — that is the shape preflight sends");

  const accepted = await (SIM_FIXTURES.accepted as any)("v1/sites/3/wizard/");
  assert.equal(accepted.data.can_materialize, true);
  const { data: report } = await (SIM_FIXTURES.accepted as any)("v1/projects/3/readiness/");
  assert.ok(report.blockers.some((b: any) => b.acceptance?.blocking_only_declared === true),
    "the accepted state lost the blocker it is supposed to be reviewed against");
});
