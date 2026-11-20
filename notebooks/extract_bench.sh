#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

export ORDO_LLM_BASE_URL="${ORDO_LLM_BASE_URL:-https://gpt-oss-20b-predictor.cfo-ai.svc.cluster.local:8443/v1}"
export ORDO_DOCLING_URL="${ORDO_DOCLING_URL:-http://docling-serve.cfo-ai.svc.cluster.local:5001}"

python3 -m pip install -q --index-url https://pypi.org/simple "openai==3.57.0" "httpx==0.28.1" "jsonschema==4.26.0"
export PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}"
exec python3 -m backend.pipeline.extract.bench "$@"
