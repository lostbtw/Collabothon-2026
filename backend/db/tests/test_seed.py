"""Seam: seeding Companies and People."""
import json

from backend.db.seed import PEOPLE_FILE, companies, person_for_address, seed


def test_seed_creates_both_demo_companies_with_their_as_of_dates(db):
    seed(db)

    by_id = {c["id"]: c for c in companies(db)}
    assert by_id["co_borsuk"]["as_of_date"] == "2026-11-21"
    assert by_id["co_borsuk"]["base_currency"] == "PLN"
    assert by_id["co_amalfi"]["as_of_date"] == "2025-05-15"
    assert by_id["co_amalfi"]["base_currency"] == "EUR"


def test_seeding_twice_changes_nothing(db):
    seed(db)
    seed(db)

    assert len(companies(db)) == 2


def test_the_employee_who_forwards_receipts_is_known_by_e_mail(db):
    seed(db)

    assert person_for_address(db, "jan@borsuk-labs.sample")["id"] == "per_jan"


def test_a_demo_phone_address_maps_to_an_invented_person_only_through_the_secret(db):
    seed(db, address_map={"someone@phone.example": "per_jan"})

    assert person_for_address(db, "someone@phone.example")["id"] == "per_jan"
    assert person_for_address(db, "nobody@phone.example") is None


def test_no_real_e_mail_address_is_committed():
    people = json.loads(PEOPLE_FILE.read_text(encoding="utf-8"))
    assert people
    for person in people:
        assert person["email"].endswith(".sample"), person["email"]
        assert "SAMPLE" in person["name"]


def test_seed_stores_each_company_tax_id_for_who_paid(db):
    seed(db)

    tax_ids = dict(db.execute("select id, tax_id from companies").fetchall())
    assert tax_ids == {"co_borsuk": "9990000014", "co_amalfi": None}
