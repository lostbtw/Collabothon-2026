#!/usr/bin/env bash
set -euo pipefail

NS=cfo-ai
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
SAMPLES="$HERE/whisper-samples"
WHISPER_PORT="${WHISPER_PORT:-18000}"
API_PORT="${API_PORT:-18080}"
PYTHON="${PYTHON:-$ROOT/.venv/bin/python}"
API="http://127.0.0.1:$API_PORT/api/v1"

work="$(mktemp -d)"
pids=()
cleanup() {
  if ((${#pids[@]})); then
    kill "${pids[@]}" 2>/dev/null || true
  fi
  rm -rf "$work"
}
trap cleanup EXIT

wait_for() {
  local what="$1" url="$2" tries=60
  until curl -s -o /dev/null --max-time 2 "$url"; do
    tries=$((tries - 1))
    if ((tries == 0)); then
      echo "FAIL $what did not come up; log: $work" >&2
      exit 1
    fi
    sleep 1
  done
}

oc whoami >/dev/null
oc -n "$NS" port-forward svc/whisper "$WHISPER_PORT:8000" >"$work/port-forward.log" 2>&1 &
pids+=($!)
wait_for "the port-forward to svc/whisper" "http://127.0.0.1:$WHISPER_PORT/health"

ORDO_WHISPER_API_KEY="$(oc -n "$NS" extract secret/whisper-api-key --keys=API_KEY --to=- 2>/dev/null)"
ORDO_WHISPER_MODEL="$(oc -n "$NS" get configmap ordo-whisper-client -o jsonpath='{.data.ORDO_WHISPER_MODEL}')"
export ORDO_WHISPER_API_KEY ORDO_WHISPER_MODEL
export ORDO_WHISPER_URL="http://127.0.0.1:$WHISPER_PORT/v1"
export ORDO_LLM_ENABLED=0
export ORDO_DATABASE_URL="${ORDO_DATABASE_URL:-postgresql://unused@127.0.0.1:1/unused}"

(cd "$ROOT" && exec "$PYTHON" -c "import uvicorn; from backend.api.app import create_app; uvicorn.run(create_app(), host='127.0.0.1', port=$API_PORT, log_level='warning')") \
  >"$work/api.log" 2>&1 &
pids+=($!)
wait_for "the local API" "$API/health"

failed=0
health="$(curl -s "$API/health")"
if jq -e '.speech.reachable == true' <<<"$health" >/dev/null; then
  echo "OK   /health: speech $(jq -c '.speech' <<<"$health")"
else
  echo "FAIL /health: speech $(jq -c '.speech' <<<"$health")"
  failed=1
fi

post() {
  local file="$1" type="$2" language="$3"
  curl -s -o "$work/body.json" -w '%{http_code} %{time_total}\n' --max-time 90 \
    -F "file=@$file;type=$type" -F "language=$language" "$API/chat/transcribe"
}

printf '\n%-14s %4s %7s %7s  %s\n' clip HTTP audio_s total_s text
while IFS=$'\t' read -r file language expected; do
  read -r code total < <(post "$SAMPLES/$file" audio/webm "$language")
  text="$(jq -r '.text // .error.message' "$work/body.json")"
  printf '%-14s %4s %7s %7s  %s\n' "$file" "$code" "$(jq -r '.duration_seconds // "-"' "$work/body.json")" "${total:0:5}" "$text"
  if [[ "$code" != 200 ]]; then
    failed=1
  elif [[ "$(tr -d '[:punct:]' <<<"${text,,}")" != "$(tr -d '[:punct:]' <<<"${expected,,}")" ]]; then
    echo "     differs from: $expected"
  fi
done < <(jq -r '.clips[] | [.file, .language, .text] | @tsv' "$SAMPLES/samples.json")

head -c $((5 * 1024 * 1024 + 1)) /dev/zero >"$work/too-large.webm"
: >"$work/empty.webm"
refused() {
  local name="$1" file="$2" type="$3" language="$4" want="$5" code
  read -r code _ < <(post "$file" "$type" "$language")
  if [[ "$code" == "$want" ]]; then
    echo "OK   $name: HTTP $code $(jq -r '.error.code' "$work/body.json")"
  else
    echo "FAIL $name: HTTP $code, expected $want: $(head -c 200 "$work/body.json")"
    failed=1
  fi
}

printf '\n'
refused "language de" "$SAMPLES/pl_cash.webm" audio/webm de 422
refused "not audio" "$SAMPLES/samples.json" application/json pl 415
refused "over 5 MB" "$work/too-large.webm" audio/webm pl 413
refused "empty" "$work/empty.webm" audio/webm pl 422

((failed == 0))
