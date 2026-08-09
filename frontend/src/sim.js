// §F8 simulation fixtures: the five states every screen must be reviewable in,
// reachable with zero backend via ?sim=<name>.
//
// These objects are the CONTRACT copies of real API responses. They are pinned to
// the generated zod schemas by tests/sim-contract.test.ts, so if a serializer
// changes shape, the sim states fail the build instead of quietly reviewing a UI
// against responses the server no longer sends.

const CLEAN_PROJECT = {
  id: 1, name: "takko", slug: "takko", scanned_at: "2026-08-09T10:00:00Z",
  tiers: { blocker: 0, warning: 0, advice: 0, pending_sandbox: 0 },
  sites: [{ id: 1, name: "prod", domain: "takko.market",
            latest_manifest_version: 3, manifest_current: true }],
};

const MESSY_PROJECT = {
  id: 2, name: "legacy-shop", slug: "legacy-shop", scanned_at: "2026-08-09T09:30:00Z",
  tiers: { blocker: 2, warning: 1, advice: 1, pending_sandbox: 1 },
  sites: [{ id: 2, name: "prod", domain: "",
            latest_manifest_version: 1, manifest_current: false }],
};

const MESSY_REPORT = {
  scanned_at: "2026-08-09T09:30:00Z", modules: ["django"], summary: {},
  blockers: [
    { id: "django.secret-key-literal", tier: "blocker",
      title: "Secret material is a literal in source",
      detail: "config/settings/base.py: SECRET_KEY",
      fix_hint: "Load it from the environment, rotate the leaked value, and store the new one through the Hub vault." },
    { id: "django.debug-on", tier: "blocker", title: "DEBUG is on in prod settings",
      detail: "config/settings/prod.py", fix_hint: "Set DEBUG = False in prod." },
  ],
  warnings: [
    { id: "django.secret-dev-fallback", tier: "warning",
      title: "Dev-fallback secret committed (prod provably rejects it)",
      detail: "config/settings/base.py: FIELD_ENCRYPTION_KEYS",
      fix_hint: "Production hard-fails without the real value, so this cannot ship — but it lives in git history. Rotate if the repo was ever shared. (Tier per D-008.)" },
  ],
  advice: [
    { id: "django.staticfiles", tier: "advice", title: "No WhiteNoise or static route",
      detail: "", fix_hint: "Add WhiteNoise or let the Hub serve the static artifact." },
  ],
  pending_sandbox: [
    { id: "django.migrate-check", tier: "pending_sandbox",
      title: "manage.py migrate --check (runs in the build sandbox, never on the Hub)",
      detail: "", fix_hint: "" },
  ],
};

const WIZARD_STATE = {
  // Shape mirrors WizardStateSerializer EXACTLY — the contract test rejected a
  // first draft that invented required/source fields and omitted secret/warnings.
  questions: [
    { id: "site.domain", kind: "domain", prompt: "Public domain for this site (e.g. app.example.com)",
      choices: [], default: null, secret: false },
    { id: "site.exposure", kind: "choice", prompt: "Who should reach this site?",
      choices: ["public", "vpn-only"], default: "public", secret: false },
    { id: "django.env.DATABASE_URL", kind: "text", prompt: "Value for DATABASE_URL",
      choices: [], default: null, secret: false },
    { id: "django.env.SECRET_KEY", kind: "secret", prompt: "Value for SECRET_KEY",
      choices: [], default: null, secret: true },
  ],
  answered: {
    "site.exposure": "public",
    "django.env.SECRET_KEY": { answered: true, is_secret: true, changed_at: "2026-08-08T12:00:00Z" },
  },
  warnings: [
    { code: "warning", detail: "Dev-fallback secret committed (prod provably rejects it)" },
  ],
  can_materialize: false,
  blocking: [
    { code: "blockers_present", detail: "the latest scan reports blockers", items: [] },
    { code: "answers_missing", detail: "required questions are unanswered",
      items: [{ id: "site.domain", prompt: "Public domain for this site (e.g. app.example.com)" }] },
  ],
};

const REFUSAL_409 = {
  code: "blockers_present", detail: "the latest scan reports blockers", items: [],
  problems: [
    { code: "blockers_present", detail: "the latest scan reports blockers",
      items: [{ id: "django.secret-key-literal", title: "Secret material is a literal in source" }] },
    { code: "answers_missing", detail: "required questions are unanswered",
      items: [{ id: "site.domain", prompt: "Public domain for this site (e.g. app.example.com)" }] },
  ],
};

const never = () => new Promise(() => {});

// Each fixture: (path, body, method) => {status, data}
export const SIM_FIXTURES = {
  // No projects at all — first-run experience.
  empty: (path) =>
    path === "v1/projects/" ? { status: 200, data: [] } : { status: 404, data: {} },

  // Requests hang forever: every spinner is inspectable indefinitely.
  loading: never,

  // Healthy data: one clean project, one messy one, full wizard round-trip.
  live: (path, body, method) => {
    if (path === "v1/projects/") return { status: 200, data: [CLEAN_PROJECT, MESSY_PROJECT] };
    if (path.endsWith("/readiness/"))
      return path.includes("/1/")
        ? { status: 200, data: { ...MESSY_REPORT, blockers: [], warnings: [], advice: [], pending_sandbox: [] } }
        : { status: 200, data: MESSY_REPORT };
    if (path.endsWith("/wizard/") && method === "PATCH") return { status: 200, data: {} };
    if (path.endsWith("/wizard/")) return { status: 200, data: WIZARD_STATE };
    if (path.endsWith("/manifest/")) return { status: 409, data: REFUSAL_409 };
    return { status: 404, data: {} };
  },

  // Data present but stale/incomplete: never-scanned project, manifest behind scan.
  degraded: (path) => {
    if (path === "v1/projects/")
      return { status: 200, data: [
        { ...MESSY_PROJECT, scanned_at: null, tiers: { blocker: 0, warning: 0, advice: 0, pending_sandbox: 0 } },
        { ...CLEAN_PROJECT, sites: [{ ...CLEAN_PROJECT.sites[0], manifest_current: false }] },
      ] };
    if (path.endsWith("/readiness/"))
      return { status: 200, data: { ...MESSY_REPORT, scanned_at: null, blockers: [], warnings: [], advice: [], pending_sandbox: [] } };
    return { status: 503, data: { detail: "scan runner unavailable — showing last stored data" } };
  },

  // The server is gone.
  error: () => ({ status: 0, data: { detail: "Cannot reach server — check your connection and retry." } }),
};
