# Jazzar — raccourcis de développement local
SHELL := /bin/bash
BACKEND := backend
FRONTEND := frontend

.PHONY: help infra infra-down api web ingest-samples ingest-wikipedia ingest-pdf db-init eval test lint

help:
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[38;5;215m%-18s\033[0m %s\n", $$1, $$2}'

infra: ## Démarre Postgres+pgvector et Redis (docker compose)
	docker compose up -d
	@echo "Postgres: localhost:5433  Redis: localhost:6379"

infra-down: ## Arrête l'infra docker
	docker compose down

db-init: ## Crée les tables
	cd $(BACKEND) && uv run jazzar db init

api: ## Lance l'API FastAPI (http://localhost:8100/docs)
	cd $(BACKEND) && uv run uvicorn jazzar.main:app --reload --host 0.0.0.0 --port 8100

web: ## Lance le frontend Next.js (http://localhost:3000)
	cd $(FRONTEND) && npm run dev

ingest-samples: ## Ingère le corpus d'exemple fourni (data/samples)
	cd $(BACKEND) && uv run jazzar ingest samples

ingest-wikipedia: ## Ingère des articles Wikipedia jazz (corpus ouvert)
	cd $(BACKEND) && uv run jazzar ingest wikipedia --limit 60

ingest-pdf: ## Ingère les PDFs déposés dans data/raw/downbeat et data/raw/local
	cd $(BACKEND) && uv run jazzar ingest pdfs

eval: ## Lance le golden set d'évaluation
	cd $(BACKEND) && uv run jazzar eval run

test: ## Tests backend
	cd $(BACKEND) && uv run pytest -q

lint: ## Lint backend
	cd $(BACKEND) && uv run ruff check jazzar
