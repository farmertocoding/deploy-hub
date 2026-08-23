// §F8 sim fixtures must match the GENERATED zod schemas. A fixture that drifts from
// the real API shape means review rounds are approving a fiction — so drift fails
// the build here instead.
import { test } from "node:test";
import assert from "node:assert/strict";
import { schemas } from "../src/api/zod.ts";
import { SIM_FIXTURES, TAKKO_SITES } from "../src/sim.js";

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

test("project list site fixtures emit cert_refusal like project_row_body", async () => {
  // project_row_body always emits cert_refusal (null when unused). Zod's
  // .nullish() treats omit and null as the same, so schema-parse stays green
  // on a fixture that quietly dropped the field Sites.jsx CertState reads.
  // Arrival lists only — the AFTER/RESCANNED rows are pinned in parseEveryRead.
  for (const state of ["empty", "live", "stale", "degraded"]) {
    (SIM_FIXTURES[state] as any).reset?.();
    const { status, data } = await (SIM_FIXTURES[state] as any)("v1/projects/");
    assert.equal(status, 200, state);
    for (const row of data) {
      for (const site of row.sites || []) {
        assert.ok(Object.prototype.hasOwnProperty.call(site, "cert_refusal"),
          `${state}: ${row.name}/${site.name} omitted cert_refusal`);
        assert.equal(site.cert_refusal, null,
          `${state}: ${row.name}/${site.name} unused cert_refusal must be null`);
      }
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

// ── R11-Q2: the payloads a TRANSITION produces were parsed by nothing ─────────
//
// Every walk above reads the fixtures the way a screen looks at them ON ARRIVAL: GET the
// list, GET a report, GET a wizard. Four payloads in sim.js are only reachable after the
// operator does something — STAGING_WIZARD_ANSWERED (after the PATCH),
// STAGING_MANIFEST/CLEAN_PROJECT_ANSWERED (after that site's POST), CLEAN_PROJECT_AFTER
// and EDGE_PROJECT_AFTER (the list re-read a 201 triggers) — and no test in this file
// had ever asked a fixture for them. `"kind": 42` in the answered wizard's question list,
// or a project row with its `scanned_at` deleted, went through all 76 tests green.
//
// So the r8-4 walk is DRIVEN as well as read: perform each transition through the
// fixtures the way SiteWizard performs it, and re-parse everything the client re-reads
// afterwards. `parseEveryRead` is the whole surface in one place, so a state that starts
// answering a path differently after a POST is covered without a new list here.
//
// THE 409 BODIES ARE NOT PARSED HERE, and that is a gap with a reason rather than an
// oversight: `MaterializeRefused.as_dict()` has no serializer and therefore no generated
// schema, so there is nothing to parse them against. What holds them honest is the
// d012 walk above (every refusal item names a check the report reports) and the
// structural assertions in wizard-flow.test.ts. A schema for the refusal shape is a
// backend change — the serializer is the source of truth — not something to hand-write
// here, which is the §4b rule this whole file exists under.

const READS: Array<[string, "ProjectSummary" | "Readiness" | "WizardState"]> = [
  ["v1/projects/", "ProjectSummary"],
  ["v1/projects/1/readiness/", "Readiness"],
  ["v1/projects/2/readiness/", "Readiness"],
  ["v1/projects/3/readiness/", "Readiness"],
  ["v1/projects/4/readiness/", "Readiness"],
  ["v1/sites/1/wizard/", "WizardState"],
  ["v1/sites/2/wizard/", "WizardState"],
  ["v1/sites/3/wizard/", "WizardState"],
  ["v1/sites/4/wizard/", "WizardState"],
  ["v1/sites/5/wizard/", "WizardState"],
];

async function parseEveryRead(state: string, when: string) {
  for (const [path, schema] of READS) {
    const { status, data } = await (SIM_FIXTURES[state] as any)(path);
    // A state that declines to answer a route says so with a status, and a refusal is
    // not a payload — `degraded`'s 503 is the sim refusing, not the server's shape.
    if (status !== 200) continue;
    const rows = path === "v1/projects/" ? data : [data];
    for (const row of rows) {
      const parsed = (schemas as any)[schema].safeParse(row);
      assert.ok(parsed.success,
        `${state} ${when}: ${path} drifted from ${schema} — ` +
        JSON.stringify((parsed as any).error?.issues));
      if (schema === "ProjectSummary") {
        for (const site of row.sites || []) {
          assert.ok(Object.prototype.hasOwnProperty.call(site, "cert_refusal"),
            `${state} ${when}: ${row.name}/${site.name} omitted cert_refusal`);
        }
      }
    }
  }
}

test("r11-q2: live — every payload each transition produces parses against its schema",
  async () => {
    const live = SIM_FIXTURES.live as any;
    live.reset();
    await parseEveryRead("live", "before any transition");

    // The PATCH. §4.5: a PATCH answers with the full wizard state, same serializer as
    // the GET — so the response itself is a payload, not only the re-read behind it.
    const patched = await live("v1/sites/4/wizard/",
                               { answers: { "site.domain": "staging.takko.market" } }, "PATCH");
    assert.equal(patched.status, 200);
    let parsed = schemas.WizardState.safeParse(patched.data);
    assert.ok(parsed.success,
      `the PATCH response drifted: ${JSON.stringify((parsed as any).error?.issues)}`);
    await parseEveryRead("live", "after the PATCH");

    // The three POSTs that can succeed, each followed by the re-reads a 201 triggers
    // (`materializeOutcome`: reloadWizard + refreshProject).
    // ORDER IS LOAD-BEARING: takko's row is captured at three points in one linear
    // generator session — none materialized, prod materialized, then prod AND staging —
    // so prod's 201 before staging's is what makes CLEAN_PROJECT_AFTER the row the list
    // serves at all. The other way round it is skipped, and the payload this walk exists
    // to reach is never asked for.
    const posts: Array<[number, any]> = [
      [1, {}], [4, {}], [3, { confirm_warnings: true }],
    ];
    for (const [site, body] of posts) {
      const created = await live(`v1/sites/${site}/manifest/`, body);
      assert.equal(created.status, 201, `site ${site} did not materialize`);
      parsed = schemas.Manifest.safeParse(created.data);
      assert.ok(parsed.success,
        `site ${site}'s manifest drifted: ` +
        JSON.stringify((parsed as any).error?.issues));
      await parseEveryRead("live", `after site ${site}'s 201`);
    }
  });

test("r11-q2: stale — the payloads the 409 converges on parse too", async () => {
  const stale = SIM_FIXTURES.stale as any;
  stale.reset();
  await parseEveryRead("stale", "before the refusal");

  const refused = await stale("v1/sites/1/manifest/", {});
  assert.equal(refused.status, 409);
  // Every GET moves to the re-scanned truth after this, which is the whole state — and
  // until now the LIST it moves to (RESCANNED_PROJECT) was parsed by nothing.
  await parseEveryRead("stale", "after the refusal");
});

test("r11-q2: the walk covers every constant a transition can produce", async () => {
  // The scope, asserted rather than trusted — the R10-A2 lesson one file over. A payload
  // reachable only after a transition, and not produced by any transition driven above,
  // is a payload this walk cannot see; naming them here means the next one is either
  // covered or is a failing test.
  const source = await import("node:fs").then((fs) =>
    fs.readFileSync(new URL("../src/sim.js", import.meta.url), "utf-8"));
  const declared = [...source.matchAll(/^const ([A-Z0-9_]+) = \{/gm)].map((m) => m[1]);
  const postTransition = declared.filter((name) =>
    /_AFTER$|_ANSWERED$|^STAGING_MANIFEST$|^STAGING_WIZARD_ANSWERED$/.test(name));

  assert.deepEqual(postTransition.sort(), [
    "CLEAN_PROJECT_AFTER", "CLEAN_PROJECT_ANSWERED", "EDGE_PROJECT_AFTER",
    "STAGING_MANIFEST", "STAGING_WIZARD_ANSWERED",
  ], "a post-transition payload was added — drive it in the walk above");

  // …and each one really is served by the driven sequence, rather than merely declared.
  const live = SIM_FIXTURES.live as any;
  live.reset();
  const seen = new Set<string>();
  const record = (label: string, data: any) => seen.add(label + JSON.stringify(data));

  record("list", (await live("v1/projects/")).data);          // CLEAN_PROJECT + EDGE
  await live("v1/sites/4/wizard/",
             { answers: { "site.domain": "staging.takko.market" } }, "PATCH");
  record("wizard4", (await live("v1/sites/4/wizard/")).data);  // STAGING_WIZARD_ANSWERED
  await live("v1/sites/1/manifest/", {});
  record("list", (await live("v1/projects/")).data);           // CLEAN_PROJECT_AFTER
  record("manifest4", (await live("v1/sites/4/manifest/", {})).data);  // STAGING_MANIFEST
  record("list", (await live("v1/projects/")).data);           // CLEAN_PROJECT_ANSWERED
  await live("v1/sites/3/manifest/", { confirm_warnings: true });
  record("list", (await live("v1/projects/")).data);           // EDGE_PROJECT_AFTER

  // FOUR distinct list payloads, one per row capture the generator recorded. A `live`
  // that stopped remembering a 201 would collapse them into one, which is the R10-UX-F2
  // defect and the reason the AFTER rows exist.
  assert.equal([...seen].filter((s) => s.startsWith("list")).length, 4,
    "the list stopped moving after a 201 — the AFTER rows are unreachable again");
});

// ── R11-UX-F1: the converged state covered ONE of takko's two sites ──────────
//
// `?sim=stale` is a re-scan under the operator, and a re-scan moves the report under
// every site the project has. The state named site 1's payloads and fell through to
// `?sim=live` for everything else, so clicking `staging` after the refusal served the
// PRE-rescan wizard — `answers_missing` alone, under a panel listing a blocker — and one
// PATCH later the live state's 201 was reachable. A wizard that says the deploy may
// proceed while the report beside it reports a blocker is the exact combination the d012
// walk above forbids, and it was two clicks from the state whose whole job is being the
// truth after a refusal.

test("r11-ux-f1: no takko site can materialize under the converged blocking report",
  async () => {
    const stale = SIM_FIXTURES.stale as any;
    (SIM_FIXTURES.live as any).reset();
    stale.reset();

    const refused = await stale("v1/sites/1/manifest/", {});
    assert.equal(refused.status, 409);
    const { data: report } = await stale("v1/projects/1/readiness/");
    assert.ok(report.blockers.length, "the convergence must put a blocker on screen");

    for (const site of TAKKO_SITES) {
      // What the operator does next, on the site whose only refusal LOOKS answerable:
      // type the domain and press Save.
      const patched = await stale(`v1/sites/${site}/wizard/`,
                                  { answers: { "site.domain": "staging.takko.market" } },
                                  "PATCH");
      if (patched.status === 200) {
        // A state may answer this — but then what it answers with has to be a capture
        // taken against the moved report, not the live state's memory.
        assert.equal(patched.data.can_materialize, false,
          `site ${site}: the wizard says the deploy may proceed while the report ` +
          "reports a blocker — no answer clears a blocker this phase");
      } else {
        assert.match(patched.data.detail, /^\[sim\] NOT COVERED/,
          `site ${site}: a state that will not answer must say so as the simulation, ` +
          "not fall through to a payload from before the re-scan");
      }

      const { status, data: wizard } = await stale(`v1/sites/${site}/wizard/`);
      assert.equal(status, 200, `site ${site}'s wizard must still be readable`);
      assert.equal(wizard.can_materialize, false,
        `site ${site}: can_materialize under a blocking report`);
      assert.ok(schemas.WizardState.safeParse(wizard).success,
        `site ${site}: the converged wizard drifted from WizardState`);
    }
  });

test("r11-ux-f1: the converged wizard for takko/staging is the re-scanned one",
  async () => {
    // Not merely "not the live one": it has to be `_state(staging)` run against the
    // moved report, which means BOTH refusals — the blocker the re-scan introduced and
    // the domain nobody has typed — in preflight's own order.
    const stale = SIM_FIXTURES.stale as any;
    (SIM_FIXTURES.live as any).reset();
    stale.reset();

    const before = await stale("v1/sites/4/wizard/");
    assert.deepEqual(before.data.blocking.map((p: any) => p.code), ["answers_missing"],
      "before the refusal, the pre-rescan truth IS the truth");

    await stale("v1/sites/1/manifest/", {});

    const after = await stale("v1/sites/4/wizard/");
    assert.deepEqual(after.data.blocking.map((p: any) => p.code),
                     ["blockers_present", "answers_missing"]);
    const { data: report } = await stale("v1/projects/1/readiness/");
    const reported = new Set(report.blockers.map((c: any) => c.id));
    for (const problem of after.data.blocking) {
      if (problem.code !== "blockers_present") continue;
      for (const item of problem.items)
        assert.ok(reported.has(item.id),
          `the sibling wizard refuses on ${item.id}, which the report does not report`);
    }
  });

test("r11-ux-f1: the converged list does not forget another project's 201", async () => {
  // atlas-edge's manifest has nothing to do with takko's re-scan, and the converged list
  // named `EDGE_PROJECT` outright — so an operator who materialized atlas-edge and then
  // triggered takko's refusal watched the edge row lose the manifest it had just created.
  const stale = SIM_FIXTURES.stale as any;
  (SIM_FIXTURES.live as any).reset();
  stale.reset();

  const created = await stale("v1/sites/3/manifest/", { confirm_warnings: true });
  assert.equal(created.status, 201);
  await stale("v1/sites/1/manifest/", {});

  const list = (await stale("v1/projects/")).data;
  const edge = list.find((p: any) => p.name === "atlas-edge");
  assert.equal(edge.sites[0].latest_manifest_version, created.data.version,
    "the edge row forgot its own 201 when another project's report moved");
  for (const row of list)
    assert.ok(schemas.ProjectSummary.safeParse(row).success,
      `${row.name} drifted from ProjectSummary`);
});

test("r11-ux-f1: every refusal this simulation authors says it is the simulation",
  async () => {
    // The §4b rule sim.js lives under: it is a transcript of the server, so a sentence
    // invented here is the one kind of lie the no-client-authored-copy pin cannot catch.
    // A refusal it has to author anyway is marked, in the words `degraded` established.
    const stale = SIM_FIXTURES.stale as any;
    const live = SIM_FIXTURES.live as any;
    live.reset();
    stale.reset();
    await stale("v1/sites/1/manifest/", {});

    const authored = [
      await stale("v1/sites/4/manifest/", {}),
      await stale("v1/sites/1/wizard/",
                  { answers: { "site.domain": "x.example.com" } }, "PATCH"),
      await (SIM_FIXTURES.degraded as any)("v1/sites/5/manifest/", {}),
    ];
    for (const { status, data } of authored) {
      assert.ok(status >= 400, "a refusal that arrives as a 200 is not a refusal");
      assert.match(data.detail, /^\[sim\] /,
        "a synthetic response must say it is synthetic");
    }
  });

// ── R11-UX-F6: one captured manifest, pressed twice ──────────────────────────

test("r11-ux-f6: a second materialize is refused rather than replayed", async () => {
  // The captured 201 is one manifest. Pressing the button again replayed it: "Manifest
  // v4 created." twice, beside a list row that stayed at v4 — the one screen on this form
  // a real server cannot produce, because its next materialize is v5. One linear
  // generator session captures one manifest per site, so the honest answer to the second
  // press is that there is no payload for it.
  const live = SIM_FIXTURES.live as any;
  live.reset();

  const first = await live("v1/sites/1/manifest/", {});
  assert.equal(first.status, 201);

  const second = await live("v1/sites/1/manifest/", {});
  assert.notEqual(second.status, 201,
    "the same manifest version was created twice — no server does that");
  assert.match(second.data.detail, /^\[sim\] NOT COVERED: a second materialize/);

  // …and the row is unchanged by the refusal, which is the R10-UX-F3 property.
  const row = (await live("v1/projects/")).data.find((p: any) => p.name === "takko");
  assert.equal(row.sites[0].latest_manifest_version, first.data.version);
});

test("r12-a2: the takko site list is derived from the captured row, not typed", () => {
  // It was `[1, 4]` in sim.js and `[1, 4]` again in this file — two hand-typed copies of
  // a fact `CLEAN_PROJECT` already carries, in the pair of files whose whole rule is that
  // nothing in them is typed. The derivation is exported; this asserts it is a derivation
  // and not a literal that happens to agree, by comparing it against the payload the
  // simulation serves rather than against the numbers.
  const takko = (SIM_FIXTURES.live as any)("v1/projects/").data
    .find((p: any) => p.name === "takko");

  assert.deepEqual(TAKKO_SITES, takko.sites.map((s: any) => s.id));
  assert.ok(TAKKO_SITES.length >= 2,
    "the stale-state walk needs the sibling site the finding was about");
});
