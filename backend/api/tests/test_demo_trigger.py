"""The stage trigger: one call is an e-mail from the employee with the receipt photo, stored like the mailbox does."""
from backend.api.routes.demo import with_nonce
from backend.db.fixtures import load_fixtures
from backend.db.store import Store


def demo(client, db):
    load_fixtures(db)
    return client


def test_one_call_stores_the_e_mail_and_its_photo_and_announces_them(client, db):
    demo(client, db)

    answer = client.get("/api/v1/demo/receipt")

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["status"] == "sent" and len(body["raw_item_ids"]) == 2
    email, photo = (Store(db).get("raw_item", rid) for rid in body["raw_item_ids"])
    assert (email["kind"], photo["kind"]) == ("email", "email_attachment")
    assert photo["parent_raw_item_id"] == email["id"] and photo["content_type"] == "image/jpeg"
    assert photo["metadata"]["forwarded_by"] and photo["metadata"]["demo_trigger"] is True
    stored = db.execute("select bytes from raw_item_content where raw_item_id = %s", (photo["id"],)).fetchone()[0]
    assert bytes(stored)[:2] == b"\xff\xd8"
    events = db.execute("select payload->>'raw_item_id' from outbox where type = 'raw_item.received'").fetchall()
    assert {e[0] for e in events} >= set(body["raw_item_ids"])


def test_every_call_is_a_new_file_and_retires_the_previous_demo_receipt(client, db):
    demo(client, db)
    first = client.get("/api/v1/demo/receipt").json()
    s = Store(db)
    s.put("document", {"id": "doc_demo_taxi", "company_id": "co_borsuk", "status": "extracted",
                       "seller": {"name": "Taxi Express Łódź sp. z o.o. (SAMPLE)", "tax_id": "999-003-14-49"}},
          company_id="co_borsuk")

    second = client.get("/api/v1/demo/receipt").json()

    assert set(first["raw_item_ids"]).isdisjoint(second["raw_item_ids"])
    assert second["retired_documents"] == ["doc_demo_taxi"]
    assert s.get("document", "doc_demo_taxi")["status"] == "rejected"


def test_an_unknown_receipt_is_refused(client, db):
    demo(client, db)
    assert client.get("/api/v1/demo/receipt?receipt=nope").status_code == 422


def test_the_nonce_keeps_a_valid_jpeg():
    jpeg = b"\xff\xd8\xff\xe0rest"
    marked = with_nonce(jpeg, "abc")
    assert marked.startswith(b"\xff\xd8\xff\xfe") and marked.endswith(b"\xff\xe0rest") and marked != jpeg


def test_a_client_payment_is_booked_in_the_sandbox_bank(client, db, sandbox_bank, monkeypatch):
    import contextlib

    import backend.api.routes.demo as demo_route
    demo(client, db)
    monkeypatch.setattr(demo_route, "make_client", lambda: contextlib.nullcontext(sandbox_bank))

    answer = client.get("/api/v1/demo/payment")

    assert answer.status_code == 200, answer.text
    line = answer.json()["bank_line"]
    assert line["transactionAmount"] == {"amount": "18400.00", "currency": "EUR"} or "18400" in str(line)
    booked = sandbox_bank.get("/v1/accounts/acc_eur/transactions", headers={"Authorization": "Bearer test-bank-token", "Consent-ID": "demo"}).json()
    assert "INVOICE 2026/10/044" in str(booked)
