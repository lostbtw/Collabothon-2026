"""One package, five processes: `python -m backend <api|connectors|pipeline|agents|mcp> [--check]`, each in `backend/<folder>/main.py`."""
import argparse
import importlib
import importlib.util
import sys

ENTRYPOINTS = {
    "api": ("backend.api.main", "role 5"),
    "connectors": ("backend.connectors.main", "role 2"),
    "pipeline": ("backend.pipeline.main", "role 3"),
    "agents": ("backend.agents.main", "role 5"),
    "finance": ("backend.finance.main", "role 4"),
    "mcp": ("backend.agents.mcp_server", "role 5"),
    "demo-reset": ("backend.agents.demo_reset", "role 5"),
}


def _module_exists(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except ModuleNotFoundError:
        return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend")
    parser.add_argument("process", choices=sorted(ENTRYPOINTS))
    parser.add_argument("--check", action="store_true", help="import and exit without serving")
    args, rest = parser.parse_known_args(argv)

    module_name, owner = ENTRYPOINTS[args.process]
    if not _module_exists(module_name):
        print(f"{args.process}: placeholder ({module_name} not written yet, owner {owner})")
        return 0

    module = importlib.import_module(module_name)
    if args.check:
        print(f"{args.process}: ok ({module_name})")
        return 0
    return module.run(rest) or 0


if __name__ == "__main__":
    sys.exit(main())
