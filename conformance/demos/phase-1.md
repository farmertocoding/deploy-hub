# Phase 1 exit demo — recorded (P1-SCAN-DEMO)

**Date:** 2026-08-11 (second re-record) · **Commit under test:** branch
`demo-records-post-n7` on `d87ee2a` (N7 and the follow-up-2 spec merged; N8 built on
this branch) · **Recorded by:** Cowork session, cloud container,
`python -m hub scan <path>` — the same CLI entry point a user runs.

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
| `phase-1/scan-SATURDAYS_site.txt` | `~/SATURDAYS_site` @ `960a83e` (Django + frontend) | exit 1 — 1 blocker |
| `phase-1/scan-TAKKO.txt` | `~/TAKKO` @ `ea7b221` (Django + Vite monorepo) | exit 1 — 2 blockers |
| `phase-1/scan-sample-node-site.json` | in-repo `sample-node-site/` fixture | exit 0 — **byte-identical to the 2026-08-04 recording**, through N5, N6, N7 and N8 |

Real-repo copies were staged from the Mac as working-tree tarballs (minus `.git`,
`node_modules`, `.venv`, `__pycache__` and tool caches). The fixture record not moving
one byte across four scanner changes is the control: all four were Django-module or
common-core changes whose effect on the node-ts path is asserted to be nil, and the
byte-identity is the proof.

## What this re-record found: N8

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

## D-011r revisit data — post-N7 fleet measurement

Counts are `core.secret-scan` evidence lines; arrows show the R4-10 record → this one.

| Repo | `.env` present | `[proof]` | `[heuristic]` (blocking) | `[heuristic]` (test material) |
|---|---|---|---|---|
| E-invoice | 1 → **0**¹ | 1 | 2 → **1** | 2 |
| hr-saas-starter | 0 | 0 | 9 → **6** | 5 → 3 |
| SATURDAYS_site | 2 | 0 | 26 → **15** | 2 |
| TAKKO | — → **2** | 0 | — → **0** | — → 5 |
| `sample-node-site` | 0 | 0 | 0 | 0 |

¹ E-invoice's one "committed .env" line was `app/.env.prod.example` — a template, no
longer counted as an env file (N7 Fix 3); its lines are scanned instead (which is how
N8 was found). The evidence wording also changed fleet-wide: ".env file present in the
scan tree" — the scanner reads a tree and cannot see git, and TAKKO proved the old
"committed" claim false (its two `.env` files are gitignored and untracked).

**Reading it.** N7 removed 14 blocking heuristic lines fleet-wide (26% of the R4-10
total), every one a false positive class the fixtures could not show. What remains is
sharper than before: SATURDAYS_site's drill tree is now **10 of its 15** blocking
lines (was 20 of 26 — the other 10 were dotted-path/`var(--…)` false positives inside
the same directory), and it is still the single dominant noise class in the fleet.
The declared-test-material spec (`docs/spec-declared-test-material.md`, follow-up 2,
ruled 2026-08-11) should therefore expect **15 → 5** on SATURDAYS_site, not the
26 → 6 written before this re-record. The remaining non-drill lines on
SATURDAYS_site (Dockerfile fallback key, four CI-workflow values) and hr-saas-starter's
six (a prod-smoke env file with four real-shaped values, an e2e helper, a seed
command) are the kind an operator should actually read before deploying. **Still does
not trigger the D-011r reopen**; the case is unchanged, and stronger by 14 lines.

## Follow-up findings status

1. ~~Generated-artifact directories~~ — closed by N6 (prior record).
2. **Declared drill/QA trees** — ruled by Joseph 2026-08-11 (repo-declared
   `deployhub.yaml`, report shows every claimed downgrade); spec merged at `d87ee2a`;
   implementation pending, own branch, mandatory adversarial pass. Expectation
   updated above.
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
