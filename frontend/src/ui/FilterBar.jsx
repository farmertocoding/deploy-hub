import React from "react";

export function FilterBar({ filters = [], values = {}, onChange }) {
  return (
    <form className="hud-filter" onSubmit={(e) => e.preventDefault()}>
      {filters.map((f) => (
        f.type === "select" ? (
          <label key={f.id}>
            {f.label}
            <select
              aria-label={f.label}
              value={values[f.id] || ""}
              onChange={(e) => onChange?.(f.id, e.target.value)}
            >
              {(f.options || []).map((o) => (
                <option key={o.value} value={o.value}>{o.label}</option>
              ))}
            </select>
          </label>
        ) : (
          <label key={f.id}>
            {f.label}
            <input
              aria-label={f.label}
              value={values[f.id] || ""}
              onChange={(e) => onChange?.(f.id, e.target.value)}
            />
          </label>
        )
      ))}
    </form>
  );
}
