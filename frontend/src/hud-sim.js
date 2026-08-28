// Simulation fixtures for HUD read models. Separate from sim.js so the
// zod-pinned §F8 transcripts stay a copy of real serializer output.

function never() {
  return new Promise(() => {});
}

const OBSERVED = "2026-08-27T12:00:00Z";

const OVERVIEW = {
  observed_at: OBSERVED,
  version: 1,
  findings: { p1: 1, p2: 2, p3: 4, open: 5 },
  deployments: { active: 2, queued: 1, running: 1, waiting_for_lock: 0, failed: 1 },
  site_health: { healthy: 3, warming: 0, unhealthy: 0, stale: 1 },
  target_readiness: { ready: 2, pressured: 1, unreachable: 0, decommissioned: 0 },
  attention: [
    {
      id: "finding-1",
      severity: "p1",
      title: "Probe failed on shop/prod",
      href: "#/findings/1",
    },
  ],
  active_deployments: [
    {
      id: 11,
      site: "shop/prod",
      version: 4,
      state: "running",
      current_step: "health_check",
    },
  ],
  integrations: { cloudflare: "connected", aws: "missing", vault: "connected", notifications: "unknown" },
  setup: [],
  links: {
    findings: "#/findings",
    deploys: "#/deploys",
    sites: "#/admin/sites",
    targets: "#/targets",
  },
  allowed_actions: [{ id: "project.create", label: "ADD APPLICATION" }],
  disabled_actions: [],
};

const SITE_ROWS = [
  {
    id: 1,
    name: "prod",
    project: "shop",
    domain: "shop.example.test",
    health: "healthy",
    environment: "production",
    exposure: "public",
    target: "edge-1",
    tls: "ok",
    live_release: "v4",
    desired_release: "v4",
    active_deployment: 11,
    findings: 1,
    observed_at: OBSERVED,
    allowed_actions: [
      { id: "site.view_details", label: "View site details" },
      { id: "site.open_live", label: "Open live site" },
      { id: "site.view_deploy", label: "View deploy" },
      { id: "site.fix_blockers", label: "Fix blockers" },
      { id: "site.deploy", label: "Deploy" },
      { id: "site.more", label: "More" },
    ],
    disabled_actions: [
      {
        id: "site.delete",
        label: "Delete",
        code: "not_permitted",
        reason: "Sites are not deleted from this table.",
      },
    ],
  },
  {
    id: 2,
    name: "staging",
    project: "alpha",
    domain: "staging.example.test",
    health: "stale",
    environment: "staging",
    exposure: "mesh_only",
    target: "edge-2",
    tls: "ok",
    live_release: "v1",
    desired_release: "v1",
    active_deployment: null,
    findings: 0,
    observed_at: OBSERVED,
    allowed_actions: [
      { id: "site.view_details", label: "View site details" },
      { id: "site.deploy", label: "Deploy" },
      { id: "site.more", label: "More" },
    ],
    disabled_actions: [
      {
        id: "site.open_live",
        label: "Open live site",
        code: "mesh_only",
        reason: "No healthy public route is known.",
      },
      {
        id: "site.delete",
        label: "Delete",
        code: "not_permitted",
        reason: "Sites are not deleted from this table.",
      },
    ],
  },
];

const DEPLOY_DETAIL = {
  id: 11,
  site: "shop/prod",
  version: 4,
  state: "running",
  headline: "Old version still serving — site unaffected",
  live_release: "v3",
  desired_release: "v4",
  previous_release: "v3",
  target: "edge-1",
  observed_at: OBSERVED,
  steps: [
    { name: "build", state: "succeeded" },
    { name: "ship", state: "succeeded" },
    { name: "migrate", state: "succeeded" },
    { name: "start_green", state: "succeeded" },
    { name: "health_check", state: "running" },
  ],
  allowed_actions: [
    { id: "deployment.abort", label: "Abort and clean up" },
    { id: "site.view_health", label: "View site health" },
    { id: "deployment.view_log", label: "View live log" },
    { id: "deployment.view_artifacts", label: "View artifacts" },
    { id: "deployment.view_audit", label: "View full audit trail" },
  ],
  disabled_actions: [
    {
      id: "deployment.rollback",
      code: "in_progress",
      reason: "Rollback is available after this attempt finishes or fails.",
    },
  ],
};

const SECRET_ROWS = [
  {
    id: 8,
    kind: "api_token",
    owner_type: "dns_account",
    owner_id: "2",
    fingerprint: "a1b2c3d4e5f67890",
    created_at: OBSERVED,
    last_used_at: OBSERVED,
    exportable: false,
    references: [{ type: "site", id: "1", name: "shop/prod" }],
    allowed_actions: [
      { id: "secret.rotate_plan", label: "Plan rotation" },
    ],
    disabled_actions: [
      {
        id: "secret.export",
        label: "Export",
        code: "not_exportable",
        reason: "This kind is not exportable.",
      },
    ],
  },
];

function overview(sim) {
  if (sim === "empty") {
    return {
      ...OVERVIEW,
      findings: { p1: 0, p2: 0, p3: 0, open: 0 },
      deployments: { active: 0, queued: 0, running: 0, waiting_for_lock: 0, failed: 0 },
      site_health: { healthy: 0, warming: 0, unhealthy: 0, stale: 0 },
      target_readiness: { ready: 0, pressured: 0, unreachable: 0, decommissioned: 0 },
      attention: [],
      active_deployments: [],
      setup: [{ id: "enroll", title: "Enroll a target", href: "targets" }],
      allowed_actions: [{ id: "project.create", label: "ADD APPLICATION" }],
    };
  }
  return OVERVIEW;
}

const PROJECT_ROWS = [
  {
    id: 1, name: "shop", slug: "shop", source_kind: "git",
    source: "git@example/shop", scan_state: "scanned", sites: 2,
    observed_at: OBSERVED,
    allowed_actions: [{ id: "project.open", label: "Open" }, { id: "project.scan", label: "Scan now" }],
    disabled_actions: [{ id: "project.delete", label: "Delete permanently", reason: "Sites still exist." }],
  },
];
const TARGET_ROWS = [
  {
    id: 1, host: "edge-1", kind: "ssh", zone: "hud-net", status: "ready",
    lifecycle: "permanent", sites: 1, observed_at: OBSERVED,
    allowed_actions: [{ id: "target.open", label: "Open" }, { id: "target.probe", label: "Probe router" }],
    disabled_actions: [{ id: "target.decommission", label: "Decommission Target", reason: "Workloads still scheduled." }],
  },
];
const FINDING_ROWS = [
  {
    id: 1, severity: "p1", state: "open", title: "Probe failed", entity: "site:shop",
    fingerprint: "hud-p1", source_engine: "uptime", observed_at: OBSERVED,
    allowed_actions: [{ id: "finding.open", label: "Open" }, { id: "finding.ack", label: "Ack" }],
    disabled_actions: [],
  },
];
const PARTNER_ROWS = [
  {
    id: 1, slug: "acme", name: "Acme", suspended: false, sites: 1, observed_at: OBSERVED,
    allowed_actions: [{ id: "partner.open", label: "Open" }, { id: "partner.view_sites", label: "View Sites" }],
    disabled_actions: [],
  },
];
const AUDIT_ROWS = [
  { id: 1, ts: OBSERVED, actor: "admin", action: "site.deploy", object_type: "deployment", object_id: "11" },
];
const INTEGRATIONS = {
  observed_at: OBSERVED,
  aws: { state: "connected", account_last4: "1234", region: "us-east-1" },
  cloudflare: { state: "connected", account: "cf-main" },
  dns: [{ id: 1, provider: "cloudflare", label: "prod-zone", zones: 1 }],
  vault: { kek_id: "kek-1", kek_age_days: 12, active_secrets: 1 },
  allowed_actions: [{ id: "integration.verify", label: "Verify again" }],
  disabled_actions: [],
};
const SHELL = {
  observed_at: OBSERVED,
  p1_p2: 3,
  scope: "production",
  operations: [{ id: "op-1", state: "running", label: "Retry shop/prod" }],
  allowed_actions: [],
};

export function hudSim(sim, path, body, method) {
  const verb = (method || (body !== undefined ? "POST" : "GET")).toUpperCase();
  if (sim === "loading" || sim === "loading-report" || sim === "loading-wizard") {
    return never();
  }
  if (sim === "error") {
    return { status: 0, data: { detail: "Cannot reach server — check your connection and retry." } };
  }
  if (verb === "POST") {
    if (path.startsWith("v1/hud/projects/test-source")) {
      return { status: 200, data: { ok: true, detail: "connected" } };
    }
    if (path.startsWith("v1/hud/projects") && !path.includes("commands") && !path.includes("test-source")) {
      return { status: 201, data: { id: 9, name: body?.name || "app", operation_id: 9 } };
    }
    if (path === "v1/hud/secrets/") {
      return { status: 201, data: { secret_id: 99, kind: body?.kind || "api_token" } };
    }
    if (path === "v1/hud/members/") {
      return { status: 202, data: { invitation_id: "inv-1", username: body?.username } };
    }
    return {
      status: 202,
      data: { operation_id: 42, state: "queued", action: body?.action },
    };
  }
  if (path.startsWith("v1/hud/projects/test-source")) {
    return { status: 200, data: { ok: true, detail: "connected" } };
  }
  if (path.startsWith("v1/hud/overview")) {
    const qs = path.includes("?") ? path.slice(path.indexOf("?") + 1) : "";
    const scope = new URLSearchParams(qs).get("scope") || "production";
    return { status: 200, data: { ...overview(sim), scope } };
  }
  if (/^v1\/hud\/sites\/\d+/.test(path.split("?")[0])) {
    const row = SITE_ROWS[0];
    return {
      status: 200,
      data: {
        ...row,
        tabs: ["overview", "configuration", "environment", "releases", "instances", "backups", "adoption", "activity", "removal"],
        instances: [],
        manifests: [{ id: 1, version: 4, created_at: OBSERVED }],
        deploy_strategy: "blue_green",
        deploy_policy: "auto",
        deploy_window_cron: "",
        copies: 1,
        owner: "admin",
        backup: "unknown",
      },
    };
  }
  if (path.startsWith("v1/hud/sites")) {
    const qs = path.includes("?") ? path.slice(path.indexOf("?") + 1) : "";
    const params = new URLSearchParams(qs);
    const sort = params.get("sort") || "name";
    const reverse = sort.startsWith("-");
    const key = sort.replace(/^-/, "");
    const page = Math.max(1, Number(params.get("page") || 1) || 1);
    const pageSize = Math.min(50, Math.max(1, Number(params.get("page_size") || 20) || 20));
    let rows = sim === "empty" ? [] : SITE_ROWS.slice();
    const allowed = new Set(["name", "project", "domain", "health", "target"]);
    const sortKey = allowed.has(key) ? key : "name";
    rows.sort((a, b) => {
      const cmp = String(a[sortKey] || "").localeCompare(String(b[sortKey] || ""));
      return reverse ? -cmp : cmp;
    });
    const q = (params.get("q") || "").toLowerCase();
    if (q) rows = rows.filter((r) => `${r.project} ${r.name} ${r.domain}`.toLowerCase().includes(q));
    const count = rows.length;
    const start = (page - 1) * pageSize;
    const chunk = rows.slice(start, start + pageSize);
    const next = start + pageSize < count ? String(page + 1) : null;
    if (params.get("export") === "csv") {
      const csv = ["project,name,domain,health", ...rows.map((r) => `${r.project},${r.name},${r.domain},${r.health}`)].join("\n");
      return {
        status: 200,
        data: {
          observed_at: OBSERVED, csv, filename: "sites.csv", count,
          results: [], next: null, page, sort,
          allowed_actions: [
            { id: "site.create", label: "ADD SITE" },
            { id: "site.export_view", label: "EXPORT VIEW" },
          ],
          disabled_actions: [],
        },
      };
    }
    return {
      status: 200,
      data: {
        observed_at: OBSERVED, results: chunk, next, page, sort, count,
        scope: params.get("scope") || "production",
        allowed_actions: [
          { id: "site.create", label: "ADD SITE" },
          { id: "site.export_view", label: "EXPORT VIEW" },
        ],
        disabled_actions: [],
      },
    };
  }
  if (path.match(/^v1\/hud\/deployments\/\d+\//)) {
    return { status: 200, data: DEPLOY_DETAIL };
  }
  if (path.startsWith("v1/hud/deployments")) {
    const qs = path.includes("?") ? path.slice(path.indexOf("?") + 1) : "";
    const facet = new URLSearchParams(qs).get("facet") || "";
    let rows = sim === "empty" ? [] : [{
      id: 11, site: "shop/prod", version: 4, state: "running",
      current_step: "health_check", observed_at: OBSERVED,
      allowed_actions: [{ id: "deployment.view", label: "Open" }],
      disabled_actions: [],
    }];
    if (facet === "active") rows = rows.filter((r) => r.state === "queued" || r.state === "running");
    return { status: 200, data: { observed_at: OBSERVED, results: rows, allowed_actions: [], disabled_actions: [] } };
  }
  const rotate = path.match(/^v1\/hud\/secrets\/(\d+)\/rotate-plan\/?/);
  if (rotate) {
    const row = SECRET_ROWS.find((s) => String(s.id) === rotate[1]) || SECRET_ROWS[0];
    return {
      status: 200,
      data: {
        secret_id: row.id,
        kind: row.kind,
        owner_type: row.owner_type,
        owner_id: row.owner_id,
        fingerprint: row.fingerprint,
        affected: row.references || [],
        allowed_actions: [],
        disabled_actions: [{
          id: "secret.rotate_activate",
          code: "plan_only",
          reason: "Rotation names affected objects first; activation is a separate replacement write.",
        }],
      },
    };
  }
  if (path.startsWith("v1/hud/secrets")) {
    const rows = sim === "empty" ? [] : SECRET_ROWS;
    return { status: 200, data: { observed_at: OBSERVED, results: rows } };
  }
  if (path.startsWith("v1/hud/projects") && !path.includes("commands") && !path.includes("test-source")) {
    return {
      status: 200,
      data: {
        observed_at: OBSERVED,
        results: sim === "empty" ? [] : PROJECT_ROWS,
        allowed_actions: [{ id: "project.create", label: "ADD APPLICATION" }],
        disabled_actions: [],
      },
    };
  }
  if (path.startsWith("v1/hud/targets") && !path.includes("commands")) {
    return {
      status: 200,
      data: {
        observed_at: OBSERVED,
        results: sim === "empty" ? [] : TARGET_ROWS,
        allowed_actions: [{ id: "target.create", label: "Create Target" }],
        disabled_actions: [],
      },
    };
  }
  if (path.startsWith("v1/hud/findings")) {
    const qs = path.includes("?") ? path.slice(path.indexOf("?") + 1) : "";
    const params = new URLSearchParams(qs);
    let rows = sim === "empty" ? [] : FINDING_ROWS.slice();
    if (params.get("facet") === "p1p2") rows = rows.filter((r) => r.severity === "p1" || r.severity === "p2");
    if (params.get("entity")) {
      const entity = params.get("entity").toLowerCase();
      rows = rows.filter((r) => (r.entity || "").toLowerCase().includes(entity));
    }
    return {
      status: 200,
      data: {
        observed_at: OBSERVED,
        results: rows,
        operations: [{ id: "lock-1", kind: "deploy", state: "held", object: "site:1" }],
        allowed_actions: [],
        disabled_actions: [],
      },
    };
  }
  if (path.startsWith("v1/hud/partners") && !path.includes("commands")) {
    return {
      status: 200,
      data: {
        observed_at: OBSERVED,
        results: sim === "empty" ? [] : PARTNER_ROWS,
        allowed_actions: [{ id: "partner.create", label: "Create Partner" }],
        disabled_actions: [],
      },
    };
  }
  if (path.startsWith("v1/hud/integrations") && !path.includes("commands")) {
    return { status: 200, data: INTEGRATIONS };
  }
  if (path.startsWith("v1/hud/audit")) {
    return {
      status: 200,
      data: { observed_at: OBSERVED, results: sim === "empty" ? [] : AUDIT_ROWS, allowed_actions: [], disabled_actions: [] },
    };
  }
  if (path === "v1/hud/shell/") {
    return { status: 200, data: SHELL };
  }
  if (path.startsWith("v1/hud/search")) {
    return {
      status: 200,
      data: {
        observed_at: OBSERVED,
        groups: [
          { kind: "project", results: [{ id: "p1", label: "shop", href: "projects/1" }] },
          { kind: "site", results: [{ id: "s1", label: "shop.example.test", href: "sites/1" }] },
        ],
      },
    };
  }
  if (path === "v1/hud/members/") {
    return {
      status: 200,
      data: {
        results: [
          { id: 1, username: "op", role: "owner" },
        ],
        allowed_actions: [],
        disabled_actions: [{
          id: "member.retire",
          label: "Retire owner",
          code: "last_owner",
          reason: "The last Owner cannot be retired.",
        }],
      },
    };
  }
  return null;
}

export const HUD_OVERVIEW_FIXTURE = OVERVIEW;
export const HUD_SITE_FIXTURE = SITE_ROWS[0];
export const HUD_DEPLOY_FIXTURE = DEPLOY_DETAIL;
export const HUD_SECRET_FIXTURE = SECRET_ROWS[0];
