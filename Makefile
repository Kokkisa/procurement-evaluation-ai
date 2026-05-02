.PHONY: help install up down logs migrate seed eval test fmt lint

help:
	@echo "Available targets:"
	@echo "  install   Install package + dev deps in current environment"
	@echo "  migrate   Run Alembic migrations against \$$DATABASE_URL"
	@echo "  up        Run migrations and print commands to start API + UI"
	@echo "  down      No-op (local Postgres runs as a Windows service)"
	@echo "  logs      No-op locally (use docker compose logs in containerized runs)"
	@echo "  seed      Generate synthetic vendors and seed the DB"
	@echo "  eval      Run the end-to-end integration eval"
	@echo "  test      Run pytest with coverage"
	@echo "  fmt       Format with ruff"
	@echo "  lint      Lint with ruff"

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
