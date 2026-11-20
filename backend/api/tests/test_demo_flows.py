"""Seam: the M3 / M4 demo flows over the HTTP API (on stand-ins until the other roles' code lands)."""
import pytest
from fastapi.testclient import TestClient

from backend.api.app import create_app
from backend.api.demo import hero, liquidity_flow
from backend.db.fixtures import load_fixtures


@pytest.fixture
def api(db, db_url):
    load_fixtures(db)
    with TestClient(create_app(database_url=db_url, chat_model=lambda: None), base_url="http://testserver/api/v1") as c:
        yield c


def test_the_hero_flow_runs_end_to_end_inside_the_time_budget(api, db):
    run = hero(api, db)

    assert run.ok, run.report()
    assert [s.name for s in run.steps][-1].startswith("phone to forecast under 30 s")
    assert any(s.name.startswith("owner approves") and "SIM-PD-" in s.detail for s in run.steps)


def test_the_liquidity_flow_runs_end_to_end(api, db):
    run = liquidity_flow(api, db)

    assert run.ok, run.report()
    assert any("SIM-CL-" in s.detail for s in run.steps)
