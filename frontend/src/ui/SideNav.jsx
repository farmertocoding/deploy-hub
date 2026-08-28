import React from "react";
import { NAV } from "../Chrome.jsx";

export function SideNav({ items = NAV, current, onNav, label = "Operator", compact = false }) {
  return (
    <nav className={`hud-sidenav${compact ? " hud-sidenav--compact" : ""}`} aria-label={label}>
      {items.map((n) => (
        <button
          key={n.id}
          type="button"
          aria-current={current === n.id ? "page" : undefined}
          onClick={() => onNav(n.id)}
        >
          {compact ? n.label.slice(0, 1) : n.label}
          {compact ? <span className="hud-sidenav__full">{n.label}</span> : null}
        </button>
      ))}
    </nav>
  );
}
