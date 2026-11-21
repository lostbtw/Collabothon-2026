#!/usr/bin/env bash
set -euo pipefail

NS=cfo-ai
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
APP="$ROOT/deploy/app"
OBS="$ROOT/deploy/observability"
GUARDRAILS="$ROOT/deploy/guardrails"
UWM_NS=openshift-user-workload-monitoring
DSC=default-dsc
MODEL_JOB=gpt-oss-20b-metrics
ORDO_RULES=(ordo-model ordo-workloads)
GRAFANA_TABLES="outbox, outbox_delivery, outbox_subscription, recommendations, sources, sync_runs, companies"
IMAGES=(backend sim web)
M1_QUESTION="How much cash do we have today, and what is the next large payment?"
EXISTING_SECRETS=(llm-token docling-api-key)
SECRET_VALUES=(
  "ordo-db POSTGRESQL_PASSWORD"
  "github-webhook WebHookSecretKey"
  "sandbox-bank-token BANK_TOKEN"
  "docling-api-key DOCLING_SERVE_API_KEY"
  "llm-token token"
  "ordo-grafana GF_SECURITY_ADMIN_PASSWORD"
  "ordo-grafana GRAFANA_DB_PASSWORD"
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
  grafana_secret
}

grafana_secret() {
  if secret_exists ordo-grafana; then
    echo "secret ordo-grafana already exists, kept"
  else
    oc -n "$NS" create secret generic ordo-grafana \
      --from-literal=GF_SECURITY_ADMIN_PASSWORD="$(random_hex)" \
      --from-literal=GRAFANA_DB_PASSWORD="$(random_hex)"
  fi
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

bank_csv() {
  local file="${1:-}"
  if [[ -z "$file" || ! -f "$file" ]]; then
    echo "usage: $0 bank-csv <the organisers' pizzeria-amalfi-bank-statement CSV, not in Git>" >&2
    exit 2
  fi
  oc -n "$NS" create configmap bank-pizzeria-csv --from-file="statement.csv=$file" --dry-run=client -o yaml |
    oc label --local -f - app.kubernetes.io/part-of=ordo -o yaml |
    oc apply --server-side --force-conflicts -f -
  if oc -n "$NS" get deployment ordo-bank >/dev/null 2>&1; then
    oc -n "$NS" rollout restart deployment/ordo-bank
    oc -n "$NS" rollout status deployment/ordo-bank --timeout=300s
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

app_inputs() {
  local name
  for name in ordo-db llm-token docling-api-key sandbox-bank-token; do
    if ! secret_exists "$name"; then
      echo "secret $name is missing, see deploy/secrets.example.yaml" >&2
      exit 1
    fi
  done
  if ! oc -n "$NS" get configmap bank-pizzeria-csv >/dev/null 2>&1; then
    echo "configmap bank-pizzeria-csv is missing, run: $0 bank-csv <pizzeria CSV>" >&2
    exit 1
  fi
  if ! secret_exists ordo-mailbox; then
    echo "note: no secret ordo-mailbox, the invoices mailbox is not read (see deploy/secrets.example.yaml)" >&2
  fi
}

app() {
  local name
  app_inputs
  oc apply -f "$APP/config.yaml" -f "$APP/bank.yaml" -f "$APP/api.yaml" -f "$APP/web.yaml" -f "$APP/pipeline.yaml" \
    -f "$APP/extractor.yaml" -f "$APP/connectors.yaml" -f "$APP/agents.yaml" -f "$APP/finance.yaml" -f "$APP/mcp.yaml"
  for name in ordo-bank ordo-api ordo-web ordo-pipeline ordo-extractor ordo-connectors ordo-agents ordo-finance ordo-mcp; do
    oc -n "$NS" rollout status "deployment/$name" --timeout=300s
  done
}

ogx_ready() {
  [[ "$(oc -n "$NS" get ogxserver ordo-ogx -o jsonpath='{.status.phase}' 2>/dev/null)" == "Ready" ]]
}

ogx_database() {
  local owner
  owner="$(oc -n "$NS" extract secret/ordo-db --keys=POSTGRESQL_USER --to=-)"
  oc -n "$NS" exec -i deployment/postgresql -- psql -U postgres -v ON_ERROR_STOP=1 -q <<SQL
select 'create database ogx owner "$owner"' where not exists (select 1 from pg_database where datname = 'ogx') \\gexec
SQL
  echo "OK   database ogx exists (OGX keeps its own state there, apart from Ordo's data)"
}

ogx_restart_agents() {
  local name
  oc -n "$NS" rollout restart deployment/ordo-api deployment/ordo-agents
  for name in ordo-api ordo-agents; do
    oc -n "$NS" rollout status "deployment/$name" --timeout=300s
  done
}

ogx() {
  # OGX replaces the Llama Stack operator and refuses to install next to it (Red Hat's migration: remove it first).
  if oc get crd llamastackdistributions.llamastack.io >/dev/null 2>&1 &&
    [[ -n "$(oc get llamastackdistributions -A -o name 2>/dev/null)" ]]; then
    echo "FAIL the cluster still runs Llama Stack servers; migrate them to OGXServer before enabling OGX" >&2
    return 1
  fi
  oc patch datasciencecluster default-dsc --type=merge \
    -p '{"spec":{"components":{"llamastackoperator":{"managementState":"Removed"},"ogx":{"managementState":"Managed"}}}}'
  wait_for "the OGXServer resource type" 300 oc get crd ogxservers.ogx.io
  wait_for "the OGX operator pod" 300 oc -n redhat-ods-applications wait pod \
    -l app.kubernetes.io/name=ogx-k8s-operator --for=condition=Ready --timeout=30s
  ogx_database
  oc apply -f "$APP/mcp.yaml"
  oc -n "$NS" rollout status deployment/ordo-mcp --timeout=300s
  oc apply -f "$APP/ogx.yaml"
  wait_for "the OGX server ordo-ogx" 600 ogx_ready
  oc apply -f "$APP/ogx-config.yaml" -f "$APP/api.yaml" -f "$APP/agents.yaml"
  ogx_restart_agents
  check_ogx
}

check_ogx() {
  if oc -n "$NS" exec deployment/ordo-api -- python -m backend.agents.ogx "How much cash do I have?"; then
    echo "OK   OGX ran the chat's tool loop and called Ordo's tools over MCP"
  else
    echo "FAIL OGX + MCP: see oc -n $NS logs deployment/ordo-mcp and oc -n $NS get ogxserver ordo-ogx -o yaml" >&2
    return 1
  fi
}

ogx_off() {
  oc -n "$NS" delete configmap ordo-ogx --ignore-not-found
  ogx_restart_agents
  echo "OK   the agents run their own tool loop again"
}

guardrails() {
  oc apply -f "$HERE/limits.yaml" -f "$GUARDRAILS/nemo-guardrails.yaml"
  wait_for "the Deployment ordo-guardrails" 120 oc -n "$NS" get deployment/ordo-guardrails
  oc -n "$NS" rollout status deployment/ordo-guardrails --timeout=300s
  check_guardrails rails || return 1
  oc apply -f "$APP/guardrails-config.yaml" -f "$APP/api.yaml"
  oc -n "$NS" rollout restart deployment/ordo-api
  oc -n "$NS" rollout status deployment/ordo-api --timeout=300s
  check_guardrails
}

check_guardrails() {
  if oc -n "$NS" exec -i deployment/ordo-api -c api -- python - "$@" <"$GUARDRAILS/check_guardrails.py"; then
    echo "OK   NeMo Guardrails mask IBANs, card numbers and tax ids and refuse investment advice${1:+ (rails only)}"
  else
    echo "FAIL guardrails: see oc -n $NS logs deployment/ordo-guardrails -c nemo-guardrails" >&2
    return 1
  fi
}

guardrails_off() {
  oc -n "$NS" delete configmap ordo-guardrails-client --ignore-not-found
  oc -n "$NS" rollout restart deployment/ordo-api
  oc -n "$NS" rollout status deployment/ordo-api --timeout=300s
  echo "OK   the chat runs without NeMo Guardrails"
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

app_base() {
  echo "https://$(oc -n "$NS" get route ordo-web -o jsonpath='{.spec.host}')"
}

check_web() {
  local base="$1" page
  if page="$(curl -fsS "$base/")" && grep -q '<div id="root">' <<<"$page"; then
    echo "OK   $base/ opens the Ordo app from outside the cluster"
  else
    echo "FAIL $base/ does not open the Ordo app" >&2
    return 1
  fi
}

check_health() {
  local base="$1" health
  if health="$(curl -fsS "$base/api/v1/health")" && jq -e '.llm.reachable == true' <<<"$health" >/dev/null; then
    echo "OK   $base/api/v1/health: $(jq -r '.llm.model + " at " + .llm.base_url' <<<"$health") is reachable"
  else
    echo "FAIL $base/api/v1/health does not report the model reachable: ${health:-no answer}" >&2
    return 1
  fi
}

first_company() {
  curl -fsS "$1/api/v1/companies" | jq -r '.items[0].id // empty'
}

check_bank() {
  local entry name container failed=0
  for entry in "ordo-api api" "ordo-connectors connectors"; do
    read -r name container <<<"$entry"
    oc -n "$NS" exec -i "deployment/$name" -c "$container" -- python - <"$HERE/check_bank.py" || failed=1
  done
  ((failed == 0))
}

check_m2() {
  local base company items failed=0
  base="$(app_base)"
  check_web "$base" || failed=1
  check_health "$base" || failed=1
  company="$(first_company "$base")" || company=""
  if [[ -z "$company" ]]; then
    echo "FAIL $base/api/v1/companies lists no company" >&2
    failed=1
  else
    items="$(curl -fsS "$base/api/v1/recommendations?company_id=$company" | jq -r '.items | length')" || items=0
    if ((items > 0)); then
      echo "OK   $base/api/v1/recommendations serves $items items for $company"
    else
      echo "FAIL $base/api/v1/recommendations serves nothing for $company" >&2
      failed=1
    fi
  fi
  check_bank || failed=1
  ((failed == 0))
}

redeploy() {
  app_inputs
  build
  app
  check_m2
}

check_m1() {
  local base company request answer before after failed=0
  base="$(app_base)"
  check_web "$base" || failed=1
  check_health "$base" || failed=1

  company="$(first_company "$base")" || company=""
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

uwm_ready() {
  [[ "$(oc -n "$UWM_NS" get pod prometheus-user-workload-0 \
    -o jsonpath='{.status.containerStatuses[?(@.name=="prometheus")].ready}' 2>/dev/null)" == true ]]
}

thanos() {
  # GET a Thanos Querier API path through its route, with your own oc token (read from stdin, not in argv).
  local path="$1" host
  shift
  host="$(oc -n openshift-monitoring get route thanos-querier -o jsonpath='{.spec.host}')"
  curl -fsS -G -H @- "$@" "https://$host$path" <<<"Authorization: Bearer $(oc whoami -t)"
}

promql() {
  thanos /api/v1/query --data-urlencode "query=$1" | jq -c '.data.result'
}

expected_rules() {
  oc -n "$NS" get prometheusrule "${ORDO_RULES[@]}" -o json | jq '[.items[].spec.groups[].rules[]] | length'
}

ordo_rules() {
  local groups
  groups="$(oc -n "$NS" get prometheusrule "${ORDO_RULES[@]}" -o json | jq -c '[.items[].spec.groups[].name]')"
  thanos /api/v1/rules | jq -r --argjson groups "$groups" '.data.groups[] | select(.name as $n | $groups | index($n))
    | .name as $g | .rules[] | "\($g) \(.name) \(.health)"' | sort -u
}

rules_evaluated() {
  local expected lines
  expected="$(expected_rules)"
  lines="$(ordo_rules)" || return 1
  [[ "$(grep -c . <<<"$lines")" -eq "$expected" ]] && ! grep -q ' unknown$' <<<"$lines"
}

monitoring() {
  local current
  current="$(oc -n openshift-monitoring get configmap cluster-monitoring-config -o jsonpath='{.data.config\.yaml}' 2>/dev/null)" ||
    current=""
  oc apply -f "$OBS/user-workload-monitoring-config.yaml"
  if [[ -z "$current" ]]; then
    oc apply -f "$OBS/cluster-monitoring-config.yaml"
  elif grep -Eq '^enableUserWorkload: *true *$' <<<"$current"; then
    echo "user-workload monitoring is already on, cluster-monitoring-config kept"
  else
    echo "configmap openshift-monitoring/cluster-monitoring-config holds other settings;" \
      "add 'enableUserWorkload: true' to its config.yaml by hand. Now it is:" >&2
    echo "$current" >&2
    exit 1
  fi
  wait_for "prometheus-user-workload-0" 600 uwm_ready
  oc apply -f "$OBS/prometheus-rules.yaml"
  wait_for "the first evaluation of the ordo rules" 300 rules_evaluated
  check_monitoring
}

check_monitoring() {
  local up model expected lines bad firing failed=0
  up="$(promql "up{namespace=\"$NS\",job=\"$MODEL_JOB\"}" | jq -r '.[0].value[1] // empty')" || up=""
  if [[ "$up" == 1 ]]; then
    echo "OK   user-workload Prometheus scrapes gpt-oss-20b ($MODEL_JOB)"
  else
    echo "FAIL no healthy scrape of $MODEL_JOB; is user-workload monitoring on? oc -n $UWM_NS get pods" >&2
    failed=1
  fi

  model="$(promql "max by (__name__) ({namespace=\"$NS\",__name__=~\"vllm:num_requests_running|vllm:num_requests_waiting|vllm:kv_cache_usage_perc\"})" |
    jq -r 'map({(.metric.__name__): (.value[1] | tonumber)}) | add // {}
      | if length == 3 then "\(.["vllm:num_requests_running"]) running, \(.["vllm:num_requests_waiting"]) waiting, KV cache \(.["vllm:kv_cache_usage_perc"] * 100 | floor) %" else empty end')" ||
    model=""
  if [[ -n "$model" ]]; then
    echo "OK   vLLM metrics are queryable: $model"
  else
    echo "FAIL vLLM metrics of $NS are not in Thanos Querier" >&2
    failed=1
  fi

  expected="$(expected_rules)"
  lines="$(ordo_rules)" || lines=""
  bad="$(grep -v ' ok$' <<<"$lines" || true)"
  if [[ -n "$lines" && "$(grep -c . <<<"$lines")" -eq "$expected" && -z "$bad" ]]; then
    echo "OK   all $expected ordo rules are loaded and evaluate without errors"
  else
    echo "FAIL ordo rules: $(grep -c . <<<"$lines") of $expected loaded" >&2
    if [[ -n "$bad" ]]; then
      echo "$bad" >&2
    fi
    failed=1
  fi

  firing="$(promql "ALERTS{namespace=\"$NS\",alertstate=\"firing\"}" | jq -r '[.[].metric.alertname] | unique | join(", ")')" ||
    firing=""
  echo "     firing now in $NS: ${firing:-nothing}"
  ((failed == 0))
}

grafana_db_role() {
  # A login role that reads only the dashboards' tables, read-only with a statement timeout so a panel cannot slow the app.
  local password
  password="$(oc -n "$NS" get secret ordo-grafana -o jsonpath='{.data.GRAFANA_DB_PASSWORD}' | base64 -d)"
  oc -n "$NS" exec -i deployment/postgresql -- psql -U postgres -d ordo -v ON_ERROR_STOP=1 -q <<SQL
do \$\$ begin
  if not exists (select 1 from pg_roles where rolname = 'grafana_ro') then
    create role grafana_ro login;
  end if;
end \$\$;
alter role grafana_ro with login password '$password' connection limit 10;
alter role grafana_ro set default_transaction_read_only = on;
alter role grafana_ro set statement_timeout = '15s';
grant connect on database ordo to grafana_ro;
grant usage on schema public to grafana_ro;
grant select on $GRAFANA_TABLES to grafana_ro;
SQL
  echo "OK   database role grafana_ro reads: $GRAFANA_TABLES"
}

grafana_dashboards() {
  oc -n "$NS" create configmap grafana-dashboards --from-file="$OBS/dashboards" --dry-run=client -o yaml |
    oc label --local -f - app.kubernetes.io/part-of=ordo -o yaml |
    oc apply --server-side --force-conflicts -f -
}

grafana() {
  grafana_secret
  grafana_db_role
  grafana_dashboards
  oc apply -f "$OBS/grafana.yaml"
  oc -n "$NS" rollout restart deployment/grafana
  oc -n "$NS" rollout status deployment/grafana --timeout=300s
  check_grafana
}

grafana_url() {
  echo "https://$(oc -n "$NS" get route ordo-grafana -o jsonpath='{.spec.host}')"
}

grafana_api() {
  local method="$1" path="$2" body="${3:-}"
  local args=(-sS --max-time 60 -X "$method" -K - -H 'Content-Type: application/json')
  if [[ -n "$body" ]]; then
    args+=(--data-binary "$body")
  fi
  if [[ -z "${GRAFANA_URL:-}" ]]; then
    GRAFANA_URL="$(grafana_url)"
  fi
  if [[ -z "${GRAFANA_PASSWORD:-}" ]]; then
    GRAFANA_PASSWORD="$(oc -n "$NS" get secret ordo-grafana -o jsonpath='{.data.GF_SECURITY_ADMIN_PASSWORD}' | base64 -d)"
  fi
  curl "${args[@]}" "$GRAFANA_URL$path" <<<"user = \"admin:$GRAFANA_PASSWORD\""
}

dashboards_loaded() {
  local file uid want have
  for file in "$OBS"/dashboards/*.json; do
    uid="$(jq -r '.uid' "$file")"
    want="$(jq -c '[.panels[] | [.type, .title]]' "$file")"
    have="$(grafana_api GET "/api/dashboards/uid/$uid" | jq -c '[.dashboard.panels[]? | [.type, .title]]')" || return 1
    [[ "$want" == "$have" ]] || return 1
  done
}

grafana_reload_dashboards() {
  # New dashboards without a restart (nobody logged out): the mounted ConfigMap updates in minutes, Grafana rereads it every 30 s.
  grafana_dashboards
  wait_for "Grafana to load the new dashboards" 480 dashboards_loaded
  echo "OK   Grafana serves the dashboards in $OBS/dashboards"
  check_grafana
}

check_grafana() {
  local url uid status expected found plugins unknown file query title answer errors ok=0 failed=0
  url="$(grafana_url)"
  GRAFANA_URL="$url"
  if [[ "$(curl -fsS --max-time 30 "$url/api/health" | jq -r '.database')" == ok ]]; then
    echo "OK   Grafana answers at $url"
  else
    echo "FAIL Grafana does not answer at $url" >&2
    return 1
  fi

  for uid in prometheus ordo-postgres; do
    status="$(grafana_api GET "/api/datasources/uid/$uid/health" | jq -r '"\(.status): \(.message)"')" || status=""
    if [[ "$status" == OK:* ]]; then
      echo "OK   datasource $uid: ${status#OK: }"
    else
      echo "FAIL datasource $uid: ${status:-no answer}" >&2
      failed=1
    fi
  done

  expected="$(find "$OBS/dashboards" -name '*.json' | wc -l)"
  found="$(grafana_api GET '/api/search?type=dash-db&tag=ordo' | jq 'length')" || found=0
  if ((found == expected)); then
    echo "OK   $found dashboards loaded in folder Ordo"
  else
    echo "FAIL $found of $expected dashboards loaded" >&2
    failed=1
  fi

  plugins="$(grafana_api GET '/api/plugins?type=panel' | jq -c '[.[].id]')" || plugins='[]'
  unknown="$(jq -r --argjson known "$plugins" '.panels[] | select(.type as $t | $known | index($t) | not)
    | "\(.title) (\(.type))"' "$OBS"/dashboards/*.json)"
  if [[ -z "$unknown" ]]; then
    echo "OK   every panel type is a Grafana panel plugin"
  else
    echo "FAIL panels with an unknown type:" >&2
    echo "$unknown" >&2
    failed=1
  fi

  for file in "$OBS"/dashboards/*.json; do
    while IFS= read -r query; do
      title="$(jq -r '.title' <<<"$query")"
      answer="$(grafana_api POST /api/ds/query \
        "$(jq -c '{queries: [.query], from: "now-6h", to: "now"}' <<<"$query")")" || answer='{"message": "no answer"}'
      errors="$(jq -r '[(.message // empty), (.results[]? | .error // empty)] | join("; ")' <<<"$answer")"
      if [[ -z "$errors" ]]; then
        ok=$((ok + 1))
      else
        echo "FAIL $title: $errors" >&2
        failed=1
      fi
    done < <(jq -c '.title as $d | .panels[] | .title as $p | .targets[]
      | {title: "\($d) / \($p) / \(.refId)", query: (. + {intervalMs: 60000, maxDataPoints: 500})}' "$file")
  done
  echo "     $ok panel queries answered without errors"
  echo "     log in as admin; password: oc -n $NS extract secret/ordo-grafana --keys=GF_SECURITY_ADMIN_PASSWORD --to=-"
  ((failed == 0))
}

mlflow_crd_ready() {
  oc get crd mlflows.mlflow.opendatahub.io >/dev/null 2>&1
}

mlflow_operator_ready() {
  [[ "$(oc get datasciencecluster "$DSC" \
    -o jsonpath='{.status.conditions[?(@.type=="MLflowOperatorReady")].status}' 2>/dev/null)" == True ]]
}

mlflow_available() {
  [[ "$(oc get mlflow mlflow -o jsonpath='{.status.conditions[?(@.type=="Available")].status}' 2>/dev/null)" == True ]]
}

mlflow() {
  oc patch datasciencecluster "$DSC" --type merge \
    -p '{"spec":{"components":{"mlflowoperator":{"managementState":"Managed"}}}}'
  wait_for "the MLflow CRD" 600 mlflow_crd_ready
  wait_for "condition MLflowOperatorReady on $DSC" 600 mlflow_operator_ready
  local role
  role="$(oc -n "$NS" get rolebinding cfo-app-mlflow-integration -o jsonpath='{.roleRef.name}' 2>/dev/null)" || role=""
  if [[ -n "$role" && "$role" != mlflow-operator-mlflow-integration ]]; then
    oc -n "$NS" delete rolebinding cfo-app-mlflow-integration
  fi
  oc apply -f "$HERE/mlflow.yaml"
  wait_for "MLflow to become Available" 600 mlflow_available
  check_mlflow
}

check_mlflow() {
  local address url
  address="$(oc get mlflow mlflow -o jsonpath='{.status.address.url}')"
  url="$(oc get mlflow mlflow -o jsonpath='{.status.url}')"
  oc get mlflow mlflow -o jsonpath='{range .status.conditions[*]}     {.type}={.status} {.message}{"\n"}{end}'
  echo "     in-cluster: ${address:-none}"
  echo "     UI:         ${url:-none}"
  if [[ -z "$address" ]]; then
    echo "FAIL MLflow reports no in-cluster address" >&2
    return 1
  fi
  oc -n "$NS" exec -i deployment/ordo-extractor -c extractor -- python - "$address" <"$HERE/check_mlflow.py"
}

WORKBENCH=model-tests
WORKBENCH_STOPPED=kubeflow-resource-stopped
WORKBENCH_ENV=(MLFLOW_TRACKING_URI MLFLOW_WORKSPACE MLFLOW_TRACKING_TOKEN LLM_BASE_URL ORDO_LLM_API_KEY
  ORDO_DOCLING_URL ORDO_DOCLING_API_KEY)

workbench_ready() {
  [[ "$(oc -n "$NS" get pod "$WORKBENCH-0" \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" == True ]]
}

workbench_gone() {
  ! oc -n "$NS" get pod "$WORKBENCH-0" >/dev/null 2>&1
}

eval_workbench() {
  oc -n "$NS" get notebook "$WORKBENCH" -o json | jq --arg name "$WORKBENCH" --arg stopped "$WORKBENCH_STOPPED" '
    del(.metadata.annotations[$stopped])
    | .spec.template.spec.containers |= map(if .name != $name then . else
        .envFrom = ([(.envFrom // [])[] | select(.configMapRef.name != "ordo-config")]
                    + [{configMapRef: {name: "ordo-config"}}])
        | .env = ([(.env // [])[] | select(.name != "MLFLOW_TRACKING_TOKEN" and .name != "MLFLOW_GENAI_EVAL_MAX_WORKERS")]
                  + [{name: "MLFLOW_TRACKING_TOKEN", valueFrom: {secretKeyRef: {name: "llm-token", key: "token"}}},
                     {name: "MLFLOW_GENAI_EVAL_MAX_WORKERS", value: "1"}])
      end)' | oc replace -f -
  sleep 10
  wait_for "workbench $WORKBENCH to be ready" 600 workbench_ready
  check_workbench
}

check_workbench() {
  local host
  oc -n "$NS" exec "$WORKBENCH-0" -c "$WORKBENCH" -- bash -c '
    failed=0
    for name in "$@"; do
      if [[ -n "${!name:-}" ]]; then echo "OK   $name is set"; else echo "FAIL $name is not set" >&2; failed=1; fi
    done
    exit $failed' _ "${WORKBENCH_ENV[@]}"
  host="$(oc -n redhat-ods-applications get route data-science-gateway -o jsonpath='{.spec.host}' 2>/dev/null)" || host=""
  echo "     open https://${host:-<data-science-gateway>}/notebook/$NS/$WORKBENCH/lab"
  echo "     then Collabothon-2026/notebooks/extraction_eval.ipynb (git pull first); stop it with: $0 stop-workbench"
}

stop_workbench() {
  oc -n "$NS" annotate notebook "$WORKBENCH" "$WORKBENCH_STOPPED=$(date -u +%Y-%m-%dT%H:%M:%SZ)" --overwrite
  wait_for "workbench $WORKBENCH to stop" 300 workbench_gone
  echo "OK   workbench $WORKBENCH is stopped: no pod $WORKBENCH-0"
}

SMOKE_DOC=doc_rcpt412
SMOKE_RECEIPT="$ROOT/sim/documents/november/$SMOKE_DOC.jpg"
SMOKE_TRUTH="$ROOT/sim/scenario/out/november_documents.json"
SMOKE_BODY=""

smoke_ok() {
  echo "OK   $1: $2"
}

smoke_fail() {
  echo "FAIL $1: $2"
}

smoke_get() {
  local url="$1" token="${2:-}" auth=()
  if [[ -n "$token" ]]; then
    auth=(-H "Authorization: Bearer $token")
  fi
  curl -s -o "$SMOKE_BODY" -w '%{http_code}' --max-time 20 "${auth[@]}" "$url" || true
}

smoke_route() {
  local name="$1" host code anonymous
  host="$(oc -n "$NS" get route "$name" -o jsonpath='{.spec.host}')"
  case "$name" in
    ordo-web)
      code="$(smoke_get "https://$host/")"
      if [[ "$code" == 200 ]] && grep -q '<div id="root">' "$SMOKE_BODY"; then
        smoke_ok "route $name" "https://$host/ opens the app"
      else
        smoke_fail "route $name" "https://$host/ answered HTTP $code without the app"
      fi
      ;;
    ordo-api)
      code="$(smoke_get "https://$host/api/v1/health")"
      if [[ "$code" == 200 ]] && jq -e '.llm.reachable == true' "$SMOKE_BODY" >/dev/null; then
        smoke_ok "route $name" "https://$host/api/v1/health: $(jq -r '.llm.model + " reachable at " + .llm.base_url' "$SMOKE_BODY")"
      else
        smoke_fail "route $name" "https://$host/api/v1/health answered HTTP $code: $(head -c 200 "$SMOKE_BODY")"
      fi
      ;;
    gpt-oss-20b)
      anonymous="$(smoke_get "https://$host/v1/models")"
      code="$(smoke_get "https://$host/v1/models" "$(oc whoami -t)")"
      if [[ "$anonymous" == 401 && "$code" == 200 ]] && jq -e '.data | any(.id == "gpt-oss-20b")' "$SMOKE_BODY" >/dev/null; then
        smoke_ok "route $name" "https://$host/v1/models: 401 without a token, serves gpt-oss-20b with one"
      else
        smoke_fail "route $name" "https://$host/v1/models answered HTTP $anonymous without a token, HTTP $code with one"
      fi
      ;;
    ordo-guardrails)
      code="$(smoke_get "https://$host/")"
      if [[ "$code" == 401 ]]; then
        smoke_ok "route $name" "https://$host/ refuses calls without a token (HTTP 401)"
      else
        smoke_fail "route $name" "https://$host/ answered HTTP $code, expected 401 from its auth proxy"
      fi
      ;;
    ordo-grafana)
      code="$(smoke_get "https://$host/api/health")"
      if [[ "$code" == 200 ]] && jq -e '.database == "ok"' "$SMOKE_BODY" >/dev/null; then
        smoke_ok "route $name" "https://$host/api/health: Grafana $(jq -r '.version' "$SMOKE_BODY"), database ok"
      else
        smoke_fail "route $name" "https://$host/api/health answered HTTP $code: $(head -c 200 "$SMOKE_BODY")"
      fi
      ;;
    ordo-pgadmin)
      code="$(smoke_get "https://$host/misc/ping")"
      if [[ "$code" == 200 ]]; then
        smoke_ok "route $name" "https://$host/misc/ping answers"
      else
        smoke_fail "route $name" "https://$host/misc/ping answered HTTP $code"
      fi
      ;;
    *)
      smoke_fail "route $name" "setup.sh has no smoke probe for this route"
      ;;
  esac
}

smoke_routes() {
  local name
  for name in $(oc -n "$NS" get routes -o jsonpath='{.items[*].metadata.name}'); do
    smoke_route "$name"
  done
}

smoke_mlflow() {
  local url code
  url="$(oc get mlflow mlflow -o jsonpath='{.status.url}' 2>/dev/null)"
  if ! mlflow_available; then
    smoke_fail mlflow "the MLflow CR mlflow is not Available"
    return
  fi
  code="$(smoke_get "$url/")"
  if [[ "$code" == 200 || "$code" == 302 ]]; then
    smoke_ok mlflow "CR Available, the UI at $url answers HTTP $code"
  else
    smoke_fail mlflow "CR Available, but the UI at $url answered HTTP $code"
  fi
}

smoke_workloads() {
  local name want ready
  while read -r name want ready; do
    if ((want == 0)); then
      smoke_fail "deployment $name" "scaled to 0"
    elif ((ready >= want)); then
      smoke_ok "deployment $name" "$ready/$want ready"
    else
      smoke_fail "deployment $name" "$ready/$want ready"
    fi
  done < <(oc -n "$NS" get deployments -o json |
    jq -r '.items[] | "\(.metadata.name) \(.spec.replicas // 1) \(.status.readyReplicas // 0)"')
  if [[ "$(oc -n "$NS" get inferenceservice gpt-oss-20b \
    -o jsonpath='{.status.conditions[?(@.type=="Ready")].status}' 2>/dev/null)" == True ]]; then
    smoke_ok "inferenceservice gpt-oss-20b" "Ready"
  else
    smoke_fail "inferenceservice gpt-oss-20b" "not Ready: oc -n $NS describe inferenceservice gpt-oss-20b"
  fi
  for name in $(oc -n "$NS" get notebooks -o json |
    jq -r --arg stopped "$WORKBENCH_STOPPED" '.items[] | select(.metadata.annotations[$stopped] == null) | .metadata.name'); do
    echo "NOTE workbench $name is running; stop it before the demo: $0 stop-workbench"
  done
}

smoke_in_pod() {
  local deployment="$1" container="$2"
  shift 2
  if ! oc -n "$NS" exec -i "deployment/$deployment" -c "$container" -- python -c "$(cat "$HERE/smoke.py")" "$@"; then
    smoke_fail "$deployment" "smoke.py $1 did not run in the pod"
  fi
}

smoke_extract() {
  local amount currency
  read -r amount currency < <(jq -r --arg id "$SMOKE_DOC" '.[] | select(.id == $id) | "\(.totals.gross) \(.currency)"' "$SMOKE_TRUTH")
  smoke_in_pod ordo-extractor extractor extract "$(basename "$SMOKE_RECEIPT")" "$amount" "$currency" <"$SMOKE_RECEIPT"
}

smoke_checks() {
  set +e
  echo "     smoke $(date -u +%FT%TZ) as $(oc whoami) on $(oc whoami --show-server)"
  smoke_workloads
  smoke_routes
  smoke_mlflow
  smoke_in_pod ordo-api api api </dev/null
  smoke_extract
}

smoke() {
  local log total failed
  SMOKE_BODY="$(mktemp)"
  log="$(mktemp)"
  smoke_checks 2>&1 | tee "$log" || true
  total="$(grep -cE '^(OK|FAIL) ' "$log" || true)"
  failed="$(grep -E '^FAIL ' "$log" | sed -E 's/^FAIL +([^:]+):.*/\1/' | awk '!seen[$0]++' | paste -sd ';' - || true)"
  rm -f "$log" "$SMOKE_BODY"
  if [[ -n "$failed" ]]; then
    echo "smoke: $total checks, FAIL: ${failed//;/, }" >&2
    return 1
  fi
  echo "smoke: $total checks, all OK"
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
  bank-csv) bank_csv "$@" ;;
  redeploy) redeploy ;;
  check-bank) check_bank ;;
  check-m2) check_m2 ;;
  verify) verify ;;
  webhook-urls) webhook_urls ;;
  freeze) freeze ;;
  tag-demo) tag_demo ;;
  app) app ;;
  db-fixtures) db_fixtures ;;
  ogx) ogx ;;
  check-ogx) check_ogx ;;
  ogx-off) ogx_off ;;
  guardrails) guardrails ;;
  check-guardrails) check_guardrails "$@" ;;
  guardrails-off) guardrails_off ;;
  check-m1) check_m1 ;;
  monitoring) monitoring ;;
  check-monitoring) check_monitoring ;;
  grafana) grafana ;;
  grafana-dashboards) grafana_reload_dashboards ;;
  check-grafana) check_grafana ;;
  mlflow) mlflow ;;
  check-mlflow) check_mlflow ;;
  eval-workbench) eval_workbench ;;
  check-workbench) check_workbench ;;
  stop-workbench) stop_workbench ;;
  smoke) smoke ;;
  *)
    echo "usage: $0 secrets|apply|bank-csv|build|dev-build|dev-build-web|app|redeploy|db-fixtures|ogx|check-ogx|ogx-off|guardrails|check-guardrails|guardrails-off|check-m1|check-m2|check-bank|monitoring|check-monitoring|grafana|grafana-dashboards|check-grafana|mlflow|check-mlflow|eval-workbench|check-workbench|stop-workbench|smoke|verify|webhook-urls|freeze|tag-demo [${IMAGES[*]}]" >&2
    exit 2
    ;;
esac
