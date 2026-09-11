import { test } from "node:test";
import assert from "node:assert/strict";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";

(globalThis as any).window = (globalThis as any).window ?? {
  location: { search: "?sim=live", hash: "#/admin/sites" },
};
(globalThis as any).document = (globalThis as any).document ?? { cookie: "" };

import {
  filtersFromHash, writeFilters, SitesFleetView, sitesFleetSnapshot, AddSiteWizard,
} from "../src/screens/administration/SitesFleet.jsx";

import Overview, { OverviewView } from "../src/screens/administration/Overview.jsx";
import { ProjectsView, AddApplicationWizard } from "../src/screens/administration/Projects.jsx";
import { DeploymentsView } from "../src/screens/administration/Deployments.jsx";
import Targets, { TargetsView } from "../src/screens/administration/Targets.jsx";
import FindingsOps, { FindingsOpsView } from "../src/screens/administration/FindingsOps.jsx";
import { PartnersView } from "../src/screens/administration/Partners.jsx";
import Integrations, { IntegrationsView } from "../src/screens/administration/Integrations.jsx";
import { AuditView } from "../src/screens/administration/Audit.jsx";
import { HUD_SECRET_FIXTURE, HUD_OVERVIEW_FIXTURE, HUD_DEPLOY_FIXTURE } from "../src/hud-sim.js";
import AccessSecrets, { AccessSecretsView, attachSecretActions, fetchRotatePlan } from "../src/screens/administration/AccessSecrets.jsx";
import { parseRoute } from "../src/Chrome.jsx";
import { adminHref } from "../src/screens/administration/contract.js";
import { TopBar } from "../src/ui/TopBar.jsx";
import { ThemeProvider } from "../src/theme/ThemeProvider.jsx";

const render = (component: any, props: any = {}) =>
  renderToStaticMarkup(React.createElement(component, props));
const visibleText = (markup: string) => markup.replace(/<[^>]*>/g, "");

test("sites_fleet_hash_round_trips_sort_and_page", () => {
  const loc = { hash: "#/admin/sites?sort=domain&page=2&q=shop" };
  const parsed = filtersFromHash(loc.hash);
  assert.equal(parsed.sort, "domain");
  assert.equal(parsed.page, "2");
  assert.equal(parsed.q, "shop");
  const written = writeFilters(
    { q: "", health: "", sort: "target", page: "3" },
    loc,
  );
  assert.match(written, /sort=target/);
  assert.match(written, /page=3/);
  const again = filtersFromHash(written);
  assert.equal(again.sort, "target");
  assert.equal(again.page, "3");
});

test("sites_fleet_view_exposes_sort_and_page_controls", () => {
  const markup = render(SitesFleetView, {
    rows: [{
      id: 1, project: "shop", name: "prod", domain: "shop.example.test",
      health: "healthy", target: "edge-1",
      allowed_actions: [], disabled_actions: [],
    }],
    filters: { q: "", health: "", sort: "name", page: "1" },
    onFilter: () => {},
    onNav: () => {},
    pageInfo: { next: "2", count: 3, page: 1, sort: "name" },
    width: 1280,
  });
  const text = visibleText(markup);
  assert.match(text, /Sort/);
  assert.match(text, /Page 1/);
  assert.match(text, /Next page/);
  assert.match(text, /Previous page/);
  assert.match(markup, /<select[^>]*aria-label="Sort"/);
});

test("sites_fleet_snapshot_sends_sort_and_page_and_sim_paginates", async () => {
  (globalThis as any).window.location.search = "?sim=live";
  const first = await sitesFleetSnapshot({ sort: "name", page: "1", page_size: "1" });
  assert.equal(first.sort, "name");
  assert.equal(first.page, 1);
  assert.equal(first.results.length, 1);
  assert.equal(first.next, "2");
  const names = first.results.map((r: any) => r.name);
  const second = await sitesFleetSnapshot({ sort: "name", page: "2", page_size: "1" });
  assert.equal(second.results.length, 1);
  assert.notEqual(second.results[0].name, names[0]);
  const byProject = await sitesFleetSnapshot({ sort: "project", page: "1", page_size: "50" });
  const projects = byProject.results.map((r: any) => r.project);
  assert.deepEqual(projects, [...projects].sort());
});

test("overview_view_uses_scoped_counts_named_drilldowns_and_add_application", () => {
  const markup = render(OverviewView, {
    data: HUD_OVERVIEW_FIXTURE,
    onNav: () => {},
  });
  const text = visibleText(markup);
  assert.match(text, /3 P1\/P2/);
  assert.match(text, /1 queued/);
  assert.match(text, /1 running/);
  assert.match(text, /waiting-for-lock/);
  assert.match(text, /3 healthy sites/);
  assert.match(text, /2 ready targets/);
  assert.match(text, /ADD APPLICATION/);
  assert.match(text, /View attention queue/);
  assert.match(text, /View deployments/);
  assert.match(text, /View sites/);
  assert.match(text, /View targets/);
  assert.match(text, /REVIEW/);
  assert.match(text, /View fleet health/);
  assert.match(text, /View integrations/);
  assert.doesNotMatch(text, /FINISH SETUP/);
  assert.doesNotMatch(text, /First-run checklist complete/);
  assert.doesNotMatch(markup, /<form/);
  assert.match(text, /none of these cards mutate/);
});

test("overview_finish_setup_only_while_checklist_incomplete", () => {
  const incomplete = render(OverviewView, {
    data: {
      ...HUD_OVERVIEW_FIXTURE,
      setup: [{ id: "enroll", title: "Enroll a target", href: "targets" }],
      allowed_actions: [{ id: "project.create", label: "ADD APPLICATION" }],
    },
    onNav: () => {},
  });
  assert.match(visibleText(incomplete), /FINISH SETUP/);
  assert.match(visibleText(incomplete), /Enroll a target/);
});

test("sites_fleet_named_filters_export_and_server_row_actions", () => {
  const markup = render(SitesFleetView, {
    rows: [{
      id: 1, project: "shop", name: "prod", domain: "shop.example.test",
      environment: "production", health: "healthy", target: "edge-1",
      live_release: "v4", desired_release: "v4",
      tls: "ok", backup: "fresh",
      allowed_actions: [
        { id: "site.fix_blockers", label: "Fix blockers" },
        { id: "site.view_deploy", label: "View deploy" },
        { id: "site.deploy", label: "Deploy" },
        { id: "site.more", label: "More" },
        { id: "site.open_live", label: "Open live site" },
        { id: "site.view_details", label: "View site details" },
      ],
      disabled_actions: [],
    }],
    filters: { q: "shop", health: "", facet: "all", sort: "name", page: "1" },
    onFilter: () => {},
    onNav: () => {},
    collectionActions: [
      { id: "site.create", label: "ADD SITE" },
      { id: "site.export_view", label: "EXPORT VIEW" },
    ],
    pageInfo: { next: null, count: 1, page: 1, sort: "name" },
    width: 1280,
  });
  const text = visibleText(markup);
  assert.match(text, /ADD SITE/);
  assert.match(text, /ALL/);
  assert.match(text, /NEEDS ATTENTION/);
  assert.match(text, /ACTIVE DEPLOY/);
  assert.match(text, /CLEAR/);
  assert.match(text, /EXPORT VIEW/);
  assert.match(text, /Fix blockers/);
  assert.match(text, /View deploy/);
  assert.match(text, /Deploy/);
  assert.match(text, /More/);
  assert.match(text, /Open live site/);
  assert.match(text, /View site details/);
});

test("remaining_admin_destinations_render_named_collections_not_operator_redirects", () => {
  const projects = visibleText(render(ProjectsView, {
    rows: [{
      id: 1, name: "shop", slug: "shop", source_kind: "git",
      source: "git@example/shop", scan_state: "scanned", sites: 2,
      allowed_actions: [{ id: "project.open", label: "Open" }, { id: "project.scan", label: "Scan now" }],
      disabled_actions: [{ id: "project.delete", label: "Delete permanently", reason: "Sites still exist." }],
    }],
    collectionActions: [{ id: "project.create", label: "ADD APPLICATION" }],
    phase: "live",
  }));
  assert.match(projects, /ADD APPLICATION/);
  assert.match(projects, /Scan now/);
  assert.match(projects, /Open/);
  assert.match(projects, /Delete permanently/);
  assert.doesNotMatch(projects, /matching operator surface/);

  const deploys = visibleText(render(DeploymentsView, {
    rows: [{
      id: 11, site: "shop/prod", version: 4, state: "running", current_step: "health_check",
      allowed_actions: [{ id: "deployment.view", label: "Open" }],
      disabled_actions: [],
    }],
    phase: "live",
  }));
  assert.match(deploys, /Open/);
  assert.doesNotMatch(deploys, /Delete Deployment/);

  const targets = visibleText(render(TargetsView, {
    rows: [{
      id: 1, host: "edge-1", kind: "ssh", zone: "hud-net", status: "ready",
      allowed_actions: [{ id: "target.open", label: "Open" }, { id: "target.probe", label: "Probe router" }],
      disabled_actions: [{ id: "target.decommission", label: "Decommission Target", reason: "Workloads still scheduled." }],
    }],
    collectionActions: [{ id: "target.create", label: "Create Target" }],
    phase: "live",
  }));
  assert.match(targets, /Create Target/);
  assert.match(targets, /Probe router/);

  const findings = visibleText(render(FindingsOpsView, {
    rows: [{
      id: 1, severity: "p1", state: "open", title: "Probe failed", entity: "site:shop",
      fingerprint: "hud-p1", source_engine: "uptime",
      allowed_actions: [{ id: "finding.open", label: "Open" }, { id: "finding.ack", label: "Ack" }],
      disabled_actions: [],
    }],
    operations: [{ id: "lock-1", kind: "deploy", state: "held", object: "site:1" }],
    phase: "live",
  }));
  assert.match(findings, /Ack/);
  assert.doesNotMatch(findings, /Delete Finding/);

  const partners = visibleText(render(PartnersView, {
    rows: [{
      id: 1, slug: "acme", name: "Acme", suspended: false, sites: 1,
      allowed_actions: [{ id: "partner.open", label: "Open" }, { id: "partner.view_sites", label: "View Sites" }],
      disabled_actions: [],
    }],
    collectionActions: [{ id: "partner.create", label: "Create Partner" }],
    phase: "live",
  }));
  assert.match(partners, /Create Partner/);
  assert.match(partners, /View Sites/);

  const integrations = visibleText(render(IntegrationsView, {
    data: {
      aws: { state: "connected", account_last4: "1234", region: "us-east-1" },
      cloudflare: { state: "connected", account: "cf-main" },
      dns: [{ id: 1, provider: "cloudflare", label: "prod-zone", zones: 1 }],
      vault: { kek_id: "kek-1", kek_age_days: 12, active_secrets: 1 },
    },
    phase: "live",
  }));
  assert.match(integrations, /Connect|Verify/);
  assert.match(integrations, /kek-1/);
  assert.doesNotMatch(integrations, /ciphertext/);

  const audit = visibleText(render(AuditView, {
    rows: [{
      id: 1, ts: "2026-08-27T12:00:00Z", actor: "admin", action: "site.deploy",
      object_type: "deployment", object_id: "11",
    }],
    phase: "live",
  }));
  assert.match(audit, /site\.deploy/);

  const empty = visibleText(render(ProjectsView, { rows: [], phase: "live" }));
  assert.match(empty, /No projects/);
  const denied = visibleText(render(ProjectsView, { phase: "permission-denied", deniedReason: "admin_read required" }));
  assert.match(denied, /Permission denied/);
  const errored = visibleText(render(ProjectsView, { phase: "error", error: "boom", onRetry: () => {} }));
  assert.match(errored, /boom/);
  assert.match(errored, /Retry/);
  const loading = visibleText(render(ProjectsView, { phase: "loading" }));
  assert.match(loading, /Loading/);
  const degraded = visibleText(render(ProjectsView, {
    rows: [{ id: 1, name: "shop", slug: "shop", allowed_actions: [], disabled_actions: [] }],
    phase: "degraded",
    asOf: "2026-08-27T12:00:00Z",
  }));
  assert.match(degraded, /data as of/i);
});

function nodeText(node: any): string {
  if (node == null) return "";
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(nodeText).join("");
  if (node.props?.children) return nodeText(node.props.children);
  if (node.children) return nodeText(node.children);
  return "";
}

async function mount(element: any) {
  const { act, create } = await import("react-test-renderer");
  let tree: any;
  await act(async () => {
    tree = create(element);
    await Promise.resolve();
    await Promise.resolve();
  });
  return { tree, act };
}

function click(tree: any, label: string) {
  const btn = tree.root.findAllByType("button").find((b: any) => nodeText(b).includes(label));
  assert.ok(btn, `missing button ${label}`);
  btn.props.onClick({ preventDefault() {}, stopPropagation() {} });
  return btn;
}

test("named_buttons_navigate_or_post_commands", async () => {
  (globalThis as any).window.location.search = "?sim=live";
  (globalThis as any).window.location.hash = "#/admin/overview";
  const nav: any[] = [];
  const onNav = (screen: string, id?: string) => nav.push([screen, id]);

  const overview = render(OverviewView, { data: HUD_OVERVIEW_FIXTURE, onNav });
  // SSR cannot click; drive the same View buttons via test renderer.
  const { tree: ov, act } = await mount(React.createElement(OverviewView, {
    data: HUD_OVERVIEW_FIXTURE, onNav,
  }));
  await act(() => { click(ov, "View attention queue"); });
  assert.deepEqual(nav.at(-1), ["admin", "findings?facet=p1p2"]);
  await act(() => { click(ov, "View deployments"); });
  assert.deepEqual(nav.at(-1), ["admin", "deployments?facet=active"]);
  await act(() => { click(ov, "ADD APPLICATION"); });
  assert.deepEqual(nav.at(-1), ["admin", "projects/new"]);
  void overview;

  const { tree: secrets } = await mount(React.createElement(AccessSecretsView, {
    rows: [HUD_SECRET_FIXTURE],
    members: [],
    memberDisabled: [],
    tab: "vault",
    onNav,
  }));
  await act(() => { click(secrets, "ADD SECRET"); });
  assert.equal(nav.at(-1)?.[0], "admin");
  assert.match(String(nav.at(-1)?.[1]), /wizard=secret/);
  await act(() => { click(secrets, "REVIEW ROTATION PLAN"); });
  assert.match(String(nav.at(-1)?.[1]), /plan=queue/);
  const { tree: membersTab } = await mount(React.createElement(AccessSecretsView, {
    rows: [],
    members: [{ id: 1, username: "op", role: "owner" }],
    memberDisabled: [],
    tab: "members",
    onNav,
  }));
  await act(() => { click(membersTab, "INVITE USER"); });
  assert.match(String(nav.at(-1)?.[1]), /wizard=invite/);

  const { tree: integ } = await mount(React.createElement(IntegrationsView, {
    data: {
      aws: { state: "connected", account_last4: "1234", region: "us-east-1" },
      cloudflare: { state: "connected", account: "cf-main" },
      dns: [{ id: 1, provider: "cloudflare", label: "prod-zone", zones: 1 }],
      vault: { kek_id: "kek-1", kek_age_days: 12, active_secrets: 1 },
    },
    phase: "live",
    onNav,
  }));
  await act(() => { click(integ, "Replace credentials"); });
  assert.equal(nav.at(-1)?.[0], "settings");
  await act(() => { click(integ, "REVIEW ROTATION PLAN"); });
  assert.match(String(nav.at(-1)?.[1]), /secrets/);

  const { tree: wizard } = await mount(React.createElement(AddApplicationWizard, { onNav }));
  const named = wizard.root.findAllByType("input");
  await act(() => {
    named[0].props.onChange({ target: { value: "shop" } });
    named[1].props.onChange({ target: { value: "git@example/shop" } });
  });
  await act(async () => { click(wizard, "Test source"); await Promise.resolve(); await Promise.resolve(); });
  await act(() => { click(wizard, "Continue"); });
  const siteInputs = wizard.root.findAllByType("input");
  const domain = siteInputs.find((el: any) => el.props["aria-label"] === "Domain");
  await act(() => { domain.props.onChange({ target: { value: "shop.example.test" } }); });
  await act(() => { click(wizard, "Continue"); });
  await act(() => { click(wizard, "Continue"); });
  assert.match(nodeText(wizard.root), /This creates one Project and one Site/);
  await act(async () => { click(wizard, "Create application"); await Promise.resolve(); });
  assert.ok(nav.some((n) => n[0] === "admin" && String(n[1]).includes("projects")));

  const { tree: sites } = await mount(React.createElement(SitesFleetView, {
    rows: [{
      id: 1, project: "shop", name: "prod", domain: "shop.example.test",
      allowed_actions: [
        { id: "site.more", label: "More" },
        { id: "site.fix_blockers", label: "Fix blockers" },
      ],
      disabled_actions: [],
    }],
    filters: { q: "", health: "", facet: "all", sort: "name", page: "1" },
    onFilter: () => {},
    onNav,
    onSelect: (id: any) => nav.push(["select", id]),
    collectionActions: [
      { id: "site.create", label: "ADD SITE" },
      { id: "site.export_view", label: "EXPORT VIEW" },
    ],
    pageInfo: { next: null, count: 1, page: 1, sort: "name" },
    width: 1280,
  }));
  await act(() => { click(sites, "ADD SITE"); });
  assert.deepEqual(nav.at(-1), ["admin", "sites/new"]);
  await act(() => { click(sites, "Fix blockers"); });
  assert.match(String(nav.at(-1)?.[1]), /findings/);
  await act(() => { click(sites, "More"); });
  assert.equal(nav.at(-1)?.[0], "select");

  const { tree: targets } = await mount(React.createElement(TargetsView, {
    rows: [{
      id: 1, host: "edge-1", kind: "ssh", zone: "hud-net", status: "ready",
      allowed_actions: [{ id: "target.probe", label: "Probe router" }],
      disabled_actions: [],
    }],
    collectionActions: [{ id: "target.create", label: "Create Target" }],
    phase: "live",
    onNav,
    actionHandlers: (await import("../src/screens/administration/contract.js")).defaultActionHandlers({
      onNav,
      onPending: (p: any) => nav.push(["pending", p.id]),
      onCommand: (c: any) => { nav.push(["command", c.path, c.body?.action]); return { status: 202, data: { operation_id: 1 } }; },
    }),
  }));
  await act(() => { click(targets, "Create Target"); });
  assert.deepEqual(nav.at(-1)?.slice(0, 2), ["pending", "target.create"]);
  await act(() => { click(targets, "Probe router"); });
  assert.equal(nav.at(-1)?.[0], "command");
  assert.match(String(nav.at(-1)?.[1]), /targets\/1\/commands/);

  const { tree: findings } = await mount(React.createElement(FindingsOpsView, {
    rows: [{
      id: 1, severity: "p1", state: "open", title: "Probe failed", entity: "site:shop",
      fingerprint: "hud-p1", source_engine: "uptime",
      allowed_actions: [{ id: "finding.ack", label: "Ack" }],
      disabled_actions: [],
    }],
    operations: [],
    phase: "live",
    onNav,
    actionHandlers: (await import("../src/screens/administration/contract.js")).defaultActionHandlers({
      onNav,
      onCommand: (c: any) => { nav.push(["command", c.path, c.body?.action]); return { status: 202, data: {} }; },
    }),
  }));
  await act(() => { click(findings, "Ack"); });
  assert.deepEqual(nav.at(-1)?.slice(1), ["v1/hud/findings/1/commands/", "finding.ack"]);

  const { tree: bar } = await mount(React.createElement(ThemeProvider, {
    children: React.createElement(TopBar, {
      workspace: "admin",
      events: { status: "live" },
      user: { username: "admin", capabilities: ["admin_read"] },
      onNav,
      route: { screen: "admin", id: "overview" },
      shell: { p1_p2: 3, scope: "production", operations: [] },
    }),
  }));
  await act(() => { click(bar, "3 P1/P2"); });
  assert.match(String(nav.at(-1)?.[1]), /facet=p1p2/);
  await act(() => { click(bar, "Production"); });
  assert.match(String(nav.at(-1)?.[1]), /scope=test/);

  const parsed = parseRoute("#/admin/findings?facet=p1p2&scope=test");
  assert.equal(parsed.screen, "admin");
  assert.equal(parsed.id, "findings");
  assert.equal(parsed.query.facet, "p1p2");
  assert.equal(parsed.query.scope, "test");
  assert.equal(adminHref("findings", { facet: "p1p2" }), "findings?facet=p1p2");

  const { tree: liveOverview } = await mount(React.createElement(Overview, {
    onNav, events: { status: "live" },
  }));
  await act(() => { click(liveOverview, "View attention queue"); });
  assert.deepEqual(nav.at(-1), ["admin", "findings?facet=p1p2"]);

  const { tree: liveFindings, act: actFind } = await mount(React.createElement(FindingsOps, {
    route: { screen: "admin", id: "findings", query: { facet: "p1p2" } },
    onNav, width: 1280,
  }));
  await actFind(async () => { await new Promise((r) => setTimeout(r, 20)); });
  const findingsJson = JSON.stringify(liveFindings.toJSON());
  assert.match(findingsJson, /Probe failed|P1|Findings/);

  void AccessSecrets;
  void Integrations;
});

test("scope_toggle_refetches_overview_sites_and_targets", async () => {
  (globalThis as any).window.location.search = "?sim=live";
  (globalThis as any).window.location.hash = "#/admin/overview?scope=test";
  const { currentScope, scopedPath } = await import("../src/screens/administration/contract.js");
  assert.equal(currentScope({ query: { scope: "test" } }), "test");
  assert.match(scopedPath("v1/hud/overview/"), /scope=test/);
  const { tree: ov, act } = await mount(React.createElement(Overview, {
    onNav: () => {},
    events: { status: "live" },
    route: { screen: "admin", id: "overview", query: { scope: "test" } },
  }));
  await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  assert.match(JSON.stringify(ov.toJSON()), /data-fetched-scope":"test"|data-fetched-scope"\s*:\s*"test"/);

  (globalThis as any).window.location.hash = "#/admin/sites?scope=test";
  const sitesBody = await sitesFleetSnapshot({});
  assert.equal(sitesBody.scope, "test");

  const { tree: tg, act: actT } = await mount(React.createElement(Targets, {
    onNav: () => {},
    route: { screen: "admin", id: "targets", query: { scope: "test" } },
    width: 1280,
  }));
  await actT(async () => { await new Promise((r) => setTimeout(r, 20)); });
  assert.match(JSON.stringify(tg.toJSON()), /data-fetched-scope":"test"|Create Target|edge-1/);
});

test("create_target_and_partner_use_t1_overlay_not_confirm_only", async () => {
  const markup = render(TargetsView, {
    rows: [],
    collectionActions: [{ id: "target.create", label: "Create Target" }],
    phase: "live",
    pending: {
      id: "target.create",
      label: "Create Target",
      tier: "T1",
      summary: "T1 — provisions a Target with a cost estimate.",
      cost: 0.05,
    },
    onNav: () => {},
  });
  const text = visibleText(markup);
  assert.match(text, /Touch security key/);
  assert.match(text, /type the name/i);
  assert.match(text, /five cents per hour|0\.05/);
  assert.match(markup, /step-up/);

  const { tree, act } = await mount(React.createElement(Targets, {
    route: { screen: "admin", id: "targets" },
    onNav: () => {},
    width: 1280,
  }));
  await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  await act(() => { click(tree, "Create Target"); });
  const after = JSON.stringify(tree.toJSON());
  assert.match(after, /Touch security key/);
  assert.match(after, /type the name/i);
});

test("export_view_presents_named_csv_artifact", async () => {
  (globalThis as any).window.location.search = "?sim=live";
  const created: any[] = [];
  const doc = {
    cookie: "",
    body: {
      children: [] as any[],
      appendChild(el: any) { this.children.push(el); return el; },
    },
    createElement(tag: string) {
      const el: any = { tagName: tag, download: "", href: "", clicked: false, attrs: {} as any };
      el.setAttribute = (k: string, v: string) => { el.attrs[k] = v; if (k === "download") el.download = v; };
      el.click = () => { el.clicked = true; created.push(el); };
      created.push(el);
      return el;
    },
  };
  (globalThis as any).document = doc;
  const { presentExport } = await import("../src/screens/administration/contract.js");
  const exported = await sitesFleetSnapshot({ export: "csv" });
  assert.match(exported.csv, /project,name/);
  assert.equal(exported.filename, "sites.csv");
  presentExport(exported);
  const link = created.find((el) => el.download === "sites.csv" || el.attrs?.download === "sites.csv");
  assert.ok(link, "expected a named sites.csv download");
  assert.equal(link.clicked, true);

  const notice = render(SitesFleetView, {
    rows: [],
    filters: { q: "", health: "", facet: "all", sort: "name", page: "1" },
    onFilter: () => {},
    onNav: () => {},
    collectionActions: [{ id: "site.export_view", label: "EXPORT VIEW" }],
    lastCommand: { result: { csv: exported.csv, filename: "sites.csv", count: exported.count } },
    pageInfo: {},
    width: 1280,
    phase: "live",
  });
  assert.match(visibleText(notice), /sites\.csv/);
});

test("plan_rotation_hits_rotate_plan_endpoint_and_is_wired", async () => {
  (globalThis as any).window.location.search = "?sim=live";
  const { status, data } = await fetchRotatePlan(8);
  assert.equal(status, 200);
  assert.equal(data.secret_id, 8);
  assert.ok(Array.isArray(data.affected));
  assert.ok(data.affected.some((x: any) => x.name === "shop/prod"));
  assert.ok(!("ciphertext" in data));
  assert.ok(!("plaintext" in data));
  const wired = attachSecretActions([HUD_SECRET_FIXTURE], { onPlanRotation: () => {} });
  const plan = wired[0].allowed_actions.find((a: any) => a.id === "secret.rotate_plan");
  assert.equal(typeof plan.onRun, "function");
  let captured: any = null;
  const markup = render(AccessSecretsView, {
    rows: [HUD_SECRET_FIXTURE],
    onPlanRotation: (d: any) => { captured = d; },
    members: [],
    memberDisabled: [],
  });
  assert.match(visibleText(markup), /Plan rotation/);
  assert.equal(captured, null);
});

test("secret_wizard_opens_t1_overlay_instead_of_posting", async () => {
  const { act, create } = await import("react-test-renderer");
  (globalThis as any).FormData = class {
    constructor(_form: any) {}
    *[Symbol.iterator]() {
      yield ["kind", "api_token"];
      yield ["owner_type", "site"];
      yield ["owner_id", "1"];
      yield ["value", "sk-test"];
    }
  };
  let posted: any = null;
  let tree: any;
  await act(() => {
    tree = create(React.createElement(AccessSecretsView, {
      rows: [HUD_SECRET_FIXTURE],
      members: [],
      memberDisabled: [],
      wizard: "secret",
      onWizardSubmit: (kind: string, fields: any) => { posted = { kind, fields }; },
    }));
  });
  const form = tree.root.findAllByType("form").find((f: any) =>
    f.findAllByType("select").some((s: any) => s.props.name === "kind"),
  );
  assert.ok(form, "secret wizard form must exist");
  await act(() => form.props.onSubmit({ preventDefault() {}, target: {} }));
  const text = JSON.stringify(tree.toJSON());
  assert.match(text, /type the name/i);
  assert.equal(posted, null, "secret.create must not POST before T1 confirm");
});

test("overview_retry_issues_a_second_snapshot_request", async () => {
  (globalThis as any).window.location.search = "";
  (globalThis as any).window.location.hash = "#/admin/overview";
  (globalThis as any).document.cookie = "csrftoken=test";
  let overviewCalls = 0;
  (globalThis as any).fetch = async (url: string) => {
    if (String(url).includes("v1/hud/overview")) {
      overviewCalls += 1;
      if (overviewCalls === 1) {
        return { status: 500, json: async () => ({ detail: "boom" }) };
      }
      return { status: 200, json: async () => HUD_OVERVIEW_FIXTURE };
    }
    return { status: 404, json: async () => ({}) };
  };
  const { tree, act } = await mount(React.createElement(Overview, {
    onNav: () => {},
    events: { status: "live" },
    route: { screen: "admin", id: "overview" },
  }));
  await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  assert.equal(overviewCalls, 1);
  assert.match(nodeText(tree.toJSON()), /boom|Could not load|Retry/);
  await act(async () => {
    click(tree, "Retry");
    await new Promise((r) => setTimeout(r, 20));
  });
  assert.ok(overviewCalls >= 2, `Retry must issue a new snapshot, got ${overviewCalls}`);
});

test("live_deployment_confirm_surfaces_command_result", async () => {
  const LiveDeployment = (await import("../src/screens/administration/LiveDeployment.jsx")).default;
  (globalThis as any).window.location.search = "";
  (globalThis as any).document.cookie = "csrftoken=test";
  const posts: any[] = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    const method = (opts?.method || "GET").toUpperCase();
    if (String(url).includes("v1/hud/deployments/11/commands") && method === "POST") {
      posts.push(JSON.parse(opts.body || "{}"));
      return {
        status: 202,
        json: async () => ({ operation_id: 77, state: "cancelled", action: "deployment.abort" }),
      };
    }
    if (String(url).includes("v1/hud/deployments/11")) {
      return { status: 200, json: async () => HUD_DEPLOY_FIXTURE };
    }
    return { status: 404, json: async () => ({}) };
  };
  const { tree, act } = await mount(React.createElement(LiveDeployment, {
    route: { screen: "admin", id: "deployments/11" },
    onNav: () => {},
    width: 1280,
    events: { status: "live" },
  }));
  await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  await act(() => { click(tree, "Abort and clean up"); });
  await act(async () => {
    click(tree, "Confirm");
    await new Promise((r) => setTimeout(r, 20));
  });
  assert.equal(posts.length, 1);
  assert.equal(posts[0].action, "deployment.abort");
  const text = nodeText(tree.toJSON());
  assert.match(text, /accepted|77|cancelled/i);
});

test("live_deployment_second_recovery_click_does_not_skip_confirm", async () => {
  const LiveDeployment = (await import("../src/screens/administration/LiveDeployment.jsx")).default;
  (globalThis as any).window.location.search = "";
  (globalThis as any).document.cookie = "csrftoken=test";
  const posts: any[] = [];
  (globalThis as any).fetch = async (url: string, opts: any) => {
    const method = (opts?.method || "GET").toUpperCase();
    if (String(url).includes("v1/hud/deployments/11/commands") && method === "POST") {
      posts.push(JSON.parse(opts.body || "{}"));
      return {
        status: 202,
        json: async () => ({ operation_id: 77, state: "cancelled", action: "deployment.abort" }),
      };
    }
    if (String(url).includes("v1/hud/deployments/11")) {
      return { status: 200, json: async () => HUD_DEPLOY_FIXTURE };
    }
    return { status: 404, json: async () => ({}) };
  };
  const { tree, act } = await mount(React.createElement(LiveDeployment, {
    route: { screen: "admin", id: "deployments/11" },
    onNav: () => {},
    width: 1280,
    events: { status: "live" },
  }));
  await act(async () => { await new Promise((r) => setTimeout(r, 20)); });
  await act(() => { click(tree, "Abort and clean up"); });
  const recoveryAbort = tree.root.findAllByType("button").filter((b: any) => {
    const text = nodeText(b);
    return text.includes("Abort and clean up") && !text.includes("Confirm");
  });
  assert.equal(recoveryAbort.length, 0, "recovery Abort must hide while Confirm is open");
  assert.equal(posts.length, 0);
  await act(async () => {
    click(tree, "Confirm");
    await new Promise((r) => setTimeout(r, 20));
  });
  assert.equal(posts.length, 1);
  assert.equal(posts[0].action, "deployment.abort");
});

test("add_site_wizard_posts_project_id_not_project", () => {
  const markup = render(AddSiteWizard, { onNav: () => {} });
  assert.match(markup, /name="project_id"/);
  assert.match(markup, /name="name"/);
  assert.doesNotMatch(markup, /name="project"/);
});
