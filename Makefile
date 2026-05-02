.PHONY: help install up down logs migrate seed eval test fmt lint check-secrets install-hooks

help:
	@echo "Available targets:"
	@echo "  install         Install package + dev deps in current environment"
	@echo "  install-hooks   Install the pre-commit secret guard"
	@echo "  migrate         Run Alembic migrations against \$$DATABASE_URL"
	@echo "  up              Run migrations and print commands to start API + UI"
	@echo "  down            No-op (local Postgres runs as a Windows service)"
	@echo "  logs            No-op locally (use docker compose logs in containerized runs)"
	@echo "  seed            Generate synthetic vendors and seed the DB"
	@echo "  eval            Run the end-to-end integration eval"
	@echo "  test            Run pytest with coverage"
	@echo "  fmt             Format with ruff"
	@echo "  lint            Lint with ruff"
	@echo "  check-secrets   Scan staged files for Anthropic API keys"

install:
	pip install -e ".[dev]"

migrate:
	alembic upgrade head

up: migrate
	@echo ""
	@echo "Migrations applied. Start the services in two terminals:"
	@echo "  uvicorn proceval.api.main:app --reload --port 8000"
	@echo "  streamlit run src/ui/streamlit_app.py --server.port 8501"

down:
	@echo "Local Postgres runs as a Windows service — nothing to tear down."

logs:
	@echo "No container logs locally. Use 'docker compose logs -f' when running via deploy/docker-compose.yml."

seed:
	python scripts/generate_synthetic_vendors.py
	python scripts/seed_db.py

eval:
	python scripts/run_eval_test.py

test:
	pytest -v --cov=src/proceval

fmt:
	ruff format src tests scripts

lint:
	ruff check src tests scripts

check-secrets:
	python scripts/check_no_secrets.py

install-hooks:
	@printf '#!/usr/bin/env sh\nset -e\nfor PY in ./.venv/Scripts/python.exe ./.venv/bin/python python3 python; do\n  if command -v "$$PY" >/dev/null 2>&1 || [ -x "$$PY" ]; then\n    exec "$$PY" scripts/check_no_secrets.py\n  fi\ndone\necho "pre-commit: no python interpreter found" >&2\nexit 1\n' > .git/hooks/pre-commit
	@chmod +x .git/hooks/pre-commit 2>/dev/null || true
	@echo "Installed: .git/hooks/pre-commit (runs scripts/check_no_secrets.py via best-available python)"
