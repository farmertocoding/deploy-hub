.PHONY: dev test lint conformance review-round generate-client

# §4.5 pipeline: serializers → OpenAPI → generated TS types. Regenerate after any
# serializer change; CI will later assert the generated files are not stale.
generate-client:
	python manage.py spectacular --file frontend/src/api/openapi.yaml --settings=hub.settings.dev
	cd frontend && npx openapi-typescript src/api/openapi.yaml -o src/api/types.ts

dev:
	docker compose up --build

test:
	pytest -q

lint:
	ruff check .
	bandit -q -c pyproject.toml -r core vault catalog scanner provision deploys reconcile providers monitor scaling realtime hub
	pip-audit -r requirements.txt || true   # advisory until Phase 1; blocking after

conformance:
	python conformance/check.py --phase 0

# One review round (build-process.md §4). Agent review sweep is run from a
# Cowork session; this target covers the mechanical gates.
review-round: lint test conformance
	@echo "mechanical gates green — run the agent review sweep against REVIEW_CHECKLIST.md"
