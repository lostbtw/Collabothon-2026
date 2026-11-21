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

## Demo day

`setup.sh freeze` turns the webhook builds off, so a push no longer changes the cluster; after that, deploy a fix with `setup.sh build <name>`. `redeploy` does not turn the webhooks back on. `setup.sh tag-demo` tags the current images as `demo`.
