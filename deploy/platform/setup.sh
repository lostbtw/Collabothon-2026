#!/usr/bin/env bash
set -euo pipefail

NS=cfo-ai
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
IMAGES=(backend sim)
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

job_finished() {
  local status
  status="$(oc -n "$NS" get job platform-check -o jsonpath='{.status.succeeded}{.status.failed}')"
  [[ -n "$status" ]]
}

check_platform() {
  oc -n "$NS" delete job platform-check --ignore-not-found --wait
  oc apply -f "$HERE/check-job.yaml"
  wait_for "job platform-check" 300 job_finished
  oc -n "$NS" logs job/platform-check
  local succeeded
  succeeded="$(oc -n "$NS" get job platform-check -o jsonpath='{.status.succeeded}')"
  oc -n "$NS" delete job platform-check --wait
  if [[ "$succeeded" != 1 ]]; then
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

oc whoami >/dev/null

stage="${1:-}"
shift || true

case "$stage" in
  secrets) secrets ;;
  apply) apply ;;
  build) build "$@" ;;
  dev-build) dev_build "$@" ;;
  verify) verify ;;
  *)
    echo "usage: $0 secrets|apply|build|dev-build|verify [${IMAGES[*]}]" >&2
    exit 2
    ;;
esac
