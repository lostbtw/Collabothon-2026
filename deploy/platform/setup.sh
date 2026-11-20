#!/usr/bin/env bash
set -euo pipefail

NS=cfo-ai
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
IMAGES=(backend)

apply() {
  oc apply -f "$HERE/builds.yaml"
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

oc whoami >/dev/null

stage="${1:-}"
shift || true

case "$stage" in
  apply) apply ;;
  build) build "$@" ;;
  dev-build) dev_build "$@" ;;
  *)
    echo "usage: $0 apply|build|dev-build [${IMAGES[*]}]" >&2
    exit 2
    ;;
esac
