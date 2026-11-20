"""Seam: loading contracts/fixtures as demo data (the skeleton's mock)."""
from backend.db.fixtures import load_fixtures
from backend.db.store import Store


def test_fixtures_load_with_each_entity_under_its_company(db):
    load_fixtures(db)
    store = Store(db)

    assert store.company_of("match", "mat_412") == "co_borsuk"
    assert store.company_of("transaction", "txn_pz0615") == "co_amalfi"
    assert store.company_of("raw_item", "raw_bank731") == "co_borsuk"
    assert store.company_of("sync_run", "run_000981") == "co_borsuk"
    assert store.company_of("approval", "apr_0007") == "co_borsuk"


def test_loading_fixtures_twice_changes_nothing(db):
    load_fixtures(db)
    load_fixtures(db)

    assert len(Store(db).list("recommendation")) == 4


def test_fixture_events_are_in_the_outbox_in_order(db):
    load_fixtures(db)

    ids = [r[0] for r in db.execute("select id from outbox order by seq")]
    assert ids == ["evt_9001", "evt_9002", "evt_9003", "evt_9004", "evt_9005"]
