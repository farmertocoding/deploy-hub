// Shared HUD administration helpers. Screens compose these; they do not
// invent permissions, hex colors, or step names.

export const STEP_LABELS = {
  build: "Build",
  ship: "Ship",
  migrate: "Migrate",
  start_green: "Start green",
  health_check: "Health check",
  dns: "DNS",
  route_tls: "Route & TLS",
  smoke_test: "Smoke test",
  cutover: "Cutover",
};

export function scopedCount(n, unit) {
  const count = Number(n) || 0;
  return `${count} ${unit}`;
}

export function adminHref(id, query = {}) {
  const q = new URLSearchParams();
  Object.entries(query || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value) !== "") {
      q.set(key, String(value));
    }
  });
  const qs = q.toString();
  const path = id || "overview";
  return qs ? `${path}?${qs}` : path;
}

export function currentScope(route) {
  return (route?.query?.scope || parseHashQuery().scope || "");
}

export function scopedPath(path, route) {
  const scope = currentScope(route);
  if (!scope) return path;
  if (/(?:^|[?&])scope=/.test(path)) return path;
  const join = path.includes("?") ? "&" : "?";
  return `${path}${join}scope=${encodeURIComponent(scope)}`;
}

export function parseHashQuery(hash, defaults = {}) {
  try {
    const raw = hash ?? (typeof window !== "undefined" ? window.location.hash : "");
    const q = new URLSearchParams((String(raw).split("?")[1]) || "");
    const out = { ...defaults };
    q.forEach((value, key) => {
      out[key] = value;
    });
    return out;
  } catch {
    return { ...defaults };
  }
}

export function writeHashQuery(values, loc, baseHash = "#/admin") {
  const q = new URLSearchParams();
  Object.entries(values || {}).forEach(([key, value]) => {
    if (value !== undefined && value !== null && String(value) !== "") {
      q.set(key, String(value));
    }
  });
  const target = loc || (typeof window !== "undefined" ? window.location : { hash: baseHash });
  const base = String(target.hash || baseHash).split("?")[0] || baseHash;
  const qs = q.toString();
  target.hash = qs ? `${base}?${qs}` : base;
  return target.hash;
}

export function filtersActive(values, skip = ["sort", "page", "tab", "scope"]) {
  return Object.entries(values || {}).some(([key, value]) => {
    if (skip.includes(key)) return false;
    if (key === "facet" && (value === "" || value === "all")) return false;
    return value !== undefined && value !== null && String(value) !== "";
  });
}

export function attachRowActions(rows, handlers = {}) {
  return (rows || []).map((row) => ({
    ...row,
    allowed_actions: (row.allowed_actions || []).map((action) => ({
      ...action,
      onRun: action.onRun || ((item) => handlers[action.id]?.(item || row, action)),
    })),
  }));
}

import { api } from "../../api.js";

export async function hudGet(path, route) {
  const { status, data } = await api(scopedPath(path, route));
  if (status === 401) throw { status, signedOut: true, data };
  if (status === 403) throw { status, denied: true, data };
  if (status === 404) throw { status, notFound: true, data };
  if (status === 409) throw { status, conflict: true, data };
  if (status !== 200 && status !== 202) throw { status, data };
  return data;
}

export function presentExport(data) {
  if (!data?.csv) return data;
  const filename = data.filename || "export.csv";
  const doc = typeof document !== "undefined" ? document : null;
  if (doc?.createElement) {
    const a = doc.createElement("a");
    a.setAttribute("download", filename);
    a.download = filename;
    a.href = `data:text/csv;charset=utf-8,${encodeURIComponent(data.csv)}`;
    a.textContent = `Download ${filename}`;
    if (typeof a.click === "function") a.click();
    if (doc.body?.appendChild) doc.body.appendChild(a);
  }
  return data;
}

export async function hudPost(path, body) {
  const payload = body && typeof body === "object" ? { ...body } : body;
  if (payload && typeof payload === "object" && !payload.idempotency_key) {
    payload.idempotency_key = (
      typeof crypto !== "undefined" && crypto.randomUUID
        ? crypto.randomUUID()
        : `hud-${Date.now()}`
    );
  }
  const { status, data } = await api(path, payload, "POST");
  if (status === 401) throw { status, signedOut: true, data };
  if (status === 403) throw { status, denied: true, data };
  if (status === 409) throw { status, conflict: true, data };
  if (status !== 200 && status !== 201 && status !== 202) throw { status, data };
  return { status, data };
}

export function defaultActionHandlers({ onNav, onSelect, onCommand, onPending } = {}) {
  const command = (path, body, extra = {}) => {
    if (onCommand) return onCommand({ path, body, ...extra });
    return hudPost(path, body);
  };
  return {
    "project.create": () => onNav?.("admin", "projects/new"),
    "project.open": (row) => onNav?.("admin", `projects/${row.id}`),
    "project.scan": (row) => command(`v1/hud/projects/${row.id}/commands/`, { action: "project.scan" }),
    "target.create": () => onPending?.({
      id: "target.create",
      label: "Create Target",
      tier: "T1",
      cost: 0.05,
      confirmName: "host",
      summary: "T1 — provisions a Target with a cost estimate. Type the host and touch a security key.",
      path: "v1/hud/targets/commands/",
      body: { action: "target.create" },
    }),
    "target.open": (row) => onNav?.("admin", `targets/${row.id}`),
    "target.probe": (row) => command(`v1/hud/targets/${row.id}/commands/`, { action: "target.probe" }),
    "partner.create": () => onPending?.({
      id: "partner.create",
      label: "Create Partner",
      tier: "T1",
      confirmName: "slug",
      summary: "T1 — create a partner tenant. Type the slug and touch a security key.",
      path: "v1/hud/partners/commands/",
      body: { action: "partner.create" },
    }),
    "partner.open": (row) => onNav?.("admin", `partners/${row.id}`),
    "partner.view_sites": (row) => onNav?.("admin", adminHref("sites", { q: row.slug })),
    "finding.open": (row) => onNav?.("admin", `findings/${row.id}`),
    "finding.ack": (row) => command(`v1/hud/findings/${row.id}/commands/`, { action: "finding.ack" }),
    "site.create": () => onNav?.("admin", "sites/new"),
    "site.view": (row) => onNav?.("admin", `sites/${row.id}`),
    "site.view_details": (row) => onNav?.("admin", `sites/${row.id}`),
    "site.view_deploy": (row) => onNav?.("admin", `deployments/${row.active_deployment}`),
    "site.fix_blockers": (row) => onNav?.("admin", adminHref("findings", { entity: row.name })),
    "site.deploy": (row) => onNav?.("admin", adminHref("deployments", { site: row.id })),
    "site.more": (row) => onSelect?.(row.id),
    "site.open_live": (row) => {
      if (row.domain && typeof window !== "undefined") {
        window.open(`https://${row.domain}`, "_blank", "noopener");
      }
    },
    "site.export_view": async () => {
      if (onCommand) return onCommand({ path: "v1/hud/sites/?export=csv", method: "GET" });
      return presentExport(await hudGet("v1/hud/sites/?export=csv"));
    },
    "secret.create": () => onNav?.("admin", adminHref("secrets", { wizard: "secret" })),
    "member.invite": () => onNav?.("admin", adminHref("secrets", { wizard: "invite", tab: "members" })),
    "secret.rotate": (row) => onNav?.("admin", adminHref("secrets", { rotate: row?.id || "queue" })),
    "secret.rotate_queue": () => onNav?.("admin", adminHref("secrets", { tab: "vault", plan: "queue" })),
    "integration.verify": () => command("v1/hud/integrations/commands/", { action: "integration.verify" }),
    "aws.connect": () => onNav?.("settings"),
    "aws.verify": () => command("v1/hud/integrations/commands/", { action: "aws.verify" }),
    "aws.replace": () => onNav?.("settings"),
    "cloudflare.connect": () => onNav?.("settings"),
    "cloudflare.verify": () => command("v1/hud/integrations/commands/", { action: "cloudflare.verify" }),
    "cloudflare.replace": () => onNav?.("settings"),
    "dns.add_zone": () => onNav?.("settings"),
    "dns.verify": () => command("v1/hud/integrations/commands/", { action: "dns.verify" }),
  };
}
