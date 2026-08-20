# Phase 1 exit demo — recorded (P1-SCAN-DEMO)

**Date:** 2026-08-20 · **Branch:** `phase-1-continue` · **Recorded by:** Grok 4.6
session, `python -m hub scan <path>` — the same CLI entry point a user runs.

This re-record is required for three independent reasons, each of which would
have made the previous artifacts a lie:

1. **D-012 left Phase 1** (Joseph, 2026-08-16, Option A of the round-6 cap
   decision). The previous SATURDAYS_site record described declaration
   acceptance: a third bucket, a confirm, a legend that said those findings
   "block until you accept it in the wizard". That mechanism is parked.
   `scanner/declarations.py` is unimported. A repo that still carries
   `deployhub.yaml` now gets `core.declaration-file` at warning tier, and
   every finding under a declared path reports at full tier.
2. **`django.allowed-hosts` missed annotated assignments.** TAKKO writes
   `ALLOWED_HOSTS: list[str] = env.list(...)`. `_top_assigns` walked only
   `ast.Assign`, so the check warned "empty or absent" about a site that
   already does what its own fix_hint asks. Closed. The same visibility
   change then warned on hr-saas-starter's empty `ALLOWED_HOSTS: list[str] = []`
   in `base.py` even though `prod.py` overrides it from the environment —
   that follow-on false positive is closed too: a non-empty/env-driven
   assignment in any prod-reachable file is enough.
3. **The blocker title still said "Committed secrets detected".** N7 reworded
   the evidence lines because the scanner reads a tree and cannot see git;
   the title did not follow. It now says "Secrets detected in the scanned
   tree" (ok: "No secrets found in the scanned tree").

The in-repo fixture JSON is `schema_version` 2 (bumped when D-012 left so a
stored v1 report with a baked-in acceptance contract cannot materialize). Its
check set is otherwise the same 30 checks: the only title that moved is
`core.secret-scan`'s ok title.

Presentation differences versus the 2026-08-12 records (indent of continuation
lines, `Fix:` capitalisation, sandbox `fix_hint`s rendering at every tier)
are the R15-ARCH-1 shared presentation model landing in the CLI; they are
not new findings about the repos.

## Artifacts

| Artifact | Source | Result |
|---|---|---|
| `phase-1/scan-E-invoice.txt` | staged tree of `~/E-invoice` (Django, uv, ASGI) | exit 1 — 2 blockers, **0 warnings** (`app/.gitignore` is now the file this check reads) |
| `phase-1/scan-hr-saas-starter.txt` | staged tree of `~/hr-saas-starter` (Django + React) | exit 1 — 1 blocker, 1 warning (unpinned `FROM`) |
| `phase-1/scan-SATURDAYS_site.txt` | staged tree of `~/SATURDAYS_site` @ working tree with `deployhub.yaml` | exit 1 — 1 blocker (15 heuristic/`.env` lines, of which 10 are the drill tree that used to be a declaration), 2 warnings (`core.digest-pins` + `core.declaration-file`) |
| `phase-1/scan-TAKKO.txt` | staged tree of `~/TAKKO` (Django + Vite monorepo) | exit 1 — 2 blockers, **0 warnings** (the false `django.allowed-hosts` warning is gone) |
| `phase-1/scan-sample-node-site.json` | in-repo `sample-node-site/` fixture | exit 0 — same 30 checks as the prior recording; `schema_version` 1 → 2; `core.secret-scan` ok title no longer says "committed" |

Real-repo copies were the working-tree tarballs under `.stage-tmp/` (minus
`.git`, `node_modules`, `.venv`, `__pycache__` and tool caches), the same
staging used for the 2026-08-12 records.

## What the SATURDAYS record now shows

`deployhub.yaml` is still in the tree:

    scanner:
      test_material:
        - path: frontend/scripts/drill
          reason: red-team / QA drill scripts; deliberate fake credentials

It is **not parsed**. `core.declaration-file` says so in one warning line.
The ten drill findings sit in `core.secret-scan` with every other heuristic
line, unlabelled, blocking. That is D-012-out-of-phase-1 in a report, not
in a comment.

## Follow-up findings status

1. Generated-artifact directories — closed by N6.
2. Declared drill/QA trees — **parked out of Phase 1** (D-012 cap decision).
   SATURDAYS_site's file is ignored and announced.
3. `_WEAK_SECRET_KEYS`-shaped values — unchanged, waiver-shaped.
4. **E-invoice `core.gitignore` warns at scan root** (project lives at `app/`)
   — **CLOSED.** The check walks up from `manage.py` toward the scan root and
   reads `app/.gitignore`. A `frontend/.gitignore` is not a substitute.
5. Self-scan flags the scanner's own detector vectors — unchanged, recorded.
6. **`django.allowed-hosts` vs `env.list` / annotated assignment** — **CLOSED**.
   TAKKO is ok. An empty annotated list with no override still warns.
7. **The blocker title "Committed secrets detected"** — **CLOSED**. The title
   names the tree, not git.

## Open, still

- Two consecutive clean review rounds to close Phase 1.

J-1 (T2 fidelity) closed 2026-08-20, D-015 — `docs/j1-t2-fidelity-spike.md`.
