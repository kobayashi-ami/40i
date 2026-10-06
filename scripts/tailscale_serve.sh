#!/usr/bin/env bash
# Publish the local API (127.0.0.1:8260) inside the tailnet only, over HTTPS with the machine's MagicDNS name.
# Never uses `tailscale funnel` (that would put it on the public internet).
#   scripts/tailscale_serve.sh on | off | status
set -euo pipefail
PORT="${API_PORT:-8260}"
TARGET="http://127.0.0.1:${PORT}"

command -v tailscale >/dev/null || { echo "tailscale CLI not found (Tailscale.app → Settings → CLI integration)" >&2; exit 1; }

# The serve CLI changed shape across versions; read the installed one's help before running anything.
HELP="$(tailscale serve --help 2>&1 || true)"

case "${1:-status}" in
  on)
    if grep -q -- "--bg" <<<"$HELP"; then
      CMD=(tailscale serve --bg --https=443 "$TARGET")          # 1.52+ syntax
    else
      CMD=(tailscale serve https / "$TARGET")                    # older syntax
    fi
    echo "tailscale version: $(tailscale version | head -1)"
    echo "will run: ${CMD[*]}"
    read -r -p "proceed? [y/N] " ok
    [[ "$ok" == "y" || "$ok" == "Y" ]] || { echo "aborted"; exit 1; }
    "${CMD[@]}"
    tailscale serve status
    if tailscale funnel status 2>/dev/null | grep -qi "funnel on"; then
      echo "WARNING: funnel appears to be on for this node. 1260 must stay tailnet-only: tailscale funnel reset" >&2
    fi
    ;;
  off)
    if grep -q "reset" <<<"$HELP"; then tailscale serve reset; else tailscale serve https / off; fi
    ;;
  status)
    tailscale serve status
    ;;
  *)
    echo "usage: $0 on | off | status" >&2; exit 2 ;;
esac
