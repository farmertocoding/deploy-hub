// §F8 sim fixtures must match the GENERATED zod schemas. A fixture that drifts from
// the real API shape means review rounds are approving a fiction — so drift fails
// the build here instead.
import { test } from "node:test";
import assert from "node:assert/strict";
import { schemas } from "../src/api/zod.ts";
import { SIM_FIXTURES } from "../src/sim.js";

// window shim: sim.js is a browser module; the fixtures themselves are pure.
(globalThis as any).window = { location: { search: "" } };

// One state per §F8 situation, plus one per SPINNER: three fetches happen in a chain
// (list → report → wizard) and a single hanging state can only ever show the first of
// them (round-9 item 10).
const REQUIRED_STATES = ["empty", "loading", "loading-report", "loading-wizard",
                         "live", "stale", "degraded", "error"];

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
// A fixture "hangs" if it has not settled by the time an ordinary one would have,
// several times over. `never()` never settles at all, so the margin is arbitrary.
async function hangs(pending: any) {
  return (await Promise.race([Promise.resolve(pending).then(() => "settled"),
                              sleep(50).then(() => "hung")])) === "hung";
}

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
  (SIM_FIXTURES.stale as any).reset();
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

// ── round 9: the payload families §F8 had no fixture for ──────────────────────
//
// Each test below names the screen that was unreachable before its fixture existed. The
// point is not the assertion — it is that a reviewer can now open the state and look.

test("r9-2: the warnings ack is a real gate — one site, one POST, two answers", async () => {
  // materialize.py raises `warnings_unconfirmed` when a site clears preflight and its
  // report still carries warnings. No sim state produced that shape, so the checkbox
  // beside the Materialize button ("I have read the warnings above and accept them")
  // could be ticked or not and the screen behaved identically. atlas-edge is the first
  // fixture site that clears preflight WITH warnings.
  const wizard = await (SIM_FIXTURES.live as any)("v1/sites/3/wizard/");
  assert.equal(wizard.data.can_materialize, true, "the site must clear preflight");
  assert.ok(wizard.data.warnings.length >= 2, "…and still carry warnings");

  const refused = await (SIM_FIXTURES.live as any)("v1/sites/3/manifest/",
                                                   { confirm_warnings: false });
  assert.equal(refused.status, 409);
  assert.equal(refused.data.code, "warnings_unconfirmed");
  const accepted = await (SIM_FIXTURES.live as any)("v1/sites/3/manifest/",
                                                    { confirm_warnings: true });
  assert.equal(accepted.status, 201);
  assert.equal(accepted.data.version, 1);

  // The refusal names the warnings the report shows, which is what makes the checkbox
  // an informed decision rather than a dare.
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/3/readiness/");
  const reported = new Set(report.warnings.map((c: any) => c.id));
  for (const item of refused.data.items)
    assert.ok(reported.has(item.id),
      `the refusal names ${item.id}, which the report does not report as a warning`);
});

test("r9-11: the node-ts containment warnings have a fixture, and it is a real scan", async () => {
  // §F8 had no node-ts report at all, so two checks the scanner spent rounds 8 and 9
  // adding — a workspace pattern that escapes the repo, a symlinked file that resolves
  // outside it — had never been seen on a screen. This fixture is a scan of a tree that
  // really does point at /tmp/edge-neighbour, so the report is evidence the refusal
  // held: the neighbour's marker, its package and the dependency that would have armed
  // three ingestion checks appear nowhere in it.
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/3/readiness/");
  const ids = report.warnings.map((c: any) => c.id);
  assert.ok(ids.includes("node-ts.workspace-patterns"), ids);
  assert.ok(ids.includes("node-ts.symlinked-files"), ids);

  const serialized = JSON.stringify(report);
  for (const leak of ["NEIGHBOUR-TREE-MARKER", "vendored-analytics", "ccxt"])
    assert.ok(!serialized.includes(leak),
      `${leak} reached the report — this fixture is supposed to prove it cannot`);
  assert.equal(report.blockers.length, 0,
    "the warnings path needs a site with no blockers; a blocker here would refuse first");
});

test("r9-4: after the stale 409 every GET serves the report the refusal named", async () => {
  // The screen the operator was left on: a refusal naming a Stripe key, above a panel
  // reading "✓ No findings" and a button still enabled, because the 409 branch set a
  // message and re-read nothing. The fixture has to be able to MOVE for the client fix
  // to be reviewable at all — before the POST it is the clean report, after it the
  // re-scanned one.
  const stale = SIM_FIXTURES.stale as any;
  stale.reset();

  const before = await stale("v1/sites/1/wizard/");
  assert.equal(before.data.can_materialize, true);
  const beforeReport = await stale("v1/projects/1/readiness/");
  assert.equal(beforeReport.data.blockers.length, 0);

  const refused = await stale("v1/sites/1/manifest/", { confirm_warnings: false });
  assert.equal(refused.status, 409);
  const named = refused.data.problems.flatMap((p: any) => p.items).map((i: any) => i.id);

  const after = await stale("v1/sites/1/wizard/");
  assert.equal(after.data.can_materialize, false,
    "the wizard still says the deploy may proceed after the server refused it");
  const afterReport = await stale("v1/projects/1/readiness/");
  assert.deepEqual(afterReport.data.blockers.map((c: any) => c.id), named,
    "the report the operator sees does not name what the refusal named");
  const list = await stale("v1/projects/");
  assert.equal(list.data[0].tiers.blocker, named.length,
    "the project list still shows the pre-refusal tier counts");
});

test("r9-3: a fresh site's only refusal is answers_missing", async () => {
  // takko/staging: a clean project, nothing wrong with the repo, nobody has typed the
  // domain yet. This is the commonest state a new site is ever in and no fixture had it,
  // which is how "⛔ Blocked" survived as its label.
  const { data: wizard } = await (SIM_FIXTURES.live as any)("v1/sites/4/wizard/");
  assert.equal(wizard.can_materialize, false);
  assert.deepEqual(wizard.blocking.map((p: any) => p.code), ["answers_missing"]);
  const { data: report } = await (SIM_FIXTURES.live as any)("v1/projects/1/readiness/");
  assert.equal(report.blockers.length, 0, "…and its project reports no blocker at all");
});

test("r9-6: the never-scanned project shows preflight's own scan_required", async () => {
  // What `?sim=degraded` used to hide. The 503 it answered with carried a sentence
  // written in sim.js — "scan runner unavailable — showing last stored data" — that
  // exists nowhere server-side, and it stood in front of this, which does.
  const { data: wizard } = await (SIM_FIXTURES.degraded as any)("v1/sites/5/wizard/");
  assert.deepEqual(wizard.blocking.map((p: any) => p.code), ["scan_required"]);
  assert.equal(wizard.can_materialize, false);

  const { data: report } = await (SIM_FIXTURES.degraded as any)("v1/projects/4/readiness/");
  assert.equal(report.scanned_at, null);
  assert.deepEqual(report.modules, [], "a never-scanned project ran no module");
  assert.deepEqual(report.summary, {}, "…and counted no checks");

  // A 503 is kept for the routes this state does not answer, and it must not claim to
  // be quoting the server.
  const fallback = await (SIM_FIXTURES.degraded as any)("v1/sites/5/manifest/", {});
  assert.equal(fallback.status, 503);
  assert.match(fallback.data.detail, /^\[sim\]/,
    "a synthetic response must say it is synthetic");
});

test("r9-10: each loading state hangs one fetch and resolves everything shallower", async () => {
  // `loading` hung the FIRST request, so the two spinners behind it — the report panel
  // and the wizard — were unreachable: with no project list there is nothing to select.
  assert.ok(await hangs((SIM_FIXTURES.loading as any)("v1/projects/")),
    "?sim=loading must still hang the project list");

  const report = SIM_FIXTURES["loading-report"] as any;
  assert.equal((await report("v1/projects/")).status, 200);
  assert.ok(await hangs(report("v1/projects/2/readiness/")));

  const wizard = SIM_FIXTURES["loading-wizard"] as any;
  assert.equal((await wizard("v1/projects/")).status, 200);
  assert.equal((await wizard("v1/projects/2/readiness/")).status, 200);
  assert.ok(await hangs(wizard("v1/sites/2/wizard/")));
});

test("r9: every readiness/wizard pair a reviewer can reach parses against its schema", async () => {
  // The r8-4 walk, widened to the states and ids round 9 added — a new fixture that
  // drifts from the serializers is the same defect as an old one that does.
  const reachable: Array<[string, number, number]> = [
    ["live", 1, 1], ["live", 1, 4], ["live", 2, 2], ["live", 3, 3],
    ["stale", 1, 1], ["degraded", 4, 5], ["degraded", 1, 1],
  ];
  for (const [state, projectId, siteId] of reachable) {
    const { data: report } =
      await (SIM_FIXTURES[state] as any)(`v1/projects/${projectId}/readiness/`);
    const parsedReport = schemas.Readiness.safeParse(report);
    assert.ok(parsedReport.success,
      `${state}/p${projectId}: ${JSON.stringify((parsedReport as any).error?.issues)}`);
    const { data: wizard } =
      await (SIM_FIXTURES[state] as any)(`v1/sites/${siteId}/wizard/`);
    const parsedWizard = schemas.WizardState.safeParse(wizard);
    assert.ok(parsedWizard.success,
      `${state}/s${siteId}: ${JSON.stringify((parsedWizard as any).error?.issues)}`);
  }
});
