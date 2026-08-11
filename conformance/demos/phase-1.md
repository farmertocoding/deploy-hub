# Phase 1 exit demo — recorded (P1-SCAN-DEMO)

**Date:** 2026-08-11 · **Commit under test:** branch `demo-records-r4-10` on `38a0dc4`
(round-6, round-6b, N4 and D-011r all merged) · **Recorded by:** Cowork session, cloud
container, `python -m hub scan <path>` — the same CLI entry point a user runs.

This record closes **R4-10** and **item 9 of the D-010 follow-up list**: the four
phase-1 scan records were stale (recorded 2026-08-04, commit `a345630`, before D-010
composed the common core suite into Django scans and before round-6b widened four of
the seven core checks), and nothing in the conformance registry checked that the demo
tree existed at all. `P1-SCAN-DEMO` in `conformance/requirements.yaml` now names all
four artifacts, so `check.py --phase 1` goes red if a record is deleted or blanked.

## Artifacts

| Artifact | Source | Result |
|---|---|---|
| `phase-1/scan-E-invoice.txt` | `~/E-invoice` (Django, uv, ASGI) | exit 1 — 2 blockers |
| `phase-1/scan-hr-saas-starter.txt` | `~/hr-saas-starter` (Django + React) | exit 1 — 1 blocker |
| `phase-1/scan-SATURDAYS_site.txt` | `~/SATURDAYS_site` (Django + frontend) | exit 1 — 1 blocker |
| `phase-1/scan-sample-node-site.json` | in-repo `sample-node-site/` fixture | exit 0 — **byte-identical to the 2026-08-04 recording** |

Real-repo copies were staged from the Mac as tarballs (working tree, minus
`node_modules` / `.venv` / `__pycache__` / build caches — directories the scanner
skips anyway, verified by the byte-identical fixture run). The fixture record not
moving one byte is the control: the changes below are Django-module changes, and the
node-ts path is untouched by them.

## What the re-record found: N5

**The first run of the widened checks against the real fleet fired a blocker-tier
false positive on every Django project that exists.** `django.secret-key-literal`
reported `INSTALLED_APPS` and `MIDDLEWARE` as committed secret material in all three
repos, plus `PASSWORD_HASHERS` in one. Two independent causes in `_check_secret_key`,
both invisible to the fixtures:

1. `_string_literal` **joined** a list's elements before measuring entropy — added for
   D-008's real shape (`FIELD_ENCRYPTION_KEYS = ["<fernet>"]`). A twelve-app
   `INSTALLED_APPS` joins to ~300 characters of mixed lowercase and dots: past the
   24-character floor, past 4.0 bits, indistinguishable from key material by that
   measure. The fixtures' app lists are short enough to stay under it.
2. The `secretish` axis matched a **name** substring and accepted **any** non-empty
   string value, so `PASSWORD_HASHERS` (contains `PASS`) and `_WEAK_SECRET_KEYS`
   (contains `SECRET`) qualified on their names alone.

**Fix (N5):** dotted import paths are dropped from a value before either axis runs,
and entropy is judged **per element** rather than on the concatenation. One rule
closes both routes — no published credential format survives
`^ident(\.ident)+$`. Four failing-first regression tests, including an
over-correction guard that keeps D-008's single-element Fernet list blocking while a
module full of dotted-path lists sits beside it.

Effect on the fleet: `django.secret-key-literal` went `blocker → ok` on
hr-saas-starter and SATURDAYS_site, and on E-invoice narrowed from four names to two
— `DEV_FALLBACK_ENCRYPTION_KEY` (a real committed key, the D-008 finding, unchanged
since the 2026-08-04 record) and `_WEAK_SECRET_KEYS`, a list of known-weak values the
code refuses. The second is residual noise the scanner cannot resolve from the value
alone; it is a waiver-shaped finding, recorded here rather than special-cased.

## D-011r revisit data — heuristic noise across the real fleet

The D-011 ruling (Joseph, 2026-08-11) kept heuristic-only secret findings at blocker
tier, with an explicit revisit trigger: *reopen if the demo re-records show heuristic
noise high enough to train blocker-bypass.* This is that measurement. Counts are
`core.secret-scan` evidence lines, blocking section vs. the non-blocking test-material
tail:

| Repo | committed `.env` | `[proof]` | `[heuristic]` (blocking) | `[heuristic]` (test material, non-blocking) |
|---|---|---|---|---|
| E-invoice | 1 | 1 | 2 | 2 |
| hr-saas-starter | 0 | 0 | 10 | 5 |
| SATURDAYS_site | 2 | 0 | 26 | 2 |
| `sample-node-site` | 0 | 0 | 0 | 0 |

(`deploy-hub` scanning itself is not a fleet data point and is left out on purpose:
its blocking evidence is dominated by the scanner's own detector test vectors, which
are real published-format credentials by construction. Recorded as follow-up 5.)

**Reading it.** Two of three real repos carry **zero** proof-tier evidence, so on
those the blocker rests entirely on the heuristic axis — exactly the D-008 argument.
The 26 on SATURDAYS_site are not spread thin: **20 of them are one directory**,
`frontend/scripts/drill/**`, QA and red-team drill scripts that hold deliberate
`admin_password` / `staff_password` literals. They are test material by intent and by
content; they are not test material by *path*, because round-6b deliberately narrowed
the test-material downgrade after a security pass found it reaching `spec`, `fixtures`,
`e2e` and `cypress` — names that also occur in production trees.

Two further clusters are artifacts rather than source:

- `frontend/coverage/lcov-report/src/auth.ts.html` — a **generated coverage report**
  echoing the source line above it, counted twice for one underlying literal.
- `.claude/skills/**` — tooling checked into the repo, not deployed code.

**Assessment, not a ruling.** The honest number for "findings an operator would
dismiss without reading" is roughly 22 of the 38 blocking heuristic lines across
the fleet, concentrated in two structural classes — *a drill/QA script tree* and
*generated build artifacts* — rather than distributed randomly. That shape argues the
next move is **narrowing what gets scanned**, not demoting the tier: excluding
generated-artifact directories (`coverage/`, `htmlcov/`, `lcov-report/`, `.next/`,
`dist/`) is unambiguous, and a per-repo opt-out for a declared drill tree is a
scanner-config question. D-011r's demotion argument is not yet the cheapest fix
available, so this record does **not** trigger the reopen; it hands Joseph the numbers
and names the two exclusions as follow-up findings.

## Follow-up findings raised by this record

1. **Generated-artifact directories are scanned** — `coverage/`, `lcov-report/`,
   `htmlcov/`, `dist/`, `.next/` produce duplicate findings that echo a source line
   already reported. Unambiguous exclusion; no judgment call.
2. **A declared drill/QA tree has no way to say so** — 20 of 38 blocking heuristic
   lines on one repo. Needs a decision on scanner config before code.
3. **`_WEAK_SECRET_KEYS`-shaped values** — a list of known-weak literals a project
   refuses. Residual after N5; waiver-shaped, low volume (one instance fleet-wide).
4. **E-invoice `core.gitignore` warns at scan root** — the Django project lives at
   `app/`, and the `.gitignore` that matters sits with it. Scan-root-only reading was
   fixed for `core.lockfile`/`core.gitignore` in round-6b for the *nested* case;
   this is the inverse (repo root above the project root) and is a real gap.
   Confirmed: `app/.gitignore` and `app/frontend/.gitignore` both exist and were
   not read.
5. **Self-scan reports the scanner's own detector test vectors** — scanning
   `deploy-hub` flags `conformance/run-report.json` and the fixture strings inside
   `scanner/modules/fallbacks.py`. Harmless here, but the same shape (a security
   tool's own corpus) will recur in any repo that stores test credentials, and it is
   the one class where `[proof]` tier is confidently wrong.
