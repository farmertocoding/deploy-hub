.PHONY: dev test lint conformance review-round

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
