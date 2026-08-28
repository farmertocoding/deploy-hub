import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? {
  location: { search: "", hash: "#/sites/3" },
  matchMedia: () => ({ matches: true }),
};
(globalThis as any).document = (globalThis as any).document ?? {
  documentElement: {
    attrs: {} as Record<string, string>,
    setAttribute(k: string, v: string) { this.attrs[k] = v; },
    getAttribute(k: string) { return this.attrs[k]; },
  },
};

import {
  APPEARANCE_KEY, ROOT_THEMES, parseStoredAppearance, resolveAndApply,
  resolveRootTheme, writeStoredAppearance,
} from "../src/theme/theme-store.js";
import { ThemeProvider } from "../src/theme/ThemeProvider.jsx";
import { AppearanceMenu } from "../src/ui/AppearanceMenu.jsx";
import { NAV, parseRoute } from "../src/Chrome.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

class MemoryStorage {
  m = new Map<string, string>();
  getItem(k: string) { return this.m.has(k) ? this.m.get(k)! : null; }
  setItem(k: string, v: string) { this.m.set(k, String(v)); }
}

test("only_dark_and_light_are_root_themes", () => {
  assert.deepEqual([...ROOT_THEMES], ["dark", "light"]);
  assert.equal(parseStoredAppearance("sepia"), null);
  assert.equal(parseStoredAppearance("DARK"), null);
  assert.equal(resolveRootTheme("system", true), "dark");
  assert.equal(resolveRootTheme("system", false), "light");
  assert.equal(resolveRootTheme(null, true), "dark");
  assert.equal(resolveRootTheme("light", true), "light");
});

test("appearance_persists_under_versioned_key_and_applies_before_paint", () => {
  const storage = new MemoryStorage();
  const doc = {
    documentElement: {
      attrs: {} as Record<string, string>,
      setAttribute(k: string, v: string) { this.attrs[k] = v; },
      getAttribute(k: string) { return this.attrs[k]; },
    },
  };
  const first = resolveAndApply({
    storage,
    matchMedia: () => ({ matches: true }),
    doc,
  });
  assert.equal(first.theme, "dark");
  assert.equal(doc.documentElement.attrs["data-theme"], "dark");
  writeStoredAppearance(storage, "light");
  assert.equal(storage.getItem(APPEARANCE_KEY), "light");
  const second = resolveAndApply({
    storage,
    matchMedia: () => ({ matches: true }),
    doc,
  });
  assert.equal(second.theme, "light");
  assert.equal(doc.documentElement.attrs["data-theme"], "light");
});

test("hud_material_uses_layered_cover_fog_grid_and_transparent_panels", () => {
  const themes = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../src/styles/themes.css"), "utf8");
  const tokens = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../src/styles/tokens.css"), "utf8");
  const components = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../src/styles/components.css"), "utf8");
  assert.match(tokens, /--hud-pattern-size:\s*75px/);
  assert.match(tokens, /Chakra Petch/);
  assert.match(themes, /html::before/);
  assert.match(themes, /--hud-cover/);
  assert.match(themes, /--hud-pattern/);
  assert.match(themes, /linear-gradient\(180deg/);
  assert.match(themes, /--hud-panel-fill:\s*transparent/);
  assert.match(components, /backdrop-filter:\s*none/);
  assert.doesNotMatch(components, /backdrop-filter:\s*blur/);
  assert.match(components, /hud-frame__corner--tl/);
  assert.match(components, /hud-frame__corner--tr/);
  assert.match(components, /hud-frame__corner--br/);
  assert.match(components, /hud-frame__corner--bl/);
  assert.match(components, /--hud-corner-size/);
});

test("appearance_menu_names_dark_and_light_with_word_check_and_border", () => {
  const storage = new MemoryStorage();
  storage.setItem(APPEARANCE_KEY, "dark");
  const markup = render(ThemeProvider, {
    storage,
    matchMedia: () => ({ matches: true }),
    children: React.createElement(AppearanceMenu, { defaultOpen: true }),
  });
  const text = visibleText(markup);
  assert.match(markup, /aria-label="Appearance"/);
  assert.ok(text.includes("Dark"));
  assert.ok(text.includes("Light"));
  assert.match(markup, /aria-checked="true"/);
  assert.match(markup, /selected/);
  assert.match(markup, /hud-appearance__choice/);
});

test("theme_change_keeps_route", () => {
  const storage = new MemoryStorage();
  const loc = { hash: "#/sites/3" };
  (globalThis as any).window.location.hash = loc.hash;
  writeStoredAppearance(storage, "light");
  resolveAndApply({
    storage,
    matchMedia: () => ({ matches: true }),
    doc: (globalThis as any).document,
  });
  assert.equal((globalThis as any).window.location.hash, "#/sites/3");
  assert.deepEqual(parseRoute("#/sites/3"), { screen: "sites", id: "3" });
  assert.deepEqual(NAV.map((n) => n.id),
    ["home", "sites", "targets", "deploys", "findings", "settings"]);
});

test("index_html_resolves_theme_before_react_and_accepts_only_dark_light_system", () => {
  const html = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../index.html"), "utf8");
  assert.match(html, /deploy-hub\.appearance\.v1/);
  assert.match(html, /data-theme/);
  assert.match(html, /prefers-color-scheme: dark/);
  assert.doesNotMatch(html, /background:#0f1115/);
});

test("new_screen_modules_use_tokens_not_literal_colors", () => {
  const root = join(dirname(fileURLToPath(import.meta.url)), "../src/screens/administration");
  const files = readdirSync(root).filter((f) => f.endsWith(".js") || f.endsWith(".jsx"));
  for (const f of files) {
    const text = readFileSync(join(root, f), "utf8");
    assert.doesNotMatch(text, /#[0-9a-fA-F]{3,8}\b/, `${f} has a hex color`);
    assert.doesNotMatch(text, /rgb\(/i, `${f} has rgb()`);
    assert.doesNotMatch(text, /hsl\(/i, `${f} has hsl()`);
  }
});
