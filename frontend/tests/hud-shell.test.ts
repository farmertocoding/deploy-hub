import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? {
  location: { search: "", hash: "#/" },
};
(globalThis as any).document = (globalThis as any).document ?? { cookie: "", documentElement: { getAttribute: () => "dark", setAttribute() {} } };

import { NAV, parseRoute, routeHash } from "../src/Chrome.jsx";
import { NavBar } from "../src/App.jsx";
import { HudAppShell } from "../src/ui/AppShell.jsx";
import { SideNav } from "../src/ui/SideNav.jsx";
import { WorkspaceMenu } from "../src/ui/WorkspaceMenu.jsx";
import { ConfirmAction } from "../src/ui/ConfirmAction.jsx";
import { DataTable } from "../src/ui/DataTable.jsx";
import { TopBar } from "../src/ui/TopBar.jsx";
import { ADMIN_NAV } from "../src/screens/administration/admin-nav.js";
import { hudUiEnabled, adminReadEnabled } from "../src/flags.js";
import { createEventsClient } from "../src/useEvents.js";
import { ThemeProvider } from "../src/theme/ThemeProvider.jsx";
import { SETTINGS_TABS } from "../src/screens/Settings.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

test("operator_nav_ids_unchanged_and_administration_is_not_among_them", () => {
  assert.deepEqual(NAV.map((n) => n.id),
    ["home", "sites", "targets", "deploys", "findings", "settings"]);
  assert.ok(!NAV.some((n) => /admin/i.test(n.id) || /admin/i.test(n.label)));
  const markup = render(NavBar, {
    route: { screen: "home" }, onNav: () => {},
    status: "live", asOf: null, username: "j",
  });
  const text = visibleText(markup);
  for (const n of NAV) assert.ok(text.includes(n.label), n.label);
  assert.ok(!/Administration/.test(text));
  assert.ok(!/Style Guide/i.test(text));
  assert.ok(!/Demo/.test(text));
  assert.ok(!/Advisor/i.test(text));
  assert.deepEqual(SETTINGS_TABS.map((t) => t.id),
    ["security", "cloudflare", "aws", "partners", "developer", "vault"]);
});

test("unknown_hash_still_lands_home_admin_is_a_separate_workspace", () => {
  assert.deepEqual(parseRoute("#/map/3"), { screen: "home", id: undefined });
  assert.deepEqual(parseRoute("#/findings/7"), { screen: "findings", id: "7" });
  assert.deepEqual(parseRoute("#/admin/overview"), { screen: "admin", id: "overview" });
  assert.deepEqual(parseRoute("#/admin/deployments/11"), { screen: "admin", id: "deployments/11" });
  assert.equal(routeHash("admin", "secrets"), "#/admin/secrets");
  const filtered = parseRoute("#/admin/findings?facet=p1p2");
  assert.equal(filtered.id, "findings");
  assert.equal(filtered.query.facet, "p1p2");
});

test("hud_operator_shell_uses_the_six_nav_items", () => {
  const markup = render(HudAppShell, {
    user: { username: "op", capabilities: ["hud_ui_v1"] },
    events: { status: "live", asOf: null },
    route: { screen: "sites", id: undefined },
    onNav: () => {},
    children: "main",
  });
  const text = visibleText(markup);
  for (const n of NAV) assert.ok(text.includes(n.label), n.label);
  assert.ok(!ADMIN_NAV.every((n) => text.includes(n.label)));
  assert.match(markup, /aria-current="page"/);
  assert.match(markup, /Skip to main content/);
});

test("administration_entry_is_workspace_menu_gated_not_operator_nav", () => {
  const denied = visibleText(render(WorkspaceMenu, {
    user: { username: "op", capabilities: ["hud_ui_v1"] },
    onNav: () => {},
  }));
  assert.ok(!denied.includes("Administration"));
  const allowed = render(WorkspaceMenu, {
    user: { username: "op", capabilities: ["hud_ui_v1", "admin_read"] },
    onNav: () => {},
  });
  assert.match(allowed, /aria-haspopup="menu"/);
  assert.equal(adminReadEnabled({ capabilities: ["hud_ui_v1"] }), false);
  assert.equal(adminReadEnabled({ capabilities: ["admin_read"] }), true);
});

test("hud_ui_v1_query_restores_previous_shell", () => {
  assert.equal(hudUiEnabled({ capabilities: ["hud_ui_v1"] }, "?hud=0"), false);
  assert.equal(hudUiEnabled({ capabilities: [] }, "?hud=1"), true);
  assert.equal(hudUiEnabled({ capabilities: ["hud_ui_v1"] }), true);
  assert.equal(hudUiEnabled({ authenticated: true, capabilities: [] }), false);
});

test("theme_module_does_not_construct_a_socket", () => {
  const theme = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../src/theme/ThemeProvider.jsx"), "utf8");
  const store = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../src/theme/theme-store.js"), "utf8");
  const appearance = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "../src/ui/AppearanceMenu.jsx"), "utf8");
  for (const src of [theme, store, appearance]) {
    assert.doesNotMatch(src, /createEventsClient/);
    assert.doesNotMatch(src, /WebSocket/);
    assert.doesNotMatch(src, /useEvents/);
  }
  const client = createEventsClient({
    makeSocket: () => ({ readyState: 0, send() {}, close() {}, onopen: null, onclose: null, onmessage: null }),
    schedule: () => 1,
    cancel: () => {},
    onChange: () => {},
  });
  assert.equal(typeof client.subscribe, "function");
});

test("admin_nav_is_not_operator_nav", () => {
  assert.deepEqual(ADMIN_NAV.map((n) => n.label), [
    "Overview", "Projects", "Sites", "Deployments", "Targets",
    "Findings & Operations", "Partners", "Access & Secrets",
    "Integrations & DNS", "Audit",
  ]);
  assert.ok(!ADMIN_NAV.some((n) => n.id === "home"));
  const markup = render(SideNav, {
    items: ADMIN_NAV, current: "overview", onNav: () => {},
  });
  assert.match(visibleText(markup), /Overview/);
  assert.doesNotMatch(visibleText(markup), /\bHome\b/);
});

test("live_status_click_keeps_shell_and_opens_connection_popover", async () => {
  const { act, create } = await import("react-test-renderer");
  const { ThemeProvider } = await import("../src/theme/ThemeProvider.jsx");
  let tree: any;
  await act(() => {
    tree = create(React.createElement(ThemeProvider, {
      children: React.createElement(HudAppShell, {
        user: { username: "admin", capabilities: ["hud_ui_v1", "admin_read"] },
        events: { status: "live", asOf: null },
        route: { screen: "admin", id: "overview" },
        onNav: () => {},
        shell: { p1_p2: 3, scope: "production", operations: [] },
        children: React.createElement("div", { id: "main-sentinel" }, "fleet overview stays"),
      }),
    }));
  });
  const before = JSON.stringify(tree.toJSON());
  assert.match(before, /fleet overview stays/);
  const liveBtn = tree.root.findAllByType("button").find((b: any) => (
    b.props["aria-label"] === "Connection status"
  ));
  assert.ok(liveBtn, "LIVE control");
  await act(() => liveBtn.props.onClick({ preventDefault() {}, stopPropagation() {} }));
  const after = JSON.stringify(tree.toJSON());
  assert.match(after, /fleet overview stays/);
  assert.match(after, /Transport multiplexed events|last successful refresh|Last refresh/i);
  assert.match(after, /hud-live/);
});

test("admin_shell_exposes_breadcrumbs_scope_search_p1p2_and_operations", () => {
  const markup = render(HudAppShell, {
    user: { username: "admin", role: "owner", capabilities: ["hud_ui_v1", "admin_read"] },
    events: { status: "live", asOf: null },
    route: { screen: "admin", id: "sites/1" },
    onNav: () => {},
    shell: {
      p1_p2: 3,
      scope: "production",
      operations: [{ id: "op-1", state: "running", label: "Retry shop/prod" }],
    },
    children: "main",
  });
  const text = visibleText(markup);
  assert.match(text, /Administration/);
  assert.match(text, /Sites/);
  assert.match(markup, /aria-label="Breadcrumb"/);
  assert.match(text, /Production/);
  assert.match(markup, /aria-label="Global search"/);
  assert.match(text, /3 P1\/P2/);
  assert.match(markup, /aria-label="Operations"/);
  assert.match(text, /LIVE/);
  assert.match(markup, /aria-label="Appearance"/);
});

test("workspace_menu_lists_profile_security_administration_and_sign_out", () => {
  const markup = render(WorkspaceMenu, {
    user: { username: "admin", role: "owner", capabilities: ["hud_ui_v1", "admin_read"] },
    onNav: () => {},
    defaultOpen: true,
  });
  const text = visibleText(markup);
  assert.match(text, /Profile/);
  assert.match(text, /Security/);
  assert.match(text, /Administration/);
  assert.match(text, /Sign out/);
});

test("appearance_does_not_change_admin_hash_filters_or_selection", () => {
  (globalThis as any).window.location.hash = "#/admin/sites/1?q=shop&sort=name";
  const markup = render(TopBar, {
    title: "Deploy Hub",
    events: { status: "live" },
    user: { username: "admin", capabilities: ["admin_read"] },
    onNav: () => {},
    workspace: "admin",
    crumbs: [
      { label: "Administration", screen: "admin", id: "overview" },
      { label: "Sites", screen: "admin", id: "sites" },
      { label: "prod" },
    ],
  });
  assert.match(markup, /aria-label="Appearance"/);
  assert.equal(
    (globalThis as any).window.location.hash,
    "#/admin/sites/1?q=shop&sort=name",
  );
});

function nodeText(node: any): string {
  if (node == null) return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (node.props?.children) return nodeText(node.props.children);
  if (node.children) return nodeText(node.children);
  return "";
}

test("login_success_hydrates_capabilities_and_admin_guard_without_reload", async () => {
  const { act, create } = await import("react-test-renderer");
  const { Login } = await import("../src/screens/Login.jsx");
  const AdminShell = (await import("../src/screens/administration/AdminShell.jsx")).default;
  const canonical = {
    authenticated: true,
    username: "admin",
    otp_enrolled: true,
    webauthn_count: 2,
    totp_enrolled: true,
    t1_available: true,
    capabilities: ["hud_ui_v1", "admin_read"],
  };
  const calls: string[] = [];
  (globalThis as any).document.cookie = "csrftoken=test";
  (globalThis as any).fetch = async (url: string) => {
    calls.push(String(url));
    if (String(url).includes("auth/login")) {
      return { status: 200, json: async () => ({ username: "admin", otp_enrolled: true }) };
    }
    if (String(url).includes("auth/me")) {
      return { status: 200, json: async () => canonical };
    }
    return { status: 404, json: async () => ({}) };
  };
  let sessionUser: any;
  let tree: any;
  await act(() => {
    tree = create(React.createElement(Login, { onLogin: (u: any) => { sessionUser = u; } }));
  });
  const totpToggle = tree.root.findAllByType("button").find((b: any) =>
    nodeText(b).includes("authenticator code"),
  );
  await act(() => totpToggle.props.onClick({ preventDefault() {} }));
  const inputs = tree.root.findAllByType("input");
  await act(() => {
    inputs[0].props.onChange({ target: { value: "admin" } });
    inputs[1].props.onChange({ target: { value: "pw" } });
    inputs[2].props.onChange({ target: { value: "123456" } });
  });
  await act(async () => {
    await tree.root.findByType("form").props.onSubmit({ preventDefault() {} });
  });
  assert.ok(sessionUser, "login must call onLogin");
  assert.ok(Array.isArray(sessionUser.capabilities), "session user includes capabilities");
  assert.ok(sessionUser.capabilities.includes("admin_read"));
  assert.equal(adminReadEnabled(sessionUser), true);
  const allowed = visibleText(render(AdminShell, {
    user: sessionUser,
    route: { screen: "admin", id: "overview" },
    onNav: () => {},
    width: 1280,
    events: { status: "live" },
  }));
  assert.doesNotMatch(allowed, /Permission denied/);
  assert.match(allowed, /Fleet overview|Loading overview/i);
  const deniedUser = { ...sessionUser, capabilities: ["hud_ui_v1"] };
  assert.equal(adminReadEnabled(deniedUser), false);
  const nav: any[] = [];
  let deniedTree: any;
  await act(() => {
    deniedTree = create(React.createElement(AdminShell, {
      user: deniedUser,
      route: { screen: "admin", id: "overview" },
      onNav: (screen: string, id?: string) => nav.push([screen, id]),
      width: 1280,
      events: { status: "live" },
    }));
  });
  const deniedText = nodeText(deniedTree.toJSON());
  assert.match(deniedText, /Permission denied/);
  assert.match(deniedText, /Reload permissions/);
  assert.match(deniedText, /Return to Operator Console/);
  const returnBtn = deniedTree.root.findAllByType("button").find((b: any) =>
    nodeText(b).includes("Return to Operator Console"),
  );
  await act(() => returnBtn.props.onClick({ preventDefault() {} }));
  assert.deepEqual(nav.at(-1)?.[0], "home");
});

test("confirm_action_locks_after_the_first_click", async () => {
  const { act, create } = await import("react-test-renderer");
  let n = 0;
  let tree: any;
  await act(() => {
    tree = create(React.createElement(ConfirmAction, {
      label: "Abort and clean up",
      summary: "Abort shop/prod v4",
      onConfirm: () => { n += 1; },
      onDismiss: () => {},
    }));
  });
  const findConfirm = () => tree.root.findAllByType("button").find((b: any) =>
    String(b.props.className || "").includes("hud-btn--primary"),
  );
  const first = findConfirm();
  assert.ok(first, "Confirm button must exist");
  await act(() => first.props.onClick({ preventDefault() {} }));
  assert.equal(n, 1);
  const locked = findConfirm();
  assert.equal(locked.props["aria-busy"], true);
  assert.equal(locked.props["aria-disabled"], true);
  await act(() => locked.props.onClick({ preventDefault() {} }));
  assert.equal(n, 1, "ConfirmAction must ignore Enter-spam after the first confirm");
});

test("confirm_action_shows_before_after_and_is_a_modal", () => {
  const markup = render(ConfirmAction, {
    label: "Abort and clean up",
    summary: "Abort shop/prod v4",
    action: "deployment.abort",
    objectId: 11,
    current: "running",
    proposed: "cancelled",
    affected: [{ name: "shop/prod" }],
    interruption: "Running instance may stop.",
    rollback: "v3",
    onConfirm: () => {},
    onDismiss: () => {},
  });
  const text = visibleText(markup);
  assert.match(text, /Current running/);
  assert.match(text, /proposed cancelled/);
  assert.match(text, /shop\/prod/);
  assert.match(text, /Running instance may stop/);
  assert.match(markup, /aria-modal="true"/);
  assert.match(markup, /role="dialog"/);
});

test("data_table_separates_empty_from_filtered_and_exposes_more_actions", () => {
  const empty = visibleText(render(DataTable, {
    columns: [{ id: "name", label: "Name" }],
    rows: [],
    emptySentence: "No projects in this workspace.",
    emptyButton: "ADD APPLICATION",
  }));
  assert.match(empty, /No projects/);
  assert.doesNotMatch(empty, /No matches for the active filters/);
  const filtered = visibleText(render(DataTable, {
    columns: [{ id: "name", label: "Name" }],
    rows: [],
    filtered: true,
    emptySentence: "No projects in this workspace.",
  }));
  assert.match(filtered, /No matches for the active filters/);
  assert.match(filtered, /Clear filters/);
  const rows = render(DataTable, {
    columns: [
      { id: "name", label: "Name" },
      { id: "actions", label: "Actions" },
    ],
    rows: [{
      id: 1, name: "prod",
      allowed_actions: [
        { id: "site.view_details", label: "View site details" },
        { id: "site.fix_blockers", label: "Fix blockers" },
      ],
      disabled_actions: [{ id: "site.delete", label: "Delete", reason: "not from this table" }],
    }],
  });
  assert.match(visibleText(rows), /More actions/);
  assert.match(visibleText(rows), /Fix blockers/);
  assert.match(rows, /tabindex="0"/i);
});

test("workspace_profile_and_security_do_not_route_through_administration", async () => {
  const { act, create } = await import("react-test-renderer");
  const nav: any[] = [];
  const props = {
    user: { username: "op", capabilities: ["hud_ui_v1"] },
    onNav: (screen: string, id?: string) => nav.push([screen, id]),
    defaultOpen: true,
  };
  let tree: any;
  await act(() => {
    tree = create(React.createElement(WorkspaceMenu, props));
  });
  const profile = tree.root.findAllByType("button").find((b: any) => nodeText(b) === "Profile");
  await act(() => profile.props.onClick({ preventDefault() {} }));
  assert.notEqual(nav.at(-1)?.[0], "admin");
  tree.unmount();
  await act(() => {
    tree = create(React.createElement(WorkspaceMenu, props));
  });
  const security = tree.root.findAllByType("button").find((b: any) => nodeText(b) === "Security");
  assert.ok(security, "Security menu item");
  await act(() => security.props.onClick({ preventDefault() {} }));
  assert.notEqual(nav.at(-1)?.[0], "admin");
  assert.ok(nav.every((n) => n[0] !== "admin"));
});

test("sign_out_clears_react_auth_state_immediately", async () => {
  const { act, create } = await import("react-test-renderer");
  let cleared = false;
  const props = {
    user: { username: "op", capabilities: ["hud_ui_v1"] },
    onNav: () => {},
    onLogout: () => { cleared = true; },
    defaultOpen: true,
  };
  let tree: any;
  await act(() => {
    tree = create(React.createElement(WorkspaceMenu, props));
  });
  const signOut = tree.root.findAllByType("button").find((b: any) => nodeText(b) === "Sign out");
  assert.ok(signOut, "Sign out menu item");
  await act(() => signOut.props.onClick({ preventDefault() {} }));
  assert.equal(cleared, true);
  tree.unmount();
});
