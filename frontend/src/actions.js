// §F5's action-tier table, client half (UX-F5-T2-T3-FRICTION — the buildable
// clauses, D-040). ONE declarative table decides how much friction an action gets:
//
//   T2 disruptive-reversible  → one confirm dialog summarizing the diff
//   T3 recovery               → single click + undo toast, NEVER behind step-up —
//                               deliberately the lowest-friction actions in the
//                               product, because they're needed at 2 a.m. from a phone
//   T1 irreversible           → type-the-name + require_recent_touch. stepUp is
//                               "required": a WebAuthn touch plus typing the name
//                               runs the action; TOTP is not a substitute.
//
// ACTION_TIERS is generated from core/actions.py into src/api/action_tiers.js
// (`make generate-client`). This file keeps presentation + the runner.

import { ACTION_TIERS } from "./api/action_tiers.js";

export { ACTION_TIERS };

export function tierFor(actionId) {
  const row = ACTION_TIERS.find((r) => r.id === actionId);
  if (!row) throw new Error(`unknown action: ${actionId} — add it to ACTION_TIERS`);
  return row;
}

// What each tier RENDERS AS, derived from the table and nothing else. `stepUp` has
// two values on purpose: "none" (T2/T3 — §F5's hard rule is that T3 can NEVER grow a
// step-up, and this is the single place a refactor would have to break) and
// "required" (T1 — WebAuthn hardware touch + type-the-name).
export function presentation(row) {
  if (row.tier === "T3") return { confirm: false, undo: true, stepUp: "none" };
  if (row.tier === "T2") return { confirm: true, undo: false, stepUp: "none" };
  return { confirm: false, undo: false, stepUp: "required" };
}

// The runner: one state machine for both built tiers, so a screen wires an action by
// tier row + callbacks and never re-derives the friction rules. States:
//
//   idle → (T2 click) confirming → (confirm) run → idle
//   idle → (T3 click) run immediately → undoable(window) → (undo) onUndo → idle
//                                                        → (expiry) idle
//   idle → (T1 click) steppingUp → (touch + type-the-name) run → idle
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
      if (p.stepUp === "required") {
        set({ phase: "steppingUp", args: args ?? {}, typed: "", touched: false });
        return;
      }
      if (p.confirm) { set({ phase: "confirming", args }); return; }
      run(args);
    },
    totp() {
      // TOTP authenticates login, never T1 (D-062). Leave the overlay in place.
    },
    touch() {
      if (state.phase !== "steppingUp") return;
      set({ ...state, touched: true });
    },
    confirmStepUp({ name } = {}) {
      if (state.phase !== "steppingUp") return;
      const expected = state.args?.expected;
      if (!state.touched || !name || (expected !== undefined && name !== expected)) {
        set({ ...state, phase: "refused",
              reason: "Requires hardware touch and type-the-name." });
        return;
      }
      run({ ...state.args, name });
    },
    confirm() {
      if (state.phase !== "confirming") return;
      run(state.args);
    },
    dismiss() {
      if (state.phase === "confirming" || state.phase === "steppingUp") set({ phase: "idle" });
    },
    undo() {
      if (state.phase !== "undoable") return;
      if (undoTimer !== null) { cancel(undoTimer); undoTimer = null; }
      onUndo();
      set({ phase: "idle" });
    },
  };
}
