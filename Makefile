UV ?= uv
WORKERS ?= 2

.PHONY: setup infra infra-down migrate dev up down status serve unserve test lint mockups mockups-hires

setup:            ## install Python deps and create .env
	$(UV) sync
	@test -f .env || cp .env.example .env

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

test:             ## integration tests (needs `make infra`)
	$(UV) run pytest

lint:
	$(UV) run ruff check . && $(UV) run ruff format --check .

mockups:
	$(UV) run --group design python design/render_mockups.py

mockups-hires:
	$(UV) run --group design python design/render_mockups.py --hires
