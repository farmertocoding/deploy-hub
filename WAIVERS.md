# WAIVERS.md — one line per waived finding: fingerprint + reason + date
# (build-process.md §4: a finding is a fix-with-regression-test OR a line here. Nothing else.)

WAIVED: .github/workflows+supply-chain+actions-pinned-by-tag — third-party actions pinned by major tag, not SHA; repo is local-only until D-001 GitHub move (Phase 2.5 at latest), at which point actions get SHA-pinned in the same PR that enables branch protection (2026-08-03)

# R4-9 (SPEC-gate-integrity.md §3.2 rule 4): `verify: checklist` reqs now have to name the
# gate that enforces them. These three have no gate on this tree. Per the spec, a waiver is
# the correct answer where no gate exists yet — inventing one to reach green is not. Each
# names what would retire the waiver. Fingerprint = req id + uncovered(no gate).
WAIVED: SEC-B4-REDIS-CROWN-JEWEL — uncovered(no gate): Redis is compose-internal with requirepass and JSON-pinned Celery serializers in docker-compose.yml today, but nothing asserts it — the compose file is read by no test and the §6B external port-scan of the Hub is a Phase-2 activity. Retire when a test parses docker-compose.yml for {no published redis port, requirepass set, CELERY_*_SERIALIZER == json} and this req becomes verify: test (2026-08-11)
WAIVED: PROC-REGRESSION-TEST — uncovered(no gate): build-process.md §5 puts this on the auto-fix PR template plus "a path-glob check on any PR closing an issue"; neither the template nor the check exists on this tree, and a PR-scoped check cannot run until the repo moves to GitHub (D-001). Retire with the PR-template + path-glob workflow in the D-001 move PR (2026-08-11)
WAIVED: PROC-SENSITIVE-HUMAN-MERGE — uncovered(no gate): the `sensitive-path-guard` job in push-checks.yml is a placeholder that only echoes "wire branch-protection + CODEOWNERS when repo moves to GitHub (D-001)"; naming it in `gate:` would make check.py green on a step that enforces nothing, which is the exact defect R4-9 exists to kill. Retire when CODEOWNERS + branch protection derived from conformance/paths.yaml land with D-001 (2026-08-11)

# Round-5 F1: a gate that enforces *something else* is not this requirement's gate. The
# review found SEC-69-NO-SECRETS-IN-EXHAUST reported `verified` on `make log-scrub`, which
# greps source files for `SECRET_KEY\s*=`; the requirement is about exhaust after write and
# names a CI scrubber over captured test output. `gate: log-scrub` removed from the registry;
# log-scrub itself kept as the source-scan gate it genuinely is.
WAIVED: SEC-69-NO-SECRETS-IN-EXHAUST — uncovered(no gate): the requirement says secrets never appear in logs, Celery task args or frontend responses after write, and that CI greps test output for plaintext markers; nothing on this tree checks any of those three surfaces. `make log-scrub` is a source scan for an assignment literal and enforces materially less, so claiming it as this req's gate reported a green that was not earned. Retire when a gate scans captured test output (pytest stdout/stderr and log capture) and Celery task kwargs for the vault's plaintext markers and this req becomes verify: test (2026-08-11)

# Round-5 F9: an unreachable check, recorded rather than left silent. Fingerprint = the
# artifact tree + why nothing reads it.
# R4-11 WI-3 (audit finding, 2026-08-11): a requirement read `verified` on one clause of
# three. Fingerprint = req id + the unproven clauses. The two markers that produced the
# green were removed rather than left claiming the whole text; the tests they were on
# still run. Retiring this waiver means restoring those markers. See DECISIONS.md D-009.
WAIVED: SCAN-M4-EXPOSURE-AUTH — blocker-escalation clause unimplemented AND the "both modules" clause false for django: (a) "Blocker when the wizard tags financial/personal data" has no code path — `scanner/modules/fallbacks.py::_check_exposure_auth` returns only ok/warning, and no wizard question anywhere tags data sensitivity (the full question set is site.domain, site.exposure, django.{domain,exposure,db,env.*}, node-ts.{service-package,dev-packages,data-dir,worker-threads,exposure,exclusive-upstream}, dockerfile.{domain,exposure,port,env}, static.{domain,exposure}), so there is no answer for an escalation to read and inventing the question was out of scope for a test-honesty PR; (b) the django module's `checks()` never calls `common_checks`, so `core.exposure-auth` never appears in a Django scan report — the warning clause holds for node-ts and the two fallbacks only. Proven today by tests/test_scanner_fallbacks.py::test_no_auth_indicators_fires_exposure_auth_warning, ::test_auth_indicators_silence_exposure_auth and tests/test_scanner_node_ts.py::test_issue_r4_11_node_ts_module_surfaces_the_exposure_auth_check (all unmarked while this waiver stands). Retire when a wizard data-sensitivity question exists, public-exposure + financial/personal + no-auth escalates `core.exposure-auth` to blocker with a marked test, and the django module emits the check — at which point the markers above go back on (2026-08-11)

WAIVED: conformance/demos/phase-1+unchecked-by-any-requirement — no phase-1 requirement is `verify: demo`, so the four artifacts under conformance/demos/phase-1/ are read by nothing: check.py only opens the paths a `demo:` key names (or the phase-N.md fallback), and the sole demo req is P0-WS-DEMO at phase 0. This is why R4-10 (the stale E-invoice scan record) did not surface when SPEC-gate-integrity.md §3.4 predicted it would — the content check landed, but no requirement points it at that tree. Retire by adding a phase-1 `verify: demo` requirement whose `demo:` names conformance/demos/phase-1/ in the registry PR (2026-08-11)
