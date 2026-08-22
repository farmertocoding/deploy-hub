// The tier controls (§F5): what makeTierRunner's states LOOK like. Logic lives in
// actions.js; this file is markup only, exported so tests/actions.test.ts can render
// every state by props — the Readiness.jsx arrangement, for the same reason: the only
// way to assert markup is to render it, and a state inside a component is a state no
// renderToStaticMarkup test can reach.
import React, { useState } from "react";
import { makeTierRunner, presentation } from "./actions.js";

const box = { padding: 8, background: "#1a1d24", color: "#e6e6e6", border: "1px solid #333" };

// T2's confirm: the body is the caller's DIFF SUMMARY, verbatim — this component
// composes no copy about what the action will do, because the screen wiring it is the
// one that knows ("abc123 → def456, 2 migrations"). role="dialog" + the summary as
// visible text, not a tooltip (the R9-7 lesson, applied before the defect this time).
export function ConfirmDialog({ label, summary, onConfirm, onDismiss }) {
  return (
    <div role="dialog" aria-label={label}
      style={{ ...box, marginTop: 8, borderColor: "#e3b341" }}>
      <p style={{ marginTop: 0 }}>{summary}</p>
      <button style={{ ...box, marginRight: 8 }} onClick={onConfirm}>
        Confirm — {label}</button>
      <button style={box} onClick={onDismiss}>Cancel</button>
    </div>
  );
}

// T3's undo window: the action already RAN — this toast is the recovery of the
// recovery, visible for the whole window with the seconds named so the operator knows
// it is a window and not a permanent control. role="status": it appears where the
// operator is not looking, under the finger that just pressed the one-click action.
export function UndoToast({ label, seconds, onUndo }) {
  return (
    <div role="status"
      style={{ ...box, marginTop: 8, borderColor: "#7ee787", display: "inline-block" }}>
      ✓ {label} — <button style={box} onClick={onUndo}>Undo ({seconds} s)</button>
    </div>
  );
}

// One control per action, friction decided by the table row and nothing local:
// T3 renders a single button that runs on click and offers UndoToast; T2 renders a
// button that opens ConfirmDialog with the caller's `summary`; T1 renders a disabled
// control carrying its refusal as visible text (disabledBox reasoning from
// Readiness.jsx: an inline style overrides :disabled, so disabled must LOOK disabled).
export function ActionButton({ row, summary, onRun, onUndo }) {
  const [state, setState] = useState({ phase: "idle" });
  const [runner] = useState(() => makeTierRunner({
    row, onRun, onUndo: onUndo ?? (() => {}), onState: setState,
  }));
  const p = presentation(row);
  if (p.stepUp === "deferred") {
    return (
      <span>
        <button style={{ ...box, color: "#6e7681", background: "#15181e",
          borderColor: "#2a2e35", cursor: "not-allowed" }} disabled>{row.label}</button>
        {" "}<small style={{ color: "#8b949e" }}>
          requires step-up — lands in Phase 4</small>
      </span>
    );
  }
  return (
    <span style={{ marginRight: 8 }}>
      <button style={box} onClick={() => runner.click()}>{row.label}</button>
      {state.phase === "confirming" && (
        <ConfirmDialog label={row.label} summary={summary}
          onConfirm={() => runner.confirm()} onDismiss={() => runner.dismiss()} />
      )}
      {state.phase === "undoable" && (
        <UndoToast label={row.label} seconds={state.until_s}
          onUndo={() => runner.undo()} />
      )}
    </span>
  );
}
