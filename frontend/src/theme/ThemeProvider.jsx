import React, { createContext, useCallback, useMemo, useState } from "react";
import {
  applyRootTheme,
  parseStoredAppearance,
  readStoredAppearance,
  resolveRootTheme,
  writeStoredAppearance,
  prefersDarkScheme,
} from "./theme-store.js";

export const ThemeContext = createContext(null);

function currentDoc() {
  return typeof document !== "undefined" ? document : null;
}

function currentStorage() {
  try {
    return typeof localStorage !== "undefined" ? localStorage : null;
  } catch {
    return null;
  }
}

function currentMatchMedia() {
  return typeof window !== "undefined" && window.matchMedia
    ? window.matchMedia.bind(window)
    : null;
}

export function ThemeProvider({ children, storage, matchMedia, doc }) {
  const store = storage === undefined ? currentStorage() : storage;
  const mm = matchMedia === undefined ? currentMatchMedia() : matchMedia;
  const documentRef = doc === undefined ? currentDoc() : doc;

  const [preference, setPreference] = useState(() => readStoredAppearance(store));
  const [theme, setThemeState] = useState(() =>
    resolveRootTheme(readStoredAppearance(store), prefersDarkScheme(mm)));

  const setAppearance = useCallback((value) => {
    const parsed = parseStoredAppearance(value);
    if (!parsed) return;
    writeStoredAppearance(store, parsed);
    const next = resolveRootTheme(parsed, prefersDarkScheme(mm));
    applyRootTheme(documentRef, next);
    setPreference(parsed);
    setThemeState(next);
  }, [store, mm, documentRef]);

  const value = useMemo(() => ({
    theme,
    preference: preference || "system",
    setAppearance,
  }), [theme, preference, setAppearance]);

  return (
    <ThemeContext.Provider value={value}>
      {children}
    </ThemeContext.Provider>
  );
}

export function useTheme() {
  const ctx = React.useContext(ThemeContext);
  if (ctx) return ctx;
  let fallbackTheme = "dark";
  try {
    const t = typeof document !== "undefined"
      && document.documentElement
      && document.documentElement.getAttribute
      && document.documentElement.getAttribute("data-theme");
    if (t === "light" || t === "dark") fallbackTheme = t;
  } catch { /* tests may stub a cookie-only document */ }
  return {
    theme: fallbackTheme === "light" ? "light" : "dark",
    preference: "system",
    setAppearance: (value) => {
      const parsed = parseStoredAppearance(value);
      if (!parsed) return;
      writeStoredAppearance(currentStorage(), parsed);
      applyRootTheme(
        currentDoc(),
        resolveRootTheme(parsed, prefersDarkScheme(currentMatchMedia())),
      );
    },
  };
}
