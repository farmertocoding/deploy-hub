# Spec N7 — three false-positive classes found by the TAKKO demo scan (2026-08-11)

**Context.** The TAKKO scan (Django+Vite monorepo, first real repo with a modern
frontend in-tree) produced 16 blocking `[heuristic]` lines and 3 "committed .env"
lines from `core.secret-scan`; triage found **none** of the 16 is a real secret. Three
new FP classes, all in `scanner/modules/fallbacks.py`. This change makes
`core.secret-scan` quieter, so the standing rule applies: an independent adversarial
pass weighted misses-over-noise is mandatory before merge, and every fix carries an
over-correction guard test proving the adjacent real-secret shape still fires.

All work in `scanner/modules/fallbacks.py` + `tests/test_scanner_fallbacks.py` (follow
the N5 commit `492d443` shape: failing-first tests, comments that carry the reasoning).

## Fix 1 — CSS custom-property references are not credentials

TAKKO: `token: "var(--color-pink-fill)"` ×12 in `EventIllustration.tsx`. Name axis
matches `token`, value passes length/entropy. Rule (N5's principle — judge the VALUE):
a value matching `^var\(--[A-Za-z0-9_-]+\)$` (anchored, exact) can never be a
credential. Applies to both the quoted and unquoted heuristic arms, before entropy.

Guards: `token = "ghp_" + 36 alnum` must still fire `[proof]`; a random ≥16-char quoted
value assigned to `token` must still fire `[heuristic]`; `var(--x)abc123...` (prefix,
not exact match) must NOT be excused.

## Fix 2 — dotted identifier paths on the core heuristic axis

TAKKO: `qr_token=preorder.pickup_code.token,` (a Python kwarg) fired the UNQUOTED arm —
the value alphabet allows `.`, and N5's `^ident(\.ident)+$` rule landed only in
`django.py::_looks_like_import_path`, never on the core axis. Port the same rule
(same regex: segments `[A-Za-z_][A-Za-z0-9_]*`, ≥2 segments) to both heuristic arms in
`_check_secret_scan` — a value that is entirely a dotted identifier path is dropped
before the name/entropy judgment.

**Over-correction guard (the reason this fix must ship with Fix 2b):** a JWT
(`eyJ….eyJ….sig`) is dot-separated and its base64url segments CAN match the ident
pattern when they contain no `-` and no leading digit. A dotted-ident exclusion
without a JWT guard opens a hole.

## Fix 2b — JWTs join axis 1 as a published credential format

Add to `_CREDENTIAL_FORMATS`:
`("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\b"))`
— both header and payload of a real JWT are base64url of `{"…`, which is `eyJ`; no
dotted import path starts a segment with `eyJ` followed by base64. Test: a JWT assigned
to a harmless name (`data = "<jwt>"`) fires `[proof]`; a JWT that would satisfy the
dotted-ident pattern (crafted all-letter segments) STILL fires — axis 1 runs first.

## Fix 3 — `.env` template suffixes

`_is_env_file` excludes only the exact names `.env.example|sample|template`, so TAKKO's
`docker/.env.prod.example` was reported "committed .env file". Change to a suffix
rule: any `.env*` name ending in `.example`, `.sample`, or `.template` is a template.
`docker/.env.prod` must still be flagged. The heuristic and `[proof]` axes still run
over template files (a real key pasted into a template is a real leak — test with a
`ghp_` token inside `.env.example` → still a blocking `[proof]` finding).

## Fix 3b — two placeholder markers

`SECRET_KEY=dev-only-not-a-secret-change-in-prod` (TAKKO `.env.example` and
`config/settings/base.py`) fires the heuristic; the value announces itself as a
non-secret. Add markers `"dev-only"` and `"not-a-secret"` to `_PLACEHOLDER_MARKERS`.
The existing `_looks_placeholder` escape (≥40 chars AND ≥4.0 bits/char is never
excused) is the over-correction guard — test a 45-char high-entropy value containing
`dev-only` still fires.

## Fix 4 — the `.env` line stops claiming "committed"

The scanner reads a tree; it cannot see git. TAKKO's `backend/.env` is gitignored and
untracked, and the report called it "committed .env file" — false. Reword the evidence
line to `f"{rel}: .env file present in the scan tree"` and adjust the fix_hint's first
sentence to say the file will ship with a deploy of this tree, is a leak if committed,
and to check git status / rotate accordingly. Update the tests that assert the old
wording. `scan-sample-node-site.json` must stay byte-identical (it has no `.env`
findings — verify by re-running the comparison test). The three fleet demo records
will need re-recording before phase exit; that is already true because of Fixes 1–3
and is recorded in the build docs, not handled here.

## Non-goals

- No change to `django.py` (N5 already fixed the django-side axes).
- No change to `_GENERATED_DIRS`/`_SKIP_DIRS`, the walk, or test-material routing.
- No registry (`conformance/requirements.yaml`) edits; new tests attach to the
  requirement ids the existing secret-scan tests already carry.
- The declared drill/QA config file (follow-up 2) is a separate spec.

## Acceptance

- Every fix lands with its failing-first test (verified failing on the unfixed module)
  plus the named over-correction guards above.
- Full suite green; `make review-round` gates green; `check.py --phase 1` exit 0.
- TAKKO re-scan drops from 16 blocking heuristic + 3 env lines to **0 blocking
  heuristic + 2 env lines** (`backend/.env`, `docker/.env.prod` — both real files in
  the tree, reworded per Fix 4) — `django.secret-key-literal` (blocker) and
  `django.allowed-hosts` (warning) are unchanged by this spec.
