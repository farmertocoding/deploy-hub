// §F8 simulation fixtures: the states every screen must be reviewable in,
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

// R8-4. Everything below about the declared-tree blocker is COPIED FROM A REAL SCAN of
// a tree whose deployhub.yaml declares `frontend/scripts/drill` as test material —
// title, detail, fix_hint, the confirm id and the confirm prompt. The command that
// produced them is in this commit's message. The id in particular is not typeable: it
// is the sha256-derived digest `scanner.declarations.confirm_question_id` computes from
// the declared path and its reason, and three places have to carry the SAME one — the
// check's `acceptance.questions`, the wizard's question, and the manifest record.
const DRILL_CONFIRM = "scanner.test_material.frontend-scripts-drill--a38574e34e643d90";

const DRILL_CONFIRM_PROMPT =
  "This repo declares `frontend/scripts/drill` as test material — \"red-team / QA " +
  "drill scripts; deliberate fake credentials\". Accept that claim? Until you do, the " +
  "heuristic secret findings under that path BLOCK the deploy like any other; " +
  "accepting reports them without blocking. Published credential formats and .env " +
  "files there block either way; refusing is recorded in the manifest, and editing " +
  "the path or the reason brings this question back.";

// The state R8-1 was invisible in: a blocker that no repo change can clear, because
// there is nothing in the repo to fix — only an operator's answer clears it, and the
// stored scan report keeps reporting it afterwards.
const DECLARED_BLOCKER = {
  id: "core.secret-scan", tier: "blocker",
  title: "Secrets in a declared tree — your acceptance is required",
  detail: "Downgrades claimed by deployhub.yaml: frontend/scripts/drill (\"red-team / " +
    "QA drill scripts; deliberate fake credentials\", 1 findings)\n\nDeclared test " +
    "material (downgrade requested by deployhub.yaml — these findings block until you " +
    "accept it in the wizard):\nfrontend/scripts/drill/qa/03_regressions.mjs:1: " +
    "[heuristic, declared: frontend/scripts/drill — \"red-team / QA drill scripts; " +
    "deliberate fake credentials\"] hardcoded staff_password value",
  fix_hint: "Every blocking line here is a heuristic finding inside a tree this repo's " +
    "deployhub.yaml declares as test material, so the deploy is refused for exactly " +
    "one reason: nobody has accepted that claim yet. Read the reason and read the " +
    "lines, then answer the wizard's confirm.\n\n[proof] lines matched a published " +
    "credential format — a GitHub token, a PEM block, an AWS key id — and are not " +
    "guesses. [heuristic] lines are a secret-shaped name assigned a high-entropy " +
    "literal: real most of the time, and worth a look before you decide.\n\nThe " +
    "`Downgrades claimed` header above, and any `[heuristic, declared: …]` line, is " +
    "this repo's own deployhub.yaml REQUESTING that those findings stop blocking. " +
    "Asking is not getting: they block until you accept that declaration in the " +
    "wizard. Accepting clears exactly those lines and lets this check pass. Your " +
    "answer is recorded in the frozen manifest against the exact wording you were " +
    "shown — edit the path or the reason and you will be asked again. Refusing leaves " +
    "them blocking and records the refusal, so refusing is how you say the " +
    "declaration is wrong.",
  acceptance: { questions: [DRILL_CONFIRM], blocking_only_declared: true },
};

const MESSY_PROJECT = {
  id: 2, name: "legacy-shop", slug: "legacy-shop", scanned_at: "2026-08-09T09:30:00Z",
  tiers: { blocker: 3, warning: 1, advice: 1, pending_sandbox: 1 },
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
    DECLARED_BLOCKER,
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
    // `default: null` is the scanner's, not a nicety: an unanswered claim is not an
    // accepted one, so this question cannot arrive pre-ticked.
    { id: DRILL_CONFIRM, kind: "bool", prompt: DRILL_CONFIRM_PROMPT,
      choices: [], default: null, secret: false },
  ],
  answered: {
    "site.exposure": "public",
    "django.env.SECRET_KEY": { answered: true, is_secret: true, changed_at: "2026-08-08T12:00:00Z" },
  },
  warnings: [
    { code: "warning", detail: "Dev-fallback secret committed (prod provably rejects it)" },
  ],
  can_materialize: false,
  // R8-1/R8-4: `blocking` is the axis under review, and it is the WIZARD's answer, not
  // the report's — `live` is the acceptance-pending state (the confirm is unanswered,
  // so preflight names it under `answers_missing`), `accepted` below is the same
  // report after the answer. Both hold MESSY_REPORT fixed on purpose: an answer never
  // rewrites a scan report, which is the whole of R8-1.
  //
  // Held out deliberately, and a reviewer should know: a live server whose report also
  // carried the two `django.*` blockers would send `blockers_present` alongside this.
  // Carrying it here would make every state of this fixture render "⛔ Blocked" and the
  // acceptance-pending copy — the R8-1 fix itself — would be reviewable nowhere.
  blocking: [
    { code: "answers_missing", detail: "required questions are unanswered",
      items: [
        { id: "site.domain", prompt: "Public domain for this site (e.g. app.example.com)" },
        { id: DRILL_CONFIRM, prompt: DRILL_CONFIRM_PROMPT },
      ] },
  ],
};

// R8-4: the dead end only shows itself AFTER the answer — the report still reports the
// blocker, and on ffec190 the button was still disabled. Same project, same readiness
// report, one answered confirm.
const WIZARD_STATE_ACCEPTED = {
  ...WIZARD_STATE,
  answered: { ...WIZARD_STATE.answered, "site.domain": "app.example.com",
              [DRILL_CONFIRM]: true },
  can_materialize: true,
  blocking: [],
};

// The body of a REAL materialize of the declared drill tree, with the confirm answered
// true — `declared_test_material` is the record of that acceptance, which is the point
// of the flow. `version` is 2 because this site's fixture already has a v1.
const MANIFEST_201 = {
  version: 2, schema_version: 1,
  scan_report_hash: "ec037f0c0a0f00bdc63315614e0dd12809ba2c4b4a2b3d0e3aae9d61da13123a",
  created_at: "2026-08-12T06:54:12.458764Z",
  body: {
    schema_version: 1,
    components: { service: { kind: "dockerfile", port: 8000 }, static_route: null, jobs: [] },
    jobs_image: null, volumes: [], deploy_strategy: "blue_green", exposure: "public",
    healthz: { liveness_path: null, readiness_path: null, warmup_timeout_s: null,
               data_staleness_threshold: null },
    domain: "app.example.com",
    declared_test_material: [{ path: "frontend/scripts/drill",
      reason: "red-team / QA drill scripts; deliberate fake credentials",
      question_id: DRILL_CONFIRM, accepted: true }],
    env_names: [], site: { id: 2, name: "prod", domain: "app.example.com" },
    env_bundle_ref: null,
  },
};

const REFUSAL_409 = {
  code: "blockers_present", detail: "the latest scan reports blockers", items: [],
  problems: [
    { code: "blockers_present", detail: "the latest scan reports blockers",
      items: [{ id: "django.secret-key-literal", title: "Secret material is a literal in source" }] },
    { code: "answers_missing", detail: "required questions are unanswered",
      items: [
        { id: "site.domain", prompt: "Public domain for this site (e.g. app.example.com)" },
        // R8-4: what an unanswered declaration looks like in a refusal — the operator
        // is being told the deploy is refused for a question, not for a repo problem.
        { id: DRILL_CONFIRM, prompt: DRILL_CONFIRM_PROMPT },
      ] },
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

  // The declaration accepted (R8-4): the SAME readiness report — still a red blocker
  // count, still the core.secret-scan card with its acceptance hint — and a wizard that
  // now says the deploy may proceed. That combination is the whole of R8-1, and it was
  // unrenderable before this state existed.
  accepted: (path, body, method) => {
    if (path.endsWith("/wizard/") && method !== "PATCH")
      return { status: 200, data: WIZARD_STATE_ACCEPTED };
    if (path.endsWith("/manifest/")) return { status: 201, data: MANIFEST_201 };
    return SIM_FIXTURES.live(path, body, method);
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
