#!/usr/bin/env bash
# Development: Postgres/Redis in OrbStack, migrations, then API (auto-reload) + N workers in the foreground.
#   WORKERS=2 make dev
set -euo pipefail
cd "$(dirname "$0")/.."

docker compose up -d --wait
uv run alembic upgrade head

trap 'kill 0' EXIT INT TERM
uv run uvicorn api.main:app --host "${API_HOST:-127.0.0.1}" --port "${API_PORT:-8260}" \
  --reload --reload-dir api --reload-dir core &
for _ in $(seq "${WORKERS:-1}"); do
  uv run python -m worker &
done
echo "1260 dev: http://127.0.0.1:${API_PORT:-8260}/  (Ctrl-C stops everything)"
wait
