import React from "react";
import { HudFrame } from "./HudFrame.jsx";
import { Button } from "./Button.jsx";

export function Inspector({
  title,
  open = true,
  overlay = false,
  onClose,
  children,
  width = 1280,
}) {
  if (!open) return null;
  const overlaying = overlay || (width >= 768 && width < 1440);
  return (
    <aside
      className={`hud-inspector${overlaying ? " hud-inspector--drawer" : ""}`}
      aria-label={title || "Inspector"}
      aria-modal={overlaying ? "true" : undefined}
      role={overlaying ? "dialog" : "complementary"}
    >
      <HudFrame variant="inspector">
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <h2 className="hud-kicker" style={{ margin: 0 }}>{title}</h2>
          {overlaying && onClose ? (
            <Button variant="quiet" onClick={onClose}>Close</Button>
          ) : null}
        </div>
        {children}
      </HudFrame>
    </aside>
  );
}
