import React, { useEffect, useId, useRef, useState } from "react";
import { HudFrame } from "./HudFrame.jsx";
import { Icon } from "./Icon.jsx";
import { useTheme } from "../theme/useTheme.js";

export function AppearanceMenu({ defaultOpen = false }) {
  const { theme, setAppearance } = useTheme();
  const [open, setOpen] = useState(defaultOpen);
  const panelId = useId();
  const rootRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open]);

  return (
    <div className="hud-appearance" ref={rootRef}>
      <button
        type="button"
        className="hud-btn"
        aria-label="Appearance"
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => setOpen((v) => !v)}
      >
        Appearance
      </button>
      {open ? (
        <div id={panelId} role="dialog" aria-label="Appearance" className="hud-appearance__panel">
          <HudFrame variant="popover">
            <p className="hud-kicker">Appearance</p>
            {["dark", "light"].map((mode) => {
              const selected = theme === mode;
              const label = mode === "dark" ? "Dark" : "Light";
              return (
                <button
                  key={mode}
                  type="button"
                  role="option"
                  aria-checked={selected}
                  className="hud-appearance__choice"
                  onClick={() => {
                    setAppearance(mode);
                    setOpen(false);
                  }}
                >
                  <span className={`hud-appearance__swatch hud-appearance__swatch--${mode}`} />
                  <span>{label}</span>
                  {selected ? <Icon name="check" label="selected" /> : null}
                </button>
              );
            })}
          </HudFrame>
        </div>
      ) : null}
    </div>
  );
}
