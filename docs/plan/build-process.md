# Build Process — Agent Team, Quality Gates, and the Self-Improving Loop

**Project:** web deploy automation & monitor · **Applies to:** every build phase in `plan-addendum-2026-07-30.md` §I
**Companion docs:** `deploy-system-plan.md` (what to build) · `plan-addendum-2026-07-30.md` (authoritative patches) · this doc (how it gets built and verified)

Three standing rules govern everything below:

1. **Research, don't block.** When a decision surfaces mid-build, an agent researches primary sources and decides by stated criteria; the decision and its rationale land in `DECISIONS.md`. Joseph is only stopped for the short list in §6.
2. **The automation proposes; sensitive changes need a human merge.** Everything can be drafted, tested, and staged automatically — but this codebase holds fleet SSH access, so diffs touching the sensitive-path list (§5) always wait for Joseph's approval click.
3. **Nothing counts as done until it's green in CI and the review loop has converged** (two consecutive clean rounds, §4).

---

## 1. The agent team

Each phase is built by a team of specialist agents run from Cowork sessions (as subagents/workflows). Roles, not headcount — one session may play several; heavyweight roles fan out in parallel.

**Model assignment rule (set by Joseph, 2026-07-30; overridden 2026-08-20): Grok 4.6 writes code, makes decisions, and does QA.** Cheap mechanical roles drop to Haiku. The assignments below are the standing defaults — a session spawns the team with these unless Joseph overrides for a specific phase.

| Role | Model | Mandate | Engages |
|---|---|---|---|
| **Architect** | `grok-4.6` | Owns module boundaries (§D4 layout), interfaces (§D5), data-model changes; reviews any diff that adds a table, interface, or cross-app import. **Delegates the actual writing** of interface stubs/migrations to an Implementer (see the delegation rule below) | Phase start (design note) + every review round |
| **Implementer(s)** — 2–4 in parallel | `grok-4.6` | Writes the code, mockup-first (plain readable Python/JS, no premature optimization — per Joseph's standing preference); every remote effect goes through `Transport`/provider seams | Throughout |
| **Security expert** | `grok-4.6` | Reviews against the threat model (§6.8 + addendum §B): secrets handling, authz on every new endpoint/topic, injection surfaces, catalog entries (anything that runs as root on targets), sensitive-path diffs. Delegates any code it wants written | Every review round; **veto power** — a security finding is never waivable by another agent |
| **Quality engineer** | `grok-4.6` (strategy) → `grok-4.6` (test code) | Owns the four test tiers and decides what must be tested; the drift/kill-matrix/idempotency tests themselves are written by an Implementer instance since test code is code. Enforces regression-test-per-bug; maintains flake quarantine (cap: 5 tests) | Throughout + gates each round |
| **SRE reviewer** | `grok-4.6` | Reviews for the §C failure modes: lock correctness, backoff/brakes, backpressure, alert classification, runbook updates; owns drills staying green | Review rounds of Phases 2+ |
| **UX/design reviewer** | `grok-4.6` | Reviews every screen against §F specs: Finding-model consistency, empty/error/degraded states in simulation mode, action-tier friction (§F5), accessibility (no color-only status, dark mode) | Review rounds of any UI work |
| **Researcher** | `grok-4.6` | Fires on any `DECISION:` marker in code/notes or open item in addendum §J; primary sources only; writes `DECISIONS.md` entries | On demand — never blocks the build |
| **Adversarial verifier** | `grok-4.6` | Independently re-derives the phase's exit claims: re-runs the suite from clean checkout, tries to break the milestone by hand (wrong inputs, killed processes, concurrent operations), audits that waivers are honest | Final round of each phase |
| **Scribe** | `haiku` | Updates project docs, `DECISIONS.md` / `WAIVERS.md` entries, phase summaries, changelog. No judgment calls — it records decisions others made | End of each round/phase |
| **Triage bot** | `haiku` | Turns a failed nightly/e2e run into a filed issue with the full repro bundle attached (§5). Pure packaging, no diagnosis | On every red run |

**Delegation rule (reviewer and implementer are different sessions, even when they share a model).** Reviewer roles never write the code they review — when the Architect or Security expert wants code produced, it hands a written spec to an Implementer instance (`grok-4.6`) and reviews the result. Joseph's 2026-08-20 override put every judgment seat on `grok-4.6`, so the model assignment no longer differentiates the two roles; the session split is what preserves the property that the reviewer is never grading its own homework.

Findings from all reviewers funnel into one queue with one shape (mirroring the product's own §F2 Finding model): `{fingerprint, severity, file/screen, claim, suggested fix}`. Fingerprint = path + rule + normalized message, so the same nitpick can't recycle across rounds.

---

## 2. Phase workflow

Every phase in the roadmap runs the same cycle:

**① Design note (Architect, ~1 page).** What lands this phase, which interfaces/tables change, which addendum items apply, what the exit demo is. Open decisions get `DECISION:` markers → Researcher fires immediately, in parallel with early implementation.

**② Build.** Implementers work feature-by-feature; Quality engineer adds tests in the same change (a feature PR without its tests is an automatic round finding). Simulation-mode fixtures (§F8) are extended whenever a new UI state is introduced.

**③ Review rounds until converged** — protocol in §4.

**④ Exit gate.** All applicable test tiers green in CI · review loop converged · the phase's milestone demo performed end-to-end (recorded as a checklist, and from Phase 2 on, as the T3 live-e2e run — the demo *is* a test) · Adversarial verifier signs off · addendum/plan updated if the build taught us something (the docs stay true to the code, in the project).

**UPDATE 2026-08-02 (review3):** per review3 §Q4, the exit gate gains executable phase acceptance: each phase carries `tests/acceptance/test_phase_N.py` — each test a literal transcription of one milestone clause, marked `@pytest.mark.acceptance(phase=N)` and carrying the reqs it proves. `check.py --phase N` must pass: every phase-due requirement is `verified` (its tests green in the gating CI run) or has a `WAIVERS.md` line, and `verify: demo` reqs require a checked-in record under `conformance/demos/phase-N.md`. The Adversarial verifier's sign-off **explicitly re-runs the acceptance module from a clean checkout** — its "re-derives the exit claims" mandate becomes a command instead of judgment.

---

## 3. Live testing (the standing harness)

Defined fully in addendum §A7/§G; operationally:

- **Per push (CI, free tier):** lint/type/security static gates (ruff, mypy, bandit, pip-audit, eslint/tsc, log-scrubber grep) + T1 unit (<2 min) + T2 container-tier integration (~5–10 min: real sshd target, provisioner, pipeline steps, run-twice idempotency, lock and crash tests). **UPDATE 2026-08-02 (review3):** the static gates gain **shellcheck + shfmt + `bash -n` over `scripts/**`** (review3 §Q8), and a new per-push CI job, **`conformance-check`** (review3 §Q2): every phase-due requirement in `conformance/requirements.yaml` with `verify: test` must have ≥ 1 collected test bearing its `@pytest.mark.req(...)` marker — else red; every marker in the suite must resolve to a live registry id — unknown or retired id is red; the job emits `conformance/matrix.json` (req → test ids → last status) as a build artifact. A stale `text_hash` on a changed plan section = red (review3 §Q3), forcing the same PR that edits a doc to touch the registry.
- **Nightly:** T3 live e2e — real Multipass/KVM VM, real provision, real deploy of `sample-site/` into the dedicated **test DNS zone** with **LE staging**, asserting HTTPS + security headers + v2 deploy + rollback-within-60s, teardown in `finally` + reaper assertion that nothing survived; toxiproxy fault runs (SSH timeout mid-deploy → resume works); T4 Playwright (WebAuthn virtual authenticator + simulation-mode failure states). Nightly failures page nothing — they auto-file (§5) and appear in the morning digest. **UPDATE 2026-08-02 (review3):** per review3 §Q7 the T3 matrix gains a **second leg deploying `sample-node-site/`**, asserting readiness-gated cutover (traffic never switches before `ready`), named-volume survival across deploys, ws reconnect across a v2 deploy, and — for sites whose manifest declares a ws endpoint — a smoke-test substep that opens **one real `wss://` connection through Cloudflare+Caddy**, completes the upgrade, and receives one frame.
- **Scheduled drills (Beat jobs once the Hub exists, §G):** monthly Hub-down/site-survival, monthly restore-to-clean-container, weekly reaper drill. A drill that fails **or doesn't run** alerts like a down site. **UPDATE 2026-08-02 (review3):** the **monthly pager test** (review3 §V8) joins the scheduled-drills list — the one drill protecting the pager inherits the same rule: a skipped drill alerts like a down site.
- **Phase-5.5 partner-surface tests — UPDATE 2026-08-02 (review3, §Q9):** **T1:** Ed25519 signature vectors (valid/expired/replayed/mutated-body), idempotency, and quota unit tests run against **both** the intake verifier and the Hub's authoritative re-verifier **from one shared signature-vector file** — the two implementations structurally can't drift. **T2:** intake container + Hub poller integration — signed job → outbox → poll → Deployment created; tampered job → rejected + AuditEvent; **replayed job → rejected at the Hub even when the intake forwards it**. **T3:** a nightly partner-path leg — signed create-site + deploy of a catalog template into the test zone; webhook delivery asserted with a Standard-Webhooks reference verifier; per-partner kill switch asserted to stop containers and detach routes.
- **Credential wall (§B9):** the harness only ever holds test-plane credentials — separate cloud account with $10 budget alarm, test-zone-scoped Cloudflare token, per-run SSH keys, `HUB_TEST_MODE` refusing non-test zones. Prod vault material never enters CI.
- **Budget:** ~$5/month ceiling, stated so the nightly never gets quietly turned off.

---

## 4. The self-improving loop

The convergence requirement: **a phase closes only after two consecutive clean rounds.**

**One round = `make review-round`:**
1. **Full applicable test suite** (tiers per phase; nightly tiers may use the latest nightly result rather than re-running live infra per round).
2. **Static gates** (list above).

   **2.5. UPDATE 2026-08-02 (review3):** run **`conformance-check`** (review3 §Q5); its three outputs (uncovered reqs, stale reqs, phase-gate misses) are injected into the round's finding queue with **fingerprint = req id + state** — same triage rule as every finding (fix-with-regression-test or `WAIVERS.md` line; no silent dismissal), persisting across rounds until resolved. Reviewer agents receive `conformance/matrix.json` in round context, so "is this invariant actually tested" is a lookup.
3. **Agent review sweep** — the expert roles in §1 review the phase's full diff against `REVIEW_CHECKLIST.md`: a fixed, versioned checklist derived from the plan's own invariants — every playbook step idempotent (P3, verified by the run-twice test), every remote op through Transport, every endpoint through §4.5 serializers, every subscribe through `authorize_topic`, every state change published to its topic, no secret in logs/task-args/build contexts, every catalog entry has check+fix+rollback+version, every new UI state present in simulation mode, every new table in the retention/audit tables where applicable. **UPDATE 2026-08-02 (review3):** `REVIEW_CHECKLIST.md` becomes **partially generated** — every checklist item restating a plan invariant carries its req id inline, and a check asserts every such id is live in the registry (replacing hand-derivation with a mechanical, versioned one that catches checklist rot when reqs retire).
4. **Triage — every finding becomes exactly one of:** a fix committed **with a failing-first regression test**, or a one-line entry in `WAIVERS.md` (fingerprint + reason + date). Silent dismissal doesn't exist.

**Clean =** all gates green **and** zero new non-waived findings (new = fingerprint not seen in a prior round of this phase).

**Termination:** 2 consecutive clean rounds → phase exits. **Hard caps:** 6 rounds per phase, plus a wall-clock/VM-hour cap — if a phase hasn't converged by round 6, the findings are design problems, not polish; stop, write a design note, fix the design (this guard exists so "self-improving" can't become infinite churn).

**Anti-gaming guards (security expert's requirement):** the loop may never modify `REVIEW_CHECKLIST.md`, the gate scripts, or the waiver rules in the same round it is being judged by them — checklist changes are their own reviewed PR; and a round that "improves" by deleting checks is an automatic critical finding. The success criterion is frozen relative to the code being judged. **UPDATE 2026-08-02 (review3):** this rule extends **verbatim** to `conformance/requirements.yaml` — the registry is never edited in the round being judged by it.

**Mechanical teeth for soft process rules — UPDATE 2026-08-02 (review3, §Q6):** three rules previously enforced only by agent diligence become checks, each registered as a `PROC-` requirement so they can't be quietly removed: **(a)** "feature PR without tests = round finding" → a **diff-coverage gate** (diff-cover; advisory first, then blocking); **(b)** the flake-quarantine cap of 5 → a **marker count, red at > 5**; **(c)** "every bug fix carries its named regression test" → the auto-fix PR template **requires the named `test_issue_<n>_*` regression file**, verified by the path-glob check on any PR closing an issue.

---

## 5. Bug-fix automation

- **Detect:** any test/drill/e2e failure auto-files a GitHub issue carrying the full repro bundle — the P3/P4 machinery makes this nearly free: Deployment + step records + artifacts + logs + Transport call recording + target log excerpts + DNS state. The artifacts *are* the reproduction.
- **Fix (drafted, not shipped):** labeling the issue `auto-fix` runs a headless agent with the bundle and the instruction: *write the failing regression test first, then make it pass; touch nothing outside the implicated module.* Result = a PR; the full suite must pass before it's surfaced for review. Models follow §1: the fix is written by an Implementer (`grok-4.6`); the PR is reviewed by the relevant `grok-4.6` reviewer (a different session) before it reaches Joseph.
- **Merge policy:** ordinary paths — Joseph may enable auto-merge-on-green if he chooses after watching it for a while (propose-mode first, same philosophy as the scaler). **Sensitive paths — always human-merged, no exceptions:** `vault/`, auth/2FA/session code, `catalog/` entries, SSH transport, `providers/` (DNS/cloud adapters), CI workflow files, this process's own gate scripts. **UPDATE 2026-08-02 (review3):** the always-human-merged list gains **`scripts/**`** (the five root-running shell scripts, review3 §Q8), **`intake/**`** (the partner-facing surface, review3 §O2), and **`conformance/requirements.yaml`** (the requirements registry, review3 §Q1). One path-glob check enforces it.
- **Rule that makes bugs stay dead:** no bug fix merges without its named regression test (`test_issue_47_caddy_route_lost_on_reboot`) — checked in every review round.
- **Where the loop runs:** on the dev machine / CI runners. **Never on the Hub host** (crown-jewel rule §9.6.2 r1 — an agent with repo write access does not live on the machine holding fleet keys).

---

## 6. Decision protocol

Default: **decide and log, don't ask.** When a fork appears: an agent states the options + criteria → Researcher checks primary sources if facts are missing → decision made by the criteria → one entry in `DECISIONS.md` (date, decision, why, what would reverse it) → build continues. Reversible-by-default is the bar: prefer the option that's cheapest to undo.

Joseph is interrupted **only** for: real spend above the stated ceilings (~$5/mo tests, ~$1/mo KMS, target VM costs) · anything irreversible outside the test plane (prod DNS changes on real domains, deleting data, credential rotation on live systems) · security-expert vetoes on sensitive-path diffs (§5) · a phase that hit the round-6 cap and needs a design reset with product trade-offs. Everything else shows up in the digest and `DECISIONS.md`, reviewable after the fact — matching how the product itself treats its operator (propose mode, budget caps, audit trail).

---

## 7. Repo artifacts this process maintains

`REVIEW_CHECKLIST.md` (versioned; changes are their own PR) · `WAIVERS.md` · `DECISIONS.md` · `sample-site/` fixture app · the `hub-test-target` image definition · `hub-upgrade.sh` + break-glass runbooks (from Phase 2) · CI workflows (push ×2, nightly ×1) · simulation-mode seed fixtures. **UPDATE 2026-08-02 (review3):** the list gains the **five shell scripts under `scripts/`** (`harden-ubuntu.sh`, `update-cloudflare-ufw.sh`, `verify-hardening.sh`, `hub-upgrade.sh`, `server-watch.sh` — review3 §Q8) · **`sample-node-site/`** (the pnpm-monorepo CI fixture with its mutation set, review3 §Q7) · the **`conformance/` tree** (`requirements.yaml`, `schema.json`, `paths.yaml`, `check.py`, `demos/`, and the generated `matrix.json` — review3 §Q1–Q2). The project docs (`deploy-system-plan.md`, addendum, this file) are updated at each phase exit so a fresh session can always resume from the project alone.
