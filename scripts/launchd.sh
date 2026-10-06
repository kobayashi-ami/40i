#!/usr/bin/env bash
# Resident mode on macOS: one LaunchAgent for the API and one per worker, restarted if they die.
#   scripts/launchd.sh install [WORKERS]   # default 2 workers
#   scripts/launchd.sh uninstall
#   scripts/launchd.sh status
# Postgres/Redis are not managed here: compose.yaml uses restart: unless-stopped, so they come back with OrbStack
# (enable "Start at login" in OrbStack).
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT="$(pwd)"
UV="$(command -v uv)"
AGENTS="$HOME/Library/LaunchAgents"
LOGS="$HOME/Library/Logs/1260"
DOMAIN="gui/$(id -u)"
TEMPLATE="deploy/launchd/com.1260.service.plist.in"

render() {  # label, args...
  local label="$1"; shift
  local argfile; argfile="$(mktemp)"
  for a in "$@"; do printf '    <string>%s</string>\n' "$a" >> "$argfile"; done
  sed -e "s#__LABEL__#${label}#g" -e "s#__ROOT__#${ROOT}#g" -e "s#__LOGS__#${LOGS}#g" \
      -e "s#__PATH__#$(dirname "$UV"):/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin#g" "$TEMPLATE" |
    awk 'FNR == NR { args = args $0 "\n"; next } /__ARGS__/ { printf "%s", args; next } { print }' "$argfile" - \
    > "$AGENTS/${label}.plist"
  rm -f "$argfile"
}

labels() { ls "$AGENTS" 2>/dev/null | sed -n 's/^\(com\.1260\..*\)\.plist$/\1/p'; }

case "${1:-}" in
  install)
    n="${2:-2}"
    mkdir -p "$AGENTS" "$LOGS"
    "$0" uninstall >/dev/null 2>&1 || true
    docker compose up -d --wait
    "$UV" run alembic upgrade head
    render com.1260.api "$UV" run uvicorn api.main:app --host 127.0.0.1 --port 8260
    for i in $(seq "$n"); do render "com.1260.worker.$i" "$UV" run python -m worker; done
    for l in $(labels); do launchctl bootstrap "$DOMAIN" "$AGENTS/$l.plist"; done
    echo "installed: $(labels | tr '\n' ' ')"
    echo "logs: $LOGS"
    ;;
  uninstall)
    for l in $(labels); do
      launchctl bootout "$DOMAIN/$l" 2>/dev/null || true
      rm -f "$AGENTS/$l.plist"
    done
    echo "uninstalled"
    ;;
  status)
    for l in $(labels); do launchctl print "$DOMAIN/$l" 2>/dev/null | grep -E "^\s*(state|pid|last exit code)" | sed "s/^/$l: /"; done
    ;;
  *)
    echo "usage: $0 install [WORKERS] | uninstall | status" >&2; exit 2 ;;
esac
