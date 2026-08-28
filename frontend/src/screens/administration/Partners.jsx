import React from "react";
import { CollectionScreen } from "./CollectionScreen.jsx";
import { Status } from "../../ui/Status.jsx";
import { currentScope, hudGet } from "./contract.js";
import { useHudActions } from "./useHudActions.js";
import { useHudLoad } from "./useHudLoad.js";

export function PartnersView({
  rows = [],
  collectionActions = [],
  phase = "live",
  error,
  onRetry,
  asOf,
  deniedReason,
  onReloadPermissions,
  selectedId,
  onSelect,
  onNav,
  actionHandlers = {},
  pending,
  onConfirmPending,
  onCancelPending,
}) {
  return (
    <CollectionScreen
      title="Partners"
      caption="Partners"
      columns={[
        { id: "slug", label: "Slug" },
        { id: "name", label: "Name" },
        { id: "status", label: "Status", render: (row) => <Status state={row.suspended ? "failed" : "active"} /> },
        { id: "sites", label: "Sites" },
        { id: "actions", label: "Actions" },
      ]}
      rows={rows}
      collectionActions={collectionActions.map((a) => ({
        ...a,
        primary: a.id === "partner.create",
      }))}
      actionHandlers={actionHandlers}
      pending={pending}
      onConfirmPending={onConfirmPending}
      onCancelPending={onCancelPending}
      selectedId={selectedId}
      onSelect={onSelect}
      onNav={onNav}
      phase={phase}
      error={error}
      onRetry={onRetry}
      asOf={asOf}
      deniedReason={deniedReason}
      onReloadPermissions={onReloadPermissions}
      emptySentence="No partners registered."
      emptyButton="Create Partner"
      inspector={selectedId ? {
        body: (() => {
          const row = rows.find((r) => String(r.id) === String(selectedId));
          if (!row) return <p>Select a partner.</p>;
          return (
            <div>
              <p>{row.name} ({row.slug})</p>
              <p>Intake {row.intake || "unknown"}</p>
              <p>Affected sites: {(row.affected_sites || []).join(", ") || "none"}</p>
              {row.suspended ? <p>Suspended — Sites stay listed until recovered.</p> : null}
            </div>
          );
        })(),
      } : null}
    />
  );
}

export default function Partners({ route, onNav, width, onReloadPermissions }) {
  const objectId = (route?.id || "").split("/")[1];
  const { pending, handlers, onCancelPending, onConfirmPending } = useHudActions({ onNav });
  const scope = currentScope(route);
  const { phase, data, error, retry, asOf } = useHudLoad(
    () => hudGet("v1/hud/partners/", route),
    [scope],
  );
  return (
    <PartnersView
      rows={data?.results || []}
      collectionActions={data?.allowed_actions || [{ id: "partner.create", label: "Create Partner" }]}
      phase={phase}
      error={error}
      asOf={asOf}
      onRetry={retry}
      onReloadPermissions={onReloadPermissions}
      selectedId={objectId}
      onSelect={(id) => onNav("admin", id ? `partners/${id}` : "partners")}
      onNav={onNav}
      actionHandlers={handlers}
      pending={pending}
      onCancelPending={onCancelPending}
      onConfirmPending={onConfirmPending}
      width={width}
    />
  );
}
