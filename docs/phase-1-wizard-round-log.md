# Phase 1 Build Record — Addendum: the `phase-1-wizard` branch

**Written:** 2026-08-09, by the session that did the work · **Covers:** commits
`c711732..6b422cf` (8 commits on `phase-1-wizard`, branched from `a345630`)
**Suite:** 99 → 237 backend + 10 frontend · **Registry:** 75 → 79 reqs, all phase-1
covered · **Round state at close:** rounds 1–3 done (6, 2, 4 findings), convergence
requires the next two rounds clean

This extends `phase-1-build-record.md`, which recorded the scanner half at `a345630`.
Everything below happened on a branch and is unmerged until Joseph merges it.

---

## 1. What was built, in commit order

**`c711732` — vault (SEC-69-ENVELOPE-ENCRYPTION).** §6.9 at rung ① of the KEK
ladder. Fresh AES-256-GCM DEK per write; AAD binds `kind|owner_type|owner_id` —
proven by performing the cut-and-paste attack in a test and watching GCM refuse, not
asserted in a comment. Decrypt failures raise `VaultDecryptError` and audit at
severity=security. No plaintext accessor on the model; reads go through
`service.get()`, which stamps and audits. `vault_init_keyfile` refuses to overwrite.
Rungs ②/③ are a backend-class swap (D-006).

**`9664ec3` — SSRF guard + rejected-input audit.** `validate_git_url`: allowlist
(https/ssh, ports 22/443, no userinfo-as-credential, no control chars), every
resolved address checked against loopback/RFC1918/CGNAT/link-local/ULA — ANY private
address rejects, not ALL. Known limit (DNS rebinding) documented in the docstring
with its structural mitigation — the Hub never clones (§B1/M1) — and a test that
fails if that note is deleted (D-007). `audited_exception_handler`: every DRF
ValidationError writes an AuditEvent with field PATHS and codes, never values;
X-Forwarded-For counted from the right per `HUB_TRUSTED_PROXY_HOPS`.

**`51a0d77` — wizard + materialization.** See §3 below for its unusual provenance.
Server-driven questions (base + module + gap), partial PATCH saves, secret answers
straight to the vault, append-only versioned Manifests, preflight refusals, the
V6 import boundary extended in the grep test.

**`3d412ae` — round 1** (§4 below). **`3d85e44` — D-008** (§5). **`bb3460e` —
round 2 + acceptance module.** Five milestone clauses as executable tests; CLI
parity tested as a literal subprocess with Django stripped from the environment.
**`0231430` + `6b422cf` — round 3 + F7-lite** (§§4, 6).

## 2. Decisions taken (all recorded in DECISIONS.md)

- **D-006** KEK ladder seam. **D-007** rebinding mitigation placement (resolve-and-pin
  at the target, Phase 2). **D-008** dev-fallback tier — Joseph's ruling, §5.
- **Env values never enter the manifest body** (round-1 F1): each manifest version
  owns ONE vault env bundle, plain + secret merged, AAD-bound to `site:version`.
  Consequence worth remembering: v3 deploys with v3's env exactly as frozen, and
  superseded per-answer Secrets can be deleted without breaking old manifests.
- **No fingerprint in wizard state** (round-1 F3): `changed_at` instead. Fingerprints
  remain in vault rows and audit — §7.4's precedent is key material, not passwords.
- **`manifest_current` instead of a warnings-diff** (F7): the true diff needs the
  prior report stored, which it isn't. The honest substitute is stated in the view
  docstring; if the diff is ever wanted, store report snapshots first.

## 3. The inherited commit — record this honestly

`51a0d77` was found already in the session clone: authored under the session's git
identity, timestamped after the session's own commits, reflog confirming local
origin — work from an earlier continuation of the same conversation whose transcript
was not available. Provenance was verified (bundle carried only `a345630`; no
remote), then the commit was treated as an **unreviewed implementer's diff** and put
through a full multi-track round rather than trusted or rebuilt.

Lesson for the process doc: agent sessions can resume with amnesia about their own
recent work. The defense that worked was the same one that catches everything else —
gates first, then a real review round. The round found six defects behind fully
green gates (§4), which would have shipped had the commit been trusted on gate
color alone.

## 4. Three rounds, twelve findings, one meta-lesson

**Round 1 (on `51a0d77`, 6 findings):**
- **F1 (security, HIGH):** plain-classified env values frozen into `Manifest.body`
  behind a substring heuristic — while the registry text for WIZ-V5-ONE-MANIFEST
  itself said "env NAMES only, never values." A marked test passed while the
  invariant was violated: the exact gap between *marked* and *proven*.
- **F2 (security, HIGH):** `site.domain` coerced as free text (2048 chars, control
  characters allowed) into a 253-char column feeding future Caddy/DNS consumers.
  Now `validate_domain` (RFC-1123, IDNA, rejects URLs/ports/wildcards/IP literals),
  validator cap pinned to the model's max_length by test.
- **F3 (security, MED):** fingerprint-as-confirmation-oracle in wizard state.
- **F4 (UX, MED):** refusals raised only `problems[0]` while the docstring bragged
  about gathering all of them; the 409 now carries the full list.
- **F5 (quality, MED):** GET deleted downgraded plaintext rows; two consecutive
  refreshes reported different problem codes. Detection is now read-only; scrubbing
  happens on writes, and the materialize refusal names what THIS call scrubbed.
- **F6 (SRE, LOW):** unlocked concurrent PATCH; also fixed a latent lock-ordering
  bug (version feeds the bundle AAD, so the lock must precede its computation).

**Round 2 (2 findings):** unattributed vault decryptions during materialization
(actor now threads through); D-008 had tests but no registry anchor
(SCAN-D008-DEV-FALLBACK-TIER added).

**Round 3 (4 findings + 1 audit) — three of five came from OUTSIDE the session:**
- **R3-1 (Joseph's machine):** the Makefile's bandit line omitted `wizard/` — `make
  lint` never scanned the new secret-handling app. The session never noticed because
  it ran bandit manually with `wizard` included: **the agent's invocation and the
  repo's gate had drifted apart, and only a second machine could see it.**
- **R3-2 (Joseph's machine):** Python floor (≥3.11) enforced nowhere a user hits it;
  a 3.10 venv installed cleanly then died in cryptic tomllib imports. conftest and
  manage.py now fail loud with the exact fix in the message.
- **R3-3 (audit):** inherited `#nosec B105` suppressions in `wizard/service.py`
  verified legitimate — dict keys named `secret_ref`, rationale documented in-file.
- **R3-4:** `make conformance` (inside `review-round`) still pinned `--phase 0` —
  the review gate had never evaluated a phase-1 requirement. Fixed.

**Meta-lesson, same shape three times:** F1's marked-but-unproven test, R3-1's
drifted gate, and the sim fixture in §6 that invented API fields — in each case a
green signal existed and was wrong. The countermeasures that worked were structural:
tests that perform the attack, contract tests pinned to generated schemas, and a
human running the real gates on a different machine.

## 5. D-008 (Joseph, 2026-08-09)

Committed dev-fallback secret + prod provably rejecting it (hard-fail `environ[...]`
subscript reassignment of the same NAME) → **warning-with-context**
(`django.secret-dev-fallback`), per-offender. Unguarded literals and `.get(default)`
stay blockers; a mixed project carries both. Rationale and reversal condition in
DECISIONS.md.

Writing the regression test against E-invoice's REAL shape
(`FIELD_ENCRYPTION_KEYS = ["<fernet>"]`) exposed that the original check missed
list literals entirely and lacked ENCRYPTION in `_SECRETISH` — the finding that
prompted the decision was caught in the recorded demo by entropy luck, not design.
Both fixed. **Open action:** the stored E-invoice demo says "1 blocker"; it will say
"1 warning" on re-scan. Re-record `conformance/demos/phase-1/scan-e-invoice` when
the repo copy is re-staged, or the artifact contradicts the scanner.

## 6. F7-lite + §F8 harness

`GET /api/v1/projects/` (tier counts, `manifest_current`), then
`frontend/src/Readiness.jsx`: list → three-tier report → wizard drawer →
materialize. §F9 held: symbol+word+count badges, staleness stamps, refusals render
every problem, secret inputs show "set on ⟨date⟩; leave blank to keep."

All five §F8 states reachable with zero backend (`?sim=...`), pinned to the
GENERATED zod schemas by `tests/sim-contract.test.ts` — which caught its first drift
on its first run, in the fixture its own author had just written (invented
`required`/`source`, omitted `secret`/`warnings`). Fixed against the serializer, not
by loosening the test. shadcn/§A8 remains deferred; the screen is deliberately in
the Phase-0 plain-React idiom.

## 7. Verification state at close

Joseph independently reproduced all gates on macOS / Python 3.13 (container: Linux /
3.12) and skimmed the sensitive paths (`vault/`, `wizard/materialize.py`,
`wizard/service.py`): **skim clean, 2026-08-09**. The two environment findings that
run produced are R3-1/R3-2 above.

## 8. Remaining for Phase 1 exit

**Sessions:** round 4 adversarial from a CLEAN checkout (deliberately a fresh
session — this one wrote what it would be reviewing), round 5 if clean; then the
gate ritual: demos recorded, `check.py --phase 1` green from the verifier's
checkout, `deploy-system-plan.md` synced verbatim into `docs/plan/`.

**Joseph:** walk the five sim states (that walk IS the §F8 human review); tarballs
for TAKKO + trading repo + E-invoice (demo scans; the private node-ts milestone; the
D-008 re-record); shape checks for `ecommerce` and `fb-group-poster` (**both ruled
not deploy candidates — Joseph, 2026-08-09** — so §V12's clause (a) only: framework,
serving process, which scanner module each lands on; ~15 min per repo once the
folders are connected, and the ONLY thing §J7 still owes); J-1 spike (shapes Phase
2's T2); merge this branch. The Phase 0 convergence call was accepted 2026-08-09
(see phase-0-round-log.md).

**Phase 2 deploy-target pool, now final:** TAKKO, SATURDAYS_site, hr-saas-starter.
TAKKO first — the only one already proven live end-to-end (the 0.5 spike), so Phase
2's milestone is "make the spike reproducible through the real pipeline," not "make
a new thing work."

**Known debts carried forward:** IDNA-2008 (`idna` package) deferred until a real
user hits a 2003/2008 difference; F6's concurrency pinned structurally (SQLite
ignores FOR UPDATE — real test needs Postgres at T2); frontend has no render tests
(contract tests only) until the tooling decision lands with shadcn.

## 9. Round 5 — the gate-integrity PR (branch `gate-integrity-r4`, 2026-08-11)

Round 4 found that the gates themselves were hollow and wrote the finding as a
buildable spec (`spec-gate-integrity-r4-8-r4-9.md`, project docs) rather than a
commit, per §4's anti-gaming rule and §1's delegation rule. This branch is that spec
built, by sessions that did not find the findings.

**Three commits.** `e2f62c4` — R4-8/R4-12 (CI calls `make`; bandit and log-scrubber
roots derived from the tree, not typed) and R4-9 (`check.py` grades run outcomes from
a SHA-pinned `conformance/run-report.json` instead of counting markers; `demo:`,
`gate:`, `text_hash`, retired-id detection, real status in `matrix.json`).
`15b87dd` — reworded a scanner `fix_hint` the widened scrubber hit, rather than
loosening the pattern. `80d7198` — the ten findings an independent review returned.

**What the first honest `--phase 1` run cost:** exactly the five reqs §3.4 predicted.
Two got real gates; four now carry dated waivers. The one worth re-reading is
`SEC-69-NO-SECRETS-IN-EXHAUST`: it was initially pointed at `make log-scrub`, and the
reviewer's finding F1 was that a source grep for an assignment literal enforces
materially less than "secrets never appear in logs, task args or responses". Waived
instead. That is the whole lesson of this branch in one requirement — the failure mode
is not a red gate, it is a green one nobody earned.

**Reviewer findings, all closed and re-verified by reproduction (not by report):**
a workflow could neuter a gate with `&&`/`|| true`/`continue-on-error` and the parity
test stayed green (F2); `gate:` resolved on a bare name, so a no-op target or an
echo-only step read as `verified` (F3); a whitespace-only demo artifact passed the
content check (F4); unpinned `text_hash` was silent (F5); markers on tests inside a
class reported `not-collected` (F6); `PYTEST_ADDOPTS` could forge `full_run` (F7);
the required-gate set was hand-typed a third time (F8); the phase-1 demo tree is
checked by nothing, which is why R4-10 never surfaced (F9, recorded as a waiver);
`log-scrub` had no escape hatch short of degrading product copy (F10).

**Open, deliberately.** `text_hash` pins only the first cited section of a
multi-section `source:`. The run report is bound to `git rev-parse HEAD`, not to the
working tree, so `make conformance` alone on a dirty checkout can pass on a tree the
report does not describe (unreachable in CI and in `review-round`, which order
`test` before `conformance`). Four re-review nits: `check.py` and the parity test have
two implementations of "CI invokes this gate" (N1); a wired-in no-op target still
resolves, now documented in three places (N2); the `if:` ban on gate steps will need
an escape hatch when D-001's PR-only `sensitive-path-guard` becomes a real gate (N3);
one tautological assertion and two reflow-brittle doc assertions (N4).

**State at hand-off:** 263 passed, ruff clean, `make lint`/`log-scrub` green,
`check.py --phase 1` exit 0 with six honest warnings. `requirements.yaml` carries zero
semantic edits across the branch — one removed `gate:` line, plus added `demo:`,
`gate:`, `text_hash:` keys and comments. Sensitive paths (CI workflows, gate scripts,
the registry) are human-merge-only: awaiting Joseph.

---

## 10. Round 6 — the gate follow-up (branch `gate-followup-n1-n3`, 2026-08-11)

Round 5 closed ten findings and wrote down five it deliberately did not. This branch
closes four of them, plus item 2 of the D-010 scanner follow-up list, which is the same
defect class as N1 and belonged with it. **N2 stays open** — a wired-in no-op target
still resolves as a gate — documented in three places, and it surfaced a second time
during this round (see below).

**Five commits on `8faa666`**, built by an Implementer and audited across **four
adversarial verification passes** by a session that wrote none of it. Each pass closed
what it found; the fourth found no active defect and called the iteration converged.

| commit | contents |
|---|---|
| `88d503f` | N1, N3, the two deferrals, D-010 item 2 |
| `c988796` | verifier findings F1–F9 |
| `84d145f` | re-verification finding N1 (`env: MAKEFLAGS`) + the fail-safe residuals |
| `3cb28b2` | GF-R8 — the Makefile refuses to start |
| `fe3f6fe` | fourth-pass nits |

### What was built

**N1 — one implementation of "does CI invoke this gate".** `check.py` and
`tests/test_gate_parity.py` had each grown their own answer, at different strictnesses:
check.py accepted the substring `make lint` anywhere in any `run:`, while the parity test
— since round-5 F2 — required a bare `make <target>`. So a workflow could neuter a gate
step and check.py would go on reporting the requirement it guards as `verified` while the
parity test failed. One rule, two declarations, drifting: R4-8's own defect reproduced
inside the machinery built to kill it. Both now import `conformance/gates.py`.

**N3 — the `if:` ban gets a declared escape hatch.** D-001's `sensitive-path-guard`
compares a branch to its merge base and a push has none, so under the blanket ban that
gate has no legal shape. `PR_ONLY_GATES` in the Makefile, beside the gate list; a
declared gate must still be a `review-round` prerequisite, still a bare `make <target>`,
still free of `continue-on-error:`, may use only `github.event_name == 'pull_request'`,
and must live in a workflow that triggers on `pull_request`. Ships empty.

**The run report is bound to the working tree, not to HEAD.** HEAD does not move when a
file is edited, which is the dangerous window exactly: watch a requirement go red, edit
the code, re-run the gate — which reads the working tree — and it grades a tree the tests
never saw. Probed by hand in both directions.

**`text_hash` pins every section a source cites.** `P0-AUTHZ-TOPIC` is §A1 (every
subscribe is authorised) *and* §D7 (the vocabulary it is authorised against); §D7 could
be rewritten with the pin green. Single-citation hashes are byte-identical, so 66 of 74
pins did not move and the 8 that did are exactly the 8 with two resolvable citations —
checked mechanically against `master`, not asserted.

**A malformed waiver line is a gate failure.** check.py's parser had no end anchor and
matched any parenthesised date in the line; the parity test's was anchored. They
disagreed about `SCAN-M4-EXPOSURE-AUTH`, whose real tail is prose — waived to one file,
unwaived to the other.

### What four verification passes cost, and the lesson

Pass one found **ten**: a `make --dry-run` step read as an honest gate invocation (F1);
a retired requirement that kept its `text_hash` crashed the gate (F2); the structural
"no second implementation" ban had four holes (F3); near-miss waiver ids stayed silent
(F4); broken steps were keyed by name alone (F5); the exemption's narrowness was social
(F6); a `workflow_dispatch`-only workflow resolved a gate (F7); duplicate waivers
collapsed (F8); a doc alias matched on a prefix (F9). Pass two found `env: MAKEFLAGS: -n`
— the same false green through the environment. Pass three found
`echo "MAKEFLAGS=-n" >> "$GITHUB_ENV"`, which appears in **no `env:` block anywhere**, so
no amount of workflow parsing can reach it.

**That is the meta-lesson of this round, and it is worth more than any single finding:
three passes in a row, each closing one input channel to `make` and surfacing the next.
Enumerating a tool's inputs is a losing game.** So the gates stopped playing it and
defend themselves: a parse-time `$(error)` at the top of the Makefile refuses to start
when make's own inputs carry a recipe-suppressing flag — and `$(error)` fires while the
makefile is *read*, which happens even under `-n`. Route no longer matters. The workflow
`env:` check stays as the early, reviewable signal that catches the honest mistake in the
diff, and no longer claims to be the last line of defence.

Both halves are held to the same variable list by a test that *runs make* rather than
grepping the Makefile for a name — because a name in a comment satisfies a substring
check while enforcing nothing, which is N1 in miniature.

### N2's cost, surfacing twice

An exemption naming every gate but a no-op one passes, because knowing a target is a
no-op is N2. Recorded rather than fixed, deliberately: it is one defect, and it is
already open.

### Open, deliberately

N2 (a wired-in no-op target still resolves as a gate). Outside the threat model by
construction, and no in-repo check can change either: deleting the Makefile guard (a
reviewable diff, caught by a test that runs inside `review-round`) and prepending a fake
`make` to `PATH` (an attacker who owns the runner). Five requirements' sources cite a
section nothing watches — each now named in a warning instead of hashed over in silence.

**State at hand-off:** 383 passed (was 296), ruff clean, `make lint` / `log-scrub` /
`test-frontend` / `check-generated` green, `check.py --phase 1` exit 0 with honest
warnings. `--print-text-hashes` byte-identical to `88d503f` across all 79 reqs; the
master-vs-branch pin diff is exactly the 8 intended entries. Gate machinery and the
registry are human-merge-only: awaiting Joseph.

## 11. N4 — the guard accused GNU make 3.81 of an override it cannot express (branch `fix-make381-guard-false-positive`, 2026-08-11)

Found live, during the round-6 merge itself: Joseph's first `make test` on the Mac was
refused with `carries [undefined]`, and after switching his shell to Homebrew make 4.x,
seven tests still failed — every test that spawns `make` as a subprocess found stock
`/usr/bin/make` on PATH, which is GNU make **3.81** (2006, the newest Apple ships).

The mechanism: `.SHELLFLAGS` does not exist before make 3.82, so on 3.81
`$(origin .SHELLFLAGS)` is the string `undefined`, and the guard's
`$(filter-out file default,…)` passed it straight into `_MF_BAD`. The guard did exactly
what round 6's own test warned against: "a guard that refuses everything is not a guard,
it is an outage" — on an entire platform, for honest invocations, with an accusation
naming no actionable input.

The repair is one word per origin check: `undefined` joins `file default` as a clean
origin. A variable that does not exist cannot carry an override — on 3.81 the feature is
absent (its `-c` is hardcoded), and on ≥3.82 the only route to an undefined `.SHELLFLAGS`
is an `undefine` in a makefile: this repo's own (reviewed), or an injected one via
`MAKEFILES` (already refused). A real override still arrives with origin `command line`
or `environment` and is still refused — held by a residual test.

The regression test does not require a 2006 make on the box: `undefine .SHELLFLAGS`
before `include`-ing the real Makefile puts the origin in exactly the state 3.81 reports
natively, and the guard evaluates while the makefile is read. (The shim restores the
variable after the include — simulation plumbing only, so the recipe itself can run on
modern make.) Verified failing against the unfixed Makefile, passing against the fix.

Per the broken-gate-repair rule (build-process.md, round 4), this rides its own branch
and touches nothing else: `Makefile` + `tests/test_gate_followup.py` + this entry.
Working-environment note recorded alongside: the Mac's PATH now fronts Homebrew make
via gnubin in `~/.zshrc`, but any tool that constructs its own PATH may still find 3.81
— after this fix, that is fine.

## 12. 2026-08-20 — Grok 4.6 session (model assignment, three scanner follow-ups, J-1)

Not a numbered review round: the loop has been in finding-fix mode since round 7, the
round-6 cap already spent D-012, and this session did not re-derive the whole Phase 1
diff from a clean checkout. Recorded so the next session does not re-do it.

**Model assignment (D-014, `b5dfac5`).** fable/opus replaced with grok 4.6. Delegation
rule is a session split. Hashes for PROC-REGRESSION-TEST and PROC-SENSITIVE-HUMAN-MERGE
re-pinned.

**Scanner follow-ups, both listed open on the 2026-08-12 demo record:**

- `cbe040d` — `_top_assigns` sees `AnnAssign` (TAKKO's `env.list` line); empty base +
  prod override is configured, not a warning; secret-scan titles no longer say
  "committed". P1-SCAN-DEMO re-recorded (schema_version 2; SATURDAYS_site shows
  `core.declaration-file`, not an acceptance bucket).
- `95e803b` — `core.gitignore` walks up from `manage.py` when the scan root has no
  file. E-invoice 0 warnings.

**J-1 (D-015, `42ee231`).** T2 = sshd+systemd container, inner docker on vfs.
Multipass is not needed sooner. Probe record `docs/j1-t2-fidelity-spike.md`.

**Mechanical gates this session (venv on PATH):** ruff clean, log-scrub green,
`make test-frontend` 140/140, `make check-generated` green. `pytest` 946 passed with
the APFS-illegal-byte tests deselected; 8 failures remain, all host-environment
(GNUMAKEFLAGS on this make, N4 3.81 shim, `.DS_Store` in the mutation cache watch
list, macOS symlink loops). None of them moved with the scanner diffs. Mutation gate
not re-run.

**Not a clean round.** The 8 Mac failures predate this session; mutation was skipped;
no full adversarial re-derivation of Phase 1. Next session that wants a convergence
counter to advance runs `make review-round` on a Linux/cgroup runner (or with Homebrew
make on PATH the way N4 recorded) and a fresh checkout.

**Still open for Phase 1 exit:** two consecutive clean rounds.

## 13. 2026-08-20 — goal review sweep (reviewer ≠ implementer)

Reviewer session against HEAD `b8b4565` vs REVIEW_CHECKLIST.md. Queue in the
goal scratch (`finding-queue.md`). Five findings; all addressed. **Not a
clean Phase 1 round** (host pytest fingerprints unchanged; mutation not
re-run). Ordinary-path work merged to master.

| id | sev | fingerprint | outcome |
|---|---|---|---|
| F-1 | bug | Readiness.jsx PATCH unwrapped qid map | **fixed** `fb5d5b0` — `{answers: draft}`; Django PATCH of that body 200; `wizardSaveBody` spy pin |
| F-2 | bug | wizard 400 nested strings not `{field:[{code,message,hint}]}` | **fixed** `fb5d5b0` — `{errors: …}` via `audited_exception_handler`; codes from `coerce_answer` kept |
| F-3 | bug | wizard env secrets share site AAD | **fixed** `9d1b0f2` — `owner_id=f"{pk}:{qid}"`; same-site crypto copy raises `VaultDecryptError`. Files were `wizard/service.py` + tests (not `vault/**`); merged as ordinary |
| F-4 | bug | sim.js still `Committed secrets detected` | **fixed** `fb5d5b0` — regenerated; `test_sim_js_secret_scan_titles_match_the_scanner` |
| F-5 | suggestion | wizard omitted from import-rule APPS | **fixed** `fb5d5b0` — `"wizard"` on both APPS lists |

Mechanical (venv on PATH): ruff, log-scrub, frontend, check-generated green at
the start of the sweep. Pytest 947 passed / 15 failed, all 15 host fingerprints
from §12. After merge: F-1–F-5 named tests 8/8 python, 52 frontend including
the save-body spy.

Silent drop: none. No WAIVERS.md lines.

## 14. 2026-08-20 — §J7 inventory complete (ecommerce + fb-group-poster)

Not a numbered review round. The folders named in §8 were connected; Joseph's
2026-08-09 ruling still holds (neither is a deploy candidate), so this is
§V12 clause (a) only.

| folder | framework | serving | scanner module |
|---|---|---|---|
| `ecommerce` | none — leftover Python 3.10.6 venv with Django 4.2.2 in site-packages, no `manage.py` | none | none (`detect_modules == []`) |
| `fb-group-poster` | Django 4.2.2 startproject (`fbposter` + `posts`), sqlite, templates | WSGI (`manage.py runserver` locally; unused startproject `asgi.py`) | `django` (gunicorn / `fbposter.wsgi`) |

**No third framework lurks.** Module list stays django + node-ts + fallbacks.
Phase 2 deploy-target pool unchanged: TAKKO, SATURDAYS_site, hr-saas-starter.

Pins (failing-first on a tree that already behaved this way — characterization
of the live folders, not a scanner-module edit; `scanner/modules/**` untouched):

- `tests/test_scanner_django.py::test_j7_a_venv_with_django_installed_is_not_a_django_project`
- `tests/test_scanner_django.py::test_j7_startproject_asgi_py_without_channels_stays_wsgi`

Full tables: `project-inventory.md`. **Still open for Phase 1 exit:** two
consecutive clean `make review-round`s (not claimable on this Mac host).

## 15. 2026-08-20 — re-review of F-1..F-5 landing (reviewer ≠ implementer)

Reviewer session against `b8b4565..c3d0ef4` vs REVIEW_CHECKLIST.md. F-1 through
F-5 held. One residual on the F-2 renderer.

| id | sev | fingerprint | outcome |
|---|---|---|---|
| F-6 | bug | Readiness.jsx wizard400Text ignores data.detail | **fixed** — status 0 / 501 Save now show `data.detail`; 400 field map unchanged |

`save()` used the §4.5 field-map renderer for every non-200. Dead socket
(status 0, `data.detail` from `api.js`) and sim `notCovered` 501 rendered an
empty red line. `materializeOutcome` already kept the detail. Failing-first:
`wizard-flow.test.ts` harness of `save()` with those two payloads; then
`wizard400Text(data, status)` returns the field map when `data.errors` is
non-empty, else `data.detail || HTTP ${status}`. Ordinary path (`frontend/`).

Silent drop: none. No WAIVERS.md lines. Not a clean Phase 1 round.

## 16. 2026-08-20 — demo follow-ups 3 and 5 (N5 leftover + self-scan)

The 2026-08-20 demo record left two items "waiver-shaped" / "recorded" with
no `WAIVERS.md` line. That is silent drop. Closed as:

| id | fingerprint | outcome |
|---|---|---|
| F-7 | django.secret-key-literal + `_WEAK_SECRET_KEYS` denylist | **fix on branch** `p1-scan-fp-denylist-and-url-interp` (`dabf998`). E-invoice `prod.py` assigns a membership denylist of placeholders; N5's test named the identifier in a docstring and never assigned it. Failing-first, then skip WEAK_* names unless a literal is high-entropy. **Not merged:** `scanner/modules/**` is human-merge-only. Live check after the fix: E-invoice blocker is only `DEV_FALLBACK_ENCRYPTION_KEY` (a real Fernet in base.py). |
| F-8 | core.secret-scan + `redis://:{VAR}@` f-string | **same branch.** Hub `hub/settings/base.py` interpolates `REDIS_PASSWORD` into `redis://:{var}@host`; proof-axis userinfo treated `{REDIS_PASSWORD}` as a password. `_looks_interpolation` vetoes `{ident}` / `${ident}` / `$ident`. Real `redis://:realS3cretPass@` still blocks. **Not merged** (same glob). |
| F-9 | core.secret-scan + self-scan detector vectors | **waived** `WAIVERS.md` 2026-08-20. Scanning this repo flags comment examples in `fallbacks.py` and fixture values under `tests/` / `scripts_dev/`. Not a customer-tree finding. D-012 parked. |

Silent drop: none. **Still open for Phase 1 exit:** two consecutive clean
rounds; Joseph merge of `p1-scan-fp-denylist-and-url-interp`. Not a clean
round. Phase 2 not started.
