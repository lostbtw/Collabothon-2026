"""`uv run python -m backend api [--host H] [--port P]`: serve the API with uvicorn."""
import argparse

import uvicorn

from backend.api.app import create_app


def run(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend api")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args(argv)
    uvicorn.run(create_app(), host=args.host, port=args.port)
    return 0
