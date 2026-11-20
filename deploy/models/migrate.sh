#!/usr/bin/env bash
set -euo pipefail

NS=cfo-ai
NOTEBOOK=model-tests
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
MANIFESTS=(-f "$HERE/gpt-oss-20b.yaml" -f "$HERE/llm-client.yaml" -f "$HERE/docling-serve.yaml")
WORKBENCH_ENV=(ORDO_LLM_API_KEY ORDO_DOCLING_API_KEY)

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

token_ready() {
  [[ -n "$(oc -n "$NS" get secret llm-token -o jsonpath='{.data.token}' 2>/dev/null)" ]]
}

notebook_container_index() {
  oc -n "$NS" get notebook "$NOTEBOOK" -o jsonpath='{range .spec.template.spec.containers[*]}{.name}{"\n"}{end}' |
    awk -v name="$NOTEBOOK" '$0 == name { print NR - 1 }'
}

notebook_env_names() {
  oc -n "$NS" get notebook "$NOTEBOOK" -o jsonpath="{.spec.template.spec.containers[$1].env[*].name}" | tr ' ' '\n'
}

env_entry() {
  printf '{"op":"add","path":"/spec/template/spec/containers/%s/env/-","value":{"name":"%s","valueFrom":{"secretKeyRef":{"name":"%s","key":"%s"}}}}' "$1" "$2" "$3" "$4"
}

workbench_pod_has_env() {
  local names
  names="$(oc -n "$NS" get pod "$NOTEBOOK-0" -o jsonpath="{.spec.containers[?(@.name==\"$NOTEBOOK\")].env[*].name}" 2>/dev/null | tr ' ' '\n')"
  for name in "${WORKBENCH_ENV[@]}"; do
    grep -qx "$name" <<<"$names" || return 1
  done
}

prep() {
  oc apply -f "$HERE/llm-client.yaml" -f "$HERE/docling-serve.yaml"
  wait_for "the token in Secret llm-token" 120 token_ready

  local index
  index="$(notebook_container_index)"
  if [[ -z "$index" ]]; then
    echo "container $NOTEBOOK not found in notebook $NOTEBOOK" >&2
    exit 1
  fi

  local present ops=()
  present="$(notebook_env_names "$index")"
  grep -qx ORDO_LLM_API_KEY <<<"$present" || ops+=("$(env_entry "$index" ORDO_LLM_API_KEY llm-token token)")
  grep -qx ORDO_DOCLING_API_KEY <<<"$present" || ops+=("$(env_entry "$index" ORDO_DOCLING_API_KEY docling-api-key DOCLING_SERVE_API_KEY)")

  if ((${#ops[@]})); then
    oc -n "$NS" patch notebook "$NOTEBOOK" --type=json -p "[$(IFS=,; echo "${ops[*]}")]"
  else
    echo "notebook $NOTEBOOK already has ${WORKBENCH_ENV[*]}"
  fi

  wait_for "workbench pod $NOTEBOOK-0 with ${WORKBENCH_ENV[*]}" 600 workbench_pod_has_env
  oc -n "$NS" wait --for=condition=Ready "pod/$NOTEBOOK-0" --timeout=600s
}

cleanup() {
  oc -n "$NS" delete route docling-serve --ignore-not-found
  oc -n "$NS" delete inferenceservice qwen3-8b --ignore-not-found --timeout=300s
  oc -n "$NS" delete servingruntime qwen3-8b --ignore-not-found
  oc -n "$NS" delete secret cfo-app-token --ignore-not-found

  if oc diff "${MANIFESTS[@]}"; then
    echo "cluster matches deploy/models"
  else
    echo "cluster differs from deploy/models" >&2
    exit 1
  fi
}

oc whoami >/dev/null

case "${1:-}" in
  prep) prep ;;
  cleanup) cleanup ;;
  *)
    echo "usage: $0 prep|cleanup" >&2
    exit 2
    ;;
esac
