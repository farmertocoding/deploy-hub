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

# Plaintext secrets must not sit in source (SEC-69-NO-SECRETS-IN-EXHAUST). Command and
# `settings` exemption carried over verbatim from the push-checks step this replaces;
# the only change is scope, which is now $(PY_ROOTS) instead of the four packages that
# existed when it was written — it had never looked at wizard/ or scanner/ (R4-12).
# NOTE (2026-08-11): widening to $(PY_ROOTS) surfaced one hit on first run — a fix_hint
# string in scanner/modules/django.py that quoted the assignment form as remediation
# advice. Resolved by rewording that string (own commit), NOT by loosening the pattern
# or exempting the path; see the branch's second commit.
log-scrub:
	! grep -rn "SECRET_KEY\s*=" --include="*.py" $(PY_ROOTS) | grep -v "settings" \
		|| (echo "possible secret in code" && exit 1)

# One review round (build-process.md §4). Agent review sweep is run from a
# Cowork session; this target covers the mechanical gates.
# R4-8 parity: a round must exercise every gate CI runs, in CI's order — otherwise the
# copy that guards the branch is again the copy nobody exercises. `test` precedes
# `conformance` because the run report conformance reads is written by the pytest run.
review-round: lint log-scrub test test-frontend check-generated conformance
	@echo "mechanical gates green — run the agent review sweep against REVIEW_CHECKLIST.md"
