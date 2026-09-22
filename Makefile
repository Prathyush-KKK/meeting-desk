PY := api/.venv/bin/python
PIP := api/.venv/bin/pip

.PHONY: live live-logs live-down help venv install install-llm check check-api ci lint fmt test migrate run worker jobs-schema token-key compose-check clean web-install web-check web-dev web-build e2e helm-lint helm-template docker-build

help:
	@echo "make install     - create api/.venv and install the API with its dev extras"
	@echo "make install-llm - add the Vertex AI and Bedrock SDKs (only needed with FAKE_LLM=0)"
	@echo "make ci          - everything a merge needs: ruff, pytest, tsc, vitest, vite build, helm, docker"
	@echo "make check       - ruff + pytest + the web check (the fast inner loop)"
	@echo "make check-api   - ruff + pytest only"
	@echo "make web-install - pnpm install in web/"
	@echo "make live        - the Mac launch: real Google + Google sign-in via docker-compose.live.yml (make live-logs, live-down)"
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
	cd api && FAKE_GOOGLE=1 FAKE_LLM=1 AUTH_DEV_USER=prathyush.kodhanpur@simpleo.ai \
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
	helm lint deploy/helm/meeting-desk && helm lint deploy/helm/meeting-desk -f deploy/helm/meeting-desk/values-internal.yaml

helm-template:
	helm template meeting-desk deploy/helm/meeting-desk -f deploy/helm/meeting-desk/values-internal.yaml

docker-build:
	docker build -f deploy/Dockerfile.api -t meeting-desk-api:dev .

compose-check:
	docker compose config >/dev/null && echo "docker-compose.yml is valid"

clean:
	rm -rf api/.venv api/.pytest_cache api/**/__pycache__ api/meeting-desk.db web/node_modules web/dist .ci

# --- the Mac launch (docker-compose.live.yml: real Google, Google sign-in, Postgres) -------------
live:
	scripts/mac-launch.sh

live-logs:
	scripts/mac-launch.sh logs

live-down:
	scripts/mac-launch.sh down
