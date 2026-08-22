// UX-F5-T2-T3-FRICTION, client half (the buildable §F5 clauses, D-040): ONE
// declarative tier table decides the friction, T2 confirms with the caller's diff
// summary, T3 is a single click with an undo window and can NEVER grow a step-up,
// and T1 renders as an explicit refusal because its flow is Phase 4's
// (SEC-F5-T1-HARDWARE-TOUCH) — the client does not improvise a weaker one.
//
// The pytest markers for the req id land with core/actions.py (Tasks 4/13), when the
// table has a server half to be one-source with; these tests pin the client half now.
import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ACTION_TIERS, makeTierRunner, presentation, tierFor } from "../src/actions.js";
import { ActionButton, ConfirmDialog, UndoToast } from "../src/Tiers.jsx";

(globalThis as any).window = (globalThis as any).window ?? { location: { search: "" } };

const render = (component: any, props: any) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

function timers() {
  const pending = new Map<number, { fn: () => void; at: number }>();
  let nextId = 1;
  return {
    schedule: (fn: any, ms: number) => { const id = nextId++; pending.set(id, { fn, at: ms }); return id; },
    cancel: (id: number) => pending.delete(id),
    fire: () => { for (const [id, p] of [...pending]) { pending.delete(id); p.fn(); } },
    size: () => pending.size,
  };
}

test("rollback_restart_and_rerun_are_t3_and_never_behind_step_up", () => {
  // §F5's hard rule: the recovery actions are deliberately the LOWEST-friction
  // actions in the product, because they're needed at 2 a.m. from a phone.
  for (const id of ["site.rollback", "site.restart", "check.rerun"]) {
    const row = tierFor(id);
    assert.equal(row.tier, "T3", id);
    assert.deepEqual(presentation(row), { confirm: false, undo: true, stepUp: "none" },
      `${id} grew friction beyond one click + undo`);
    assert.ok(row.undo_window_s >= 5, `${id}'s undo window is too small to reach`);
  }
  // …and the rule holds for every T3 row the table will ever hold, not three names.
  for (const row of ACTION_TIERS.filter((r) => r.tier === "T3")) {
    assert.equal(presentation(row).stepUp, "none", `${row.id} is T3 behind a step-up`);
    assert.equal(presentation(row).confirm, false, `${row.id} is T3 behind a confirm`);
  }
});

test("deploy_and_dns_change_are_t2_with_a_confirm", () => {
  for (const id of ["site.deploy", "dns.change", "site.auto_mode"]) {
    const row = tierFor(id);
    assert.equal(row.tier, "T2", id);
    assert.deepEqual(presentation(row), { confirm: true, undo: false, stepUp: "none" });
  }
});

test("t1_rows_are_named_and_refused_not_weakened", () => {
  // target delete / key export / KEK ops are in the table NOW so no screen can
  // quietly ship them at a lower tier — but their step-up flow is Phase 4's, so the
  // client refuses rather than rendering a confirm that pretends to be one.
  for (const id of ["target.delete", "key.export", "kek.rotate"]) {
    assert.equal(tierFor(id).tier, "T1", id);
    assert.equal(presentation(tierFor(id)).stepUp, "deferred", id);
  }
  const ran: string[] = [];
  const runner = makeTierRunner({ row: tierFor("target.delete"),
    onRun: () => ran.push("ran"), onUndo: () => {} });
  runner.click();
  assert.deepEqual(ran, [], "a T1 action executed without any step-up at all");
  assert.equal(runner.state.phase, "refused");
  assert.match(runner.state.reason, /Phase 4/);
});

test("t2_click_confirms_before_running_and_dismiss_runs_nothing", () => {
  const ran: any[] = [];
  const runner = makeTierRunner({ row: tierFor("site.deploy"),
    onRun: (args: any) => ran.push(args), onUndo: () => {} });

  runner.click({ version: 4 });
  assert.equal(runner.state.phase, "confirming");
  assert.deepEqual(ran, [], "T2 ran on the first click — the confirm is the tier");

  runner.dismiss();
  assert.equal(runner.state.phase, "idle");
  assert.deepEqual(ran, [], "dismissing the confirm still ran the action");

  runner.click({ version: 4 });
  runner.confirm();
  assert.deepEqual(ran, [{ version: 4 }]);
  assert.equal(runner.state.phase, "idle", "T2 has no undo window to linger in");
});

test("t3_runs_on_one_click_with_an_undo_window", () => {
  const t = timers();
  const calls: string[] = [];
  const runner = makeTierRunner({ row: tierFor("site.rollback"),
    onRun: () => calls.push("run"), onUndo: () => calls.push("undo"),
    schedule: t.schedule, cancel: t.cancel });

  runner.click();
  assert.deepEqual(calls, ["run"], "T3 is ONE click — no dialog before the action");
  assert.equal(runner.state.phase, "undoable");
  assert.equal(runner.state.until_s, tierFor("site.rollback").undo_window_s);

  runner.undo();
  assert.deepEqual(calls, ["run", "undo"]);
  assert.equal(runner.state.phase, "idle");
  assert.equal(t.size(), 0, "the expiry timer outlived the undo that cancelled it");

  // The window EXPIRING closes the offer without inventing an undo.
  runner.click();
  t.fire();
  assert.deepEqual(calls, ["run", "undo", "run"]);
  assert.equal(runner.state.phase, "idle");
  runner.undo();
  assert.deepEqual(calls, ["run", "undo", "run"], "undo worked after its window closed");
});

test("the_tier_controls_render_what_the_runner_decides", () => {
  // T2's dialog carries the CALLER'S diff summary verbatim — this component composes
  // no copy about what the action does, because the screen wiring it is what knows.
  const dialog = render(ConfirmDialog, { label: "Deploy",
    summary: "abc123 → def456, 2 migrations", onConfirm: () => {}, onDismiss: () => {} });
  assert.match(dialog, /role="dialog"/);
  assert.ok(visibleText(dialog).includes("abc123 → def456, 2 migrations"));
  assert.ok(visibleText(dialog).includes("Cancel"));

  // T3's toast names the window in seconds and is announced (it appears where the
  // operator is not looking — under the finger that just pressed the action).
  const toast = render(UndoToast, { label: "Roll back", seconds: 10, onUndo: () => {} });
  assert.match(toast, /role="status"/);
  assert.ok(visibleText(toast).includes("Undo (10 s)"));

  // A T1 control is visibly dead with its reason as text — and claims nothing about
  // hardware, because the hardware clause is Phase 4's and unbuilt (D-040).
  const t1 = render(ActionButton, { row: tierFor("key.export"), onRun: () => {} });
  assert.match(t1, /disabled=""/);
  assert.ok(visibleText(t1).includes("requires step-up — lands in Phase 4"));
  assert.ok(!/hardware/i.test(t1), "the unbuilt hardware clause is being claimed");

  // A T3 control at rest is one plain button: no dialog, no toast, no extra step.
  const t3 = render(ActionButton, { row: tierFor("site.rollback"), onRun: () => {} });
  assert.ok(!/role="dialog"/.test(t3));
  assert.equal(visibleText(t3).trim(), "Roll back");
});

test("a_mounted_action_button_reads_current_props_not_first_render_ones", async () => {
  // The review finding on the Task 13 contract: the runner is one-shot, and built
  // over first-render closures it would run the action with the props of the MOUNT.
  // SiteStatus passes `onRun={() => onRun(id, site)}` and `site` is socket-refreshed
  // data — a rollback pressed ten minutes after mount must roll back what the screen
  // shows, not what it showed. This needs a real mounted tree, so it is the one test
  // in this file on react-test-renderer rather than renderToStaticMarkup.
  (globalThis as any).IS_REACT_ACT_ENVIRONMENT = true;
  const { act, create } = await import("react-test-renderer");

  const ran: string[] = [];
  const undone: string[] = [];
  const el = (version: string) => React.createElement(ActionButton, {
    row: tierFor("site.rollback"),
    onRun: () => ran.push(version), onUndo: () => undone.push(version),
  });

  let tree: any;
  act(() => { tree = create(el("mount-time")); });
  act(() => { tree.update(el("current")); });

  act(() => { tree.root.findAllByType("button")[0].props.onClick(); });
  assert.deepEqual(ran, ["current"],
    "the runner ran the action over the props it was mounted with");

  // …and the undo half reads through the same ref: refresh again, then undo.
  // (Undoing also cancels the real 10 s expiry timer, so nothing outlives the test.)
  act(() => { tree.update(el("newer-still")); });
  const undo = tree.root.findAllByType("button")
    .find((b: any) => /Undo/.test(b.children.join("")));
  act(() => { undo.props.onClick(); });
  assert.deepEqual(undone, ["newer-still"]);
  act(() => { tree.unmount(); });
});
