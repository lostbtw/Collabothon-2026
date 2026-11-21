"""Seam: the M3 / M4 demo flows over the HTTP API. M3 still writes its first half on stand-ins; M4 runs through
the real agents, executor and finance engine (`drive` runs them in-process)."""
import pytest
from fastapi.testclient import TestClient

from backend.agents import main as agents
from backend.api.app import create_app
from backend.api.demo import hero, liquidity_flow
from backend.db.fixtures import load_fixtures
from backend.finance import main as finance
from backend.finance.handlers import recompute_due


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


@pytest.fixture
def drive(db):
    """One round of the agents and finance processes, as they run by themselves on the cluster."""
    def one_round():
        agents.process_pending(db)
        finance.process_pending(db)
        recompute_due(db, debounce=0)
        agents.process_pending(db)
    return one_round


def test_the_liquidity_flow_runs_end_to_end_through_the_real_engine_and_executor(api, drive):
    run = liquidity_flow(api, drive=drive, timeout=5)

    # The pizzeria's -21.8k low needs its full bank history (the cluster's data); the fixtures hold a few lines.
    on_fixtures = [s for s in run.steps if s.name != "pizzeria: low about -21.8k"]
    assert [s.name for s in on_fixtures if not s.ok] == [], run.report()
    assert len(on_fixtures) == 6
    assert any("SIM-CL-" in s.detail and "25,000" in s.detail for s in run.steps)


def test_a_second_liquidity_run_finds_the_card_already_decided(api, drive):
    liquidity_flow(api, drive=drive, timeout=5)

    again = liquidity_flow(api, drive=drive, timeout=1)

    assert not again.ok
    assert [s.name for s in again.steps if not s.ok][0] in ("forecast with a cash-gap alert",
                                                            "credit-line card with the explanation")
