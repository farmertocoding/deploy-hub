// The tier controls (§F5): what makeTierRunner's states LOOK like. Logic lives in
// actions.js; this file is markup only, exported so tests/actions.test.ts can render
// every state by props — the Readiness.jsx arrangement, for the same reason: the only
// way to assert markup is to render it, and a state inside a component is a state no
// renderToStaticMarkup test can reach.
import React, { useRef, useState } from "react";
import { makeTierRunner, presentation } from "./actions.js";
import { performHardwareTouch } from "./webauthn.js";

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

function costLine(cost) {
  if (cost == null || cost === "") return "";
  const symbol = typeof cost === "number" ? `$${cost.toFixed(2)}/h` : String(cost);
  const n = typeof cost === "number"
    ? cost
    : Number(String(cost).replace(/[^0-9.]/g, ""));
  if (n === 0.05 || symbol.includes("0.05")) {
    return `${symbol} — five cents per hour`;
  }
  return symbol;
}

export function T1Overlay({ label, cost, summary, onTouch, onConfirm, onDismiss }) {
  const [name, setName] = useState("");
  const costText = costLine(cost);
  return (
    <div role="dialog" aria-label={`${label} step-up`}
      style={{ ...box, marginTop: 8, borderColor: "#ff7b72", maxWidth: "100%" }}>
      <p style={{ marginTop: 0 }}>
        Type the name and touch a security key. TOTP cannot satisfy this.
      </p>
      {summary ? <p>{summary}</p> : null}
      {costText ? (
        <p>Estimated hourly cost {costText}.</p>
      ) : null}
      <input aria-label="type the name" value={name} style={box}
        placeholder="type the name"
        onChange={(e) => setName(e.target.value)} />
      <div style={{ marginTop: 8 }}>
        <button style={{ ...box, marginRight: 8 }} onClick={onTouch}>
          Touch security key</button>
        <button style={{ ...box, marginRight: 8 }}
          onClick={() => onConfirm({ name })}>Confirm — {label}</button>
        <button style={box} onClick={onDismiss}>Cancel</button>
      </div>
    </div>
  );
}

// One control per action, friction decided by the table row and nothing local:
// T3 renders a single button that runs on click and offers UndoToast; T2 renders a
// button that opens ConfirmDialog with the caller's `summary`; T1 opens the
// type-the-name + hardware-touch overlay (SEC-F5-T1-HARDWARE-TOUCH).
export function ActionButton({ row, summary, confirmName, cost, onRun, onUndo }) {
  const [state, setState] = useState({ phase: "idle" });
  // The runner is one-shot (it owns the tier state machine for this control's
  // lifetime) but its callbacks read THROUGH this ref, refreshed every render —
  // a runner built over first-render closures would invoke the action with the
  // props of the mount, and this shell's whole point is socket-refreshed data
  // (review finding on the Task 13 contract: SiteStatus passes
  // `onRun={() => onRun(id, site)}`, and `site` moves). The ROW stays frozen on
  // purpose: a mounted control changing which action it is would be a different
  // defect, and the tier table is static.
  const callbacksRef = useRef({ onRun, onUndo });
  callbacksRef.current = { onRun, onUndo };
  const [runner] = useState(() => makeTierRunner({
    row,
    onRun: (args) => callbacksRef.current.onRun(args),
    onUndo: () => callbacksRef.current.onUndo?.(),
    onState: setState,
  }));
  const p = presentation(row);
  // partner.create and other partner T1 ids omit cost; optional T2-shaped summary.
  if (p.stepUp === "required") {
    return (
      <span style={{ marginRight: 8 }}>
        <button style={box} onClick={() => runner.click({ expected: confirmName })}>
          {row.label}</button>
        {state.phase === "steppingUp" && (
          <T1Overlay label={row.label}
            cost={row.id.startsWith("partner.") ? undefined : cost}
            summary={row.id.startsWith("partner.") ? summary : undefined}
            onTouch={async () => {
              const { status } = await performHardwareTouch();
              if (status === 200) runner.touch();
            }}
            onConfirm={(payload) => runner.confirmStepUp(payload)}
            onDismiss={() => runner.dismiss()} />
        )}
        {state.phase === "refused" && (
          <small style={{ color: "#ff7b72" }}> {state.reason}</small>
        )}
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
