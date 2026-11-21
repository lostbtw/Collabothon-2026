import json
import os
import socket
import sys
import urllib.error
import urllib.request

REQUIRED = ["acc_pln", "acc_eur", "acc_owner", "acc_pizzeria"]


def fail(message):
    print(f"FAIL {socket.gethostname()}: {message}", file=sys.stderr)
    sys.exit(1)


def get(base, path, headers=None):
    request = urllib.request.Request(base.rstrip("/") + path, headers=headers or {})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        fail(f"GET {path} answered HTTP {exc.code}: {exc.read().decode(errors='replace')[:200]}")
    except (urllib.error.URLError, OSError) as exc:
        fail(f"GET {path} did not answer: {exc}")


def main():
    base = os.environ.get("ORDO_BANK_URL", "")
    token = os.environ.get("ORDO_BANK_TOKEN", "")
    if not base or not token:
        fail("ORDO_BANK_URL or ORDO_BANK_TOKEN is not set in this pod")

    health = get(base, "/health")
    if health.get("simulated") is not True:
        fail(f"{base}/health is not the Sandbox Bank: {health}")

    psd2 = {"Authorization": f"Bearer {token}", "Consent-ID": "demo"}
    accounts = {a["resourceId"]: a for a in get(base, "/v1/accounts", psd2)["accounts"]}
    missing = [a for a in REQUIRED if a not in accounts]
    if missing:
        fail(f"accounts missing in the bank: {', '.join(missing)}")

    shown = []
    for account_id in REQUIRED:
        balances = get(base, f"/v1/accounts/{account_id}/balances", psd2).get("balances") or []
        if balances:
            amount = balances[0]["balanceAmount"]
            shown.append(f"{account_id} {amount['amount']} {amount['currency']}")
        else:
            shown.append(f"{account_id} no balance")
    print(f"OK   {socket.gethostname()} reaches the Sandbox Bank at {base}: {'; '.join(shown)}")


main()
