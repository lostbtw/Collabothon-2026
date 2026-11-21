import json
import os
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request

EXPERIMENTS = ["ordo-extraction", "ordo-agents"]
WORKSPACE = "cfo-ai"
SERVICE_CA = "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt"


def fail(message):
    print(f"FAIL {socket.gethostname()}: {message}", file=sys.stderr)
    sys.exit(1)


def call(base, path, headers, body=None):
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(base.rstrip("/") + path, data=data, headers={
        **headers, **({"Content-Type": "application/json"} if data else {})})
    context = ssl.create_default_context(cafile=SERVICE_CA if os.path.isfile(SERVICE_CA) else None)
    try:
        with urllib.request.urlopen(request, timeout=15, context=context) as response:
            text = response.read().decode()
            return response.status, (json.loads(text) if text.strip().startswith("{") else text)
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read().decode(errors="replace")[:300]
    except (urllib.error.URLError, OSError) as exc:
        fail(f"{base}{path} did not answer: {exc}")


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else ""
    token = os.environ.get("LLM_TOKEN", "")
    if not base or not token:
        fail("usage: check_mlflow.py <in-cluster MLflow URL>, with LLM_TOKEN set in this pod")

    status, body = call(base, "/health", {})
    if status != 200:
        fail(f"{base}/health answered HTTP {status}: {body}")
    print(f"OK   {base}/health answers from a pod in {WORKSPACE}, trusting the service CA")

    headers = {"Authorization": f"Bearer {token}", "X-MLFLOW-WORKSPACE": WORKSPACE}
    for name in EXPERIMENTS:
        query = urllib.parse.urlencode({"experiment_name": name})
        status, body = call(base, f"/api/2.0/mlflow/experiments/get-by-name?{query}", headers)
        if status == 404:
            status, body = call(base, "/api/2.0/mlflow/experiments/create", headers, {"name": name})
            if status != 200:
                fail(f"cfo-app cannot create experiment {name} in workspace {WORKSPACE}: HTTP {status} {body}")
            print(f"OK   experiment {name} created in workspace {WORKSPACE}: id {body['experiment_id']}")
        elif status == 200:
            print(f"OK   experiment {name} exists in workspace {WORKSPACE}: id {body['experiment']['experiment_id']}")
        else:
            fail(f"cfo-app cannot read experiment {name} in workspace {WORKSPACE}: HTTP {status} {body}")


main()
