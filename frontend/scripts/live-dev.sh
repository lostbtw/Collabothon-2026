#!/usr/bin/env bash
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
API="${VITE_API_PROXY:-https://ordo-cfo-ai.apps.ocp.w6k4q.sandbox2219.opentlc.com}"
PORT="${PORT:-5173}"
NS=cfo-ai
WHISPER_PORT="${WHISPER_PORT:-18000}"
TRANSCRIBE_PORT="${TRANSCRIBE_PORT:-18080}"

if ! command -v npm >/dev/null; then
  exec nix-shell -p nodejs --run "$(printf '%q ' "${BASH_SOURCE[0]}" "$@")"
fi

pids=()
cleanup() {
  if ((${#pids[@]})); then
    kill "${pids[@]}" 2>/dev/null || true
  fi
}
trap cleanup EXIT

wait_for() {
  local what="$1" url="$2" tries=60
  until curl -s -o /dev/null --max-time 2 "$url"; do
    tries=$((tries - 1))
    if ((tries == 0)); then
      echo "$what did not come up" >&2
      exit 1
    fi
    sleep 1
  done
}

if [[ "${LOCAL_TRANSCRIBE:-0}" == 1 ]]; then
  oc -n "$NS" port-forward svc/whisper "$WHISPER_PORT:8000" >/dev/null 2>&1 &
  pids+=($!)
  wait_for "the port-forward to svc/whisper" "http://127.0.0.1:$WHISPER_PORT/health"
  ORDO_WHISPER_API_KEY="$(oc -n "$NS" extract secret/whisper-api-key --keys=API_KEY --to=- 2>/dev/null)"
  ORDO_WHISPER_MODEL="$(oc -n "$NS" get configmap ordo-whisper-client -o jsonpath='{.data.ORDO_WHISPER_MODEL}')"
  (cd "$ROOT" && ORDO_WHISPER_API_KEY="$ORDO_WHISPER_API_KEY" ORDO_WHISPER_MODEL="$ORDO_WHISPER_MODEL" \
    ORDO_WHISPER_URL="http://127.0.0.1:$WHISPER_PORT/v1" ORDO_LLM_ENABLED=0 \
    ORDO_DATABASE_URL="${ORDO_DATABASE_URL:-postgresql://unused@127.0.0.1:1/unused}" \
    exec "${PYTHON:-$ROOT/.venv/bin/python}" -c "import uvicorn; from backend.api.app import create_app; uvicorn.run(create_app(), host='127.0.0.1', port=$TRANSCRIBE_PORT, log_level='warning')") &
  pids+=($!)
  wait_for "the local transcribe API" "http://127.0.0.1:$TRANSCRIBE_PORT/api/v1/health"
  export VITE_TRANSCRIBE_PROXY="http://127.0.0.1:$TRANSCRIBE_PORT"
  echo "/api/v1/chat/transcribe goes to this branch's backend on :$TRANSCRIBE_PORT (Whisper through a port-forward)"
fi

cd "$HERE/.."
[[ -d node_modules ]] || npm ci --no-audit --no-fund
echo "open http://localhost:$PORT/?mock=0 (live API: $API)"
VITE_API_MODE=live VITE_API_PROXY="$API" npx vite --host localhost --port "$PORT" --strictPort
