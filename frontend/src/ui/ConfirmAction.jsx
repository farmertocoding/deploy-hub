import React, { useEffect, useRef } from "react";
import { HudFrame } from "./HudFrame.jsx";
import { Button } from "./Button.jsx";

export function ConfirmAction({
  label,
  summary,
  action,
  objectId,
  current,
  proposed,
  affected,
  interruption,
  rollback,
  policy,
  refusal,
  onConfirm,
  onDismiss,
}) {
  const dialogRef = useRef(null);
  useEffect(() => {
    const node = dialogRef.current;
    const previous = typeof document !== "undefined" ? document.activeElement : null;
    const focusables = node?.querySelectorAll?.("button, [href], input, select, textarea") || [];
    if (focusables[0]) focusables[0].focus();
    const onKey = (event) => {
      if (event.key === "Escape") {
        event.preventDefault();
        onDismiss?.();
      }
      if (event.key !== "Tab" || !focusables.length) return;
      const first = focusables[0];
      const last = focusables[focusables.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    node?.addEventListener?.("keydown", onKey);
    return () => {
      node?.removeEventListener?.("keydown", onKey);
      if (previous && typeof previous.focus === "function") previous.focus();
    };
  }, [onDismiss]);
  const affectedList = Array.isArray(affected) ? affected : (affected ? [affected] : []);
  return (
    <div className="hud-modal-backdrop" onClick={onDismiss}>
      <HudFrame variant="critical">
        <div
          ref={dialogRef}
          role="dialog"
          aria-modal="true"
          aria-label={label}
          onClick={(e) => e.stopPropagation()}
        >
          <p>{summary}</p>
          {action ? <p>Action {action}{objectId != null ? ` on ${objectId}` : ""}</p> : null}
          {current != null || proposed != null ? (
            <p>Current {current || "—"} → proposed {proposed || "—"}</p>
          ) : null}
          {affectedList.length ? (
            <p>Affected: {affectedList.map((item) => item.name || item).join(", ")}</p>
          ) : null}
          <p>{interruption || "No interruption is expected unless the server says otherwise."}</p>
          <p>Rollback: {rollback || "not named"}</p>
          {policy ? <p>Policy: {policy}</p> : null}
          {refusal ? <p className="hud-async__reason">{refusal}</p> : null}
          <Button variant="primary" onClick={onConfirm} disabled={Boolean(refusal)}>
            Confirm — {label}
          </Button>
          {" "}
          <Button onClick={onDismiss}>Cancel</Button>
        </div>
      </HudFrame>
    </div>
  );
}
