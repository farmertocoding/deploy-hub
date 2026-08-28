import React, { useEffect, useState } from "react";
import { CollectionScreen } from "./CollectionScreen.jsx";
import { HudFrame } from "../../ui/HudFrame.jsx";
import { Status } from "../../ui/Status.jsx";
import { hudGet, parseHashQuery, writeHashQuery } from "./contract.js";
import { useHudActions } from "./useHudActions.js";

export function FindingsOpsView({
  rows = [],
  operations = [],
  phase = "live",
  error,
  onRetry,
  asOf,
  deniedReason,
  selectedId,
  onSelect,
  onNav,
  filters = {},
  onFilter,
  actionHandlers = {},
}) {
  return (
    <CollectionScreen
      title="Findings & Operations"
      caption="Findings"
      columns={[
        { id: "severity", label: "Severity", render: (row) => <Status state={row.severity} /> },
        { id: "state", label: "State" },
        { id: "title", label: "Title" },
        { id: "entity", label: "Entity" },
        { id: "source_engine", label: "Engine" },
        { id: "fingerprint", label: "Fingerprint" },
        { id: "actions", label: "Actions" },
      ]}
      rows={rows}
      facets={[
        { id: "all", label: "ALL" },
        { id: "p1p2", label: "Open P1/P2" },
      ]}
      filters={filters}
      onFilter={onFilter}
      actionHandlers={actionHandlers}
      selectedId={selectedId}
      onSelect={onSelect}
      onNav={onNav}
      phase={phase}
      error={error}
      onRetry={onRetry}
      asOf={asOf}
      deniedReason={deniedReason}
      emptySentence="No findings match this view."
      emptyButton="CLEAR"
      onEmpty={() => onFilter?.({ ...filters, facet: "all", q: "" })}
    >
      <HudFrame variant="panel">
        <h2 className="hud-kicker">Operations</h2>
        {(operations || []).length === 0 ? (
          <p>No running operations or held locks.</p>
        ) : operations.map((op) => (
          <p key={op.id}>
            <Status state={op.state} /> {op.kind} {op.object}
            {op.holder ? ` · ${op.holder}` : ""}
            {op.age_s != null ? ` · age ${Math.round(op.age_s)}s` : ""}
            {op.heartbeat_at ? ` · heartbeat ${op.heartbeat_at}` : ""}
          </p>
        ))}
      </HudFrame>
    </CollectionScreen>
  );
}

export default function FindingsOps({ route, onNav, width }) {
  const [rows, setRows] = useState([]);
  const [operations, setOperations] = useState([]);
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  const [asOf, setAsOf] = useState(null);
  const [tick, setTick] = useState(0);
  const hashQ = { ...(route?.query || {}), ...parseHashQuery() };
  const [filters, setFilters] = useState({
    facet: hashQ.facet || "all",
    entity: hashQ.entity || "",
    scope: hashQ.scope || "",
  });
  const objectId = (route?.id || "").split("/")[1];
  const { handlers } = useHudActions({ onNav });
  useEffect(() => {
    setFilters({
      facet: hashQ.facet || "all",
      entity: hashQ.entity || "",
      scope: hashQ.scope || "",
    });
  }, [hashQ.facet, hashQ.entity, hashQ.scope]);
  useEffect(() => {
    let cancelled = false;
    const q = new URLSearchParams();
    if (filters.facet && filters.facet !== "all") q.set("facet", filters.facet);
    if (filters.entity) q.set("entity", filters.entity);
    if (filters.scope) q.set("scope", filters.scope);
    const suffix = q.toString() ? `?${q}` : "";
    hudGet(`v1/hud/findings/${suffix}`, route).then((body) => {
      if (cancelled) return;
      setRows(body.results || []);
      setOperations(body.operations || []);
      setAsOf(body.observed_at);
      setPhase("live");
    }).catch((err) => {
      if (cancelled) return;
      setPhase(err.denied ? "permission-denied" : err.signedOut ? "signed-out" : "error");
      setError(err?.data?.detail || "HTTP error");
    });
    return () => { cancelled = true; };
  }, [filters, tick]);
  return (
    <FindingsOpsView
      rows={rows}
      operations={operations}
      phase={phase}
      error={error}
      asOf={asOf}
      onRetry={() => setTick((n) => n + 1)}
      selectedId={objectId}
      onSelect={(id) => onNav("admin", id ? `findings/${id}` : "findings")}
      onNav={onNav}
      filters={filters}
      actionHandlers={handlers}
      onFilter={(next) => {
        setFilters(next);
        writeHashQuery(next, undefined, "#/admin/findings");
      }}
      width={width}
    />
  );
}
