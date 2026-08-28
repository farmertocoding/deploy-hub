import React from "react";

const VARIANTS = ["panel", "compact", "inspector", "popover", "critical"];

export function HudFrame({ variant = "panel", children, className = "", labelledBy }) {
  const kind = VARIANTS.includes(variant) ? variant : "panel";
  return (
    <section
      className={`hud-frame hud-frame--${kind} ${className}`.trim()}
      aria-labelledby={labelledBy}
    >
      <span className="hud-frame__edge hud-frame__edge--top" aria-hidden="true" />
      <span className="hud-frame__edge hud-frame__edge--right" aria-hidden="true" />
      <span className="hud-frame__edge hud-frame__edge--bottom" aria-hidden="true" />
      <span className="hud-frame__edge hud-frame__edge--left" aria-hidden="true" />
      <span className="hud-frame__corner hud-frame__corner--tl" aria-hidden="true" />
      <span className="hud-frame__corner hud-frame__corner--tr" aria-hidden="true" />
      <span className="hud-frame__corner hud-frame__corner--br" aria-hidden="true" />
      <span className="hud-frame__corner hud-frame__corner--bl" aria-hidden="true" />
      <div className="hud-frame__body">{children}</div>
    </section>
  );
}
