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
D-008 re-record); shape checks for `ecommerce` (deploy candidate? TBC) and
`fb-group-poster` (shape only — not a candidate); J-1 spike (shapes Phase 2's T2);
the still-open Phase 0 convergence call; merge this branch.

**Known debts carried forward:** IDNA-2008 (`idna` package) deferred until a real
user hits a 2003/2008 difference; F6's concurrency pinned structurally (SQLite
ignores FOR UPDATE — real test needs Postgres at T2); frontend has no render tests
(contract tests only) until the tooling decision lands with shadcn.
