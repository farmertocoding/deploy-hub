// §F8 simulation fixtures: the states every screen must be reviewable in,
// reachable with zero backend via ?sim=<name>.
//
// These objects are the CONTRACT copies of real API responses. They are pinned to
// the generated zod schemas by tests/sim-contract.test.ts, so if a serializer
// changes shape, the sim states fail the build instead of quietly reviewing a UI
// against responses the server no longer sends.
//
// SPEC §4b, and this is the whole reason that spec had to be written twice: a zod
// schema cannot tell you a fixture is a LIE, only that it is well-shaped. The first
// remedy for R8-1 hand-wrote a `blocking` list that `preflight` never produces, and the
// UI was then reviewed against it and passed. So: every `blocking` list, every refusal
// `detail`, every field of the declared-tree blocker, both manifests and the 409 below
// are COPIED FROM A REAL RUN. The command that produced each one is named above it.
// Nothing in this file is written by hand except the ids, names and dates that stitch
// the fixtures together.

// ── project 1: takko, nothing to report ───────────────────────────────────────
// python -m hub scan <tree with a digest-pinned Dockerfile, /healthz, auth, tests>
// → zero non-ok checks; wizard state below from wizard.views._state(site) with the
// domain answered.
const CLEAN_PROJECT = {
  id: 1, name: "takko", slug: "takko", scanned_at: "2026-08-09T10:00:00Z",
  tiers: { blocker: 0, warning: 0, advice: 0, pending_sandbox: 0 },
  sites: [{ id: 1, name: "prod", domain: "takko.market",
            latest_manifest_version: 3, manifest_current: true }],
};

const CLEAN_REPORT = {
  scanned_at: "2026-08-09T10:00:00Z", modules: ["dockerfile"], summary: {},
  blockers: [], warnings: [], advice: [], pending_sandbox: [],
};

const CLEAN_WIZARD = {
  questions: [
    { id: "site.domain", kind: "domain", prompt: "Public domain for this site (e.g. app.example.com)",
      choices: [], default: null, secret: false },
    { id: "site.exposure", kind: "choice", prompt: "How should this site be reachable?",
      choices: ["public", "mesh_only"], default: "public", secret: false },
    { id: "dockerfile.domain", kind: "text", prompt: "Domain to serve this site on",
      choices: [], default: null, secret: false },
    { id: "dockerfile.exposure", kind: "choice", prompt: "Who should reach this site?",
      choices: ["public", "mesh_only"], default: "public", secret: false },
    { id: "dockerfile.env", kind: "secret",
      prompt: "Environment variables/secrets the container needs (stored in the vault, injected at deploy)",
      choices: [], default: null, secret: true },
  ],
  answered: { "site.domain": "takko.market" },
  blocking: [],
  warnings: [],
  can_materialize: true,
};

// The 4th materialize of that site — the site row above says it is on v3, so this is
// the version the next POST really returns. Body verbatim from wizard.materialize.
const CLEAN_MANIFEST = {
  version: 4, schema_version: 1,
  scan_report_hash: "f859f3f69374a6f52e9d0c4e03b72ff22a39410a22a791df8cff3a7ecdc4e19d",
  created_at: "2026-08-12T07:24:34.034362Z",
  body: {
    schema_version: 1,
    components: { service: { kind: "dockerfile", port: 8000 }, static_route: null, jobs: [] },
    jobs_image: null, volumes: [], deploy_strategy: "blue_green", exposure: "public",
    healthz: { liveness_path: null, readiness_path: null, warmup_timeout_s: null,
               data_staleness_threshold: null },
    domain: "takko.market", env_names: [],
    site: { id: 1, name: "prod", domain: "takko.market" }, env_bundle_ref: null,
  },
};

// ── the declared-tree blocker, and the confirm that is its only key ───────────
// From a real scan of a tree whose deployhub.yaml declares `frontend/scripts/drill` as
// test material with the reason quoted below:
//
//   python -m hub scan /tmp/drillrepo1
//   python -c "from scanner import declarations, core; ..." → confirm_questions()
//
// The id is not typeable: it is the sha256-derived digest confirm_question_id() computes
// from the declared path and its reason, and three places must carry the SAME one — the
// check's `acceptance.questions`, the wizard's question, and the manifest record. Two of
// them are in this file, and sim-contract.test.ts fails if they drift apart.
const DRILL_CONFIRM = "scanner.test_material.frontend-scripts-drill--a38574e34e643d90";

const DRILL_CONFIRM_PROMPT =
  "This repo declares `frontend/scripts/drill` as test material — \"red-team / QA " +
  "drill scripts; deliberate fake credentials\". Accept that claim? Until you do, the " +
  "heuristic secret findings under that path BLOCK the deploy like any other; " +
  "accepting reports them without blocking. Published credential formats and .env " +
  "files there block either way; refusing is recorded in the manifest, and editing " +
  "the path or the reason brings this question back.";

// The state R8-1 was invisible in: a blocker no repo change can clear, because there is
// nothing in the repo to fix — only an operator's answer clears it, and the stored scan
// report goes on reporting it afterwards.
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

// preflight's own detail lines. The clause after the dash exists because someone on the
// server side knew "fix them and re-scan" is false for a pending acceptance; the client
// must not paraphrase it, and materialize-gate.test.ts greps to make sure it does not.
const BLOCKERS_AWAITING_DETAIL =
  "the readiness report has blockers; these must be fixed and the project re-scanned " +
  "— except where a declaration is awaiting acceptance, which you clear by answering " +
  "its confirm in this wizard, not by changing the repo";
const BLOCKERS_HARD_DETAIL =
  "the readiness report has blockers; these must be fixed and the project re-scanned";
const ANSWERS_MISSING_DETAIL = "required questions are unanswered";

const AWAITING_ITEM = {
  id: "core.secret-scan",
  title: "Secrets in a declared tree — your acceptance is required",
  awaiting_acceptance: [{ id: DRILL_CONFIRM, prompt: DRILL_CONFIRM_PROMPT }],
};

// ── project 2: legacy-shop, the mixed case ────────────────────────────────────
// Two blockers no answer can clear plus the declared one that only an answer can:
// preflight returns them in ONE `blockers_present`, and the button must stay blocked.
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

const MESSY_WIZARD = {
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
  // Verbatim from `preflight(site)` for a project carrying exactly these three blocker
  // checks with the confirm unanswered. Note what it does NOT look like: a separate
  // problem per blocker, or an `answers_missing`-only refusal. One `blockers_present`
  // holds all three items, and only the declared one carries `awaiting_acceptance` —
  // which is precisely what makes this the blocked case and not the answerable one.
  blocking: [
    { code: "blockers_present", detail: BLOCKERS_AWAITING_DETAIL,
      items: [
        { id: "django.secret-key-literal", title: "Secret material is a literal in source" },
        { id: "django.debug-on", title: "DEBUG is on in prod settings" },
        AWAITING_ITEM,
      ] },
    { code: "answers_missing", detail: ANSWERS_MISSING_DETAIL,
      items: [
        { id: DRILL_CONFIRM, prompt: DRILL_CONFIRM_PROMPT },
        { id: "site.domain", prompt: "Public domain for this site (e.g. app.example.com)" },
      ] },
  ],
};

// ── project 3: qa-drills, where the declaration is the ONLY blocker ───────────
// This is the project that makes the acceptance path real. Its scan (python -m hub scan
// /tmp/drillrepo1) reports exactly one blocker — the declared tree — so answering the
// confirm takes preflight from "blocked" to empty, and every state below is a verbatim
// wizard.views._state() of that one site.
const DRILL_PROJECT = {
  id: 3, name: "qa-drills", slug: "qa-drills", scanned_at: "2026-08-11T18:05:00Z",
  tiers: { blocker: 1, warning: 3, advice: 2, pending_sandbox: 0 },
  sites: [{ id: 3, name: "prod", domain: "",
            latest_manifest_version: null, manifest_current: false }],
};

const DRILL_REPORT = {
  scanned_at: "2026-08-11T18:05:00Z", modules: ["dockerfile"], summary: {},
  blockers: [DECLARED_BLOCKER],
  warnings: [
    { id: "core.gitignore", tier: "warning", title: "No .gitignore",
      detail: "The project has no .gitignore at its root.",
      fix_hint: "Add a .gitignore covering at least .env and (for node projects) node_modules, so secrets and dependency trees never enter the repo." },
    { id: "core.digest-pins", tier: "warning", title: "Base images not pinned by digest (§6.8)",
      detail: "Dockerfile:1: FROM python:3.12 is not digest-pinned",
      fix_hint: "Pin each FROM to an @sha256: digest so builds cannot silently change under a moving tag." },
    { id: "core.exposure-auth", tier: "warning", title: "No authentication detected",
      detail: "no authentication detected — Blocker if this site will be public with financial/personal data (wizard will ask)",
      fix_hint: "If the site is meant to be public and handles financial or personal data, add authentication before deploying, or set exposure to mesh_only in the wizard." },
  ],
  advice: [
    { id: "core.tests-exist", tier: "advice", title: "No test files found",
      detail: "No test_*.py / *_test.py / *.test.* / *.spec.* files or tests/ directory were found.",
      fix_hint: "Even a small smoke-test suite lets the pipeline verify a build before it ships." },
    { id: "core.healthz", tier: "advice", title: "No health endpoint detected",
      detail: "No route containing health/healthz/ping was found. The deploy pipeline will fall back to probing an existing 200 route or a TCP connect (§E9) — deploys still work, with a weaker readiness signal.",
      fix_hint: "Add a cheap /healthz route returning 200 for first-class readiness and warmup gating (§N2)." },
  ],
  pending_sandbox: [],
};

const DRILL_QUESTIONS = [
  { id: "site.domain", kind: "domain", prompt: "Public domain for this site (e.g. app.example.com)",
    choices: [], default: null, secret: false },
  { id: "site.exposure", kind: "choice", prompt: "How should this site be reachable?",
    choices: ["public", "mesh_only"], default: "public", secret: false },
  { id: DRILL_CONFIRM, kind: "bool", prompt: DRILL_CONFIRM_PROMPT,
    choices: [], default: null, secret: false },
  { id: "dockerfile.domain", kind: "text", prompt: "Domain to serve this site on",
    choices: [], default: null, secret: false },
  { id: "dockerfile.exposure", kind: "choice", prompt: "Who should reach this site?",
    choices: ["public", "mesh_only"], default: "public", secret: false },
  { id: "dockerfile.env", kind: "secret",
    prompt: "Environment variables/secrets the container needs (stored in the vault, injected at deploy)",
    choices: [], default: null, secret: true },
];

const DRILL_WARNINGS = [
  { id: "core.gitignore", title: "No .gitignore" },
  { id: "core.digest-pins", title: "Base images not pinned by digest (§6.8)" },
  { id: "core.exposure-auth", title: "No authentication detected" },
];

// The confirm unanswered. `blockers_present` carries `awaiting_acceptance` and NOTHING
// else blocks — this is the state the R8-1 gate has to read as "answerable", and the
// state whose shape the first remedy guessed wrong.
const DRILL_WIZARD_PENDING = {
  questions: DRILL_QUESTIONS,
  answered: { "site.domain": "app.example.com" },
  warnings: DRILL_WARNINGS,
  can_materialize: false,
  blocking: [
    { code: "blockers_present", detail: BLOCKERS_AWAITING_DETAIL, items: [AWAITING_ITEM] },
    { code: "answers_missing", detail: ANSWERS_MISSING_DETAIL,
      items: [{ id: DRILL_CONFIRM, prompt: DRILL_CONFIRM_PROMPT }] },
  ],
};

// The confirm answered true: preflight is empty and the deploy may proceed — while the
// readiness report is byte-for-byte the one above, blocker and all. That combination is
// R8-1, and before this fixture existed no screen could show it.
const DRILL_WIZARD_ACCEPTED = {
  questions: DRILL_QUESTIONS,
  answered: { "site.domain": "app.example.com", [DRILL_CONFIRM]: true },
  warnings: DRILL_WARNINGS,
  can_materialize: true,
  blocking: [],
};

// What that POST returns: a real materialize of the drill tree with the confirm
// accepted. `declared_test_material` is the record of the acceptance, which is the
// point of the whole flow.
const DRILL_MANIFEST = {
  version: 1, schema_version: 1,
  scan_report_hash: "ec037f0c0a0f00bdc63315614e0dd12809ba2c4b4a2b3d0e3aae9d61da13123a",
  created_at: "2026-08-12T07:22:14.838514Z",
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
    env_names: [], site: { id: 3, name: "prod", domain: "app.example.com" },
    env_bundle_ref: null,
  },
};

// The refusal, from the one situation that really produces a 409 the client allowed:
// the wizard GET said go, and the tree was re-scanned before the POST. Here the re-scan
// found a published credential format inside the declared tree — which no acceptance
// ever clears — and the repo also edited its declaration's reason, so the confirm the
// operator answered is keyed to a claim that no longer exists and the new one is
// unanswered. Verbatim from MaterializeRefused.as_dict(); note the second confirm id,
// which is the digest of the EDITED reason.
const REFUSAL_409 = {
  code: "blockers_present", detail: BLOCKERS_HARD_DETAIL,
  items: [{ id: "core.secret-scan", title: "Committed secrets detected" }],
  problems: [
    { code: "blockers_present", detail: BLOCKERS_HARD_DETAIL,
      items: [{ id: "core.secret-scan", title: "Committed secrets detected" }] },
    { code: "answers_missing", detail: ANSWERS_MISSING_DETAIL,
      items: [{ id: "scanner.test_material.frontend-scripts-drill--d95a7124bf7ab25c",
        prompt: "This repo declares `frontend/scripts/drill` as test material — " +
          "\"red-team / QA drill scripts and fixtures; deliberate fake credentials\". " +
          "Accept that claim? Until you do, the heuristic secret findings under that " +
          "path BLOCK the deploy like any other; accepting reports them without " +
          "blocking. Published credential formats and .env files there block either " +
          "way; refusing is recorded in the manifest, and editing the path or the " +
          "reason brings this question back." }] },
  ],
};

const never = () => new Promise(() => {});

// `v1/projects/2/readiness/` and `v1/sites/2/wizard/` both put the id in the same slot.
const idOf = (path) => Number(path.split("/")[2]);

const REPORTS = { 1: CLEAN_REPORT, 2: MESSY_REPORT, 3: DRILL_REPORT };
const WIZARDS = { 1: CLEAN_WIZARD, 2: MESSY_WIZARD, 3: DRILL_WIZARD_PENDING };
const MANIFESTS = { 1: CLEAN_MANIFEST, 3: DRILL_MANIFEST };

// Each fixture: (path, body, method) => {status, data}
export const SIM_FIXTURES = {
  // No projects at all — first-run experience.
  empty: (path) =>
    path === "v1/projects/" ? { status: 200, data: [] } : { status: 404, data: {} },

  // Requests hang forever: every spinner is inspectable indefinitely.
  loading: never,

  // Healthy data: a clean project, a blocked one, and one waiting on the operator.
  live: (path, body, method) => {
    if (path === "v1/projects/")
      return { status: 200, data: [CLEAN_PROJECT, MESSY_PROJECT, DRILL_PROJECT] };
    if (path.endsWith("/readiness/"))
      return { status: 200, data: REPORTS[idOf(path)] || CLEAN_REPORT };
    if (path.endsWith("/wizard/") && method === "PATCH") return { status: 200, data: {} };
    if (path.endsWith("/wizard/"))
      return { status: 200, data: WIZARDS[idOf(path)] || CLEAN_WIZARD };
    if (path.endsWith("/manifest/")) {
      const manifest = MANIFESTS[idOf(path)];
      return manifest ? { status: 201, data: manifest } : { status: 409, data: REFUSAL_409 };
    }
    return { status: 404, data: {} };
  },

  // The declaration accepted: the SAME readiness report as `live` — still a red blocker
  // count, still the core.secret-scan card with its acceptance hint — and a wizard that
  // now says the deploy may proceed. That pairing is the whole of R8-1, and it was
  // unrenderable before this state existed.
  accepted: (path, body, method) => {
    if (path.endsWith("/wizard/") && method !== "PATCH" && idOf(path) === 3)
      return { status: 200, data: DRILL_WIZARD_ACCEPTED };
    return SIM_FIXTURES.live(path, body, method);
  },

  // The wizard state the operator is looking at is out of date: it said the deploy may
  // proceed, the tree was re-scanned, and the POST refuses with every reason at once.
  // Without this state the 409 panel is reachable from no screen at all.
  stale: (path, body, method) => {
    if (path.endsWith("/wizard/") && method !== "PATCH" && idOf(path) === 3)
      return { status: 200, data: DRILL_WIZARD_ACCEPTED };
    if (path.endsWith("/manifest/")) return { status: 409, data: REFUSAL_409 };
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
