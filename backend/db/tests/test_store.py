"""Seam: the Store (repository) on a real Postgres. Every role writes and reads entities through it."""
import copy
import json
from pathlib import Path

import pytest

from backend.db.store import ENTITIES, Store

FIXTURES = Path(__file__).resolve().parents[3] / "contracts" / "fixtures"


def fixture_items():
    for path in sorted(FIXTURES.glob("*.json")):
        if path.stem == "event":
            continue  # events live in the outbox, see test_outbox
        for i, item in enumerate(json.loads(path.read_text(encoding="utf-8"))):
            yield pytest.param(path.stem, item, id=f"{path.stem}[{i}]")


@pytest.mark.parametrize("entity,item", list(fixture_items()))
def test_every_fixture_reads_back_unchanged(db, entity, item):
    store = Store(db)
    original = copy.deepcopy(item)

    assert store.add(entity, item, company_id="co_borsuk") is True

    assert store.get(entity, item["id"]) == original


def first_fixture(entity, id):
    items = json.loads((FIXTURES / f"{entity}.json").read_text(encoding="utf-8"))
    return next(i for i in items if i["id"] == id)


@pytest.mark.parametrize(
    "entity,fixture_id",
    [
        ("raw_item", "raw_mail412"),          # raw_item.idempotency_key
        ("transaction", "txn_731"),    # (account_id, external_id)
        ("document", "doc_rcpt412"),          # document.raw_item_ids[0]
        ("match", "mat_412"),                 # (document_id, match_type) while suggested
        ("recommendation", "rec_412"),        # (type, subject.id) while new or seen
        ("forecast", "fc_20261121a"),         # (company_id, inputs_hash) for base forecasts
    ],
)
def test_the_same_idempotency_key_under_a_new_id_is_not_stored_twice(db, entity, fixture_id):
    store = Store(db)
    item = first_fixture(entity, fixture_id)
    again = {**copy.deepcopy(item), "id": item["id"] + "_again"}

    assert store.add(entity, item, company_id="co_borsuk") is True
    assert store.add(entity, again, company_id="co_borsuk") is False

    assert store.get(entity, again["id"]) is None


def test_a_closed_recommendation_does_not_block_a_new_one_for_the_same_subject(db):
    store = Store(db)
    closed = {**first_fixture("recommendation", "rec_412"), "status": "rejected"}
    store.add("recommendation", closed)

    assert store.add("recommendation", {**first_fixture("recommendation", "rec_412"), "id": "rec_412b"}) is True


def test_every_contract_entity_except_event_has_a_table():
    schemas = Path(__file__).resolve().parents[3] / "contracts" / "schemas"
    names = {p.name.removesuffix(".schema.json") for p in schemas.glob("*.schema.json")}
    assert names - {"common", "event"} == set(ENTITIES)
