PY := api/.venv/bin/python
PIP := api/.venv/bin/pip
# The demo world's admin and workstreams (api/app/seed_data.py).
DEMO_USER := daniel.okafor@example.com
DEMO_WORKSTREAMS := Mobile,Platform,Billing,Rewards,Prod ops,Hiring

.PHONY: demo live live-logs live-down help venv install install-llm check check-api ci lint fmt test migrate run worker jobs-schema token-key compose-check clean web-install web-check web-dev web-build e2e helm-lint helm-template docker-build

help:
	@echo "make demo        - the demo in Docker on http://localhost:8000 (fake Google, no keys)"
	@echo "make install     - create api/.venv and install the API with its dev extras"
	@echo "make install-llm - add the Vertex AI, Bedrock and Anthropic SDKs (EXTRACTION_PROVIDER=openai needs none)"
	@echo "make ci          - everything a merge needs: ruff, pytest, tsc, vitest, vite build, helm, docker"
	@echo "make check       - ruff + pytest + the web check (the fast inner loop)"
	@echo "make check-api   - ruff + pytest only"
	@echo "make web-install - pnpm install in web/"
	@echo "make live        - real Google on this machine via docker-compose.live.yml (make live-logs, live-down)"
	@echo "make web-check   - tsc, vitest and the web build"
	@echo "make web-dev     - the Vite dev server on http://localhost:5173"
	@echo "make e2e         - the browser walkthrough (needs make run and make web-dev)"
	@echo "make lint        - ruff check"
	@echo "make fmt         - ruff format"
	@echo "make test        - pytest -q"
	@echo "make run         - uvicorn with FAKE_GOOGLE=1 on http://localhost:8000"
	@echo "make migrate     - alembic upgrade head"
	@echo "make jobs-schema - install procrastinate's tables in DATABASE_URL (once, Postgres only)"
	@echo "make worker      - run the procrastinate worker (JOBS_ENABLED=1, Postgres)"
	@echo "make token-key   - print a fresh MEETING_DESK_TOKEN_KEY"

venv:
	python3.12 -m venv api/.venv

install: venv
	$(PIP) install --upgrade pip
	$(PIP) install -e "api[dev]"

check: lint test web-check

# The gate. Installs helm into ~/.local/bin if it is missing; the docker step reports SKIPPED
# rather than failing where there is no daemon (see scripts/ci.sh).
ci:
	bash scripts/ci.sh

check-api: lint test

lint:
	cd api && .venv/bin/ruff check .

fmt:
	cd api && .venv/bin/ruff format .

test:
	cd api && .venv/bin/python -m pytest -q

install-llm: venv
	$(PIP) install -e "api[dev,llm]"

migrate:
	cd api && .venv/bin/python -m alembic upgrade head

jobs-schema:
	cd api && .venv/bin/python -m app.jobs.schema

worker:
	cd api && JOBS_ENABLED=1 .venv/bin/python -m app.jobs.queue

token-key:
	cd api && .venv/bin/python -c "from app.google.tokens import generate_key; print(generate_key())"

run:
	cd api && FAKE_GOOGLE=1 FAKE_LLM=1 AUTH_DEV_USER=$(DEMO_USER) WORKSTREAMS="$(DEMO_WORKSTREAMS)" \
		DATABASE_URL=sqlite:///./meeting-desk.db \
		.venv/bin/uvicorn app.main:app --reload --port 8000

web-install:
	cd web && pnpm install

web-check:
	cd web && pnpm run check

web-dev:
	cd web && pnpm dev

web-build:
	cd web && pnpm run build

e2e:
	cd web && node e2e/walkthrough.mjs

helm-lint:
	helm lint deploy/helm/meeting-desk && helm lint deploy/helm/meeting-desk -f deploy/helm/meeting-desk/values-production.example.yaml

helm-template:
	helm template meeting-desk deploy/helm/meeting-desk -f deploy/helm/meeting-desk/values-production.example.yaml

docker-build:
	docker build -f deploy/Dockerfile.api -t meeting-desk-api:dev .

compose-check:
	docker compose config >/dev/null && echo "docker-compose.yml is valid"

clean:
	rm -rf api/.venv api/.pytest_cache api/**/__pycache__ api/meeting-desk.db web/node_modules web/dist .ci

# --- the live launch (docker-compose.live.yml: real Google, Google sign-in, Postgres) -------------
live:
	scripts/live.sh

live-logs:
	scripts/live.sh logs

live-down:
	scripts/live.sh down

# --- the demo (docker-compose.demo.yml: one container, SQLite, fake Google) --------------------
demo:
	docker compose -f docker-compose.demo.yml up --build
