.PHONY: dev test test-frontend lint conformance review-round generate-client check-generated

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
	bandit -q -c pyproject.toml -r core vault catalog scanner provision deploys reconcile providers monitor scaling realtime hub wizard
	pip-audit -r requirements.txt || true   # advisory until Phase 1; blocking after

conformance:
	python conformance/check.py --phase 1

# One review round (build-process.md §4). Agent review sweep is run from a
# Cowork session; this target covers the mechanical gates.
review-round: lint test test-frontend conformance
	@echo "mechanical gates green — run the agent review sweep against REVIEW_CHECKLIST.md"
