# Phase 1 exit demo — recorded (P1-SCAN-DEMO)

**Date:** 2026-08-12 (fourth re-record, SATURDAYS_site only) · **Commit under test:**
branch `r7-enforce-declaration-acceptance` on `8a9572e` (round-7 R7-1 veto: no
acceptance, no downgrade) · **Recorded by:** Cowork session, cloud container,
`python -m hub scan <path>` — the same CLI entry point a user runs.

**This re-record changes one artifact, and it changes it because the previous record
described a control that did not exist.** See *The round-7 correction* below: the D-012
section of the 2026-08-12 record said the declared lines were "confirmed by the
operator". They were not — the confirm was raised and its answer was read by no code, so
the downgrade was applied at scan time from a file the scanned repo writes. Joseph's
ruling on the security expert's veto is that a declaration is a **request**, and this
record is the first one taken with that enforced.

SATURDAYS_site's record moves in two places: the third bucket's section header now says
the downgrade was *requested* and blocks until accepted, and the blocker `fix_hint`
carries the declaration legend it never had (R7-8). Its **tier does not move** — it
reported `blocker` before and reports `blocker` now, for the reason given below. The
other three fleet records and the fixture JSON were re-run and are **byte-identical** to
the 2026-08-11 recording, verified with `cmp`: no repo without a declaration moved, which
is the control for a change that must reach exactly one mechanism.

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
| `phase-1/scan-SATURDAYS_site.txt` | `~/SATURDAYS_site` @ `960a83e` + `deployhub.yaml` (Django + frontend) | exit 1 — 1 blocker, **10 lines declared and still blocking, pending acceptance** |
| `phase-1/scan-TAKKO.txt` | `~/TAKKO` @ `ea7b221` (Django + Vite monorepo) | exit 1 — 2 blockers |
| `phase-1/scan-sample-node-site.json` | in-repo `sample-node-site/` fixture | exit 0 — **byte-identical to the 2026-08-04 recording**, through N5, N6, N7, N8, D-012 and R7-1 |

Real-repo copies were staged from the Mac as working-tree tarballs (minus `.git`,
`node_modules`, `.venv`, `__pycache__` and tool caches). The fixture record not moving
one byte across six scanner changes is the control: N5–N8 were Django-module or common-core
changes whose effect on the node-ts path is asserted to be nil, D-012 subtracts
nothing without a declaration, R7-1 adds nothing without one (its new `acceptance`
field is omitted from the serialized check rather than written as `null`, precisely so
this file could not move), and the byte-identity is the proof.

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

## The round-7 correction — what the previous record claimed, and why it was wrong

**The previous version of this section was not accurate, and the inaccuracy is the
finding.** It said the 10 drill lines were "printed with a reason and confirmed by the
operator", and that "the accepted declaration is recorded in the manifest draft". Both
sentences described a control that no code implemented. Three reviewers found it
independently in round 7; the security expert vetoed (R7-1) and Joseph ruled on
2026-08-12: **no acceptance, no downgrade.**

What was actually shipping:

- the confirm question was raised, but it was not in `REQUIRED_IDS` — it could not have
  been, since its id carries the declared path and that set is static — so leaving it
  unanswered blocked nothing;
- its answer was written to `manifest_draft["module_answers"]` and **read by no code in
  the repo**. Answering `False` produced exactly the deploy that answering `True`
  produced;
- the manifest's `declared_test_material` was copied straight out of the scan draft, so
  the append-only audit artifact asserted an acceptance that may never have happened;
- meanwhile the tier drop was applied at **scan time**, from `deployhub.yaml` — a file
  the scanned repo writes. A repo was downgrading its own blockers, and the operator
  step the D-012 ruling paid for that trust with was decorative.

The `fix_hint` on that path told the operator that "refusing it is how you say the
declaration is wrong", which was false at the time it was printed. It is true now.

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
  Unchanged by round 7: this half of D-012 was always real.
- The 10 drill lines appear in their own section, still labelled with the path and the
  reason inline, still not deleted, merged or summarised away. Its header now reads
  **`Declared test material (downgrade requested by deployhub.yaml — blocks until you
  accept it in the wizard)`**. The old wording ended `, not blocking)` — an assertion
  about the operator's answer, printed by the one component that holds no answers.
- The **10 declared lines still count toward blocking.** `core.secret-scan` reports
  `blocker`, as it did before, and publishes a machine-readable
  `acceptance: {questions: [scanner.test_material.1.frontend-scripts-drill],
  blocking_only_declared: false}` that the wizard's preflight gates on.
- `blocking_only_declared` is **false** for this repo, and that is worth saying plainly:
  SATURDAYS_site has two `.env` files in the tree, so accepting the drill declaration
  will **not** let it deploy. Acceptance can only ever clear findings the declaration
  itself downgraded; a `[proof]` line, a `.env` file or an undeclared heuristic line
  makes the check unconditional however the operator answers. The five other blocking
  heuristic lines — `Dockerfile:43` (a fallback `SECRET_KEY`) and four
  `.github/workflows/ci.yml` values — are unchanged and still the ones worth reading
  before a deploy.
- The blocker `fix_hint` now carries the declaration legend (R7-8). It never did:
  the explanation of `[heuristic, declared: …]` lived only on the warning tier, and
  this repo — the one the whole feature was built for — has always reported at blocker
  tier, so its operator read the labels and the `Downgrades claimed` header with
  nothing anywhere on the report saying what either meant.
- The wizard raises one confirm question, `scanner.test_material.1.frontend-scripts-drill`,
  with **no default** — an unanswered claim is not an accepted one, now pinned by a test
  (R7-11) rather than only asserted in prose. It is **required**: unanswered refuses
  materialization in the same shape as a missing `site.domain`. The frozen manifest
  records what was answered — accepted declarations under `declared_test_material`,
  refused ones under `declared_test_material_refused`, because an audit trail that drops
  the refusals is the same defect pointing the other way.

## D-011r revisit data — the full arc, and its closure

Counts are `core.secret-scan` evidence lines. The arc runs left to right: the first
fleet measurement (R4-10, before N5/N6 had been built), the post-N7 record, and this
one.

| Repo | `[heuristic]` **undeclared** blocking: R4-10 → post-N7 → now | `[proof]` | `.env` | declared (blocking until accepted) |
|---|---|---|---|---|
| E-invoice | 2 → 1 → **1** | 1 | 0 | — |
| hr-saas-starter | 10 → 6 → **6** | 0 | 0 | — |
| SATURDAYS_site | 26 → 15 → **5** | 0 | 2 | **10** |
| TAKKO | — → 0 → **0** (16 at first scan) | 0 | 2 | — |
| `sample-node-site` | 0 → 0 → **0** | 0 | 0 | — |

**No number in this table moved in round 7, and the last column's meaning did.** The
heading used to be `declared`, next to a paragraph calling those 10 lines
"confirmed by the operator"; they were not confirmed by anybody, and until an operator
accepts the declaration they block like the other five. SATURDAYS_site's blocking
heuristic count is therefore **15, not 5**, on a report nobody has answered — 5
undeclared plus 10 awaiting acceptance — and it drops to 5 the moment the confirm is
answered `True`. What was measured has not changed; what it costs before someone signs
for it has.

**Fleet total: 38 → 22 → 12 undeclared blocking heuristic lines, or 22 counting the 10
awaiting acceptance.** Of the 26 lines removed since the first measurement, **16 were
false positives** fixed by N5, N6, N7 and N8 — each with an adversarial pass behind it.
Zero were removed by demoting a tier, and after round 7 that is true without an
asterisk: the remaining 10 are not removed at all, they are held against an operator's
answer.

That still closes D-011r's revisit question rather than triggering it (`DECISIONS.md`,
`D-011r-closed`), and round 7 makes the closure stronger rather than weaker: the reopen
trigger was "noise high enough to train blocker-bypass", and the bypass that most
deserved the name was the one this record used to describe approvingly — a repo quieting
its own findings with a file it ships. What is left is a Dockerfile fallback key, four
CI-workflow values, a prod-smoke env file, an invite-token literal and two `.env` files
across four production repos, plus one drill tree awaiting a yes or a no. Heuristic-only
findings stay at blocker tier.

**One honest note about this record.** `deployhub.yaml` was present in SATURDAYS_site's
working tree but not yet committed when the scan ran (`git status` showed it
untracked). The scanner reads the tree, which is the right thing for a deploy — the
tree is what ships — and it is the same limitation the `.env` wording change in N8
made explicit. It should be committed to the repo; nothing about the record changes
when it is.

## Follow-up findings status

1. ~~Generated-artifact directories~~ — closed by N6 (prior record).
2. ~~**Declared drill/QA trees**~~ — **CLOSED, and re-opened and re-closed once in
   between.** Ruled 2026-08-11, spec merged at `d87ee2a`, implemented at `8e7da8c`
   (D-012) across three adversarial rounds. The previous record closed it on the
   strength of "15 → 5 blocking, 10 declared", which was the arithmetic of a downgrade
   nobody had authorized — see *The round-7 correction* above. Closed again here on the
   ruling that a declaration is a request: 15 blocking until the operator answers, 5
   after they accept, and the difference is an act with a name attached to it.
3. `_WEAK_SECRET_KEYS`-shaped values — unchanged, waiver-shaped, one instance.
4. **E-invoice `core.gitignore` warns at scan root** (project lives at `app/`) —
   unchanged, still a real gap, still open.
5. Self-scan flags the scanner's own detector vectors — unchanged, recorded.
6. **NEW: `django.allowed-hosts` does not recognize django-environ's
   `env.list("ALLOWED_HOSTS", …)`** as an env-driven assignment — fired on TAKKO,
   whose settings do exactly what the check's own fix_hint recommends. Warning tier,
   needs a look at `_check_allowed_hosts`.
7. **The blocker title "Committed secrets detected"** still makes the claim N7's
   Fix 4 removed from the evidence lines — the scan reads a tree and cannot see git.
   Unchanged and still open. Round 7 added a second blocker title for the
   declared-only case ("Secrets in a declared tree — your acceptance is required"),
   which is accurate; this one is the same one-word-scale fix, still recorded not done.
