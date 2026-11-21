"""Seam: the command line. Every backend process starts as `python -m backend <name>`."""
import subprocess
import sys

import pytest


@pytest.mark.parametrize("name", ["api", "connectors", "pipeline", "agents", "finance"])
def test_each_entrypoint_starts_and_exits_cleanly(name):
    result = subprocess.run(
        [sys.executable, "-m", "backend", name, "--check"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert name in result.stdout


def test_unknown_entrypoint_is_refused():
    result = subprocess.run(
        [sys.executable, "-m", "backend", "nonsense"],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode != 0


def test_every_process_that_traces_imports_the_tracing_module():
    """`--check` only imports a process; a name its `run` uses but never imports fails on the cluster at start."""
    import ast
    import importlib
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    for path in root.rglob("main.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        bases = {n.value.id for n in ast.walk(tree)
                 if isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name) and n.value.id == "tracing"}
        if bases:
            module = importlib.import_module(".".join(path.relative_to(root.parent).with_suffix("").parts))
            assert hasattr(module, "tracing"), f"{path.relative_to(root.parent)} calls tracing.* without importing it"
