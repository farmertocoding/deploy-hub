import React, { useEffect, useMemo, useState } from "react";
import { HudFrame } from "../../ui/HudFrame.jsx";
import { Status } from "../../ui/Status.jsx";
import { Button } from "../../ui/Button.jsx";
import { DESKTOP_MIN_PX } from "../../Chrome.jsx";
import { currentScope, defaultActionHandlers, hudGet, hudPost, parseHashQuery, writeHashQuery } from "./contract.js";
import { CollectionScreen } from "./CollectionScreen.jsx";
import { useHudActions } from "./useHudActions.js";
import { useHudLoad } from "./useHudLoad.js";

const DEFAULTS = { q: "", health: "", facet: "all", env: "", target: "", tls: "", sort: "name", page: "1" };

export function filtersFromHash(hash) {
  return parseHashQuery(hash, DEFAULTS);
}

export function writeFilters(values, loc) {
  const next = { ...DEFAULTS, ...values };
  const payload = { ...next };
  if (payload.facet === "all") payload.facet = "";
  return writeHashQuery(payload, loc, "#/admin/sites");
}

export async function sitesFleetSnapshot(params = {}) {
  const q = new URLSearchParams();
  ["q", "health", "facet", "env", "target", "tls", "sort", "page", "page_size", "export"].forEach((k) => {
    if (params[k] !== undefined && params[k] !== "") q.set(k, String(params[k]));
  });
  const suffix = q.toString() ? `?${q}` : "";
  return hudGet(`v1/hud/sites/${suffix}`);
}

export function SitesFleetView({
  rows = [],
  selectedId,
  onSelect,
  filters,
  onFilter,
  onNav,
  width = 1280,
  phase = "live",
  error,
  onRetry,
  asOf,
  pageInfo = {},
  collectionActions = [],
  actionHandlers,
  children,
  lastCommand,
}) {
  const selected = rows.find((r) => String(r.id) === String(selectedId));
  const columns = [
    { id: "project", label: "Project", sortable: true },
    { id: "name", label: "Site", sortable: true },
    { id: "environment", label: "Environment" },
    { id: "domain", label: "Domain", sortable: true },
    { id: "health", label: "Health", render: (row) => <Status state={row.health} /> },
    {
      id: "releases",
      label: "Live → desired",
      render: (row) => `${row.live_release || "unknown"} → ${row.desired_release || "unknown"}`,
    },
    { id: "target", label: "Target", sortable: true },
    { id: "tls", label: "TLS" },
    { id: "backup", label: "Backup" },
    { id: "copies", label: "Copies" },
    { id: "owner", label: "Owner" },
    { id: "actions", label: "Actions" },
  ];
  const phoneFallback = (
    <ul className="hud-phone-list">
      {rows.map((row) => (
        <li key={row.id}>
          <button type="button" className="hud-btn hud-btn--quiet" onClick={() => onSelect?.(row.id)}>
            {row.project}/{row.name} — {row.health}
          </button>
        </li>
      ))}
    </ul>
  );
  const handlers = actionHandlers || defaultActionHandlers({ onNav, onSelect, onCommand: (cmd) => {
    if (cmd.method === "GET" || cmd.path.includes("export=csv")) return sitesFleetSnapshot({ ...filters, export: "csv" });
    return cmd;
  } });
  return (
    <CollectionScreen
      title="Sites fleet"
      caption="Sites"
      columns={columns}
      rows={rows}
      filters={filters}
      onFilter={onFilter}
      filterDefs={[
        { id: "q", label: "Search", type: "text" },
        { id: "env", label: "Environment", type: "select", options: [
          { value: "", label: "Any" },
          { value: "production", label: "Production" },
          { value: "staging", label: "Staging" },
          { value: "preview", label: "Preview" },
        ] },
        { id: "health", label: "Health", type: "select", options: [
          { value: "", label: "Any" },
          { value: "healthy", label: "Healthy" },
          { value: "warming", label: "Warming" },
          { value: "unhealthy", label: "Unhealthy" },
          { value: "stale", label: "Stale" },
        ] },
        { id: "target", label: "Target", type: "text" },
        { id: "tls", label: "TLS", type: "select", options: [
          { value: "", label: "Any" },
          { value: "ok", label: "OK" },
          { value: "warning", label: "Warning" },
        ] },
        { id: "sort", label: "Sort", type: "select", options: [
          { value: "name", label: "Name" },
          { value: "project", label: "Project" },
          { value: "domain", label: "Domain" },
          { value: "health", label: "Health" },
          { value: "target", label: "Target" },
        ] },
      ]}
      facets={[
        { id: "all", label: "ALL" },
        { id: "needs_attention", label: "NEEDS ATTENTION" },
        { id: "active_deploy", label: "ACTIVE DEPLOY" },
      ]}
      collectionActions={collectionActions.map((action) => ({
        ...action,
        primary: action.id === "site.create",
      }))}
      actionHandlers={handlers}
      selectedId={selectedId}
      onSelect={onSelect}
      onNav={onNav}
      phase={phase}
      error={error}
      onRetry={onRetry}
      asOf={asOf}
      width={width}
      pageInfo={pageInfo}
      phoneFallback={width < DESKTOP_MIN_PX ? phoneFallback : null}
      emptySentence="No sites in this workspace — add a project on Home."
      emptyButton="Open Home"
      onEmpty={() => onNav("home")}
      inspector={selected && width >= DESKTOP_MIN_PX ? {
        body: (
          <div>
            <p>{selected.project}/{selected.name}</p>
            <Status state={selected.health} />
            <p>Live {selected.live_release} → desired {selected.desired_release}</p>
            {(selected.disabled_actions || []).map((a) => (
              <Button key={a.id} disabled disabledReason={a.reason}>{a.label}</Button>
            ))}
          </div>
        ),
      } : null}
      inspectorTitle="Site inspector"
    >
      {lastCommand?.result?.csv ? (
        <p role="status">
          Downloaded {lastCommand.result.filename || "sites.csv"}
          {lastCommand.result.count != null ? ` (${lastCommand.result.count} rows)` : ""}.
        </p>
      ) : null}
      {children}
    </CollectionScreen>
  );
}

export function AddSiteWizard({ onNav }) {
  const [error, setError] = useState("");
  const submit = async (event) => {
    event.preventDefault();
    const fields = Object.fromEntries(new FormData(event.target));
    try {
      const { status, data } = await hudPost("v1/hud/sites/commands/", { action: "site.create", ...fields });
      if (status === 201 || status === 202) {
        onNav?.("admin", data.id ? `sites/${data.id}` : "sites");
        return;
      }
      setError(data?.detail || `Unexpected ${status}`);
    } catch (err) {
      setError(err?.data?.detail || "Create failed");
    }
  };
  return (
    <HudFrame variant="panel">
      <h2 className="hud-kicker">ADD SITE</h2>
      <form className="hud-filter" onSubmit={submit}>
        <label>Project<input name="project" aria-label="Project" /></label>
        <label>Site name<input name="name" aria-label="Site name" /></label>
        <label>Domain<input name="domain" aria-label="Domain" /></label>
        <Button type="submit" variant="primary">Create site</Button>
      </form>
      {error ? <p className="hud-async__reason">{error}</p> : null}
    </HudFrame>
  );
}

export default function SitesFleet({ route, onNav, width }) {
  const initial = useMemo(() => filtersFromHash(), [route]);
  const [filters, setFilters] = useState(initial);
  const selectedId = route?.id?.includes("/") ? route.id.split("/")[1] : undefined;
  const { handlers, lastCommand } = useHudActions({
    onNav,
    onSelect: (id) => onNav("admin", id ? `sites/${id}` : "sites"),
  });
  const scope = currentScope(route);

  useEffect(() => {
    setFilters(filtersFromHash());
  }, [scope, route]);

  const { phase, data, error, retry, asOf } = useHudLoad(
    () => sitesFleetSnapshot(filters),
    [filters, scope],
  );

  const onFilter = (next) => {
    setFilters(next);
    writeFilters(next);
  };

  return (
    <SitesFleetView
      rows={data?.results || []}
      selectedId={selectedId}
      onSelect={(id) => onNav("admin", id ? `sites/${id}` : "sites")}
      filters={filters}
      onFilter={onFilter}
      onNav={onNav}
      width={width}
      phase={phase}
      error={error}
      onRetry={retry}
      asOf={asOf}
      pageInfo={{
        next: data?.next,
        count: data?.count,
        page: data?.page,
        sort: data?.sort,
      }}
      collectionActions={data?.allowed_actions || []}
      actionHandlers={handlers}
      lastCommand={lastCommand}
    >
      {selectedId === "new" ? <AddSiteWizard onNav={onNav} /> : null}
    </SitesFleetView>
  );
}
