import React from "react";

const PATHS = {
  check: "M4 12.5 8.5 17 20 6",
  menu: "M4 7h16M4 12h16M4 17h16",
  search: "M11 19a8 8 0 1 1 0-16 8 8 0 0 1 0 16Zm10 2-4.35-4.35",
  close: "M6 6l12 12M18 6 6 18",
};

export function Icon({ name, label }) {
  const d = PATHS[name] || PATHS.menu;
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.75"
      aria-hidden={label ? undefined : true}
      aria-label={label}
      role={label ? "img" : "presentation"}
    >
      <path d={d} />
    </svg>
  );
}
