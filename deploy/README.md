# Deploying Ordo to the cluster

Everything runs in OpenShift project `cfo-ai`. The app is at https://ordo-cfo-ai.apps.ocp.w6k4q.sandbox2219.opentlc.com (web on `/`, API on `/api`). Only role 1 deploys after the feature freeze.

## Redeploy from `main`

```bash
deploy/platform/setup.sh redeploy
```

This builds the three images (`ordo-backend`, `ordo-web`, `ordo-sim`) from `main` on the cluster, applies `deploy/app/`, waits for every rollout and runs `check-m2`. It needs `oc` logged in to the cluster, plus `jq` and `curl`.

A push to `main` already does most of this on its own: a GitHub webhook starts the three builds, and each Deployment rolls out the new image. Run `redeploy` after changing anything in `deploy/app/`, or to check that the cluster matches `main`.

## What runs where

| Deployment | Image | What it does |
|---|---|---|
| `ordo-web` | `ordo-web` | The built frontend on nginx |
| `ordo-api` | `ordo-backend` | The API, the approvals and the simulated executor |
| `ordo-connectors` | `ordo-backend` | Polls the Sandbox Bank, the invoices mailbox and the NBP rates |
| `ordo-pipeline` | `ordo-backend` | Normalises and matches |
| `ordo-extractor` | `ordo-backend` | Reads photos and PDFs through docling-serve and gpt-oss-20b |
| `ordo-agents` | `ordo-backend` | Turns new Matches and forecasts into inbox cards (ingestion, liquidity, receivables agents) |
| `ordo-bank` | `ordo-sim` | The Sandbox Bank, in-cluster only at `http://ordo-bank.cfo-ai.svc.cluster.local:8081` |
| `postgresql` | `rhel9/postgresql-16` | The database |
| `gpt-oss-20b-predictor`, `docling-serve` | see `deploy/models/` | The model and OCR |

The Sandbox Bank keeps its state in memory. Each start loads Borsuk Labs' accounts from `sim/scenario/out` (inside the image) and the pizzeria account from ConfigMap `bank-pizzeria-csv`. A new `ordo-sim` image, which every push to `main` builds, restarts the bank, so executions are lost.

## First set-up of an empty project

```bash
deploy/platform/setup.sh secrets
deploy/platform/setup.sh apply
deploy/platform/setup.sh bank-csv <path to pizzeria-amalfi-bank-statement-2025-v6.csv>
deploy/platform/setup.sh redeploy
```

`llm-token` and `docling-api-key` come from `deploy/models/` (see `deploy/secrets.example.yaml`). The pizzeria CSV is the organisers' file and stays out of Git. Run `bank-csv` again to replace it, which also restarts the bank.

## Checks

| Stage | Checks |
|---|---|
| `check-m2` | The web route opens the app; `/api/v1/health` reports the model reachable; the API serves data; `check-bank` |
| `check-bank` | `ordo-api` and `ordo-connectors` reach the Sandbox Bank and see its four accounts |
| `check-m1` | The chat answers with text from gpt-oss-20b |
| `verify` | Postgres and the raw volume work from a pod, every container has requests and limits, no secret value is in Git |
| `check-monitoring` | Prometheus scrapes gpt-oss-20b, its vLLM metrics are queryable, every rule in `deploy/observability/prometheus-rules.yaml` evaluates without errors; lists the alerts firing in `cfo-ai` |

## Monitoring

```bash
deploy/platform/setup.sh monitoring
```

This turns on OpenShift monitoring for user-defined projects (cluster-wide, needs cluster-admin; it refuses to overwrite a `cluster-monitoring-config` that holds other settings), keeps 48 h of metrics, loads the rules in `deploy/observability/` and runs `check-monitoring`. Prometheus then scrapes the ServiceMonitor `gpt-oss-20b-metrics`, which KServe created for the model.

Where to look: in the console, **Observe → Metrics** for queries and **Observe → Alerting** for alerts (project `cfo-ai`). The alerts are only listed there; no receiver is configured, so nothing is sent anywhere.

| Question | PromQL |
|---|---|
| Time to first token, p95 over 5 min | `model_name:vllm_time_to_first_token_seconds:p95_5m` |
| Whole request, p95 over 5 min | `model_name:vllm_e2e_request_latency_seconds:p95_5m` |
| Tokens per second generated | `model_name:vllm_generation_tokens:rate1m` |
| Requests per second | `model_name:vllm_requests:rate5m` |
| Share of answers cut off at `max_tokens` | `model_name:vllm_requests_cut_off:ratio_15m` |
| Requests running / waiting for the GPU | `vllm:num_requests_running`, `vllm:num_requests_waiting` |
| KV cache use (1 = full) | `vllm:kv_cache_usage_perc` |
| GPU use and memory (admin perspective only) | `DCGM_FI_DEV_GPU_UTIL`, `DCGM_FI_DEV_FB_USED` |

| Alert | Fires when |
|---|---|
| `OrdoModelDown` (critical) | Prometheus cannot scrape the vLLM pod for 2 min |
| `OrdoModelRequestsQueued` | Requests wait for the GPU for 2 min |
| `OrdoModelKvCacheFull` | KV cache over 90 % for 5 min |
| `OrdoModelPreempting` | vLLM preempted a request in the last 10 min |
| `OrdoModelSlowFirstToken` | TTFT p95 over 2 s for 5 min (normal: under 0.25 s) |
| `OrdoModelAnswersCutOff` | Over 20 % of answers stop at `max_tokens` for 10 min (a guidellm run also triggers it) |
| `OrdoDeploymentUnavailable` | Any Deployment in `cfo-ai` (ordo-*, docling-serve, postgresql, the model) has no ready pod for 5 min |
| `OrdoPodRestarting` | A container in `cfo-ai` restarted more than twice in 15 min |

Not covered by these alerts: docling-serve v1.9.0 has no `/metrics`, and the outbox queues live in Postgres, not Prometheus (Grafana below shows them).

## Grafana

```bash
deploy/platform/setup.sh grafana
```

Grafana runs in `cfo-ai` at the route `ordo-grafana` (`oc -n cfo-ai get route ordo-grafana`). Log in as `admin`; the password is in secret `ordo-grafana`: `oc -n cfo-ai extract secret/ordo-grafana --keys=GF_SECURITY_ADMIN_PASSWORD --to=-`. The stage creates that secret if missing, creates the database role `grafana_ro` (it can only read `outbox`, `outbox_delivery`, `outbox_subscription`, `recommendations`, `sources`, `sync_runs` and `companies`; read-only transactions, 15 s statement timeout), loads the dashboards and runs `check-grafana`.

| Dashboard | Data source | Shows |
|---|---|---|
| **Ordo pipeline** (home) | Postgres: the outbox | The data flow as a node graph (processes, the events between them, what waits and what is dead); deliveries waiting per consumer group; events per minute by type; seconds per stage; every receipt and invoice followed through its `correlation_id` to document, match and inbox card; last sync per source; dead deliveries |
| **Ordo model and GPU** | Prometheus (Thanos Querier) | Model up, requests running and waiting, KV cache, time to first token and request latency, tokens per second, answers by finish reason, GPU use, memory, power and temperature, CPU and memory per container (docling-serve's CPU is the OCR load) |

The dashboards are generated: change the queries in `deploy/observability/make_dashboards.py`, run `python3 deploy/observability/make_dashboards.py`, then `setup.sh grafana-dashboards`. That updates ConfigMap `grafana-dashboards` and waits until Grafana serves the new version (the mounted ConfigMap can take a few minutes to change), with no restart. `setup.sh grafana` restarts Grafana, which logs everyone out: logins live in the pod. They are read-only in Grafana. Grafana keeps no state of its own (emptyDir), so anything built by hand in the UI is gone after a restart. It sends nothing outside the cluster: usage reports, update checks, the news feed and plugin downloads are off.

`check-grafana`: Grafana answers, both datasources pass their health check, both dashboards are loaded, every panel type is a panel plugin Grafana knows (a wrong id such as `nodegraph` instead of `nodeGraph` shows as "Panel plugin not found"), and every panel query of every dashboard runs through Grafana's query API against the last 6 hours without an error.

## Demo day

`setup.sh freeze` turns the webhook builds off, so a push no longer changes the cluster; after that, deploy a fix with `setup.sh build <name>`. `redeploy` does not turn the webhooks back on. `setup.sh tag-demo` tags the current images as `demo`.
