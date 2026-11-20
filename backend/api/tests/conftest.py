import contextlib
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.db.seed import seed

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "sim" / "bank"))
from bank_sim.app import create_app as create_bank  # noqa: E402
from bank_sim.store import Store as BankStore  # noqa: E402

BANK_TOKEN = "test-bank-token"


@pytest.fixture(autouse=True)
def sandbox_bank(monkeypatch):
    """Approved actions run against a Sandbox Bank (role 2's executor, #36): an in-process one, never a server
    that happens to listen on the default port. Yields the bank's TestClient (e.g. GET /admin/executions)."""
    import backend.executor.simulated as executor

    with TestClient(create_bank(BankStore(), token=BANK_TOKEN)) as bank:
        monkeypatch.setattr(executor, "make_client", lambda: contextlib.nullcontext(bank))
        monkeypatch.setenv("ORDO_BANK_TOKEN", BANK_TOKEN)
        yield bank


@pytest.fixture
def client(db, db_url):
    """The API on an empty, seeded test database."""
    seed(db)
    with TestClient(create_app(database_url=db_url)) as c:
        yield c
