"""Owner screens on fixtures plus a few SAMPLE lines."""
import pytest

from backend.agents import receivables
from backend.db.fixtures import load_fixtures
from backend.db.store import Store

BORSUK = {"company_id": "co_borsuk"}


def line(id_, date, amount, raw, category, *, account="acc_pln", counterparty=None, card=None, currency="PLN", base=None):
    return {"id": id_, "account_id": account, "raw_item_id": f"raw_{id_}", "external_id": id_, "booking_date": date,
            "amount": {"amount": amount, "currency": currency}, "amount_base": {"amount": base or amount, "currency": "PLN"},
            "counterparty_name_raw": raw, "counterparty_id": counterparty, "description": raw, "status": "booked",
            "category": category, "match_status": "unmatched", "card_last4": card,
            "transaction_type": "card_payment" if card else "transfer_out"}


@pytest.fixture
def demo(client, db):
    load_fixtures(db)
    s = Store(db)
    for t in [
        line("txn_t_jan", "2026-10-30", "-5800.00", "JAN KOWALSKI WYNAGRODZENIE", "salaries"),
        line("txn_t_anna", "2026-10-31", "-10800.00", "WRONA DESIGN FV 10/2026", "other"),
        line("txn_t_zus", "2026-10-15", "-9200.00", "ZAKLAD UBEZPIECZEN SPOLECZNYCH", "social_security"),
        line("txn_t_rent", "2026-10-14", "-2460.00", "BIURO NA PIOTRKOWSKIEJ", "rent_office"),
        line("txn_t_nord", "2026-10-06", "81100.00", "NORDWIND LOGISTIK GMBH", "revenue_services", counterparty="cp_nordwind"),
        line("txn_t_chm9", "2026-09-02", "-1386.00", "CHMURA POLSKA", "cloud_hosting", card="4417"),
        line("txn_t_chm10", "2026-10-02", "-1552.00", "CHMURA POLSKA", "cloud_hosting", card="4417"),
        line("txn_t_tp_a", "2026-10-05", "-89.00", "TASKPILOT", "software_subscriptions", card="4417"),
        line("txn_t_tp_b", "2026-10-06", "-89.00", "TASKPILOT", "software_subscriptions", account="acc_owner", card="9021"),
        line("txn_t_tp_9", "2026-09-05", "-89.00", "TASKPILOT", "software_subscriptions", card="4417"),
        line("txn_t_shop", "2026-10-11", "-212.00", "KOSZYK 24 LODZ", "other", card="4417"),
    ]:
        s.put("transaction", t, company_id="co_borsuk")
    s.put("document", {**s.get("document", "doc_pixel11"), "id": "doc_t_sale", "direction": "sale", "number": "FV/10/07",
                       "issue_date": "2026-10-15", "due_date": "2026-11-14", "raw_item_ids": ["raw_t_sale"],
                       "seller": {"name": "Borsuk Labs sp. z o.o. (SAMPLE)", "tax_id": "9990000014"},
                       "buyer": {"name": "Nordwind Logistik GmbH (SAMPLE)", "counterparty_id": "cp_nordwind", "is_company": False},
                       "totals": {"gross": {"amount": "18400.00", "currency": "EUR"}, "gross_base": {"amount": "81100.00", "currency": "PLN"}},
                       "status": "approved", "flags": []}, company_id="co_borsuk")
    return client


def test_settings_have_defaults_and_keep_what_the_owner_changes(demo):
    got = demo.get("/api/v1/settings", params=BORSUK).json()
    assert got["company"] == {"id": "co_borsuk", "name": "Borsuk Labs sp. z o.o. (SAMPLE)", "tax_id": "9990000014",
                              "base_currency": "PLN", "vat_period": "monthly", "accountant_email": None}
    assert got["alerts"]["late_client_days"] == 7 and got["alerts"]["weekly_summary"] is False

    changed = demo.patch("/api/v1/settings", params=BORSUK, json={
        "company": {"accountant_email": "office@abakus.example", "vat_period": "quarterly"},
        "alerts": {"safety_buffer": {"amount": "12000.00", "currency": "PLN"}, "late_client_days": 10, "weekly_summary": True}}).json()
    assert changed["company"]["accountant_email"] == "office@abakus.example"
    assert changed["alerts"] == {"safety_buffer": {"amount": "12000.00", "currency": "PLN"}, "late_client_days": 10, "weekly_summary": True}
    assert demo.get("/api/v1/settings", params=BORSUK).json() == changed
    assert demo.patch("/api/v1/settings", params=BORSUK, json={"alerts": {"late_client_days": 0}}).status_code == 422
    assert demo.patch("/api/v1/settings", params=BORSUK, json={"company": {"base_currency": "EUR"}}).status_code == 422


def test_people_list_and_add(demo):
    team = demo.get("/api/v1/people", params=BORSUK).json()["items"]
    assert team[0]["role"] == "owner"
    jan = next(p for p in team if p["id"] == "per_jan")
    assert jan["card_last4"] == ["7730"] and jan["statement_names"] == ["JAN KOWALSKI"] and jan["pay_type"] == "salary"

    added = demo.post("/api/v1/people", params=BORSUK, json={"name": "Ewa Nowak (SAMPLE)", "email": "ewa@borsuk-labs.sample",
                                                              "role": "employee", "card_last4": ["1234"], "statement_names": ["ewa nowak"]})
    assert added.status_code == 201
    assert added.json() | {"id": "x"} == {"id": "x", "name": "Ewa Nowak (SAMPLE)", "email": "ewa@borsuk-labs.sample", "role": "employee",
                                          "pay_type": "salary", "card_last4": ["1234"], "statement_names": ["EWA NOWAK"], "tax_id": None, "iban": None}
    again = demo.post("/api/v1/people", params=BORSUK, json={"name": "Ewa", "email": "EWA@borsuk-labs.sample", "role": "employee"})
    assert again.status_code == 422


def test_a_person_can_be_edited_and_the_email_is_what_identifies_a_sender(demo):
    changed = demo.patch("/api/v1/people/per_jan", params=BORSUK, json={"email": "Phone.Jan@Gmail.example"})
    assert changed.status_code == 200 and changed.json()["email"] == "phone.jan@gmail.example"
    assert changed.json()["name"] == "Jan Kowalski (SAMPLE)" and changed.json()["card_last4"] == ["7730"]
    again = demo.patch("/api/v1/people/per_jan", params=BORSUK, json={"name": "Jan K.", "card_last4": ["1111"],
                                                                     "statement_names": ["jan k"]})
    assert again.json() | {"id": "x"} == {"id": "x", "name": "Jan K.", "email": "phone.jan@gmail.example", "role": "employee",
                                          "pay_type": "salary", "card_last4": ["1111"], "statement_names": ["JAN K"],
                                          "tax_id": None, "iban": None}
    assert demo.patch("/api/v1/people/per_jan", params=BORSUK, json={"role": "contractor"}).json()["pay_type"] == "invoice"
    taken = demo.patch("/api/v1/people/per_jan", params=BORSUK, json={"email": "marta@borsuk-labs.sample"})
    assert taken.status_code == 422
    assert demo.patch("/api/v1/people/per_jan", params=BORSUK, json={"role": "boss"}).status_code == 422
    assert demo.patch("/api/v1/people/per_jan", params=BORSUK, json={"name": " "}).status_code == 422
    assert demo.patch("/api/v1/people/per_nobody", params=BORSUK, json={"name": "X"}).status_code == 404
    assert demo.patch("/api/v1/people/per_amalfi_owner", params=BORSUK, json={"name": "X"}).status_code == 404


def test_changing_a_bank_lines_type_teaches_a_rule_the_pipeline_uses(demo, db):
    s = Store(db)
    s.put("counterparty", {"id": "cp_koszyk", "company_id": "co_borsuk", "name": "Koszyk 24 (SAMPLE)", "kind": "supplier"}, company_id="co_borsuk")
    s.put("transaction", {**s.get("transaction", "txn_t_shop"), "counterparty_id": "cp_koszyk"}, company_id="co_borsuk")

    changed = demo.patch("/api/v1/transactions/txn_t_shop", params=BORSUK, json={"category": "owner_private"})
    assert changed.status_code == 200 and changed.json()["category"] == "owner_private"
    rules = demo.get("/api/v1/rules", params=BORSUK).json()["items"]
    assert [(r["raw"], r["counterparty_name"], r["category"]) for r in rules] == [("KOSZYK 24 LODZ", "Koszyk 24 (SAMPLE)", "owner_private")]
    assert s.get("counterparty", "cp_koszyk")["default_category"] == "owner_private"

    assert demo.delete(f"/api/v1/rules/{rules[0]['id']}", params=BORSUK).status_code == 204
    assert demo.get("/api/v1/rules", params=BORSUK).json()["items"] == []
    assert s.get("counterparty", "cp_koszyk")["default_category"] is None
    assert demo.patch("/api/v1/transactions/txn_t_shop", params=BORSUK, json={"category": "groceries"}).status_code == 422


def test_changing_a_documents_type_also_teaches_a_rule(demo):
    demo.patch("/api/v1/documents/doc_pixel11", json={"category_suggestion": {"category": "software_subscriptions"}})
    assert [r["category"] for r in demo.get("/api/v1/rules", params=BORSUK).json()["items"]] == ["software_subscriptions"]


def test_costs_per_person_come_from_the_bank_lines_that_name_them(demo):
    got = demo.get("/api/v1/people/costs", params={**BORSUK, "month": "2026-10"}).json()
    by_id = {p["person_id"]: p for p in got["items"]}
    assert by_id["per_jan"]["paid"] == {"amount": "5800.00", "currency": "PLN"}
    assert by_id["per_jan"]["owed"] == {"amount": "1299.00", "currency": "PLN"}
    assert by_id["per_jan"]["receipts_owed"] == 1
    assert by_id["per_anna"]["paid"]["amount"] == "10800.00"
    assert got["totals"]["social_security"]["amount"] == "9200.00"
    assert got["totals"]["staff"]["amount"] == "25800.00"
    assert 0 < got["totals"]["share_of_costs"] < 1


def test_clients_show_what_was_paid_and_what_is_still_open(demo):
    got = demo.get("/api/v1/clients", params={**BORSUK, "month": "2026-10"}).json()
    nordwind = next(c for c in got["items"] if c["counterparty_id"] == "cp_nordwind")
    assert nordwind["paid_in_month"]["amount"] == "81100.00"
    assert nordwind["open_invoices"][0] | {"document_id": "x"} == {"document_id": "x", "number": "FV/10/07", "gross": {"amount": "18400.00", "currency": "EUR"},
                                                                   "gross_base": {"amount": "81100.00", "currency": "PLN"}, "due_date": "2026-11-14", "days_late": 7}
    assert nordwind["share_of_income"] == 1.0
    assert got["totals"]["late_base"]["amount"] >= "81100.00"


def test_subscriptions_are_monthly_tools_with_price_rises_and_double_payments(demo):
    got = demo.get("/api/v1/subscriptions", params=BORSUK).json()
    by_name = {i["name"]: i for i in got["items"]}
    chmura = by_name["CHMURA POLSKA"]
    assert chmura["monthly"]["amount"] == "1552.00" and chmura["previous_monthly"]["amount"] == "1386.00"
    assert chmura["flags"] == ["price_up"] and chmura["paid_by"] == [{"kind": "card", "label": "Company card ending 4417"}]
    taskpilot = by_name["TASKPILOT"]
    assert set(taskpilot["flags"]) == {"paid_twice", "paid_privately"}
    assert taskpilot["monthly"]["amount"] == "178.00" and taskpilot["duplicate_cost"]["amount"] == "89.00"
    assert "KOSZYK 24 LODZ" not in by_name


def test_chat_history_lists_sessions_and_their_messages(demo):
    first = demo.post("/api/v1/chat", json={"message": "How much cash do I have?", "company_id": "co_borsuk"}).json()
    demo.post("/api/v1/chat", json={"message": "And next month?", "company_id": "co_borsuk", "session_id": first["session_id"]})
    sessions = demo.get("/api/v1/chat/sessions", params=BORSUK).json()["items"]
    assert sessions[0] | {"last_at": "x"} == {"session_id": first["session_id"], "title": "How much cash do I have?", "last_at": "x", "messages": 4}
    detail = demo.get(f"/api/v1/chat/sessions/{first['session_id']}", params=BORSUK).json()
    assert [m["role"] for m in detail["messages"]] == ["user", "assistant", "user", "assistant"]
    assert demo.get("/api/v1/chat/sessions/nope", params=BORSUK).status_code == 404


def test_balance_history_works_back_from_the_reported_balance(demo):
    got = demo.get("/api/v1/balance/history", params=BORSUK).json()
    assert got["currency"] == "PLN" and len(got["points"]) >= 2
    assert all(a["date"] < b["date"] for a, b in zip(got["points"], got["points"][1:]))


def test_the_summary_can_sum_bank_lines_for_months_not_in_the_books(demo):
    books = demo.get("/api/v1/ledger/summary", params={**BORSUK, "from": "2026-10-01", "to": "2026-10-31"}).json()
    bank = demo.get("/api/v1/ledger/summary", params={**BORSUK, "from": "2026-10-01", "to": "2026-10-31", "basis": "bank"}).json()
    assert books["rows"] == []
    sums = {r["key"]: r["amount_base"]["amount"] for r in bank["rows"]}
    assert sums["salaries"] == "-5800.00"
    assert sums["contractors"] == "-10800.00"
    assert bank["kpis"] == books["kpis"]


def test_late_clients_get_a_reminder_to_approve_once(demo, db):
    demo.patch("/api/v1/settings", params=BORSUK, json={"alerts": {"late_client_days": 5}})
    created = receivables.chase_late_clients(db, "co_borsuk")
    assert len(created) == 1
    card = Store(db).get("recommendation", created[0])
    assert card["type"] == "chase_receivable" and card["control_level"] == "approval_required" and card["execution_mode"] == "simulated"
    assert card["proposed_action"]["kind"] == "send_email_draft" and card["evidence"]
    assert receivables.chase_late_clients(db, "co_borsuk") == []


def test_monthly_payments_include_rent_and_staff_and_follow_the_month(demo, db):
    Store(db).put("transaction", line("txn_t_rent9", "2026-09-14", "-2460.00", "BIURO NA PIOTRKOWSKIEJ", "rent_office"), company_id="co_borsuk")
    got = demo.get("/api/v1/subscriptions", params={**BORSUK, "scope": "all", "month": "2026-10"}).json()
    by_name = {i["name"]: i for i in got["items"]}
    assert by_name["BIURO NA PIOTRKOWSKIEJ"]["monthly"]["amount"] == "2460.00" and by_name["BIURO NA PIOTRKOWSKIEJ"]["paid_in_month"] is True
    assert "CHMURA POLSKA" in by_name and by_name["CHMURA POLSKA"]["category"] == "cloud_hosting"
    later = demo.get("/api/v1/subscriptions", params={**BORSUK, "scope": "all", "month": "2026-11"}).json()
    assert {i["name"]: i for i in later["items"]}["BIURO NA PIOTRKOWSKIEJ"]["paid_in_month"] is False
    assert demo.get("/api/v1/subscriptions", params={**BORSUK, "month": "Nov"}).status_code == 422


@pytest.mark.parametrize("question,expect", [
    ("Who still owes us?", "Clients owe you"),
    ("Why are costs up?", "Costs in 2026-11 so far"),
    ("Can I afford a December bonus?", "lowest expected balance"),
])
def test_the_suggested_questions_get_an_answer_with_sources(demo, question, expect):
    got = demo.post("/api/v1/chat", json={"message": question, "company_id": "co_borsuk"}).json()
    assert expect in got["answer"]
    assert got["evidence"]


def test_big_answers_are_compressed_but_the_event_stream_is_not(demo, monkeypatch):
    listed = demo.get("/api/v1/transactions", params=BORSUK, headers={"Accept-Encoding": "gzip"})
    assert listed.headers.get("content-encoding") == "gzip"
    assert listed.json()["items"]
    monkeypatch.setenv("ORDO_SSE_REPLAY_FIXTURES", "1")
    with demo.stream("GET", "/api/v1/events/stream", params={**BORSUK, "max_events": 1}, headers={"Accept-Encoding": "gzip"}) as stream:
        assert stream.headers.get("content-encoding") is None
        assert "event:" in stream.read().decode()
