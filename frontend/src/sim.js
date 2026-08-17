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
//   ReadinessSerializer(...).data   → *_REPORT
//   wizard.views._state(site)       → *_WIZARD
//   wizard.materialize.materialize  → *_MANIFEST, *_409
//
// The trees are built by scripts_dev/sim_fixture_repos.py, which is committed for that
// reason: a clean digest-pinned service with /healthz, auth and tests (takko,
// /tmp/cleanrepo); a Django repo with a hardcoded SECRET_KEY, DEBUG=True in prod
// settings, a dev-fallback the prod module hard-fails without, a committed .env, secrets
// in a workflow, and a drill tree under a `deployhub.yaml` declaration (legacy-shop,
// /tmp/messyrepo); a pnpm monorepo whose workspace config names a package outside the
// repo and whose service package carries a committed symlink out of the tree
// (atlas-edge, /tmp/edgerepo + /tmp/edge-neighbour); and the clean tree re-scanned with
// a live-format Stripe key committed to it (/tmp/cleanrepo-rescanned), which is the
// report `?sim=stale` converges on.
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
// ROUND 9 added the three payload families §F8 had no fixture for at all, each one a
// screen a reviewer previously could not reach (finding numbers are round-9 queue items):
//
//   atlas-edge (project 3, item 11 + item 2) — a site that CLEARS preflight and still
//     carries warnings, which is the only shape from which `materialize`'s
//     `warnings_unconfirmed` refusal exists. The ack checkbox beside the Materialize
//     button had no state in which pressing it changed anything: POST without the
//     confirm is the real 409, POST with it is the real 201. Its two warnings are the
//     round-8/round-9 containment findings (`node-ts.workspace-patterns`,
//     `node-ts.symlinked-files`) produced by a real scan of a tree that really does
//     point outside itself, not a payload typed to look like one.
//   takko/staging (site 4, item 3) — a fresh site whose only refusal is
//     `answers_missing`: every clean project before the domain is typed. The gate used
//     to call this "⛔ Blocked".
//   orders-api (project 4, item 6) — a project that has never been scanned. The wizard
//     payload behind it is a real `_state()` run: `blocking: [scan_required]`, which is
//     what the server sends and what `?sim=degraded` used to hide behind a 503 whose
//     detail string existed nowhere on the server.
//
// NOTHING IN THIS FILE IS TYPED BUT THE COMMENTS, which is a change from r8: the project
// rows used to be assembled here, and the round-9 regeneration found two of their fields
// disagreeing with any real database — legacy-shop was shown carrying a frozen manifest
// its own report has always refused to produce. The names, slugs, ids and `scanned_at`
// stamps ARE chosen, but they are chosen in scripts_dev/sim_fixture_payloads.py, as
// inputs to the run, so the rows below are `ProjectListView`'s own output over them.
// Every row is captured BEFORE the POST its screen makes: takko/prod is on v3 so its
// button returns v4, atlas-edge has no manifest so its ack-confirmed button returns v1.
// The only values a regeneration moves are the wall clocks (`created_at`, `changed_at`).
// R8-4's whole finding was that a fixture nobody could check is a UI nobody reviewed.

// ── project 1: takko, nothing to report ───────────────────────────────────────
// python -m hub scan /tmp/cleanrepo → zero non-ok checks. Two sites: `prod`, whose
// domain is answered and which materializes, and `staging`, which nobody has configured
// yet — the ordinary first state of every new site.
const CLEAN_PROJECT = {
  "id": 1,
  "name": "takko",
  "slug": "takko",
  "scanned_at": "2026-08-09T10:00:00Z",
  "tiers": {
    "blocker": 0,
    "warning": 0,
    "advice": 0,
    "pending_sandbox": 0
  },
  "sites": [
    {
      "id": 1,
      "name": "prod",
      "domain": "takko.market",
      "latest_manifest_version": 3,
      "manifest_current": true
    },
    {
      "id": 4,
      "name": "staging",
      "domain": "",
      "latest_manifest_version": null,
      "manifest_current": null
    }
  ]
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

// The same project's other site, configured by nobody. `blocking` carries
// `answers_missing` and NOTHING else — no blocker exists anywhere in this project — and
// the button that used to read "⛔ Blocked" here is what round-9 item 3 was filed about.
const STAGING_WIZARD = {
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
  "answered": {},
  "blocking": [
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
  "warnings": [],
  "can_materialize": false
};

// …and what its POST really returns, though the gate disables the button that sends it.
const STAGING_409 = {
  "code": "answers_missing",
  "detail": "required questions are unanswered",
  "items": [
    {
      "id": "site.domain",
      "prompt": "Public domain for this site (e.g. app.example.com)"
    }
  ],
  "problems": [
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

// The 4th materialize of the prod site — the site row above says it is on v3, so this is
// the version the next POST really returns, and the generator materializes four times
// rather than editing the number. Body verbatim from wizard.materialize.
const CLEAN_MANIFEST = {
  "version": 4,
  "schema_version": 1,
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
  },
  "scan_report_hash": "aaa0a81571255525bba22cdb761a72acc51fa08e89b8146d91220e37c28ee1ea",
  "created_at": "2026-08-17T03:23:27.635292Z"
};

// ── project 2: legacy-shop, the mixed case ────────────────────────────────────
// Three blockers no answer clears — which since D-012 left Phase 1 is every blocker
// there is — and the wizard's own refusal beside them.
const MESSY_PROJECT = {
  "id": 2,
  "name": "legacy-shop",
  "slug": "legacy-shop",
  "scanned_at": "2026-08-09T09:30:00Z",
  "tiers": {
    "blocker": 3,
    "warning": 3,
    "advice": 1,
    "pending_sandbox": 3
  },
  "sites": [
    {
      "id": 2,
      "name": "prod",
      "domain": "",
      "latest_manifest_version": null,
      "manifest_current": null
    }
  ]
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
      "changed_at": "2026-08-17T03:23:27.602760+00:00"
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

// ── project 3: atlas-edge, warnings and nothing else (round-9 items 2 and 11) ──
// python -m hub scan /tmp/edgerepo → no blockers, two warnings, both of them the
// scanner refusing to read outside the tree it was pointed at: a `../vendor-cache/*`
// workspace pattern and a `packages/server/src/metrics.ts` symlink into
// /tmp/edge-neighbour. Nothing from that neighbouring tree appears anywhere below —
// that is what the two findings are saying.
const EDGE_PROJECT = {
  "id": 3,
  "name": "atlas-edge",
  "slug": "atlas-edge",
  "scanned_at": "2026-08-09T11:15:00Z",
  "tiers": {
    "blocker": 0,
    "warning": 2,
    "advice": 0,
    "pending_sandbox": 3
  },
  "sites": [
    {
      "id": 3,
      "name": "prod",
      "domain": "",
      "latest_manifest_version": null,
      "manifest_current": null
    }
  ]
};

const EDGE_REPORT = {
  "scanned_at": "2026-08-09T11:15:00Z",
  "modules": [
    "node-ts"
  ],
  "summary": {
    "blocker": 0,
    "warning": 2,
    "advice": 0,
    "ok": 22,
    "pending_sandbox": 3
  },
  "blockers": [],
  "warnings": [
    {
      "id": "node-ts.workspace-patterns",
      "tier": "warning",
      "title": "Workspace patterns were refused",
      "detail": "workspace pattern '../vendor-cache/*' escapes the scanned repository with `..`; the packages it names are outside the tree this scan is about, so their sources were not read — it was ignored.",
      "fix_hint": "Workspace patterns name directories inside the repository: make each one relative and keep it within the tree.",
      "execution": "static"
    },
    {
      "id": "node-ts.symlinked-files",
      "tier": "warning",
      "title": "Symlinked files outside the scan root were not read",
      "detail": "symlinked source file 'packages/server/src/metrics.ts' resolves outside the scan root; a scan reads only the tree it was pointed at — not read.",
      "fix_hint": "A scan reads only the tree it was pointed at. Keep committed symlinks inside the repository, or vendor the file itself — content from a neighbouring tree would otherwise decide this report's findings and the defaults the wizard offers.",
      "execution": "static"
    }
  ],
  "advice": [],
  "pending_sandbox": [
    {
      "id": "node-ts.install",
      "tier": "pending_sandbox",
      "title": "[sandbox] node-ts.install",
      "detail": "Runs off-Hub (review3 §M1): pnpm install --frozen-lockfile --ignore-scripts",
      "fix_hint": "CI-honesty install check; lifecycle scripts are the §6.8 supply-chain surface, so --ignore-scripts is explicit (§M1).",
      "execution": "executing"
    },
    {
      "id": "node-ts.tsc",
      "tier": "pending_sandbox",
      "title": "[sandbox] node-ts.tsc",
      "detail": "Runs off-Hub (review3 §M1): pnpm exec tsc --noEmit",
      "fix_hint": "Strict-mode type check; requires installed node_modules and plugin execution, so sandbox-only.",
      "execution": "executing"
    },
    {
      "id": "node-ts.build",
      "tier": "pending_sandbox",
      "title": "[sandbox] node-ts.build",
      "detail": "Runs off-Hub (review3 §M1): pnpm run build",
      "fix_hint": "Production build must succeed; builds execute project code, so sandbox-only (§M1).",
      "execution": "executing"
    }
  ]
};

// The domain is answered and no blocker exists, so `preflight` is empty and
// `can_materialize` is TRUE while `warnings` carries two entries. That combination is
// the only one from which the refusal below can be reached.
const EDGE_WIZARD = {
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
      "id": "node-ts.service-package",
      "prompt": "Which workspace package is the deployable service?",
      "kind": "choice",
      "default": "server",
      "choices": [
        "server",
        "web"
      ],
      "secret": false
    },
    {
      "id": "node-ts.dev-packages",
      "prompt": "Which workspace packages are dev-only (never deployed)?",
      "kind": "text",
      "default": "web",
      "choices": [],
      "secret": false
    },
    {
      "id": "node-ts.data-dir",
      "prompt": "Where does the data directory live? (becomes a per-Site named volume surviving container replacement)",
      "kind": "text",
      "default": "data",
      "choices": [],
      "secret": false
    },
    {
      "id": "node-ts.worker-threads",
      "prompt": "Expected worker-thread count (feeds container CPU guidance)",
      "kind": "number",
      "default": 2,
      "choices": [],
      "secret": false
    },
    {
      "id": "node-ts.exposure",
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
      "id": "node-ts.exclusive-upstream",
      "prompt": "Do any upstream feeds permit only one concurrent connection per account (e.g. Alpaca standard plan)? Flagged sites require the recreate strategy or a pre-stop handoff (§N4).",
      "kind": "bool",
      "default": false,
      "choices": [],
      "secret": false
    }
  ],
  "answered": {
    "site.domain": "edge.atlas.market"
  },
  "blocking": [],
  "warnings": [
    {
      "id": "node-ts.workspace-patterns",
      "title": "Workspace patterns were refused"
    },
    {
      "id": "node-ts.symlinked-files",
      "title": "Symlinked files outside the scan root were not read"
    }
  ],
  "can_materialize": true
};

// POST with `confirm_warnings: false` — materialize.py's warnings gate, and the reason
// the ack checkbox exists. Before this fixture no §F8 state produced it, so the whole
// friction path was unreviewable.
const WARNINGS_409 = {
  "code": "warnings_unconfirmed",
  "detail": "the readiness report has warnings; confirm to proceed",
  "items": [
    {
      "id": "node-ts.workspace-patterns",
      "title": "Workspace patterns were refused"
    },
    {
      "id": "node-ts.symlinked-files",
      "title": "Symlinked files outside the scan root were not read"
    }
  ],
  "problems": [
    {
      "code": "warnings_unconfirmed",
      "detail": "the readiness report has warnings; confirm to proceed",
      "items": [
        {
          "id": "node-ts.workspace-patterns",
          "title": "Workspace patterns were refused"
        },
        {
          "id": "node-ts.symlinked-files",
          "title": "Symlinked files outside the scan root were not read"
        }
      ]
    }
  ]
};

// …and the same POST with the box ticked: version 1 of that site's manifest, from the
// same run.
const EDGE_MANIFEST = {
  "version": 1,
  "schema_version": 1,
  "body": {
    "schema_version": 2,
    "components": {
      "service": {
        "kind": "node-ts",
        "package": "server",
        "command": [
          "node",
          "dist/index.js"
        ],
        "port": null
      },
      "static_route": null,
      "jobs": []
    },
    "jobs_image": null,
    "volumes": [],
    "deploy_strategy": "blue_green",
    "exposure": "public",
    "healthz": {
      "liveness_path": "/healthz",
      "readiness_path": "/healthz",
      "warmup_timeout_s": 600,
      "data_staleness_threshold": null
    },
    "domain": "edge.atlas.market",
    "env_names": [],
    "site": {
      "id": 3,
      "name": "prod",
      "domain": "edge.atlas.market"
    },
    "env_bundle_ref": null
  },
  "scan_report_hash": "59672e5d77598b402901c601842385b49f3b29631c272fc3bda030295f498196",
  "created_at": "2026-08-17T03:23:27.642302Z"
};

// ── takko, re-scanned underneath the operator (the `stale` state) ─────────────
// /tmp/cleanrepo-rescanned is the clean tree plus one committed payment helper carrying
// a live-format Stripe key. The operator is holding the CLEAN_WIZARD state above, which
// said the deploy may proceed; the POST is refused by the report that exists now; and
// every GET after that refusal returns the three payloads below. Without this pair the
// 409 panel is reachable from no screen where the button is enabled — and without the
// convergence the screen sat under a refusal naming a Stripe key while the panel above
// it said "✓ No findings" (round-9 item 4).
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

const RESCANNED_PROJECT = {
  "id": 1,
  "name": "takko",
  "slug": "takko",
  "scanned_at": "2026-08-12T07:20:00Z",
  "tiers": {
    "blocker": 1,
    "warning": 0,
    "advice": 0,
    "pending_sandbox": 0
  },
  "sites": [
    {
      "id": 1,
      "name": "prod",
      "domain": "takko.market",
      "latest_manifest_version": 4,
      "manifest_current": false
    },
    {
      "id": 4,
      "name": "staging",
      "domain": "",
      "latest_manifest_version": null,
      "manifest_current": null
    }
  ]
};

const RESCANNED_REPORT = {
  "scanned_at": "2026-08-12T07:20:00Z",
  "modules": [
    "dockerfile"
  ],
  "summary": {
    "blocker": 1,
    "warning": 0,
    "advice": 0,
    "ok": 9,
    "pending_sandbox": 0
  },
  "blockers": [
    {
      "id": "core.secret-scan",
      "tier": "blocker",
      "title": "Committed secrets detected",
      "detail": "payments.py:4: [proof] Stripe live key",
      "fix_hint": "Move secrets to the vault / environment injection. A .env file in this tree ships with a deploy of it, and is a leak as well if it is committed — check `git status`, add .env to .gitignore, and rotate anything that was committed: it stays in git history until you do.\n\n[proof] lines matched a published credential format — a GitHub token, a PEM block, an AWS key id — and are not guesses. [heuristic] lines are a secret-shaped name assigned a high-entropy literal: real most of the time, and worth a look before you decide.",
      "execution": "static"
    }
  ],
  "warnings": [],
  "advice": [],
  "pending_sandbox": []
};

const RESCANNED_WIZARD = {
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
  "blocking": [
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
  ],
  "warnings": [],
  "can_materialize": false
};

// ── project 4: orders-api, added and never scanned (the `degraded` state) ─────
// The payload `?sim=degraded` used to hide. A project row with `scanned_at: null` was
// already there; what was missing is what the server says about it, which is a report
// with no modules and no summary at all — not a report with legacy-shop's `summary` and
// its findings deleted — and a wizard state whose single refusal is `scan_required`.
const UNSCANNED_PROJECT = {
  "id": 4,
  "name": "orders-api",
  "slug": "orders-api",
  "scanned_at": null,
  "tiers": {
    "blocker": 0,
    "warning": 0,
    "advice": 0,
    "pending_sandbox": 0
  },
  "sites": [
    {
      "id": 5,
      "name": "prod",
      "domain": "",
      "latest_manifest_version": null,
      "manifest_current": null
    }
  ]
};

const UNSCANNED_REPORT = {
  "scanned_at": null,
  "modules": [],
  "summary": {},
  "blockers": [],
  "warnings": [],
  "advice": [],
  "pending_sandbox": []
};

const UNSCANNED_WIZARD = {
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
    }
  ],
  "answered": {},
  "blocking": [
    {
      "code": "scan_required",
      "detail": "this project has not been scanned yet",
      "items": []
    }
  ],
  "warnings": [],
  "can_materialize": false
};

const never = () => new Promise(() => {});

// `v1/projects/2/readiness/` and `v1/sites/2/wizard/` both put the id in the same slot.
const idOf = (path) => Number(path.split("/")[2]);

const REPORTS = { 1: CLEAN_REPORT, 2: MESSY_REPORT, 3: EDGE_REPORT, 4: UNSCANNED_REPORT };
const WIZARDS = { 1: CLEAN_WIZARD, 2: MESSY_WIZARD, 3: EDGE_WIZARD, 4: STAGING_WIZARD,
                  5: UNSCANNED_WIZARD };

// ── the one piece of STATE in this module, and why it is here ─────────────────
//
// `?sim=stale` is not a screen, it is an EVENT: the stored report moved between the GET
// the operator is looking at and the POST they just sent. A fixture that answers every
// request from the same table can show the refusal but not what happens next, and "what
// happens next" is round-9 item 4 — the client re-reads the server after a 409 and the
// screen converges on the truth. So the refusal flips this flag, and every subsequent
// GET in that state serves the re-scanned payloads.
//
// The reset hangs off the state that HAS the memory (`SIM_FIXTURES.stale.reset()`)
// rather than off the module, because that is where a reader looks for it: tests and the
// screen both need a way back to before the re-scan, and a hidden reset (a timer, a
// request counter) would be a fixture with a memory nobody can see.
let staleRescanServed = false;

// Each fixture: (path, body, method) => {status, data}
export const SIM_FIXTURES = {
  // No projects at all — first-run experience.
  empty: (path) =>
    path === "v1/projects/" ? { status: 200, data: [] } : { status: 404, data: {} },

  // THREE loading states, one per spinner, because there are three fetches in a chain
  // and hanging the first makes the other two unreachable (round-9 item 10): with no
  // project list there is no selectable project, so "Loading report…" never renders, and
  // "Loading wizard…" is two clicks further still. Each state below resolves everything
  // shallower than the fetch it hangs, so the spinner it is named for is the one on
  // screen — indefinitely, which is what makes it inspectable.
  loading: never,                                     // "Loading projects…"
  "loading-report": (path, body, method) =>           // "Loading report…"
    path === "v1/projects/" ? SIM_FIXTURES.live(path, body, method) : never(),
  "loading-wizard": (path, body, method) =>           // "Loading wizard…"
    path.endsWith("/wizard/") && method !== "PATCH"
      ? never() : SIM_FIXTURES.live(path, body, method),

  // Healthy data: a clean project that can materialize, a blocked one that cannot, and
  // one that can materialize only after the warnings are acknowledged.
  live: (path, body, method) => {
    if (path === "v1/projects/")
      return { status: 200, data: [CLEAN_PROJECT, MESSY_PROJECT, EDGE_PROJECT] };
    if (path.endsWith("/readiness/"))
      return { status: 200, data: REPORTS[idOf(path)] || CLEAN_REPORT };
    if (path.endsWith("/wizard/") && method === "PATCH") return { status: 200, data: {} };
    if (path.endsWith("/wizard/"))
      return { status: 200, data: WIZARDS[idOf(path)] || CLEAN_WIZARD };
    if (path.endsWith("/manifest/")) {
      const site = idOf(path);
      if (site === 1) return { status: 201, data: CLEAN_MANIFEST };
      if (site === 2) return { status: 409, data: REFUSAL_409 };
      if (site === 4) return { status: 409, data: STAGING_409 };
      // The warnings gate, decided by the request body exactly as materialize.py
      // decides it — this is the one control on the screen whose checkbox changes the
      // server's answer.
      if (site === 3)
        return body?.confirm_warnings
          ? { status: 201, data: EDGE_MANIFEST }
          : { status: 409, data: WARNINGS_409 };
      return { status: 409, data: REFUSAL_409 };
    }
    return { status: 404, data: {} };
  },

  // The wizard state the operator is looking at is out of date: it said the deploy may
  // proceed, the tree was re-scanned, and the POST refuses. This is the one state where
  // the Materialize button is ENABLED and the request still comes back 409, which is the
  // only way to review that panel from a screen the operator can actually reach — and,
  // after the refusal, the only way to review the client re-reading the server: the list,
  // the report and the wizard all move to the re-scanned truth.
  stale: (path, body, method) => {
    if (path.endsWith("/manifest/") && idOf(path) === 1) {
      staleRescanServed = true;
      return { status: 409, data: STALE_REFUSAL_409 };
    }
    if (staleRescanServed) {
      if (path === "v1/projects/")
        return { status: 200, data: [RESCANNED_PROJECT, MESSY_PROJECT, EDGE_PROJECT] };
      if (path === "v1/projects/1/readiness/")
        return { status: 200, data: RESCANNED_REPORT };
      if (path === "v1/sites/1/wizard/" && method !== "PATCH")
        return { status: 200, data: RESCANNED_WIZARD };
    }
    return SIM_FIXTURES.live(path, body, method);
  },

  // Data present but stale/incomplete: a project nobody has scanned yet, and one whose
  // frozen manifest predates the scan on screen. Both rows, both reports and both wizard
  // states are real runs (orders-api has an empty `scan_report`; takko is the re-scanned
  // tree with v4 already materialized against the previous one).
  degraded: (path, body, method) => {
    if (path === "v1/projects/")
      return { status: 200, data: [UNSCANNED_PROJECT, RESCANNED_PROJECT] };
    if (path === "v1/projects/4/readiness/")
      return { status: 200, data: UNSCANNED_REPORT };
    if (path === "v1/projects/1/readiness/")
      return { status: 200, data: RESCANNED_REPORT };
    if (path === "v1/sites/5/wizard/" && method !== "PATCH")
      return { status: 200, data: UNSCANNED_WIZARD };
    if (path === "v1/sites/1/wizard/" && method !== "PATCH")
      return { status: 200, data: RESCANNED_WIZARD };
    // Anything else in this state is the SIMULATION refusing to answer, and the text
    // says so. The string it used to send — "scan runner unavailable — showing last
    // stored data" — was written here and exists nowhere server-side: sim.js is exempt
    // from the no-client-authored-copy pin precisely because it is a transcript of the
    // server, so a sentence invented here is the one kind of lie that pin cannot catch.
    // It also stood in front of the never-scanned wizard payload above, which is a real
    // refusal this state now shows instead.
    return { status: 503, data: { detail:
      "[sim] this request is not answered in the degraded state — a simulated transport "
      + "failure, with no claim about what the server would say." } };
  },

  // The server is gone.
  error: () => ({ status: 0, data: { detail: "Cannot reach server — check your connection and retry." } }),
};

SIM_FIXTURES.stale.reset = () => { staleRescanServed = false; };
