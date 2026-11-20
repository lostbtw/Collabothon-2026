"""Seam: the command line. Every backend process starts as `python -m backend <name>`."""
import subprocess
import sys

import pytest


@pytest.mark.parametrize("name", ["api", "connectors", "pipeline", "agents"])
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
