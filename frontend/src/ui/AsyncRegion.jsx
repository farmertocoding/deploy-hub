import React from "react";
import { Button } from "./Button.jsx";

export function AsyncRegion({
  phase = "live",
  what = "data",
  error,
  onRetry,
  asOf,
  children,
  deniedReason,
  onReloadPermissions,
  onReturnToOperator,
  onSignIn,
}) {
  if (phase === "loading") {
    return <p className="hud-async">Loading {what}…</p>;
  }
  if (phase === "signed-out") {
    return (
      <div className="hud-denied" role="alert">
        <p>Session expired — sign in to continue.</p>
        {onSignIn ? <Button onClick={onSignIn}>Sign in</Button> : null}
      </div>
    );
  }
  if (phase === "permission-denied") {
    return (
      <div className="hud-denied" role="alert">
        <p>Permission denied{deniedReason ? ` — ${deniedReason}` : "."}</p>
        <Button onClick={onReloadPermissions}>Reload permissions</Button>
        {onReturnToOperator ? <Button onClick={onReturnToOperator}>Return to Operator Console</Button> : null}
      </div>
    );
  }
  if (phase === "error") {
    return (
      <div className="hud-async" role="alert">
        <p className="hud-async__reason">{error || `Could not load ${what}.`}</p>
        {onRetry ? <Button onClick={onRetry}>Retry</Button> : null}
      </div>
    );
  }
  if (phase === "not-found") {
    return <p className="hud-async">Not found — this record is gone or you cannot see it.</p>;
  }
  if (phase === "conflict") {
    return (
      <div className="hud-async" role="alert">
        <p className="hud-async__reason">{error || "This record changed. Refresh the authoritative state."}</p>
        {onRetry ? <Button onClick={onRetry}>Refresh</Button> : null}
      </div>
    );
  }
  return (
    <div className="hud-async" data-phase={phase}>
      {phase === "degraded" && asOf ? (
        <p className="hud-async__stale" role="status">
          ⚠ degraded — data as of {new Date(asOf).toLocaleTimeString([], { hour12: false })}
        </p>
      ) : null}
      {children}
    </div>
  );
}
