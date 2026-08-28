import React, { useEffect, useRef, useState } from "react";
import { HudFrame } from "./HudFrame.jsx";
import { adminReadEnabled } from "../flags.js";
import { api } from "../api.js";

export function WorkspaceMenu({ user, onNav, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const root = useRef(null);
  const canAdmin = adminReadEnabled(user);
  const close = (fn) => {
    setOpen(false);
    fn?.();
  };
  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event) => { if (event.key === "Escape") close(); };
    const onDoc = (event) => {
      if (root.current && !root.current.contains(event.target)) close();
    };
    if (typeof document?.addEventListener !== "function") return undefined;
    document.addEventListener("keydown", onKey);
    document.addEventListener("mousedown", onDoc);
    return () => {
      document.removeEventListener("keydown", onKey);
      document.removeEventListener("mousedown", onDoc);
    };
  }, [open]);
  return (
    <div className="hud-workspace-menu" ref={root}>
      <button
        type="button"
        className="hud-btn hud-btn--quiet"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        {user?.username || "workspace"}
        {user?.role ? ` · ${user.role}` : ""}
      </button>
      {open ? (
        <div role="menu" aria-label="Workspace" className="hud-workspace-menu__panel">
          <HudFrame variant="popover">
            <button
              type="button"
              role="menuitem"
              className="hud-appearance__choice"
              onClick={() => close(() => onNav("home"))}
            >
              Operator Console
            </button>
            <button
              type="button"
              role="menuitem"
              className="hud-appearance__choice"
              onClick={() => close(() => onNav("settings"))}
            >
              Profile
            </button>
            <button
              type="button"
              role="menuitem"
              className="hud-appearance__choice"
              onClick={() => close(() => onNav("settings", "security"))}
            >
              Security
            </button>
            {canAdmin ? (
              <button
                type="button"
                role="menuitem"
                className="hud-appearance__choice"
                onClick={() => close(() => onNav("admin", "overview"))}
              >
                Administration
              </button>
            ) : null}
            <button
              type="button"
              role="menuitem"
              className="hud-appearance__choice"
              onClick={() => {
                close();
                api("auth/logout/", {}, "POST").finally(() => {
                  if (typeof window !== "undefined") window.location.hash = "#/";
                });
              }}
            >
              Sign out
            </button>
          </HudFrame>
        </div>
      ) : null}
    </div>
  );
}
