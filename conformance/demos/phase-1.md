# Phase 1 exit demo — recorded (P1-SCAN-DEMO)

**Date:** 2026-08-12 (third re-record, SATURDAYS_site only) · **Commit under test:**
branch `saturdays-declaration-record` on `8e7da8c` (declared test material / D-012
merged) · **Recorded by:** Cowork session, cloud container,
`python -m hub scan <path>` — the same CLI entry point a user runs.

**This re-record changes one artifact.** SATURDAYS_site now carries a `deployhub.yaml`
declaring `frontend/scripts/drill`, so its record shows the D-012 mechanism working on
the repo that motivated it. The other three fleet records and the fixture JSON were
re-run and are **byte-identical** to the 2026-08-11 recording — no repo without a
declaration moved, which is the control for a feature that can only ever subtract.

This supersedes the same-day R4-10 record (branch `demo-records-r4-10`, preserved in
git history) after **N7** changed `core.secret-scan`'s output on every real repo: the
TAKKO demo scan — the first real Django+Vite monorepo — produced 16 blocking
`[heuristic]` lines of which **zero** were real secrets, and the fixes (CSS `var(--…)`
values, dotted identifier paths on the core axis, `.env` template suffixes, two
placeholder markers, honest `.env` wording) moved every fleet record. Re-recording is
not optional after that: the records are cited by `P1-SCAN-DEMO` and a stale record is
exactly what R4-10 existed to prevent.

## Artifacts

| Artifact | Source | Result |
|---|---|---|
| `phase-1/scan-E-invoice.txt` | `~/E-invoice` @ `f5c0f5d` (Django, uv, ASGI) | exit 1 — 2 blockers |
| `phase-1/scan-hr-saas-starter.txt` | `~/hr-saas-starter` @ `f30a2a3` (Django + React) | exit 1 — 1 blocker |
| `phase-1/scan-SATURDAYS_site.txt` | `~/SATURDAYS_site` @ `960a83e` + `deployhub.yaml` (Django + frontend) | exit 1 — 1 blocker, **10 lines declared** |
| `phase-1/scan-TAKKO.txt` | `~/TAKKO` @ `ea7b221` (Django + Vite monorepo) | exit 1 — 2 blockers |
| `phase-1/scan-sample-node-site.json` | in-repo `sample-node-site/` fixture | exit 0 — **byte-identical to the 2026-08-04 recording**, through N5, N6, N7, N8 and D-012 |

Real-repo copies were staged from the Mac as working-tree tarballs (minus `.git`,
`node_modules`, `.venv`, `__pycache__` and tool caches). The fixture record not moving
one byte across five scanner changes is the control: N5–N8 were Django-module or common-core
changes whose effect on the node-ts path is asserted to be nil, D-012 subtracts
nothing without a declaration, and the byte-identity is the proof.

## What the previous re-record found: N8

The first run with template line-scanning enabled (N7 Fix 3 stopped short-circuiting
`.env.example`-family files, so their *lines* are scanned now) flagged E-invoice's
`app/.env.prod.example:31` at `[proof]` tier:

    # redis://:<this>@redis:6379/0. Use a URL-safe value (no '@' or '/').

A comment documenting the URL format, with the literal `<this>` as the "password". A
false positive at `[proof]` tier is the worst kind — that tier's whole value is that a
match is a credential, not a guess (round-6b's Twilio note: flagging a non-secret
costs the check's credibility twice over).

**Fix (N8, this branch):** per RFC 3986, bare `<`/`>` cannot appear unencoded in a
valid URI — a connection string whose matched password contains either is
documentation, not a working credential. The veto is a validity argument, not a
heuristic: inserting `<` into a real connection string breaks it, so the
one-character-bypass class does not apply. Guards: a real
`redis://:realS3cretPass@host` in the same template still fires, and a percent-encoded
`%3C…%3E` password (a *valid* URI) still fires. Failing-first test carries the
E-invoice line verbatim.

E-invoice's remaining `[proof]` line — `app/docker-compose.prod.yml:70`, a connection
string with a real embedded password — is unchanged from both prior records and is a
true finding.

## D-012 in practice — the declaration on the repo that motivated it

SATURDAYS_site's `deployhub.yaml`:

    scanner:
      test_material:
        - path: frontend/scripts/drill
          reason: red-team / QA drill scripts; deliberate fake credentials

What the record shows, and what each part is there to prove:

- The check detail opens with `Downgrades claimed by deployhub.yaml:
  frontend/scripts/drill ("red-team / QA drill scripts; deliberate fake
  credentials", 10 findings)` — the claim is the **first thing** a reviewer reads,
  ahead of the findings, and it prints even when a declaration downgrades nothing.
- The 10 drill lines appear in their own **`Declared test material (downgrade claimed
  by deployhub.yaml, not blocking)`** section, each line carrying the path and the
  reason inline. They are not deleted, not merged into the auto-detected
  test-material tail, and not summarised away.
- The remaining **5 blocking heuristic lines** are the ones worth reading before a
  deploy: `Dockerfile:43` (a fallback `SECRET_KEY`) and four `.github/workflows/ci.yml`
  values. Both `.env` files still block at full tier — a declaration cannot reach
  them.
- The wizard raises one confirm question, `scanner.test_material.1.frontend-scripts-drill`,
  with **no default** — an unanswered claim is not an accepted one — and the accepted
  declaration is recorded in the manifest draft.

## D-011r revisit data — the full arc, and its closure

Counts are `core.secret-scan` evidence lines. The arc runs left to right: the first
fleet measurement (R4-10, before N5/N6 had been built), the post-N7 record, and this
one.

| Repo | `[heuristic]` blocking: R4-10 → post-N7 → now | `[proof]` | `.env` | declared |
|---|---|---|---|---|
| E-invoice | 2 → 1 → **1** | 1 | 0 | — |
| hr-saas-starter | 10 → 6 → **6** | 0 | 0 | — |
| SATURDAYS_site | 26 → 15 → **5** | 0 | 2 | **10** |
| TAKKO | — → 0 → **0** (16 at first scan) | 0 | 2 | — |
| `sample-node-site` | 0 → 0 → **0** | 0 | 0 | — |

**Fleet total: 38 → 22 → 12 blocking heuristic lines.** Of the 26 removed, **16 were
false positives** fixed by N5, N6, N7 and N8 — each with an adversarial pass behind it
— and **10 are declared**, printed with a reason and confirmed by the operator. Zero
were removed by demoting a tier: the gate refuses exactly what it refused in the first
measurement, minus findings that were provably wrong.

That closes D-011r's revisit question rather than triggering it (`DECISIONS.md`,
`D-011r-closed`). The reopen trigger was "noise high enough to train blocker-bypass";
what is left is a Dockerfile fallback key, four CI-workflow values, a prod-smoke env
file, an invite-token literal and two `.env` files across four production repos — a
list an operator reads, not one they learn to click past. Heuristic-only findings stay
at blocker tier.

**One honest note about this record.** `deployhub.yaml` was present in SATURDAYS_site's
working tree but not yet committed when the scan ran (`git status` showed it
untracked). The scanner reads the tree, which is the right thing for a deploy — the
tree is what ships — and it is the same limitation the `.env` wording change in N8
made explicit. It should be committed to the repo; nothing about the record changes
when it is.

## Follow-up findings status

1. ~~Generated-artifact directories~~ — closed by N6 (prior record).
2. ~~**Declared drill/QA trees**~~ — **CLOSED.** Ruled 2026-08-11, spec merged at
   `d87ee2a`, implemented at `8e7da8c` (D-012) across three adversarial rounds, and
   demonstrated on SATURDAYS_site above: 15 → 5 blocking, 10 declared. The prediction
   written into the previous record (15 → 5) is what the scan produced.
3. `_WEAK_SECRET_KEYS`-shaped values — unchanged, waiver-shaped, one instance.
4. **E-invoice `core.gitignore` warns at scan root** (project lives at `app/`) —
   unchanged, still a real gap, still open.
5. Self-scan flags the scanner's own detector vectors — unchanged, recorded.
6. **NEW: `django.allowed-hosts` does not recognize django-environ's
   `env.list("ALLOWED_HOSTS", …)`** as an env-driven assignment — fired on TAKKO,
   whose settings do exactly what the check's own fix_hint recommends. Warning tier,
   needs a look at `_check_allowed_hosts`.
7. **NEW: the blocker title "Committed secrets detected"** still makes the claim N7's
   Fix 4 removed from the evidence lines. One-word-scale fix, recorded not done.
