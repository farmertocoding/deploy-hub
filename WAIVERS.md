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
