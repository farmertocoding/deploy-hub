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
//
// ROUND 10 added the AFTER rows and the two states that need them, because a fixture
// captured only before the POST can show the button and not the consequence:
//
//   CLEAN_PROJECT_AFTER / EDGE_PROJECT_AFTER / CLEAN_PROJECT_ANSWERED (R10-UX-F2) —
//     the same `ProjectListView` rows one materialize later. `live` was stateless, so
//     the re-read a 201 triggers returned the pre-POST row forever: "Manifest v1
//     created." beside "no manifest yet", permanently, on the one screen the ack
//     checkbox exists for.
//   STAGING_WIZARD_ANSWERED / STAGING_MANIFEST (R10-UX-F4) — takko/staging after a real
//     `set_answers`. The PATCH returned `{}` and the refetch returned the unanswered
//     state, so typing the domain and pressing Save reverted on screen and the one
//     refusal this form clears by itself had no clearing path in any state.
//   RESCANNED_PROJECT (R10-UX-F3) — captured at v3 now, not v4. It used to be taken
//     after the live state's materialize, so the row the operator converges on after a
//     409 showed v3→v4: a refusal appearing to have created the manifest it refused.

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
      "manifest_current": true,
      "cert_refusal": null
    },
    {
      "id": 4,
      "name": "staging",
      "domain": "",
      "latest_manifest_version": null,
      "manifest_current": null,
      "cert_refusal": null
    }
  ]
};

// R10-UX-F2: the same row one materialize later — takko/prod on v4.
// `live` used to answer every request from one table, so the re-read a 201 triggers
// returned the PRE-POST row forever: "Manifest v4 created." above a list still saying
// v3, with nothing the operator could do to make the two agree. Generated by the same
// `ProjectListView` derivation as the row above it, from the state that exists after
// `CLEAN_MANIFEST` was returned.
const CLEAN_PROJECT_AFTER = {
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
      "latest_manifest_version": 4,
      "manifest_current": true,
      "cert_refusal": null
    },
    {
      "id": 4,
      "name": "staging",
      "domain": "",
      "latest_manifest_version": null,
      "manifest_current": null,
      "cert_refusal": null
    }
  ]
};

// …and after takko/staging is answered and materialized too: prod on v4, staging on v1
// with the domain the PATCH carried. The third and last row of one linear session.
const CLEAN_PROJECT_ANSWERED = {
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
      "latest_manifest_version": 4,
      "manifest_current": true,
      "cert_refusal": null
    },
    {
      "id": 4,
      "name": "staging",
      "domain": "staging.takko.market",
      "latest_manifest_version": 1,
      "manifest_current": true,
      "cert_refusal": null
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

// R10-UX-F4: takko/staging after the operator types the domain and presses Save.
// A real `_state()` run following a real `set_answers` — `answered` carries the domain,
// `blocking` is empty and `can_materialize` is true, which is the state that turns
// "Answers needed" back into "Materialize manifest". Until this existed, `live`'s PATCH
// returned `{}` and the refetch returned the unanswered state again, so the one refusal
// this form clears by itself had no clearing path in any reviewable state.
const STAGING_WIZARD_ANSWERED = {
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
    "site.domain": "staging.takko.market"
  },
  "blocking": [],
  "warnings": [],
  "can_materialize": true
};

// …and what the now-enabled button returns. Without it the fixture would answer an
// answered wizard's POST with `answers_missing`.
const STAGING_MANIFEST = {
  "version": 1,
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
    "domain": "staging.takko.market",
    "env_names": [],
    "site": {
      "id": 4,
      "name": "staging",
      "domain": "staging.takko.market"
    },
    "env_bundle_ref": null
  },
  "scan_report_hash": "a4119c6e9b10e802b8924d9e3ef24c60db415dd063fc93992cf401ce86ebb253",
  "created_at": "2026-08-20T07:51:23.205571Z"
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
  "scan_report_hash": "a4119c6e9b10e802b8924d9e3ef24c60db415dd063fc93992cf401ce86ebb253",
  "created_at": "2026-08-20T07:51:23.172755Z"
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
      "manifest_current": null,
      "cert_refusal": null
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
      "title": "Secrets detected in the scanned tree",
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
      "changed_at": "2026-08-20T07:51:23.151198+00:00"
    }
  },
  "blocking": [
    {
      "code": "blockers_present",
      "detail": "the readiness report has blockers; these must be fixed and the project re-scanned",
      "items": [
        {
          "id": "core.secret-scan",
          "title": "Secrets detected in the scanned tree"
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
      "title": "Secrets detected in the scanned tree"
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
          "title": "Secrets detected in the scanned tree"
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
      "manifest_current": null,
      "cert_refusal": null
    }
  ]
};

// R10-UX-F2: atlas-edge one ack-confirmed materialize later — v1, and the domain the
// materialize applied to the Site. This is the row the finding is sharpest about: the
// site starts with NO manifest, so the un-converged screen read "Manifest v1 created."
// directly beside "no manifest yet".
const EDGE_PROJECT_AFTER = {
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
      "domain": "edge.atlas.market",
      "latest_manifest_version": 1,
      "manifest_current": true,
      "cert_refusal": null
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
      "execution": "static",
      "refused_paths": [
        "packages/server/src/metrics.ts"
      ]
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
  "scan_report_hash": "eb8aa141ec882dc108e3ed661382d8cfbacf8c58c1e85c440c6a64716eaecb7a",
  "created_at": "2026-08-20T07:51:23.176304Z"
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
      "title": "Secrets detected in the scanned tree"
    }
  ],
  "problems": [
    {
      "code": "blockers_present",
      "detail": "the readiness report has blockers; these must be fixed and the project re-scanned",
      "items": [
        {
          "id": "core.secret-scan",
          "title": "Secrets detected in the scanned tree"
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
      "latest_manifest_version": 3,
      "manifest_current": false,
      "cert_refusal": null
    },
    {
      "id": 4,
      "name": "staging",
      "domain": "",
      "latest_manifest_version": null,
      "manifest_current": null,
      "cert_refusal": null
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
      "title": "Secrets detected in the scanned tree",
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
          "title": "Secrets detected in the scanned tree"
        }
      ]
    }
  ],
  "warnings": [],
  "can_materialize": false
};

// R11-UX-F1: takko's OTHER site, under the report the refusal converged on.
//
// The re-scan is a PROJECT fact — it moved the report under every site takko has — and
// the converged state captured only site 1. So clicking `staging` after the refusal fell
// through to `?sim=live`'s payload: `answers_missing` alone, under a panel listing a
// blocker, and typing the domain into that form reached the live state's 201. A wizard
// saying the deploy may proceed while the report beside it reports a blocker is the one
// combination this phase must never show (`sim-contract.test.ts`'s d012 walk), and it was
// reachable by clicking the second site.
//
// This is `_state(staging)` run at the moment the stored report is the re-scanned one:
// both refusals, in preflight's own order, and `can_materialize: false`.
const RESCANNED_STAGING_WIZARD = {
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
      "code": "blockers_present",
      "detail": "the readiness report has blockers; these must be fixed and the project re-scanned",
      "items": [
        {
          "id": "core.secret-scan",
          "title": "Secrets detected in the scanned tree"
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
      "manifest_current": null,
      "cert_refusal": null
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

// ── the STATE in this module, and why it is here ─────────────────────────────
//
// A §F8 state is usually a screen. Two of them are EVENTS, and an event needs a before
// and an after or the thing under review is only half of it.
//
// `?sim=stale`: the stored report moved between the GET the operator is looking at and
// the POST they just sent. Round-9 item 4 is what happens NEXT — the client re-reads the
// server after a 409 and the screen converges on the truth — so the refusal flips a flag
// and every subsequent GET serves the re-scanned payloads.
//
// `?sim=live` (R10-UX-F2): the same shape one layer over, and it was missing. `live`
// answered every request from one table, so a 201 that succeeded never changed anything:
// the re-read the client makes after it returned the PRE-POST row, forever. On
// atlas-edge — the site the ack checkbox exists for, which starts with NO manifest —
// that read "Manifest v1 created." directly beside "no manifest yet", with nothing the
// operator could press to make the two agree. The two sites whose POST can succeed now
// remember that it did.
//
// `?sim=live`'s PATCH (R10-UX-F4): it returned `{}` and the refetch returned the same
// unanswered wizard, so typing the domain and pressing Save reverted on screen. The
// PATCH is now body-driven the way atlas-edge's ack POST already was — the one control
// whose input changes the server's answer is the model for the others.
//
// EVERY reset hangs off the state that HAS the memory (`SIM_FIXTURES.live.reset()`,
// `SIM_FIXTURES.stale.reset()`) rather than off the module, because that is where a
// reader looks for it: tests and the screen both need a way back to the beginning, and a
// hidden reset (a timer, a request counter) would be a fixture with a memory nobody can
// see.
let staleRescanServed = false;
// Site ids whose materialize has been served a 201 in this session.
let liveMaterialized = new Set();
// takko/staging's domain has been PATCHed.
let liveStagingAnswered = false;

// The takko row, per what has been materialized in this session. THREE captures, which
// is what one linear generator session produces: none, prod, then prod-and-staging.
//
// NOT COVERED, and named rather than papered over: materializing staging BEFORE prod.
// A captured row is a snapshot of a whole PROJECT, so covering every order needs the
// PRODUCT of the sites' states rather than the chain, and a fixture that assembled one
// would be sim.js composing a payload — which is exactly what round 9 took out of this
// file. The order below is the one the screen presents (sites are listed by id) and the
// one the generator records.
const takkoRow = () =>
  liveMaterialized.has(4) ? CLEAN_PROJECT_ANSWERED
    : liveMaterialized.has(1) ? CLEAN_PROJECT_AFTER : CLEAN_PROJECT;

// atlas-edge's row, per the same session memory. R11-UX-F1: written once because the
// `stale` list used to name `EDGE_PROJECT` outright — so an operator who materialized
// atlas-edge and then triggered takko's refusal watched the edge row forget its own 201.
// Nothing about takko's re-scan touches another project's manifest, and a fixture that
// says otherwise is a fiction about a project the state is not even about.
const edgeRow = () => liveMaterialized.has(3) ? EDGE_PROJECT_AFTER : EDGE_PROJECT;

// takko's sites. `stale` is ONE event — the report moved under this project — and the
// only transition captured against the moved report is site 1's refusal. Every other
// write to a takko site in this state has no payload behind it (see `notCovered`).
//
// R12-A2: DERIVED from the captured row rather than typed, and exported so the test that
// walks these sites reads the same list. It was `[1, 4]` here and `[1, 4]` again in
// sim-contract.test.ts — two hand-typed copies of a fact the payload already carries, in
// a file whose whole rule is that nothing in it is typed. `CLEAN_PROJECT` is takko's row
// as `ProjectListView` produced it, so a site added to the generator arrives here without
// an edit, and a test cannot walk a set of sites the simulation does not route.
export const TAKKO_SITES = CLEAN_PROJECT.sites.map((s) => s.id);

// Task 13: findings snapshots for ?sim= — same {seq, data} shape as
// FindingListView, so the inbox is reviewable without a backend. Not a
// *_REPORT constant: the scanner-drift gate must not parse these as scans.
const SIM_FINDINGS = [
  {
    "id": 1, "source_engine": "uptime", "severity": "p1",
    "entity": "site:shop.example.com", "title": "shop.example.com is down",
    "body": "Three consecutive probes failed; visitors see connection errors.",
    "fix_action": "Check docker ps on the target; restart the container.",
    "state": "open", "fingerprint": "fp-shop-down", "accepted_reason": "",
    "first_seen": "2026-08-22T00:00:00Z", "last_seen": "2026-08-22T00:05:00Z",
  },
  {
    "id": 7, "source_engine": "certs", "severity": "p1",
    "entity": "site:shop.example.com",
    "title": "Unproxied site cannot be issued a certificate",
    "body": "shop.example.com is public and unproxied; Hub-central DNS-01 is not built.",
    "fix_action": "Proxy the site through Cloudflare, or wait for Phase 4's DNS-01.",
    "state": "open", "fingerprint": "fp-unproxied", "accepted_reason": "",
    "first_seen": "2026-08-22T00:00:00Z", "last_seen": "2026-08-22T00:05:00Z",
  },
];

function findingsFixture(path) {
  if (path === "v1/findings/")
    return { status: 200, data: { seq: 1, data: SIM_FINDINGS } };
  const m = /^v1\/findings\/(\d+)\/$/.exec(path);
  if (!m) return null;
  const row = SIM_FINDINGS.find((f) => f.id === Number(m[1]));
  return row
    ? { status: 200, data: { seq: 1, data: row } }
    : { status: 404, data: { detail: "Not found" } };
}

// The self-identified synthetic refusal, and the established pattern for one: `degraded`
// answers the routes it does not cover with a `[sim]`-prefixed 503 rather than a sentence
// invented here and attributed to the server. Same rule, different reason — this one is
// not a simulated transport failure, it is a combination of states that NO capture in one
// linear generator session produces, so there is nothing honest to return.
//
// R11-UX-F1's whole finding is what the alternative costs: falling through to the nearest
// captured payload is not "approximately right", it is a screen asserting something the
// server never said, in the state whose entire job is being the truth after a refusal.
// 501 rather than 503: the sim is not pretending the transport failed, it is saying this
// screen does not exist yet. Both are statuses the real server never sends, which is the
// point — a fixture must never be mistaken for a transcript.
const notCovered = (what) => ({
  status: 501,
  data: { detail: `[sim] NOT COVERED: ${what} — no captured payload exists for this `
    + `combination, and the simulation will not invent one. Reload to start over.` },
});

// Each fixture: (path, body, method) => {status, data}
export const SIM_FIXTURES = {
  // No projects at all — first-run experience.
  empty: (path) => {
    if (path === "v1/projects/") return { status: 200, data: [] };
    if (path === "v1/findings/") return { status: 200, data: { seq: 0, data: [] } };
    return { status: 404, data: {} };
  },

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
    const findings = findingsFixture(path);
    if (findings) return findings;
    if (path === "v1/projects/")
      return { status: 200, data: [takkoRow(), MESSY_PROJECT, edgeRow()] };
    if (path.endsWith("/readiness/"))
      return { status: 200, data: REPORTS[idOf(path)] || CLEAN_REPORT };
    // R10-UX-F4. The PATCH used to return `{}`, which the screen discards, and the
    // refetch behind it returned the unanswered state again — so the answer went in and
    // came straight back out. It now answers with what a PATCH answers with (§4.5: the
    // full state, same serializer as the GET), and the state it answers with is the one
    // captured after a real `set_answers`. Body-driven: only a PATCH actually carrying
    // `answers["site.domain"]` moves it, exactly as atlas-edge's 201 is driven by
    // `confirm_warnings`. The client wraps the draft; an unwrapped qid map is not a
    // valid AnswersSerializer body.
    if (path.endsWith("/wizard/") && method === "PATCH") {
      if (idOf(path) === 4 && body?.answers?.["site.domain"]) liveStagingAnswered = true;
      return { status: 200, data: SIM_FIXTURES.live(path, null, "GET").data };
    }
    if (path.endsWith("/wizard/")) {
      const site = idOf(path);
      if (site === 4 && liveStagingAnswered)
        return { status: 200, data: STAGING_WIZARD_ANSWERED };
      return { status: 200, data: WIZARDS[site] || CLEAN_WIZARD };
    }
    if (path.endsWith("/manifest/")) {
      const site = idOf(path);
      // R11-UX-F6: a captured 201 is consumed ONCE. Pressing Materialize again replayed
      // the same manifest version forever — "Manifest v4 created." twice, beside a row
      // that stayed at v4 — which is the only screen on this form that a real server
      // cannot produce: the next materialize is v5. One linear generator session
      // captures one manifest per site, so the second press has no payload behind it and
      // says so rather than repeating the first.
      const created = (data) => {
        if (liveMaterialized.has(site))
          return notCovered(`a second materialize of site ${site}`);
        liveMaterialized.add(site);
        return { status: 201, data };
      };
      if (site === 1) return created(CLEAN_MANIFEST);
      if (site === 2) return { status: 409, data: REFUSAL_409 };
      // takko/staging: `answers_missing` until the domain is typed, and the manifest the
      // now-enabled button really returns after it. A fixture that kept refusing for
      // `answers_missing` under a wizard saying `can_materialize: true` would be
      // contradicting itself on one screen.
      if (site === 4)
        return liveStagingAnswered
          ? created(STAGING_MANIFEST)
          : { status: 409, data: STAGING_409 };
      // The warnings gate, decided by the request body exactly as materialize.py
      // decides it — this is the one control on the screen whose checkbox changes the
      // server's answer.
      if (site === 3)
        return body?.confirm_warnings
          ? created(EDGE_MANIFEST)
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
  //
  // R11-UX-F1: AND THE CONVERGENCE IS THE WHOLE PROJECT, not site 1. The re-scan moved
  // the report under every site takko has, and this state used to name site 1's payloads
  // and fall through to `live` for everything else — so clicking `staging` after the
  // refusal served the pre-rescan wizard: `answers_missing` alone, under a panel listing
  // a blocker, and one PATCH away from the live state's 201. A screen that can materialize
  // under a blocking report is the combination the d012 invariant exists to forbid, and
  // it was two clicks from the state whose entire job is being the truth after a refusal.
  //
  // Two answers, and which one a request gets is the point of this whole finding:
  //   * site 4's wizard has a CAPTURE now — `_state(staging)` run against the moved
  //     report — so it is served, like site 1's;
  //   * every WRITE to a takko site other than the refusal itself has no capture in a
  //     linear generator session (the product of "which sites answered" × "which report
  //     is stored" is not a chain), so it is REFUSED, visibly, by `notCovered`. Falling
  //     through would answer with what the live state remembers, which is a screen the
  //     server behind this state cannot produce.
  stale: (path, body, method) => {
    const findings = findingsFixture(path);
    if (findings) return findings;
    if (path.endsWith("/manifest/") && idOf(path) === 1) {
      staleRescanServed = true;
      return { status: 409, data: STALE_REFUSAL_409 };
    }
    const write = method === "PATCH" || path.endsWith("/manifest/");
    if (write && TAKKO_SITES.includes(idOf(path)))
      return notCovered(
        `writing to takko/site ${idOf(path)} in the stale state. This state is one `
        + "event — the report moved under this project — and the only transition "
        + "captured against the moved report is site 1's refusal");
    if (staleRescanServed) {
      if (path === "v1/projects/")
        // …and atlas-edge keeps its own session memory: nothing about takko's re-scan
        // touches another project's manifest, and this list used to say it did.
        return { status: 200, data: [RESCANNED_PROJECT, MESSY_PROJECT, edgeRow()] };
      if (path === "v1/projects/1/readiness/")
        return { status: 200, data: RESCANNED_REPORT };
      if (path === "v1/sites/1/wizard/")
        return { status: 200, data: RESCANNED_WIZARD };
      if (path === "v1/sites/4/wizard/")
        return { status: 200, data: RESCANNED_STAGING_WIZARD };
    }
    return SIM_FIXTURES.live(path, body, method);
  },

  // Data present but stale/incomplete: a project nobody has scanned yet, and one whose
  // frozen manifest predates the scan on screen. Both rows, both reports and both wizard
  // states are real runs (orders-api has an empty `scan_report`; takko is the re-scanned
  // tree carrying the v3 it materialized against the previous one — R10-UX-F3: the
  // re-scan is what makes that manifest stale, and no manifest was created by it).
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
SIM_FIXTURES.live.reset = () => {
  liveMaterialized = new Set();
  liveStagingAnswered = false;
};
