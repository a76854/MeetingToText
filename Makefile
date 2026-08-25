# MeetingToText — one-command entrypoint
#
# This Makefile is the single entrypoint for the most common development and
# deployment tasks. Every target below mirrors the repo's canonical invocation
# exactly (the same commands documented in the README / CI / tooling configs) —
# it does NOT introduce a second script dialect. If a command changes upstream,
# update it here to match.
#
# Targets are grouped as:
#   install / run / daemon lifecycle   — run the app
#   test / lint / typecheck / format   — quality gates
#   build / docker-up / docker-down    — packaging & deployment
#   help                               — list targets
#
# NOTE: `lint` and `typecheck` chain their backend and frontend halves with `;`
# so BOTH always run and report a combined result. `install` and `build` use
# `&&` because each step depends on the previous one succeeding.

install: ## Install backend (editable, dev extras) and frontend deps
	pip install -e ".[dev]" && cd frontend && npm ci

logs: ## Tail the daemon log file
	tail -n 100 -f data/logs/meetingtotext.log

test: ## Run the backend test suite (non-system)
	python -m pytest -q

test-system: ## Run the system tests (real FunASR models)
	python -m pytest -o addopts="" -m system -q

lint: ## Lint backend (ruff) and frontend (eslint)
	ruff check . ; cd frontend && npx eslint .

typecheck: ## Type-check backend (mypy) and frontend (vue-tsc)
	mypy backend/app ; cd frontend && npx vue-tsc --noEmit

format: ## Format backend (ruff) and frontend (prettier)
	ruff format . ; cd frontend && npx prettier --write .

build: ## Build the frontend for production
	cd frontend && npm run build

docker-up: ## Build and start the Docker stack
	docker compose -f docker/docker-compose.yml up -d --build

docker-down: ## Stop the Docker stack
	docker compose -f docker/docker-compose.yml down

help: ## List available targets
	@awk '/^[a-zA-Z_-]+:/{ if ($$2 == "##") { name=$$1; sub(/:$$/, "", name); desc=substr($$0, index($$0, "##")+3); printf "  %-14s %s\n", name, desc } }' $(MAKEFILE_LIST)

.PHONY: install logs test test-system lint typecheck format build docker-up docker-down help
