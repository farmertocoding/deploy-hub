# ── the gates defend themselves ─────────────────────────────────────────────
#
# make takes its own flags from `MAKEFLAGS`/`GNUMAKEFLAGS` as well as from argv, and
# `-n` prints a recipe without running it while still exiting 0; `-i` ignores its
# errors; `-q` runs nothing at all; `-t` touches instead; `MAKEFILES=x.mk` can inject a
# `SHELL := /bin/true`. Every one of those turns a gate into a step CI reaches and does
# not run — the same false green as `continue-on-error: true`, with nothing to see in
# the workflow.
#
# Three verification passes each closed one channel and surfaced the next: argv flags
# (round-6 F1), then `env:` at step/job/workflow scope (N1), then `echo MAKEFLAGS=-n >>
# $GITHUB_ENV` from an earlier step, which appears in no `env:` block anywhere and which
# no amount of workflow parsing can see. Enumerating make's inputs is a losing game, so
# this stops playing it: whatever route the flag took, make refuses to start. The
# workflow-level checks in conformance/gates.py stay as the early, reviewable signal —
# they catch the honest mistake in the diff; this catches the rest.
#
# `$(error)` fires while the makefile is being read, which happens even under `-n`.
#
# NOT covered, deliberately, and it costs nothing today: the `-o`/`--old-file`/`-W`
# family never survives into `$(MAKEFLAGS)`, so it cannot be caught here. It also cannot
# skip a `.PHONY` target, and every gate is phony — while from argv it is caught by the
# bare-`make <target>` rule in conformance/gates.py. If a gate ever stops being phony,
# that changes: re-read this comment then.
_MF_HEAD := $(firstword $(MAKEFLAGS))
_MF_SHORT := $(if $(findstring =,$(_MF_HEAD)),,$(filter-out -%,$(_MF_HEAD)))
#
# `SHELL=` is the one input that does NOT survive into `$(MAKEFLAGS)` as a word — make
# absorbs it into the variable — so it is caught by its origin instead. It is also the
# nastiest of them: `MAKEFLAGS=SHELL=/bin/true` runs every recipe through `true`, so
# the gate prints nothing and exits 0.
_MF_BAD := $(strip \
	$(foreach c,n i q t o,$(findstring $(c),$(_MF_SHORT))) \
	$(filter --dry-run --just-print --recon --ignore-errors --question --touch,\
		$(MAKEFLAGS)) \
	$(filter --eval% .SHELLFLAGS=%,$(MAKEFLAGS)) \
	$(filter-out file default,$(origin SHELL))$(filter-out file default,$(origin .SHELLFLAGS)) \
	$(MAKEFILES))
ifneq ($(_MF_BAD),)
$(error refusing to run: make's environment carries [$(_MF_BAD)], which suppresses or \
fakes recipes — a gate that does not execute is not a gate. Clear MAKEFLAGS, \
GNUMAKEFLAGS and MAKEFILES, and drop dry-run/ignore-errors/question/touch flags and \
any SHELL or .SHELLFLAGS override. To inspect what a target would do, read the Makefile.)
endif

.PHONY: dev test test-frontend lint conformance review-round generate-client check-generated \
	log-scrub py-roots

# The Python packages every source-scanning gate must cover, derived from the tree rather
# than typed out: a top-level directory with an __init__.py, minus the test suite itself.
# R4-12 (SPEC-gate-integrity.md §1) is exactly what a hand-typed list costs — `wizard/`
# landed and both the bandit list and the log-scrubber list were missed, separately.
# SPEC-gate-integrity.md §2.1 asks for `tests/roots.py::python_roots()`; that module does
# not exist on this tree, so the derivation lives here and
# tests/test_gate_parity.py::test_issue_r4_12_scan_scope_is_derived_from_the_package_roots
# asserts this list still equals the tree's packages. Import it from there once it lands.
PY_ROOTS := $(shell python3 -c "import pathlib; print(' '.join(sorted(p.name for p in pathlib.Path('.').iterdir() if p.is_dir() and (p / '__init__.py').exists() and p.name != 'tests')))")

# Printed so a test can check the scan scope without re-implementing the derivation.
py-roots:
	@echo $(PY_ROOTS)

# Gates that cannot run on a plain `push`, and may therefore carry
# `if: github.event_name == 'pull_request'` on their CI step (round-5 N3).
#
# Round 5 banned `if:` on any gate step outright (F2), which is right for every gate
# that CAN run on a push — a gate CI is allowed to skip does not guard the branch. But
# D-001's `sensitive-path-guard` compares a branch against its merge base, and a push
# event has no merge base to compare against: run it unconditionally and it is
# meaningless, guard it and the parity check calls it neutered. So the exemption is
# declared here, next to the gate list itself, and it is narrow — a target named here
# must still be a `review-round` prerequisite, must still be invoked as a bare
# `make <target>`, may still not carry `continue-on-error:`, may use only the one
# PR-scoping expression above, and must live in a workflow that triggers on
# `pull_request`. See conformance/gates.py::gate_step_violations.
#
# EMPTY TODAY, deliberately: `sensitive-path-guard` in push-checks.yml is still the
# D-001 placeholder that only echoes, and invokes no make target. This line is where it
# lands when it becomes real; adding a name here is a reviewable edit in the same diff
# that spends the exemption.
PR_ONLY_GATES :=

# §4.5 pipeline: serializers → OpenAPI → generated TS types + zod schemas (D-002).
# Regenerate after any serializer change; check-generated asserts the mirror is not stale.
generate-client:
	python manage.py spectacular --file frontend/src/api/openapi.yaml --settings=hub.settings.dev
	cd frontend && npx openapi-typescript src/api/openapi.yaml -o src/api/types.ts
	cd frontend && npx openapi-zod-client src/api/openapi.yaml -o src/api/zod.ts \
		-t node_modules/openapi-zod-client/src/templates/schemas-only.hbs --export-schemas

# Generated mirror must match the committed serializers (stale = red, §4.5).
check-generated: generate-client
	git diff --exit-code frontend/src/api/ || (echo "generated client is stale — run 'make generate-client' and commit" && exit 1)

dev:
	docker compose up --build

test:
	pytest -q

test-frontend:
	cd frontend && node --import tsx --test "tests/*.test.ts"

lint:
	ruff check .
	bandit -q -c pyproject.toml -r $(PY_ROOTS)
	pip-audit -r requirements.txt || true   # advisory until Phase 1; blocking after

conformance:
	python conformance/check.py --phase 1

# Plaintext secrets must not sit in source. Command carried over verbatim from the
# push-checks step this replaces; the only change to it is scope, which is now
# $(PY_ROOTS) instead of the four packages that existed when it was written — it had
# never looked at wizard/ or scanner/ (R4-12).
#
# NOT the gate for SEC-69-NO-SECRETS-IN-EXHAUST (round-5 F1). That requirement is about
# exhaust after write — logs, Celery task args, API responses — and names a CI scrubber
# over captured *test output*. This greps *source files* for an assignment literal, which
# is materially less; the requirement is waived in WAIVERS.md until the real gate exists.
# This target stays because a plaintext key committed to source is worth catching anyway.
#
# TWO EXEMPTIONS, both deliberate, both greppable:
#   1. `settings`  — any path containing it. Settings modules read the key by name; that
#                    is the correct place for the assignment to appear.
#   2. `# log-scrub: allow` — a trailing comment on the offending line. NOTE (2026-08-11):
#                    widening to $(PY_ROOTS) surfaced a fix_hint string in
#                    scanner/modules/django.py that quoted the assignment form as
#                    remediation advice, and the only remedy available was to reword the
#                    advice — degrading product copy to satisfy a grep (round-5 F10). Any
#                    docstring, error message or scanner rule that must name the pattern
#                    now marks the line instead. The marker is on the line it exempts, so
#                    it shows up in the diff that adds it and a reviewer sees the claim.
#
# OUT OF SCOPE, because $(PY_ROOTS) is "top-level dirs with an __init__.py, minus tests":
#   conformance/ and scripts_dev/ have no __init__.py, and tests/ is excluded by name.
#   Nothing scans those three for secret literals — they are fixtures, gate machinery and
#   dev scripts, and a real key committed there would be caught only by review.
log-scrub:
	! grep -rn "SECRET_KEY\s*=" --include="*.py" $(PY_ROOTS) | grep -v "settings" \
		| grep -v "# log-scrub: allow" \
		|| (echo "possible secret in code" && exit 1)

# One review round (build-process.md §4). Agent review sweep is run from a
# Cowork session; this target covers the mechanical gates.
# R4-8 parity: a round must exercise every gate CI runs, in CI's order — otherwise the
# copy that guards the branch is again the copy nobody exercises. `test` precedes
# `conformance` because the run report conformance reads is written by the pytest run.
review-round: lint log-scrub test test-frontend check-generated conformance
	@echo "mechanical gates green — run the agent review sweep against REVIEW_CHECKLIST.md"
