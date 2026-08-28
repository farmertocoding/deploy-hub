import React from "react";
import { CollectionScreen } from "./CollectionScreen.jsx";
import { Status } from "../../ui/Status.jsx";
import { currentScope, hudGet } from "./contract.js";
import { useHudActions } from "./useHudActions.js";
import { useHudLoad } from "./useHudLoad.js";

export function TargetsView({
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
      title="Targets"
      caption="Targets"
      columns={[
        { id: "host", label: "Host" },
        { id: "kind", label: "Kind" },
        { id: "zone", label: "Zone" },
        { id: "status", label: "Status", render: (row) => <Status state={row.status} /> },
        { id: "lifecycle", label: "Lifecycle" },
        { id: "sites", label: "Hosted sites" },
        { id: "actions", label: "Actions" },
      ]}
      rows={rows}
      collectionActions={collectionActions.map((a) => ({
        ...a,
        primary: a.id === "target.create",
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
      onReturnToOperator={() => onNav?.("home")}
      emptySentence="No targets enrolled — copy the provision command from Operator Console Targets."
      emptyButton="Open Targets"
      onEmpty={() => onNav?.("targets")}
      inspector={selectedId ? {
        body: (() => {
          const row = rows.find((r) => String(r.id) === String(selectedId));
          if (!row) return <p>Select a target.</p>;
          return (
            <div>
              <p>{row.host}</p>
              <Status state={row.status} />
              <p>{row.kind} in {row.zone}</p>
            </div>
          );
        })(),
      } : null}
      inspectorTitle="Target"
    />
  );
}

export default function Targets({ route, onNav, width, onReloadPermissions }) {
  const objectId = (route?.id || "").split("/")[1];
  const scope = currentScope(route);
  const { pending, handlers, onCancelPending, onConfirmPending } = useHudActions({
    onNav,
    onSelect: (id) => onNav("admin", id ? `targets/${id}` : "targets"),
  });
  const { phase, data, error, retry, asOf } = useHudLoad(
    () => hudGet("v1/hud/targets/", route),
    [scope],
  );
  const rows = data?.results || [];
  const actions = data?.allowed_actions || [{ id: "target.create", label: "Create Target" }];
  return (
    <div data-fetched-scope={scope || "production"}>
    <TargetsView
      rows={rows}
      collectionActions={actions}
      phase={phase}
      error={error}
      asOf={asOf}
      onRetry={retry}
      onReloadPermissions={onReloadPermissions}
      selectedId={objectId}
      onSelect={(id) => onNav("admin", id ? `targets/${id}` : "targets")}
      onNav={onNav}
      actionHandlers={handlers}
      pending={pending}
      onCancelPending={onCancelPending}
      onConfirmPending={onConfirmPending}
      width={width}
    />
    </div>
  );
}
