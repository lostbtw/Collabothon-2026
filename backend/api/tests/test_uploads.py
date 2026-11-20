from backend.db.fixtures import read
from backend.db.store import Store

BORSUK = {"company_id": "co_borsuk"}
PHOTO = {"file": ("receipt.jpg", b"\xff\xd8SAMPLE receipt", "image/jpeg")}


def test_a_receipt_added_to_a_payment_remembers_that_payment(client, db):
    Store(db).add("transaction", next(t for t in read("transaction") if t["id"] == "txn_731"), company_id="co_borsuk")

    response = client.post("/api/v1/uploads", params=BORSUK, files=PHOTO,
                           data={"submitted_by": "per_jan", "transaction_id": "txn_731"})

    assert response.status_code == 201
    assert response.json()["metadata"]["for_transaction_id"] == "txn_731"


def test_an_upload_without_a_payment_has_no_link(client):
    response = client.post("/api/v1/uploads", params=BORSUK, files=PHOTO)

    assert response.status_code == 201
    assert "for_transaction_id" not in response.json()["metadata"]


def test_an_unknown_payment_is_refused(client):
    response = client.post("/api/v1/uploads", params=BORSUK, files=PHOTO, data={"transaction_id": "txn_nope"})

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
