// §F5's action-tier table, client half (UX-F5-T2-T3-FRICTION — the buildable
// clauses, D-040). ONE declarative table decides how much friction an action gets:
//
//   T2 disruptive-reversible  → one confirm dialog summarizing the diff
//   T3 recovery               → single click + undo toast, NEVER behind step-up —
//                               deliberately the lowest-friction actions in the
//                               product, because they're needed at 2 a.m. from a phone
//   T1 irreversible           → type-the-name + require_recent_touch. NOT BUILT this
//                               phase: the step-up flow lands with WebAuthn in Phase 4
//                               (SEC-F5-T1-HARDWARE-TOUCH), so a T1 action renders as
//                               an explicit refusal, not as a weaker confirm.
//
// This table becomes the generated mirror of core/actions.py when Task 4 regenerates
// the schema (test_client_and_server_tier_tables_are_one_source lands there); until
// then it is the client's single source and tests/actions.test.ts pins its shape.
// The endpoints behind rollback/restart/re-run do not exist yet either — they land
// with Tasks 4/13 — so the rows are the CONTRACT the screens already render against,
// and the one mutating action the product has today (the developer-tab demo launch)
// is wired through the same machinery so it is exercised live, not only in tests.

export const ACTION_TIERS = [
  // T3 — recovery. `undo_window_s` is how long the undo toast stays actionable.
  { id: "site.rollback", tier: "T3", label: "Roll back", undo_window_s: 10 },
  { id: "site.restart", tier: "T3", label: "Restart", undo_window_s: 10 },
  { id: "check.rerun", tier: "T3", label: "Re-run check", undo_window_s: 10 },
  // T2 — disruptive-reversible. The confirm body is the DIFF SUMMARY the caller
  // supplies ("abc123 → def456, 2 migrations"), never a bare "are you sure".
  { id: "site.deploy", tier: "T2", label: "Deploy" },
  { id: "dns.change", tier: "T2", label: "Change DNS" },
  { id: "site.auto_mode", tier: "T2", label: "Toggle auto-mode" },
  { id: "demo.launch", tier: "T2", label: "Launch demo job" },
  // T1 — irreversible/credential-touching. Named now so no screen can quietly ship
  // them at a lower tier later; presented as a refusal until Phase 4.
  { id: "target.delete", tier: "T1", label: "Delete target" },
  { id: "key.export", tier: "T1", label: "Export key" },
  { id: "kek.rotate", tier: "T1", label: "Rotate KEK" },
];

export function tierFor(actionId) {
  const row = ACTION_TIERS.find((r) => r.id === actionId);
  if (!row) throw new Error(`unknown action: ${actionId} — add it to ACTION_TIERS`);
  return row;
}

// What each tier RENDERS AS, derived from the table and nothing else. `stepUp` has
// two values on purpose: "none" (T2/T3 — §F5's hard rule is that T3 can NEVER grow a
// step-up, and this is the single place a refactor would have to break) and
// "deferred" (T1 — the flow is Phase 4's, so the client refuses rather than improvises
// a weaker one).
export function presentation(row) {
  if (row.tier === "T3") return { confirm: false, undo: true, stepUp: "none" };
  if (row.tier === "T2") return { confirm: true, undo: false, stepUp: "none" };
  return { confirm: false, undo: false, stepUp: "deferred" };
}

// The runner: one state machine for both built tiers, so a screen wires an action by
// tier row + callbacks and never re-derives the friction rules. States:
//
//   idle → (T2 click) confirming → (confirm) run → idle
//   idle → (T3 click) run immediately → undoable(window) → (undo) onUndo → idle
//                                                        → (expiry) idle
//   (T1 click) → refused, nothing runs
//
// Injected timers for the same reason createEventsClient takes them: the undo window
// is the safety property, and a window nothing can advance is a window no test pins.
export function makeTierRunner({ row, onRun, onUndo, onState = () => {},
                                 schedule = (fn, ms) => setTimeout(fn, ms),
                                 cancel = (id) => clearTimeout(id) }) {
  const p = presentation(row);
  let state = { phase: "idle" };
  let undoTimer = null;
  const set = (next) => { state = next; onState(state); };

  function run(args) {
    onRun(args);
    if (p.undo) {
      const windowMs = (row.undo_window_s ?? 10) * 1000;
      undoTimer = schedule(() => { undoTimer = null; set({ phase: "idle" }); },
        windowMs);
      set({ phase: "undoable", until_s: row.undo_window_s ?? 10 });
    } else {
      set({ phase: "idle" });
    }
  }

  return {
    get state() { return state; },
    click(args) {
      if (p.stepUp === "deferred") {
        set({ phase: "refused",
              reason: "Requires step-up — this flow lands in Phase 4." });
        return;
      }
      if (p.confirm) { set({ phase: "confirming", args }); return; }
      run(args);
    },
    confirm() {
      if (state.phase !== "confirming") return;
      run(state.args);
    },
    dismiss() {
      if (state.phase === "confirming") set({ phase: "idle" });
    },
    undo() {
      if (state.phase !== "undoable") return;
      if (undoTimer !== null) { cancel(undoTimer); undoTimer = null; }
      onUndo();
      set({ phase: "idle" });
    },
  };
}
