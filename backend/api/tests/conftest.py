import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.db.seed import seed


@pytest.fixture
def client(db, db_url):
    """The API on an empty, seeded test database."""
    seed(db)
    with TestClient(create_app(database_url=db_url)) as c:
        yield c
