import React, { useEffect, useState } from "react";
import { CollectionScreen } from "./CollectionScreen.jsx";
import { currentScope, hudGet } from "./contract.js";

export function AuditView({
  rows = [],
  phase = "live",
  error,
  onRetry,
  asOf,
  deniedReason,
  onNav,
}) {
  return (
    <CollectionScreen
      title="Audit"
      caption="Audit events"
      columns={[
        { id: "ts", label: "Time" },
        { id: "actor", label: "Actor" },
        { id: "action", label: "Action" },
        { id: "object_type", label: "Object" },
        { id: "object_id", label: "ID" },
      ]}
      rows={rows}
      onNav={onNav}
      phase={phase}
      error={error}
      onRetry={onRetry}
      asOf={asOf}
      deniedReason={deniedReason}
      emptySentence="No audit events in this scope."
      emptyButton="View overview"
      onEmpty={() => onNav?.("admin", "overview")}
    />
  );
}

export default function Audit({ onNav, width, route }) {
  const [rows, setRows] = useState([]);
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  const [asOf, setAsOf] = useState(null);
  const [tick, setTick] = useState(0);
  const scope = currentScope(route);
  useEffect(() => {
    let cancelled = false;
    hudGet("v1/hud/audit/", route).then((body) => {
      if (cancelled) return;
      setRows(body.results || []);
      setAsOf(body.observed_at);
      setPhase("live");
    }).catch((err) => {
      if (cancelled) return;
      setPhase(err.denied ? "permission-denied" : err.signedOut ? "signed-out" : "error");
      setError(err?.data?.detail || "HTTP error");
    });
    return () => { cancelled = true; };
  }, [scope, tick]);
  return (
    <AuditView
      rows={rows}
      phase={phase}
      error={error}
      asOf={asOf}
      onNav={onNav}
      width={width}
      onRetry={() => setTick((n) => n + 1)}
    />
  );
}
