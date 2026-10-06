UV ?= uv
PNPM ?= pnpm
WORKERS ?= 2

.PHONY: setup web web-dev infra infra-down migrate dev up down status serve unserve test test-engine lint mockups mockups-hires

setup:            ## install Python deps, create .env, build the UI
	$(UV) sync
	@test -f .env || cp .env.example .env
	$(MAKE) web

web:              ## build the UI into web/dist (served by the API on the same origin)
	cd web && $(PNPM) install --frozen-lockfile && $(PNPM) build

web-dev:          ## Vite dev server on 127.0.0.1:5173 (proxies /api to :8260; run `make dev` alongside)
	cd web && $(PNPM) dev

infra:            ## Postgres + Redis in OrbStack
	docker compose up -d --wait

infra-down:
	docker compose down

migrate:          ## apply Alembic migrations
	$(UV) run alembic upgrade head

dev:              ## API (auto-reload) + workers in the foreground; WORKERS=n
	WORKERS=$(WORKERS) scripts/dev.sh

up:               ## resident: LaunchAgents for API + WORKERS workers (restart on crash, start at login)
	scripts/launchd.sh install $(WORKERS)

down:
	scripts/launchd.sh uninstall

status:
	scripts/launchd.sh status

serve:            ## publish on the tailnet (HTTPS, MagicDNS) via tailscale serve — never funnel
	scripts/tailscale_serve.sh on

unserve:
	scripts/tailscale_serve.sh off

test:             ## all tests (integration tests need `make infra`)
	$(UV) run pytest

test-engine:      ## DSP engine tests only (no database)
	$(UV) run pytest tests/engine

lint:
	$(UV) run ruff check . && $(UV) run ruff format --check .
	cd web && $(PNPM) typecheck

mockups:
	$(UV) run --group design python design/render_mockups.py

mockups-hires:
	$(UV) run --group design python design/render_mockups.py --hires
