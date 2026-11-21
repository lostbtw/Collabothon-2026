#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
API="${VITE_API_PROXY:-https://ordo-cfo-ai.apps.ocp.w6k4q.sandbox2219.opentlc.com}"
PORT="${PORT:-5173}"

if ! command -v npm >/dev/null; then
  exec nix-shell -p nodejs --run "$(printf '%q ' "${BASH_SOURCE[0]}" "$@")"
fi

cd "$HERE/.."
[[ -d node_modules ]] || npm ci --no-audit --no-fund
echo "open http://localhost:$PORT/?mock=0 (live API: $API)"
VITE_API_MODE=live VITE_API_PROXY="$API" exec npx vite --host localhost --port "$PORT" --strictPort
