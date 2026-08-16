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
// UI was then reviewed against it and passed. So every payload here is COPIED FROM A
// REAL RUN against a tree built to produce it, spliced as JSON rather than retyped:
//
//   ReadinessSerializer(...).data   → CLEAN_REPORT, MESSY_REPORT
//   wizard.views._state(site)       → CLEAN_WIZARD, MESSY_WIZARD
//   wizard.materialize.materialize  → CLEAN_MANIFEST, REFUSAL_409, STALE_REFUSAL_409
//
// The trees, built by the same procedure as the r8 rebuild: a clean digest-pinned
// service with /healthz, auth and tests (takko, /tmp/cleanrepo); and a Django repo with
// a hardcoded SECRET_KEY, DEBUG=True in prod settings, a dev-fallback the prod module
// hard-fails without, a committed .env, secrets in a workflow, and a drill tree under a
// `deployhub.yaml` declaration (legacy-shop, /tmp/messyrepo).
//
// D-012 LEFT PHASE 1 (2026-08-16), and these fixtures are what that looks like on a
// screen. The `qa-drills` project and the `?sim=accepted` state are gone with the
// mechanism they existed to show: there is no declaration confirm, no acceptance
// contract on any check, and no blocker an answer clears. legacy-shop still carries a
// `deployhub.yaml` over a drill tree — that is the point — so its report now shows the
// ten drill lines as ordinary blocking findings among fifteen, with no declaration
// header and no third bucket, plus one `core.declaration-file` warning telling the repo
// its file is not honored this phase.
//
// What IS written by hand: project/site ids, names, slugs, the `scanned_at` dates that
// stitch the fixtures together, MESSY_WIZARD's `changed_at` and CLEAN_MANIFEST's
// `created_at` (both are wall-clock times that would move on every regeneration), plus
// the comments. Every check id, title, detail, fix_hint, refusal code, refusal detail,
// question prompt and manifest body is the server's own output. R8-4's whole finding was
// that a fixture nobody could check is a UI nobody reviewed.

// ── project 1: takko, nothing to report ───────────────────────────────────────
// python -m hub scan /tmp/cleanrepo → zero non-ok checks; wizard state below from
// wizard.views._state(site) with the domain answered.
const CLEAN_PROJECT = {
  id: 1, name: "takko", slug: "takko", scanned_at: "2026-08-09T10:00:00Z",
  tiers: { blocker: 0, warning: 0, advice: 0, pending_sandbox: 0 },
  sites: [{ id: 1, name: "prod", domain: "takko.market",
            latest_manifest_version: 3, manifest_current: true }],
};

// Pasted from the run against the clean tree: no findings at all, which is a state the
// screen has to render too ("✓ No findings").
const CLEAN_REPORT = {
  "scanned_at": "2026-08-09T10:00:00Z",
  "modules": [
    "dockerfile"
  ],
  "summary": {
    "blocker": 0,
    "warning": 0,
    "advice": 0,
    "ok": 10,
    "pending_sandbox": 0
  },
  "blockers": [],
  "warnings": [],
  "advice": [],
  "pending_sandbox": []
};

const CLEAN_WIZARD = {
  "questions": [
    {
      "id": "site.domain",
      "prompt": "Public domain for this site (e.g. app.example.com)",
      "kind": "domain",
      "default": null,
      "choices": [],
      "secret": false
    },
    {
      "id": "site.exposure",
      "prompt": "How should this site be reachable?",
      "kind": "choice",
      "default": "public",
      "choices": [
        "public",
        "mesh_only"
      ],
      "secret": false
    },
    {
      "id": "dockerfile.domain",
      "prompt": "Domain to serve this site on",
      "kind": "text",
      "default": null,
      "choices": [],
      "secret": false
    },
    {
      "id": "dockerfile.exposure",
      "prompt": "Who should reach this site?",
      "kind": "choice",
      "default": "public",
      "choices": [
        "public",
        "mesh_only"
      ],
      "secret": false
    },
    {
      "id": "dockerfile.env",
      "prompt": "Environment variables/secrets the container needs (stored in the vault, injected at deploy)",
      "kind": "secret",
      "default": null,
      "choices": [],
      "secret": true
    }
  ],
  "answered": {
    "site.domain": "takko.market"
  },
  "blocking": [],
  "warnings": [],
  "can_materialize": true
};

// The 4th materialize of that site — the site row above says it is on v3, so this is
// the version the next POST really returns, and the generator materializes four times
// rather than editing the number. Body verbatim from wizard.materialize.
const CLEAN_MANIFEST = {
  "version": 4,
  "schema_version": 1,
  "scan_report_hash": "aaa0a81571255525bba22cdb761a72acc51fa08e89b8146d91220e37c28ee1ea",
  "created_at": "2026-08-12T07:24:34.034362Z",
  "body": {
    "schema_version": 2,
    "components": {
      "service": {
        "kind": "dockerfile",
        "port": 8000
      },
      "static_route": null,
      "jobs": []
    },
    "jobs_image": null,
    "volumes": [],
    "deploy_strategy": "blue_green",
    "exposure": "public",
    "healthz": {
      "liveness_path": null,
      "readiness_path": null,
      "warmup_timeout_s": null,
      "data_staleness_threshold": null
    },
    "domain": "takko.market",
    "env_names": [],
    "site": {
      "id": 1,
      "name": "prod",
      "domain": "takko.market"
    },
    "env_bundle_ref": null
  }
};

// ── project 2: legacy-shop, the mixed case ────────────────────────────────────
// Three blockers no answer clears — which since D-012 left Phase 1 is every blocker
// there is — and the wizard's own refusal beside them.
const MESSY_PROJECT = {
  id: 2, name: "legacy-shop", slug: "legacy-shop", scanned_at: "2026-08-09T09:30:00Z",
  tiers: { blocker: 3, warning: 3, advice: 1, pending_sandbox: 3 },
  sites: [{ id: 2, name: "prod", domain: "",
            latest_manifest_version: 1, manifest_current: false }],
};

// Pasted from the run above. `summary` is the scanner's own count and every check
// carries its `execution` field — both are in what the serializer sends, and leaving
// them out was a fixture that quietly described a smaller API than the real one.
const MESSY_REPORT = {
  "scanned_at": "2026-08-09T09:30:00Z",
  "modules": [
    "django"
  ],
  "summary": {
    "blocker": 3,
    "warning": 3,
    "advice": 1,
    "ok": 15,
    "pending_sandbox": 3
  },
  "blockers": [
    {
      "id": "core.secret-scan",
      "tier": "blocker",
      "title": "Committed secrets detected",
      "detail": ".env: .env file present in the scan tree\nfrontend/scripts/drill/README.md:7: [heuristic] hardcoded django_superuser_password value\nfrontend/scripts/drill/redteam/01_rbac_money.mjs:2: [heuristic] hardcoded admin_password value\nfrontend/scripts/drill/qa/03_regressions.mjs:2: [heuristic] hardcoded staff_password value\nfrontend/scripts/drill/qa/05_archive_results.mjs:2: [heuristic] hardcoded staff_password value\nfrontend/scripts/drill/qa/06_admin_shell.mjs:2: [heuristic] hardcoded staff_password value\nfrontend/scripts/drill/qa/08_redis_outage.mjs:2: [heuristic] hardcoded customer_password value\nfrontend/scripts/drill/qa/08_redis_outage.mjs:3: [heuristic] hardcoded password value\nfrontend/scripts/drill/qa/08_redis_outage.mjs:4: [heuristic] hardcoded fallback_password value\nfrontend/scripts/drill/qa/09_consent_and_lifecycle.mjs:2: [heuristic] hardcoded customer_password value\nfrontend/scripts/drill/qa/10_destinations_and_reconciliation.mjs:2: [heuristic] hardcoded customer_password value\nconfig/settings/base.py:7: [heuristic] hardcoded secret_key value\n.github/workflows/ci.yml:10: [heuristic] hardcoded secret_key value\n.github/workflows/ci.yml:11: [heuristic] hardcoded db_password value\n.github/workflows/ci.yml:12: [heuristic] hardcoded django_superuser_password value",
      "fix_hint": "Move secrets to the vault / environment injection. A .env file in this tree ships with a deploy of it, and is a leak as well if it is committed — check `git status`, add .env to .gitignore, and rotate anything that was committed: it stays in git history until you do.\n\n[proof] lines matched a published credential format — a GitHub token, a PEM block, an AWS key id — and are not guesses. [heuristic] lines are a secret-shaped name assigned a high-entropy literal: real most of the time, and worth a look before you decide.",
      "execution": "static"
    },
    {
      "id": "django.debug-hardcoded",
      "tier": "blocker",
      "title": "DEBUG is hardcoded True in prod-reachable settings",
      "detail": "DEBUG = True in: config/settings/prod.py",
      "fix_hint": "DEBUG=True serves full tracebacks and settings dumps to every visitor. Read it from the environment — DEBUG = os.environ.get('DJANGO_DEBUG', '0') == '1' — and leave DJANGO_DEBUG unset in production.",
      "execution": "static"
    },
    {
      "id": "django.secret-key-literal",
      "tier": "blocker",
      "title": "Secret material is a literal in source",
      "detail": "config/settings/base.py: SECRET_KEY",
      "fix_hint": "A secret in source sits in git history forever and in every clone. Read it from the environment instead — os.environ['DJANGO_SECRET_KEY'] — rotate the leaked value, and store the new one through the Hub vault.",
      "execution": "static"
    }
  ],
  "warnings": [
    {
      "id": "core.declaration-file",
      "tier": "warning",
      "title": "deployhub.yaml is present but declarations are disabled",
      "detail": "This repo carries a deployhub.yaml. The declared-test-material mechanism it belongs to is deferred to its own phase, so this scan did not parse the file and no claim in it changed anything: every finding under a declared path is reported at its full tier, exactly as it would be if the file were not here. The file is otherwise ignored — and it is scanned like any other file in the tree, so a credential written into it is a finding of its own.",
      "fix_hint": "Nothing to do for the deploy: no result above was downgraded. Read this as a correction to what the repo expects — if a tree was declared in deployhub.yaml in the belief that its findings would stop blocking, they are blocking, and either the findings or that expectation needs attention. Leaving the file in place is fine; it will be honored again when the mechanism returns with the threat model it is waiting on.",
      "execution": "static"
    },
    {
      "id": "django.secret-dev-fallback",
      "tier": "warning",
      "title": "Dev-fallback secret committed (prod provably rejects it)",
      "detail": "config/settings/base.py: FIELD_ENCRYPTION_KEYS",
      "fix_hint": "Production reassigns this from os.environ[...] and hard-fails without it, so the committed value cannot ship — but it lives in git history and every clone. If this repo was ever shared, rotate the value at its source. (Tier per D-008.)",
      "execution": "static"
    },
    {
      "id": "django.security-settings",
      "tier": "warning",
      "title": "Security settings missing in prod",
      "detail": "Missing: SECURE_PROXY_SSL_HEADER",
      "fix_hint": "These settings make sessions HTTPS-only behind the proxy: without them cookies leak over plain HTTP and Django cannot see the TLS termination. Add to prod settings: SECURE_SSL_REDIRECT = True, SESSION_COOKIE_SECURE = True, CSRF_COOKIE_SECURE = True, SECURE_HSTS_SECONDS = 31536000, SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https').",
      "execution": "static"
    }
  ],
  "advice": [
    {
      "id": "django.runtime-versions",
      "tier": "advice",
      "title": "Runtime versions outside the supported window",
      "detail": "Python: 3.12 (requires-python); Django: 4.2 (dependency spec).",
      "fix_hint": "The fleet standard is Python 3.12–3.14 and Django 5.2–6.x; outside that window the base images and playbooks here are untested. Bump requires-python / the Django pin, or expect manual image work.",
      "execution": "static"
    }
  ],
  "pending_sandbox": [
    {
      "id": "django.check-deploy",
      "tier": "pending_sandbox",
      "title": "[sandbox] django.check-deploy",
      "detail": "Runs off-Hub (review3 §M1): python manage.py check --deploy",
      "fix_hint": "Django's own deploy checklist; needs the app importable, so sandbox.",
      "execution": "executing"
    },
    {
      "id": "django.migrations-check",
      "tier": "pending_sandbox",
      "title": "[sandbox] django.migrations-check",
      "detail": "Runs off-Hub (review3 §M1): python manage.py makemigrations --check --dry-run",
      "fix_hint": "Detects model changes missing a migration; imports the app, so sandbox.",
      "execution": "executing"
    },
    {
      "id": "django.collectstatic",
      "tier": "pending_sandbox",
      "title": "[sandbox] django.collectstatic",
      "detail": "Runs off-Hub (review3 §M1): python manage.py collectstatic --noinput --dry-run",
      "fix_hint": "Proves static collection succeeds before a deploy depends on it.",
      "execution": "executing"
    }
  ]
};

// Pasted whole from `_state(site)` with `site.exposure` and FIELD_ENCRYPTION_KEYS
// answered and the domain not — so the screen shows a saved secret's metadata, an
// unanswered required question, and a `blocking` list with both shapes in it.
const MESSY_WIZARD = {
  "questions": [
    {
      "id": "site.domain",
      "prompt": "Public domain for this site (e.g. app.example.com)",
      "kind": "domain",
      "default": null,
      "choices": [],
      "secret": false
    },
    {
      "id": "site.exposure",
      "prompt": "How should this site be reachable?",
      "kind": "choice",
      "default": "public",
      "choices": [
        "public",
        "mesh_only"
      ],
      "secret": false
    },
    {
      "id": "django.db",
      "prompt": "Database for production",
      "kind": "choice",
      "default": "postgres",
      "choices": [
        "postgres",
        "mysql",
        "sqlite"
      ],
      "secret": false
    },
    {
      "id": "django.env.DB_NAME",
      "prompt": "Value for environment variable DB_NAME",
      "kind": "text",
      "default": null,
      "choices": [],
      "secret": false
    },
    {
      "id": "django.env.FIELD_ENCRYPTION_KEYS",
      "prompt": "Value for environment variable FIELD_ENCRYPTION_KEYS",
      "kind": "secret",
      "default": null,
      "choices": [],
      "secret": true
    }
  ],
  "answered": {
    "site.exposure": "public",
    "django.env.FIELD_ENCRYPTION_KEYS": {
      "answered": true,
      "is_secret": true,
      "changed_at": "2026-08-08T12:00:00Z"
    }
  },
  "blocking": [
    {
      "code": "blockers_present",
      "detail": "the readiness report has blockers; these must be fixed and the project re-scanned",
      "items": [
        {
          "id": "core.secret-scan",
          "title": "Committed secrets detected"
        },
        {
          "id": "django.debug-hardcoded",
          "title": "DEBUG is hardcoded True in prod-reachable settings"
        },
        {
          "id": "django.secret-key-literal",
          "title": "Secret material is a literal in source"
        }
      ]
    },
    {
      "code": "answers_missing",
      "detail": "required questions are unanswered",
      "items": [
        {
          "id": "site.domain",
          "prompt": "Public domain for this site (e.g. app.example.com)"
        }
      ]
    }
  ],
  "warnings": [
    {
      "id": "core.declaration-file",
      "title": "deployhub.yaml is present but declarations are disabled"
    },
    {
      "id": "django.secret-dev-fallback",
      "title": "Dev-fallback secret committed (prod provably rejects it)"
    },
    {
      "id": "django.security-settings",
      "title": "Security settings missing in prod"
    }
  ],
  "can_materialize": false
};

// What the POST returns for that site: a real MaterializeRefused, carrying every reason
// at once (round-1 F4) rather than the first.
const REFUSAL_409 = {
  "code": "blockers_present",
  "detail": "the readiness report has blockers; these must be fixed and the project re-scanned",
  "items": [
    {
      "id": "core.secret-scan",
      "title": "Committed secrets detected"
    },
    {
      "id": "django.debug-hardcoded",
      "title": "DEBUG is hardcoded True in prod-reachable settings"
    },
    {
      "id": "django.secret-key-literal",
      "title": "Secret material is a literal in source"
    }
  ],
  "problems": [
    {
      "code": "blockers_present",
      "detail": "the readiness report has blockers; these must be fixed and the project re-scanned",
      "items": [
        {
          "id": "core.secret-scan",
          "title": "Committed secrets detected"
        },
        {
          "id": "django.debug-hardcoded",
          "title": "DEBUG is hardcoded True in prod-reachable settings"
        },
        {
          "id": "django.secret-key-literal",
          "title": "Secret material is a literal in source"
        }
      ]
    },
    {
      "code": "answers_missing",
      "detail": "required questions are unanswered",
      "items": [
        {
          "id": "site.domain",
          "prompt": "Public domain for this site (e.g. app.example.com)"
        }
      ]
    }
  ]
};

// The refusal behind the `stale` state, and it is a different situation from the one
// above: the operator is looking at takko's wizard, which said the deploy may proceed,
// and between that GET and this POST the tree was re-scanned with a live Stripe key
// committed to it. Same site, a report that moved underneath them. Without this state
// the 409 panel is reachable from no screen where the button is enabled.
const STALE_REFUSAL_409 = {
  "code": "blockers_present",
  "detail": "the readiness report has blockers; these must be fixed and the project re-scanned",
  "items": [
    {
      "id": "core.secret-scan",
      "title": "Committed secrets detected"
    }
  ],
  "problems": [
    {
      "code": "blockers_present",
      "detail": "the readiness report has blockers; these must be fixed and the project re-scanned",
      "items": [
        {
          "id": "core.secret-scan",
          "title": "Committed secrets detected"
        }
      ]
    }
  ]
};

const never = () => new Promise(() => {});

// `v1/projects/2/readiness/` and `v1/sites/2/wizard/` both put the id in the same slot.
const idOf = (path) => Number(path.split("/")[2]);

const REPORTS = { 1: CLEAN_REPORT, 2: MESSY_REPORT };
const WIZARDS = { 1: CLEAN_WIZARD, 2: MESSY_WIZARD };
const MANIFESTS = { 1: CLEAN_MANIFEST };

// Each fixture: (path, body, method) => {status, data}
export const SIM_FIXTURES = {
  // No projects at all — first-run experience.
  empty: (path) =>
    path === "v1/projects/" ? { status: 200, data: [] } : { status: 404, data: {} },

  // Requests hang forever: every spinner is inspectable indefinitely.
  loading: never,

  // Healthy data: a clean project that can materialize, and a blocked one that cannot.
  live: (path, body, method) => {
    if (path === "v1/projects/")
      return { status: 200, data: [CLEAN_PROJECT, MESSY_PROJECT] };
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

  // The wizard state the operator is looking at is out of date: it said the deploy may
  // proceed, the tree was re-scanned, and the POST refuses. This is the one state where
  // the Materialize button is ENABLED and the request still comes back 409, which is the
  // only way to review that panel from a screen the operator can actually reach.
  stale: (path, body, method) => {
    if (path.endsWith("/manifest/") && idOf(path) === 1)
      return { status: 409, data: STALE_REFUSAL_409 };
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
