# Phase 0 review-round log (build-process.md §4)

**Dates:** 2026-08-03 · **Final HEAD:** `90568c9` · **Reviewers:** Security, Architect,
Quality, UX (persistent agent sessions, rounds 1–6) + Adversarial verifier (final round).
Mechanical gates (`make review-round`: ruff, bandit, pip-audit, pytest, frontend
contract tests, conformance-check) green at every round's close.

| Round | New findings (fixed/waived) | Notes |
|---|---|---|
| 1 | 24 fixed, 1 waived | Headliners: unenrolled-session full API access → EnrollmentRequiredMiddleware; snapshot bypassed authorize_topic (found by 3 reviewers independently); plaintext recovery codes → hashed core.RecoveryCode; login-CSRF → csrf_protect + /me bootstrap; seq/history race → atomic Lua; prod SECRET_KEY hard-fail; check.py AST markers + structured waivers; EventsConsumer WS test suite; 7 UX failure-surfacing fixes. Waiver: CI action SHA-pinning deferred to D-001 GitHub move. |
| 2 | 8 fixed | WS plane joined the 2FA gate (4403); legacy otp_static plaintext path removed; recovery codes 16 chars (~79 bits); Lua branch put under test (fakeredis[lua] + backend parity); hydration unreachable state; sim pane append-only; clipboard failure state; confirm-relaunch busy. |
| 3 | 5 fixed | dump.rdb root-caused (missing .gitignore entry) and removed; terminal WS close codes stop the client retry loop; pane topic hygiene; recovery-code length regression test. |
| 4 | 2 fixed | Architect wire-verified that close-before-accept never delivers 4401/4403 to real browsers (daphne → HTTP 403 → 1006) → accept-then-close, re-verified on the raw wire (101 + close frame); pane-topics stale-closure → useRef. Security + Quality clean. |
| 5 | 1 fixed | Empty first snapshot erased the launch seed line (regressed the round-2 pending-feedback fix). Security/Architect/Quality clean. Also fixed out-of-band: a live-demo-caught client defect (syncTopic catch masked handler exceptions as snapshot failures) — demo then 4/4 stable. |
| 6 | 1 fixed | Quality empirically proved the round-5 "hygiene" topics-init made the post-reject WS path fail-open (subscribe honored after 4403 close) → explicit `authorized` flag, receive() fails closed, regression test to the reviewer's spec, closure re-verified empirically by the same reviewer. Security/Architect/UX clean; **Adversarial verifier: SIGN OFF** (clean-checkout suite, conformance-gaming probes, waiver audit, 5/5 break attempts held). |

## Convergence status — Joseph's call required (build-process.md §6)

The strict termination rule is **two consecutive fully-clean rounds**; the hard cap is
6 rounds. Rounds 4–6 each ended with 3 of 4 tracks clean and a single new finding in
the fourth, each fixed and verified within the round — but a *fully* clean pair was
not achieved before the cap. Per §6, hitting the round-6 cap is one of the enumerated
interrupts: the convergence call belongs to Joseph, not the loop.

State at the cap: every reviewer track individually reports convergence at `90568c9`
(Security clean 5–6, Architect clean 5–6, UX clean 6, Quality's round-6 finding fixed
and empirically re-verified closed), the Adversarial verifier signed off from a clean
checkout, and the finding *rate* fell 24 → 8 → 5 → 2 → 1 → 1 with no design-level
findings after round 2 — the round-6 cap's "findings are design problems" diagnosis
does not apply. Recommendation: accept convergence; do not reset the design.

## Residuals (disclosed, non-blocking)

- Compose-stack bring-up spot-check on the Mac (`docker compose up` — the recording
  environment had no docker daemon; identical code paths were exercised natively).
- CI action SHA-pinning rides the D-001 GitHub move (waived, dated).
- Orphaned otp_static tables in dev DBs (plugin removed from INSTALLED_APPS; inert).
