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
| `ordo-finance` | `ordo-backend` | Books the Ledger from decided Matches and recomputes the forecast after every change (debounced 2 s per company) |
| `ordo-mcp` | `ordo-backend` | The agents' tools as an MCP server, in-cluster only at `http://ordo-mcp.cfo-ai.svc.cluster.local:8000/mcp`; also OGX's way to the model (`/model/v1`) |
| `ordo-ogx` (OGXServer) | OGX `rh` distribution | OGX in front of the model; runs the agents' tool loop and calls `ordo-mcp` (only after `setup.sh ogx`) |
| `ordo-guardrails` (NemoGuardrails) | TrustyAI NeMo Guardrails server | Masks IBANs, card numbers and tax ids and refuses off-topic questions before the chat calls the model (only after `setup.sh guardrails`) |
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
| `smoke` (`make smoke`) | The whole cluster in about 40 s, one line per check, nothing written to the demo data: every Deployment and the InferenceService ready; every Route answers as it should (a Route without a probe in `setup.sh` fails); MLflow up. From `ordo-api`: the database, the outbox (no dead delivery, nothing waiting over 2 min), gpt-oss-20b (refuses calls without a token, answers one question), the guardrails mask an IBAN, OGX, `ordo-mcp` lists its tools, the Sandbox Bank. From `ordo-extractor`: docling-serve, then the hero backup receipt `doc_rcpt412.jpg` read end to end (docling-serve, gpt-oss-20b, the checks) against its Ground truth within 30 s, traced to MLflow experiment `ordo-smoke`. Ends with `smoke: N checks, all OK` or the components that failed |
| `check-m2` | The web route opens the app; `/api/v1/health` reports the model reachable; the API serves data; `check-bank` |
| `check-bank` | `ordo-api` and `ordo-connectors` reach the Sandbox Bank and see its four accounts |
| `check-m1` | The chat answers with text from gpt-oss-20b |
| `verify` | Postgres and the raw volume work from a pod, every container has requests and limits, no secret value is in Git |
| `check-ogx` | One chat question goes through OGX; prints the model OGX used, each tool it called over MCP and the answer |
| `check-guardrails [rails]` | The rails mask an IBAN, block "Which stock should I buy?" and let the five tool questions pass; then (without `rails`) the chat refuses the stock question, stores and answers an IBAN message masked, and answers the read-only tool questions |
| `check-monitoring` | Prometheus scrapes gpt-oss-20b, its vLLM metrics are queryable, every rule in `deploy/observability/prometheus-rules.yaml` evaluates without errors; lists the alerts firing in `cfo-ai` |

## OGX + MCP

```bash
deploy/platform/setup.sh ogx
```

This turns on the OGX Operator (`DataScienceCluster` `spec.components.ogx`, and `llamastackoperator` to `Removed`, which OGX replaces and refuses to run next to; cluster-wide, needs cluster-admin), creates the database `ogx` that OGX keeps its own state in, starts `ordo-mcp` and the OGX server `ordo-ogx`, applies `deploy/app/ogx-config.yaml` and runs `check-ogx`.

From then on the chat (`ordo-api`) and the liquidity and FX Shield agents (`ordo-agents`) ask OGX's Responses API instead of running their own tool loop: OGX talks to gpt-oss-20b and calls Ordo's tools on `ordo-mcp`. The answer passes the same checks as before (JSON schema, no number that no tool returned). If OGX does not answer, each agent runs its own loop against the model, so the app keeps working.

OGX reaches the model through `ordo-mcp` (`/model/v1`), not directly: OGX hands a tool's result to the model as text parts, the gpt-oss chat handler of our vLLM accepts only plain text there, and the pass-through converts it. Nothing else is changed on the way.

`deploy/platform/setup.sh ogx-off` switches the agents back; OGX and `ordo-mcp` stay up.

Where to look: `oc -n cfo-ai logs deployment/ordo-mcp` shows every tool call OGX made; `oc -n cfo-ai logs deployment/ordo-api | grep ogx` shows each run.

## NeMo Guardrails

```bash
deploy/platform/setup.sh guardrails
```

This starts the NeMo Guardrails server through the TrustyAI operator (`NemoGuardrails` CR `ordo-guardrails`, config `ordo-chat` in `deploy/guardrails/nemo-guardrails.yaml`), checks its rails, then creates ConfigMap `ordo-guardrails-client`, restarts `ordo-api` and checks the chat through them.

From then on the chat sends every owner message to the server's `POST /v1/checks` before anything else sees it:

- **Masking** (Presidio, offline): IBANs (also the Polish 26-digit form and ones with a wrong checksum), card numbers and tax ids (NIP, German USt-IdNr and Steuernummer) become `<IBAN_CODE>`, `<CREDIT_CARD>`, `<TAX_ID>`. The model, the OGX run, the chat history and any inbox card get only the masked text, and the MLflow trace `chat.guardrails` records only that.
- **Topic rail** (`self check input`, asked of gpt-oss-20b after masking, about 1 s): investment advice and anything that is not about the company's finances is refused without a model call or a tool. The answer's `guardrail` field is `{blocked: true, reason}`, which the chat panel shows.
- **No answer from the server**: that turn is masked locally with the same patterns and answered without the model.

The server is in-cluster behind kube-rbac-proxy (`https://ordo-guardrails.cfo-ai.svc.cluster.local`); the operator's Route ends at the same proxy. Callers need a token that may `get` services in `cfo-ai`; the app uses ServiceAccount `cfo-app` (Secret `llm-token`). Two quirks of the RHOAI 3.5 operator, both handled in the manifest and `setup.sh`: the CR has no resources field, so the server's 3 Gi memory limit comes from LimitRange `ordo-defaults` (spaCy's model was OOMKilled at 1 Gi); and the proxy's access check carries no service name, so the Role cannot be narrowed to one Service.

`deploy/platform/setup.sh guardrails-off` switches the chat back to running without the check; the server stays up. The first check after a server start takes about 10 s (spaCy loads), the rest about 1 s.

Where to look: `oc -n cfo-ai logs deployment/ordo-guardrails -c nemo-guardrails` shows every check and the topic rail's answer.

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

## MLflow

```bash
deploy/platform/setup.sh mlflow
```

The stage switches the RHOAI component `mlflowoperator` to `Managed` in DataScienceCluster `default-dsc` (an operator change: never after Saturday 18:00), waits for the operator, then applies `deploy/platform/mlflow.yaml`: the cluster-scoped `MLflow` CR `mlflow` (MLflow 3.14, SQLite and artifacts on one 5 Gi PVC, 1 replica, 2 Gi limit) and a RoleBinding that gives SA `cfo-app` the ClusterRole `mlflow-operator-mlflow-integration` (the operator installs it with that prefix) in `cfo-ai`. MLflow keeps its own storage, apart from the ledger database. Each namespace is an MLflow workspace; the app writes to workspace `cfo-ai` with the `llm-token` bearer token.

The app traces into it from three processes: `ordo-extractor` (experiment `ordo-extraction`), `ordo-agents` and `ordo-api` (experiment `ordo-agents`, the liquidity wording and chat turns). `ordo-config` carries `MLFLOW_TRACKING_URI` (the in-cluster address), `MLFLOW_WORKSPACE=cfo-ai` and the service CA as `MLFLOW_TRACKING_SERVER_CERT_PATH`; those three Deployments also get `MLFLOW_TRACKING_TOKEN` from secret `llm-token`. A process without `MLFLOW_TRACKING_URI`, or one that cannot reach MLflow at start, runs without tracing and logs `tracing off`. Tracing adds about 45 MiB per process.

`check-mlflow`: prints the conditions, the in-cluster address and the UI URL, then from the `ordo-extractor` pod (trusting the service CA) checks `/health` and reads, or creates, the experiments `ordo-extraction`, `ordo-agents` and `ordo-evaluation` as `cfo-app`.

## Evaluation workbench

```bash
deploy/platform/setup.sh eval-workbench   # MLflow settings onto workbench model-tests, start it
deploy/platform/setup.sh stop-workbench   # stop it again: it never runs during the demo
```

The evaluation notebook `notebooks/extraction_eval.ipynb` (#19) runs in the Jupyter workbench `model-tests` in `cfo-ai` (made in the RHOAI dashboard: Data Science CPU image, 2 CPU / 4 Gi, repo cloned in its volume). `eval-workbench` gives its notebook container what `ordo-extractor` has: `envFrom` ConfigMap `ordo-config` (model, docling and MLflow addresses, workspace `cfo-ai`) and `MLFLOW_TRACKING_TOKEN` from secret `llm-token`; the model and docling keys were already set in the dashboard. It also sets `MLFLOW_GENAI_EVAL_MAX_WORKERS=1`, so documents are read one at a time and the timings are real. It then removes the `kubeflow-resource-stopped` annotation, waits for the pod, and `check-workbench` prints which variables are set (names only) and the workbench URL. `stop-workbench` sets the annotation and waits until the pod is gone.

The notebook reads the 47 November documents and the real receipt photos in `notebooks/receipt_photos/` through `extract_document()`. It compares gross, date, seller NIP and VAT with the Ground truth and logs one evaluation run (`mlflow.genai.evaluate`, one trace per document) to experiment `ordo-evaluation`. Phone photos go through `notebooks/strip_exif.py` before they are committed.

## Demo day

Sunday 07:00: run `make smoke` twice (without `make`: `deploy/platform/setup.sh smoke`), restart whatever it names, and stop the workbench when it prints a NOTE. A run during a rollout fails on the Deployment that is rolling out (every push to `main` restarts the Sandbox Bank); run it again once `oc -n cfo-ai get deployments` shows everything ready.

`setup.sh freeze` turns the webhook builds off, so a push no longer changes the cluster; after that, deploy a fix with `setup.sh build <name>`. `redeploy` does not turn the webhooks back on. `setup.sh tag-demo` tags the current images as `demo`.
