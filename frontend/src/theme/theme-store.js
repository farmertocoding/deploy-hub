// Appearance persistence and root-theme resolution (HUD-D3 / D-142).
// Root may only be data-theme="dark" | data-theme="light". Stored values may
// also be "system". Invalid stored values are ignored, never written back.

export const APPEARANCE_KEY = "deploy-hub.appearance.v1";
export const ROOT_THEMES = Object.freeze(["dark", "light"]);
export const STORED_VALUES = Object.freeze(["dark", "light", "system"]);

export function parseStoredAppearance(value) {
  if (value === "dark" || value === "light" || value === "system") return value;
  return null;
}

export function readStoredAppearance(storage) {
  if (!storage) return null;
  try {
    return parseStoredAppearance(storage.getItem(APPEARANCE_KEY));
  } catch {
    return null;
  }
}

export function writeStoredAppearance(storage, value) {
  const parsed = parseStoredAppearance(value);
  if (!parsed || !storage) return false;
  try {
    storage.setItem(APPEARANCE_KEY, parsed);
    return true;
  } catch {
    return false;
  }
}

export function prefersDarkScheme(matchMedia) {
  try {
    return Boolean(matchMedia && matchMedia("(prefers-color-scheme: dark)").matches);
  } catch {
    return false;
  }
}

export function resolveRootTheme(stored, prefersDark) {
  if (stored === "dark" || stored === "light") return stored;
  return prefersDark ? "dark" : "light";
}

export function applyRootTheme(doc, theme) {
  if (!doc || !doc.documentElement) return null;
  if (theme !== "dark" && theme !== "light") return null;
  doc.documentElement.setAttribute("data-theme", theme);
  return theme;
}

export function resolveAndApply({
  storage,
  matchMedia,
  doc,
} = {}) {
  const stored = readStoredAppearance(storage);
  const theme = resolveRootTheme(stored, prefersDarkScheme(matchMedia));
  applyRootTheme(doc, theme);
  return { stored, theme };
}
