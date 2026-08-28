import React, { useState } from "react";
import { HudFrame } from "../../ui/HudFrame.jsx";
import { DataTable } from "../../ui/DataTable.jsx";
import { FilterBar } from "../../ui/FilterBar.jsx";
import { Button } from "../../ui/Button.jsx";
import { Inspector } from "../../ui/Inspector.jsx";
import { AsyncRegion } from "../../ui/AsyncRegion.jsx";
import { attachRowActions, filtersActive } from "./contract.js";
import { ConfirmAction } from "../../ui/ConfirmAction.jsx";
import { T1Overlay } from "../../Tiers.jsx";
import { performHardwareTouch } from "../../webauthn.js";
import { simState } from "../../api.js";

function HudT1({ pending, onConfirm, onDismiss }) {
  const [touched, setTouched] = useState(false);
  return (
    <T1Overlay
      label={pending.label}
      cost={pending.cost}
      summary={pending.summary}
      onTouch={async () => {
        if (simState()) {
          setTouched(true);
          return;
        }
        const result = await performHardwareTouch();
        if (result?.status === 200) setTouched(true);
      }}
      onConfirm={({ name }) => {
        if (!touched || !name) return;
        onConfirm?.({ ...pending, name, body: { ...pending.body, name } });
      }}
      onDismiss={onDismiss}
    />
  );
}

export function CollectionScreen({
  title,
  caption,
  columns = [],
  rows = [],
  filters = {},
  filterDefs = [],
  facets = [],
  collectionActions = [],
  selectedId,
  onSelect,
  onFilter,
  onNav,
  phase = "live",
  error,
  onRetry,
  asOf,
  deniedReason,
  onReloadPermissions,
  onReturnToOperator,
  emptySentence,
  emptyButton,
  onEmpty,
  inspector,
  inspectorTitle = "Inspector",
  width = 1280,
  pageInfo = {},
  phoneFallback,
  children,
  actionHandlers = {},
  pending,
  onCancelPending,
  onConfirmPending,
}) {
  if (phase === "permission-denied" || phase === "signed-out") {
    return (
      <AsyncRegion
        phase={phase}
        deniedReason={deniedReason}
        onReloadPermissions={onReloadPermissions}
        onReturnToOperator={onReturnToOperator || (() => onNav?.("home"))}
        onSignIn={() => {
          if (typeof window !== "undefined") window.location.hash = "#/";
          onReloadPermissions?.();
        }}
      />
    );
  }
  const wired = attachRowActions(rows, actionHandlers);
  const canClear = filtersActive(filters);
  return (
    <div>
      {title ? <h1 className="hud-title">{title}</h1> : null}
      <div className="hud-toolbar">
        {collectionActions.map((action) => (
          <Button
            key={action.id}
            variant={action.primary ? "primary" : "secondary"}
            disabled={action.disabled}
            disabledReason={action.reason}
            onClick={() => (action.onRun || actionHandlers[action.id])?.(action)}
          >
            {action.label}
          </Button>
        ))}
      </div>
      {facets.length ? (
        <div className="hud-facets" role="group" aria-label="Collection facets">
          {facets.map((facet) => (
            <button
              key={facet.id}
              type="button"
              aria-pressed={filters.facet === facet.id || (!filters.facet && facet.id === "all")}
              className={`hud-btn hud-btn--${
                filters.facet === facet.id || (!filters.facet && facet.id === "all")
                  ? "primary"
                  : "quiet"
              }`}
              onClick={() => onFilter?.({ ...filters, facet: facet.id, page: "1" })}
            >
              {facet.label}
            </button>
          ))}
        </div>
      ) : null}
      {filterDefs.length ? (
        <FilterBar
          values={filters}
          onChange={(id, value) => {
            const next = { ...filters, [id]: value, page: id === "page" ? value : "1" };
            onFilter?.(next);
          }}
          filters={filterDefs}
        />
      ) : null}
      {onFilter ? (
        <Button
          disabled={!canClear}
          disabledReason={!canClear ? "No filters are active." : undefined}
          onClick={() => {
            const next = { ...filters };
            Object.keys(next).forEach((key) => {
              if (key === "sort") next[key] = "name";
              else if (key === "page") next[key] = "1";
              else if (key === "facet") next[key] = "all";
              else next[key] = "";
            });
            onFilter(next);
          }}
        >
          CLEAR
        </Button>
      ) : null}
      {pageInfo.page != null ? (
        <p className="hud-kicker">
          Page {filters.page || pageInfo.page || "1"}
          {pageInfo.count != null ? ` of ${pageInfo.count}` : ""}
        </p>
      ) : null}
      {pageInfo.page != null || pageInfo.next != null ? (
        <div style={{ display: "flex", gap: 8, marginBottom: 8 }}>
          <Button
            disabled={Number(filters.page || pageInfo.page || 1) <= 1}
            onClick={() => onFilter?.({
              ...filters,
              page: String(Math.max(1, Number(filters.page || pageInfo.page || 1) - 1)),
            })}
          >
            Previous page
          </Button>
          <Button
            disabled={!pageInfo.next}
            onClick={() => onFilter?.({ ...filters, page: String(pageInfo.next) })}
          >
            Next page
          </Button>
        </div>
      ) : null}
      <div className={inspector ? "hud-grid-2" : undefined}>
        <HudFrame variant="panel">
          <DataTable
            caption={caption || title}
            columns={columns}
            rows={wired}
            selectedId={selectedId}
            onSelect={(row) => onSelect?.(row.id)}
            phase={phase}
            error={error}
            onRetry={onRetry}
            asOf={asOf}
            width={width}
            phoneFallback={phoneFallback}
            emptySentence={emptySentence}
            emptyButton={emptyButton}
            onEmpty={onEmpty || (() => onNav?.("admin", "overview"))}
            filtered={canClear}
            onClearFilters={() => {
              const next = { ...filters };
              Object.keys(next).forEach((key) => {
                if (key === "sort") next[key] = "name";
                else if (key === "page") next[key] = "1";
                else if (key === "facet") next[key] = "all";
                else next[key] = "";
              });
              onFilter?.(next);
            }}
            sort={filters.sort}
            onSort={(sort) => onFilter?.({ ...filters, sort, page: "1" })}
          />
        </HudFrame>
        {inspector ? (
          <Inspector
            title={inspectorTitle}
            open={Boolean(selectedId) || inspector.always}
            width={width}
            onClose={() => onSelect?.(undefined)}
          >
            {inspector.body}
          </Inspector>
        ) : null}
      </div>
      {pending?.tier === "T1" ? (
        <HudT1 pending={pending} onConfirm={onConfirmPending} onDismiss={onCancelPending} />
      ) : pending ? (
        <ConfirmAction
          label={pending.label}
          summary={pending.summary || pending.label}
          action={pending.id}
          objectId={pending.objectId}
          current={pending.current}
          proposed={pending.proposed}
          affected={pending.affected}
          interruption={pending.interruption}
          rollback={pending.rollback}
          policy={pending.policy}
          refusal={pending.refusal}
          onConfirm={() => onConfirmPending?.(pending)}
          onDismiss={onCancelPending}
        />
      ) : null}
      {children}
    </div>
  );
}
