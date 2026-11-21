#!/usr/bin/env bash
set -euo pipefail

NS=cfo-ai
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
APP="$ROOT/deploy/app"
IMAGES=(backend sim web)
M1_QUESTION="How much cash do we have today, and what is the next large payment?"
EXISTING_SECRETS=(llm-token docling-api-key)
SECRET_VALUES=(
  "ordo-db POSTGRESQL_PASSWORD"
  "github-webhook WebHookSecretKey"
  "sandbox-bank-token BANK_TOKEN"
  "docling-api-key DOCLING_SERVE_API_KEY"
  "llm-token token"
)

wait_for() {
  local what="$1" seconds="$2"
  shift 2
  local deadline=$((SECONDS + seconds))
  until "$@"; do
    if ((SECONDS >= deadline)); then
      echo "timed out waiting for $what" >&2
      exit 1
    fi
    sleep 5
  done
}

secret_exists() {
  oc -n "$NS" get secret "$1" >/dev/null 2>&1
}

random_hex() {
  head -c 24 /dev/urandom | od -An -vtx1 | tr -d ' \n'
}

create_random_secret() {
  local name="$1" key="$2"
  if secret_exists "$name"; then
    echo "secret $name already exists, kept"
  else
    oc -n "$NS" create secret generic "$name" --from-literal="$key=$(random_hex)"
  fi
}

secrets() {
  local name
  for name in "${EXISTING_SECRETS[@]}"; do
    if ! secret_exists "$name"; then
      echo "secret $name is missing, see deploy/secrets.example.yaml" >&2
      exit 1
    fi
    echo "secret $name present"
  done

  if secret_exists ordo-db; then
    echo "secret ordo-db already exists, kept"
  else
    local password
    password="$(random_hex)"
    oc -n "$NS" create secret generic ordo-db \
      --from-literal=POSTGRESQL_USER=ordo \
      --from-literal=POSTGRESQL_PASSWORD="$password" \
      --from-literal=POSTGRESQL_DATABASE=ordo \
      --from-literal=ORDO_DATABASE_URL="postgresql://ordo:$password@postgresql.$NS.svc.cluster.local:5432/ordo"
  fi

  create_random_secret github-webhook WebHookSecretKey
  create_random_secret sandbox-bank-token BANK_TOKEN
}

apply() {
  if ! secret_exists ordo-db; then
    echo "secret ordo-db is missing, run: $0 secrets" >&2
    exit 1
  fi
  oc apply \
    -f "$HERE/limits.yaml" \
    -f "$HERE/storage.yaml" \
    -f "$HERE/postgresql.yaml" \
    -f "$HERE/builds.yaml" \
    -f "$HERE/routes.yaml"
  oc -n "$NS" rollout status deployment/postgresql --timeout=300s
}

build() {
  local name
  for name in "${@:-${IMAGES[@]}}"; do
    oc -n "$NS" start-build "ordo-$name" --follow --wait
  done
}

dev_build() {
  local name
  for name in "${@:-${IMAGES[@]}}"; do
    oc -n "$NS" start-build "ordo-$name" --from-repo="$ROOT" --follow --wait
  done
}

dev_build_web() {
  local ref="${1:-}" tree
  if [[ -z "$ref" ]]; then
    echo "usage: $0 dev-build-web <git ref with frontend/, e.g. origin/r6/6-live-backend>" >&2
    exit 2
  fi
  git -C "$ROOT" fetch -q origin
  tree="$(mktemp -d)"
  git -C "$ROOT" worktree add -q --detach "$tree" HEAD
  if git -C "$tree" checkout "$ref" -- frontend &&
    git -C "$tree" commit -q -m "frontend from $ref for a test build" &&
    oc -n "$NS" start-build ordo-web --from-repo="$tree" --follow --wait; then
    git -C "$ROOT" worktree remove --force "$tree"
  else
    git -C "$ROOT" worktree remove --force "$tree"
    exit 1
  fi
}

webhook_urls() {
  local server secret name
  server="$(oc whoami --show-server)"
  secret="$(oc -n "$NS" get secret github-webhook -o jsonpath='{.data.WebHookSecretKey}' | base64 -d)"
  for name in "${IMAGES[@]}"; do
    echo "ordo-$name: $server/apis/build.openshift.io/v1/namespaces/$NS/buildconfigs/ordo-$name/webhooks/$secret/github"
  done
}

freeze() {
  local name
  for name in "${IMAGES[@]}"; do
    oc -n "$NS" set triggers "bc/ordo-$name" --from-github --remove
  done
  echo "webhook builds are off; deploy fixes with: $0 build <name>"
}

tag_demo() {
  local name
  for name in "${IMAGES[@]}"; do
    oc -n "$NS" tag "ordo-$name:latest" "ordo-$name:demo"
  done
}

job_finished() {
  local status
  status="$(oc -n "$NS" get job "$1" -o jsonpath='{.status.succeeded}{.status.failed}')"
  [[ -n "$status" ]]
}

run_job() {
  local name="$1" file="$2" succeeded
  oc -n "$NS" delete job "$name" --ignore-not-found --wait
  oc apply -f "$file"
  wait_for "job $name" 300 job_finished "$name"
  oc -n "$NS" logs "job/$name"
  succeeded="$(oc -n "$NS" get job "$name" -o jsonpath='{.status.succeeded}')"
  oc -n "$NS" delete job "$name" --wait
  [[ "$succeeded" == 1 ]]
}

check_platform() {
  if ! run_job platform-check "$HERE/check-job.yaml"; then
    echo "FAIL platform-check: postgres or the raw volume is not reachable from a pod" >&2
    return 1
  fi
  echo "OK   postgres reachable from a pod, raw volume writable"
}

check_resources() {
  local missing
  missing="$(oc -n "$NS" get deployments -o json | jq -r '
    .items[] | .metadata.name as $d
    | ((.spec.template.spec.initContainers // []) + .spec.template.spec.containers)[]
    | select((.resources.requests.cpu and .resources.requests.memory and .resources.limits.cpu and .resources.limits.memory) | not)
    | "\($d)/\(.name)"')"
  if [[ -n "$missing" ]]; then
    echo "FAIL containers without requests and limits:" >&2
    echo "$missing" >&2
    return 1
  fi
  echo "OK   every Deployment container has requests and limits"
}

check_no_secret_in_git() {
  local entry name key value leaked=0
  for entry in "${SECRET_VALUES[@]}"; do
    read -r name key <<<"$entry"
    value="$(oc -n "$NS" get secret "$name" -o jsonpath="{.data.$key}" | base64 -d)"
    if [[ -z "$value" ]]; then
      echo "FAIL secret $name has no $key" >&2
      leaked=1
    elif git -C "$ROOT" grep -qF -- "$value"; then
      echo "FAIL the value of $name/$key is in a tracked file" >&2
      leaked=1
    fi
  done
  ((leaked == 0)) || return 1
  echo "OK   no secret value in tracked files"
}

verify() {
  local failed=0
  check_platform || failed=1
  check_resources || failed=1
  check_no_secret_in_git || failed=1
  ((failed == 0))
}

app() {
  local name
  for name in ordo-db llm-token docling-api-key; do
    if ! secret_exists "$name"; then
      echo "secret $name is missing, see deploy/secrets.example.yaml" >&2
      exit 1
    fi
  done
  oc apply -f "$APP/config.yaml" -f "$APP/api.yaml" -f "$APP/web.yaml" -f "$APP/pipeline.yaml" -f "$APP/extractor.yaml"
  for name in ordo-api ordo-web ordo-pipeline ordo-extractor; do
    oc -n "$NS" rollout status "deployment/$name" --timeout=300s
  done
}

db_fixtures() {
  if ! run_job db-fixtures "$APP/db-fixtures-job.yaml"; then
    echo "FAIL db-fixtures: contracts/fixtures were not loaded" >&2
    return 1
  fi
  echo "OK   contracts/fixtures loaded as demo data"
}

model_requests() {
  oc get --raw "/api/v1/namespaces/$NS/services/http:gpt-oss-20b-metrics:8080/proxy/metrics" |
    awk '/^vllm:request_success_total\{/ && !/finished_reason="abort"/ { sum += $NF } END { printf "%d\n", sum }'
}

check_m1() {
  local base health company request answer before after failed=0
  base="https://$(oc -n "$NS" get route ordo-web -o jsonpath='{.spec.host}')"

  if curl -fsS -o /dev/null "$base/"; then
    echo "OK   $base/ opens from outside the cluster"
  else
    echo "FAIL $base/ does not open" >&2
    failed=1
  fi

  if health="$(curl -fsS "$base/api/v1/health")" && jq -e '.llm.reachable == true' <<<"$health" >/dev/null; then
    echo "OK   $base/api/v1/health: $(jq -r '.llm.model + " at " + .llm.base_url' <<<"$health") is reachable"
  else
    echo "FAIL $base/api/v1/health does not report the model reachable: ${health:-no answer}" >&2
    failed=1
  fi

  company="$(curl -fsS "$base/api/v1/companies" | jq -r '.items[0].id // empty')" || company=""
  if [[ -z "$company" ]]; then
    echo "FAIL $base/api/v1/companies lists no company" >&2
    return 1
  fi
  request="$(jq -nc --arg c "$company" --arg m "$M1_QUESTION" '{company_id: $c, message: $m}')"
  before="$(model_requests)"
  if ! answer="$(curl -fsS --max-time 300 -H 'Content-Type: application/json' -d "$request" "$base/api/v1/chat")"; then
    echo "FAIL $base/api/v1/chat did not answer" >&2
    return 1
  fi
  after="$(model_requests)"
  echo "     question ($company): $M1_QUESTION"
  echo "     answer: $(jq -r '.answer' <<<"$answer")"
  echo "     answered by: $(jq -r '.model // "not reported by the API yet"' <<<"$answer")"
  if ((after > before)); then
    echo "OK   gpt-oss-20b finished $((after - before)) requests while the chat answered"
  else
    echo "FAIL gpt-oss-20b finished no request while the chat answered, the text is the fallback" >&2
    failed=1
  fi
  ((failed == 0))
}

oc whoami >/dev/null

stage="${1:-}"
shift || true

case "$stage" in
  secrets) secrets ;;
  apply) apply ;;
  build) build "$@" ;;
  dev-build) dev_build "$@" ;;
  dev-build-web) dev_build_web "$@" ;;
  verify) verify ;;
  webhook-urls) webhook_urls ;;
  freeze) freeze ;;
  tag-demo) tag_demo ;;
  app) app ;;
  db-fixtures) db_fixtures ;;
  check-m1) check_m1 ;;
  *)
    echo "usage: $0 secrets|apply|build|dev-build|dev-build-web|app|db-fixtures|check-m1|verify|webhook-urls|freeze|tag-demo [${IMAGES[*]}]" >&2
    exit 2
    ;;
esac
