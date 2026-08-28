import React, { useEffect, useState } from "react";
import { CollectionScreen } from "./CollectionScreen.jsx";
import { Status } from "../../ui/Status.jsx";
import { hudGet, parseHashQuery, writeHashQuery } from "./contract.js";

export function DeploymentsView({
  rows = [],
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
}) {
  return (
    <CollectionScreen
      title="Deployments"
      caption="Deployments"
      columns={[
        { id: "id", label: "ID" },
        { id: "site", label: "Project/Site" },
        { id: "version", label: "Release" },
        { id: "state", label: "Status", render: (row) => <Status state={row.state} /> },
        { id: "current_step", label: "Current step" },
        { id: "actions", label: "Actions" },
      ]}
      rows={rows}
      facets={[
        { id: "all", label: "ALL" },
        { id: "active", label: "Active" },
        { id: "needs_attention", label: "Needs attention" },
      ]}
      filters={filters}
      onFilter={onFilter}
      selectedId={selectedId}
      onSelect={(id) => {
        onSelect?.(id);
        if (id) onNav?.("admin", `deployments/${id}`);
      }}
      onNav={onNav}
      phase={phase}
      error={error}
      onRetry={onRetry}
      asOf={asOf}
      deniedReason={deniedReason}
      emptySentence="No deployments in this workspace."
      emptyButton="View sites"
      onEmpty={() => onNav?.("admin", "sites")}
    />
  );
}

export default function Deployments({ route, onNav, width }) {
  const [rows, setRows] = useState([]);
  const [phase, setPhase] = useState("loading");
  const [error, setError] = useState("");
  const [asOf, setAsOf] = useState(null);
  const [tick, setTick] = useState(0);
  const hashQ = { ...(route?.query || {}), ...parseHashQuery() };
  const [filters, setFilters] = useState({ facet: hashQ.facet || "all" });
  useEffect(() => {
    setFilters({ facet: hashQ.facet || "all" });
  }, [hashQ.facet]);
  useEffect(() => {
    let cancelled = false;
    const q = filters.facet && filters.facet !== "all" ? `?facet=${encodeURIComponent(filters.facet)}` : "";
    hudGet(`v1/hud/deployments/${q}`, route).then((body) => {
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
  }, [filters, hashQ.scope, tick]);
  return (
    <DeploymentsView
      rows={rows}
      phase={phase}
      error={error}
      asOf={asOf}
      onRetry={() => setTick((n) => n + 1)}
      onNav={onNav}
      filters={filters}
      onFilter={(next) => {
        setFilters(next);
        writeHashQuery(next, undefined, "#/admin/deployments");
      }}
      width={width}
    />
  );
}
