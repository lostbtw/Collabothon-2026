import os
import sys

import httpx


def main():
    base = os.environ.get("ORDO_WHISPER_URL", "").rstrip("/")
    key = os.environ.get("ORDO_WHISPER_API_KEY", "")
    model = os.environ.get("ORDO_WHISPER_MODEL", "")
    missing = [name for name, value in [("ORDO_WHISPER_URL", base), ("ORDO_WHISPER_API_KEY", key),
                                        ("ORDO_WHISPER_MODEL", model)] if not value]
    if missing:
        print(f"FAIL whisper: {', '.join(missing)} not set in this pod")
        return 1
    root = base.removesuffix("/v1")
    auth = {"Authorization": f"Bearer {key}"}
    failed = 0
    with httpx.Client(timeout=15) as client:
        anonymous = client.get(f"{root}/health").status_code
        if anonymous == 401 or anonymous == 403:
            print(f"OK   whisper: {root}/health refuses calls without the key (HTTP {anonymous})")
        else:
            print(f"FAIL whisper: {root}/health answered HTTP {anonymous} without the key")
            failed = 1
        loaded = client.get(f"{root}/api/ps", headers=auth).json()["models"]
        if model in loaded:
            print(f"OK   whisper: {model} is loaded ({', '.join(loaded)})")
        else:
            print(f"FAIL whisper: {model} is not loaded, loaded: {loaded}")
            failed = 1
        local = [item["id"] for item in client.get(f"{base}/models", headers=auth).json()["data"]]
        print(f"     models on the volume: {', '.join(local) or 'none'}")
    return failed


sys.exit(main())
