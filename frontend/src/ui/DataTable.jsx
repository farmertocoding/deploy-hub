import React, { useState } from "react";
import { Button } from "./Button.jsx";
import { AsyncRegion } from "./AsyncRegion.jsx";
import { EmptyState } from "./EmptyState.jsx";

export function DataTable({
  caption,
  columns = [],
  rows = [],
  selectedId,
  onSelect,
  phase = "live",
  emptySentence,
  emptyButton,
  onEmpty,
  onRetry,
  error,
  asOf,
  width = 1280,
  phoneFallback,
  filtered = false,
  onClearFilters,
  sort,
  onSort,
}) {
  if (width < 768 && phoneFallback) return phoneFallback;
  return (
    <AsyncRegion phase={phase} what={caption || "rows"} error={error} onRetry={onRetry} asOf={asOf}>
      {!rows.length && phase === "live" ? (
        filtered ? (
          <EmptyState
            sentence="No matches for the active filters."
            button="Clear filters"
            onAction={onClearFilters}
          />
        ) : (
          <EmptyState sentence={emptySentence} button={emptyButton} onAction={onEmpty} />
        )
      ) : (
        <div className="hud-table-wrap hud-desktop-table">
          <table className="hud-table">
            {caption ? <caption>{caption}</caption> : null}
            <thead>
              <tr>
                {columns.map((c) => (
                  <th
                    key={c.id}
                    scope="col"
                    aria-sort={c.sortable && onSort
                      ? (sort === c.id ? "ascending" : sort === `-${c.id}` ? "descending" : "none")
                      : undefined}
                  >
                    {c.sortable && onSort ? (
                      <button
                        type="button"
                        className="hud-btn hud-btn--quiet"
                        onClick={() => onSort(sort === c.id ? `-${c.id}` : c.id)}
                      >
                        {c.label}
                      </button>
                    ) : c.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => (
                <tr
                  key={row.id}
                  tabIndex={0}
                  aria-selected={String(selectedId) === String(row.id)}
                  onClick={() => onSelect?.(row)}
                  onKeyDown={(event) => {
                    if (event.key === "Enter" || event.key === " ") {
                      event.preventDefault();
                      onSelect?.(row);
                    }
                  }}
                >
                  {columns.map((c) => (
                    <td key={c.id}>
                      {c.id === "actions" ? (
                        <RowActions row={row} />
                      ) : (c.render ? c.render(row) : row[c.id])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </AsyncRegion>
  );
}

function RowActions({ row }) {
  const [open, setOpen] = useState(false);
  const allowed = (row.allowed_actions || []).filter((a) => a.label);
  const disabled = (row.disabled_actions || []).filter((a) => a.label);
  const primary = allowed.find((a) => !a.destructive) || allowed[0];
  const rest = allowed.filter((a) => a !== primary);
  const destructive = [...rest, ...disabled].filter((a) => a.destructive || /delete|decommission|purge/i.test(a.id || a.label || ""));
  const more = rest.filter((a) => !destructive.includes(a));
  return (
    <span>
      {primary ? (
        <Button
          variant={primary.destructive ? "destructive" : "quiet"}
          onClick={(e) => { e.stopPropagation(); primary.onRun?.(row, primary); }}
        >
          {primary.label}
        </Button>
      ) : null}
      {more.length || destructive.length || disabled.length ? (
        <details
          className="hud-more-actions"
          open={open}
          onToggle={(e) => setOpen(e.target.open)}
          onClick={(e) => e.stopPropagation()}
        >
          <summary>More actions</summary>
          {more.map((a) => (
            <Button key={a.id} variant="quiet" onClick={(e) => { e.stopPropagation(); a.onRun?.(row, a); }}>
              {a.label}
            </Button>
          ))}
          {destructive.map((a) => (
            a.reason ? (
              <Button key={a.id} disabled disabledReason={a.reason}>{a.label}</Button>
            ) : (
              <Button key={a.id} variant="destructive" onClick={(e) => { e.stopPropagation(); a.onRun?.(row, a); }}>
                {a.label}
              </Button>
            )
          ))}
          {disabled.filter((a) => !destructive.includes(a)).map((a) => (
            <Button key={a.id} disabled disabledReason={a.reason}>{a.label}</Button>
          ))}
        </details>
      ) : null}
    </span>
  );
}
