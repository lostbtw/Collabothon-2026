import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bank_sim.app import create_app
from bank_sim.store import Store

TOKEN = "test-token"
AUTH = {"Authorization": f"Bearer {TOKEN}"}
PSD2 = {**AUTH, "Consent-ID": "demo"}

# Newest line first, like the organisers' file; amounts with a decimal comma; one CHF line inside a EUR account.
MINI_CSV = (
    '"Account Number";"Booking Date";"Value Date";"Transaction Type";"Payment Reference";"Beneficiary/Payer";'
    '"Counterparty Account";"Bank Code";"Amount";"Currency";"Info"\n'
    '"DE89370400440532013000";"15.06.25";"15.06.25";"INTERNATIONAL WIRE TRANSFER";"Tranche 6/12";"Luigi Amalfi";"";"";"-4166,67";"CHF";"Transaction booked"\n'
    '"DE89370400440532013000";"02.06.25";"02.06.25";"GIRO CARD PAYMENT";"Fresh produce B";"Central Wholesale Market";"";"";"-100,00";"EUR";"Transaction booked"\n'
    '"DE89370400440532013000";"02.06.25";"02.06.25";"GIRO CARD PAYMENT";"Fresh produce A";"Central Wholesale Market";"";"";"-50,50";"EUR";"Transaction booked"\n'
    '"DE89370400440532013000";"01.06.25";"01.06.25";"CARD SETTLEMENT (DEBIT)";"Daily revenue";"Customers";"DE92500500000959561143";"HELADEFFXXX";"1.234,56";"EUR";"Transaction booked"\n'
)


@pytest.fixture()
def client() -> TestClient:
    return TestClient(create_app(Store(), token=TOKEN))


def post_line(client, **kw):
    body = {"accountId": "acc_pln", "bookingDate": "2026-11-20", "amount": "-180.62",
            "creditorName": "PIXELBOARD.COM* SAN FRANCISCO", "remittance": "PIXELBOARD.COM* 45.00 USD KARTA *4417",
            "cardLast4": "4417", **kw}
    return client.post("/admin/transactions", json=body, headers=AUTH)


# ---------- auth ----------
def test_bearer_and_consent_are_required(client):
    assert client.get("/v1/accounts").status_code == 401
    assert client.get("/v1/accounts", headers={"Authorization": "Bearer wrong", "Consent-ID": "demo"}).status_code == 401
    assert client.get("/v1/accounts", headers=AUTH).status_code == 403  # no Consent-ID
    assert client.get("/v1/accounts", headers={**AUTH, "Consent-ID": "other"}).status_code == 403
    assert client.get("/v1/accounts", headers=PSD2).status_code == 200


def test_admin_needs_bearer(client):
    assert client.post("/admin/clock", json={"now": "2026-11-21"}).status_code == 401
    assert client.get("/health").status_code == 200  # no auth


# ---------- accounts and balances ----------
def test_accounts_list_has_the_four_seed_accounts(client):
    accounts = client.get("/v1/accounts", headers=PSD2).json()["accounts"]
    assert {a["resourceId"] for a in accounts} == {"acc_pln", "acc_eur", "acc_owner", "acc_pizzeria"}
    first = accounts[0]
    assert set(first) == {"resourceId", "iban", "currency", "name", "ownerName", "cashAccountType"}


def test_balance_is_opening_plus_visible_lines(client):
    post_line(client, amount="-180.62")
    b = client.get("/v1/accounts/acc_pln/balances", headers=PSD2).json()["balances"][0]
    assert b["balanceType"] == "closingBooked"
    # no file loaded: the account starts at role 4's closing balance 24,730.15
    assert b["balanceAmount"] == {"amount": "24549.53", "currency": "PLN"}  # 24730.15 - 180.62
    assert b["referenceDate"] == "2026-11-20"


def test_private_card_has_no_balance_and_unknown_account_is_404(client):
    assert client.get("/v1/accounts/acc_owner/balances", headers=PSD2).json()["balances"] == []
    assert client.get("/v1/accounts/nope/balances", headers=PSD2).status_code == 404
    assert client.get("/v1/accounts/nope/transactions", headers=PSD2).status_code == 404


# ---------- delta by entryReference ----------
def test_delta_returns_only_lines_after_the_reference(client):
    for i in range(3):
        post_line(client, amount=f"-{i + 1}.00")
    url = "/v1/accounts/acc_pln/transactions"
    allr = client.get(url, params={"bookingStatus": "booked"}, headers=PSD2).json()
    refs = [t["entryReference"] for t in allr["transactions"]["booked"]]
    assert refs == ["E000000001", "E000000002", "E000000003"]
    delta = client.get(url, params={"entryReferenceFrom": "E000000002"}, headers=PSD2).json()
    assert [t["entryReference"] for t in delta["transactions"]["booked"]] == ["E000000003"]
    empty = client.get(url, params={"entryReferenceFrom": "E000000003"}, headers=PSD2).json()
    assert empty["transactions"]["booked"] == []
    assert "_links" not in empty


def test_booked_line_shape_matches_the_contract(client):
    post_line(client)
    line = client.get("/v1/accounts/acc_pln/transactions", headers=PSD2).json()["transactions"]["booked"][0]
    assert line["entryReference"] == "E000000001"
    assert line["bookingDate"] == "2026-11-20" and line["valueDate"] == "2026-11-20"
    assert line["transactionAmount"] == {"amount": "-180.62", "currency": "PLN"}
    assert line["creditorName"] == "PIXELBOARD.COM* SAN FRANCISCO"
    assert line["remittanceInformationUnstructured"].endswith("KARTA *4417")
    assert line["proprietaryBankTransactionCode"] == "CARD_PAYMENT"


def test_incoming_money_names_the_debtor(client):
    post_line(client, amount="1500.00", creditorName=None, debtorName="Nordwind GmbH (SAMPLE)")
    line = client.get("/v1/accounts/acc_pln/transactions", headers=PSD2).json()["transactions"]["booked"][0]
    assert line["debtorName"] == "Nordwind GmbH (SAMPLE)" and "creditorName" not in line


def test_paging_follows_next_link(client):
    for i in range(5):
        post_line(client, amount=f"-{i + 1}.00")
    seen, url = [], "/v1/accounts/acc_pln/transactions?bookingStatus=booked&limit=2"
    while url:
        body = client.get(url, headers=PSD2).json()
        seen += [t["entryReference"] for t in body["transactions"]["booked"]]
        url = body.get("_links", {}).get("next", {}).get("href")
    assert seen == [f"E{n:09d}" for n in range(1, 6)]


def test_bad_parameters_are_400(client):
    url = "/v1/accounts/acc_pln/transactions"
    assert client.get(url, params={"bookingStatus": "pending"}, headers=PSD2).status_code == 400
    assert client.get(url, params={"entryReferenceFrom": "731"}, headers=PSD2).status_code == 400


def test_date_from_filters_by_booking_date(client):
    post_line(client, bookingDate="2026-11-01")
    post_line(client, bookingDate="2026-11-15")
    got = client.get("/v1/accounts/acc_pln/transactions", params={"dateFrom": "2026-11-10"}, headers=PSD2).json()
    assert [t["bookingDate"] for t in got["transactions"]["booked"]] == ["2026-11-15"]


# ---------- as-of date ("demo clock") ----------
def test_lines_after_the_clock_are_hidden_and_advancing_reveals_them(client):
    post_line(client, bookingDate="2026-11-10", amount="-10.00")
    post_line(client, bookingDate="2026-11-20", amount="-20.00")
    url = "/v1/accounts/acc_pln/transactions"
    assert client.post("/admin/clock", json={"now": "2026-11-15"}, headers=AUTH).json()["now"] == "2026-11-15"
    seen = client.get(url, headers=PSD2).json()["transactions"]["booked"]
    assert [t["transactionAmount"]["amount"] for t in seen] == ["-10.00"]
    bal = client.get("/v1/accounts/acc_pln/balances", headers=PSD2).json()["balances"][0]
    assert bal["balanceAmount"]["amount"] == "24720.15" and bal["referenceDate"] == "2026-11-15"

    client.post("/admin/clock", json={"advanceDays": 10}, headers=AUTH)  # -> 2026-11-25
    seen = client.get(url, headers=PSD2).json()["transactions"]["booked"]
    assert [t["entryReference"] for t in seen] == ["E000000001", "E000000002"]


def test_clock_per_company_does_not_move_the_others(client):
    post_line(client, accountId="acc_pln", bookingDate="2026-11-20")
    post_line(client, accountId="acc_eur", bookingDate="2026-11-20", currency="EUR", amount="-5.00")
    client.post("/admin/clock", json={"now": "2026-11-01", "accountId": "acc_pln"}, headers=AUTH)
    assert client.get("/v1/accounts/acc_pln/transactions", headers=PSD2).json()["transactions"]["booked"] == []
    assert len(client.get("/v1/accounts/acc_eur/transactions", headers=PSD2).json()["transactions"]["booked"]) == 1
    state = client.get("/admin/clock", headers=AUTH).json()
    assert state == {"now": None, "accounts": {"acc_pln": "2026-11-01"}}


def test_clock_input_validation(client):
    assert client.post("/admin/clock", json={}, headers=AUTH).status_code == 400
    assert client.post("/admin/clock", json={"now": "2026-11-01", "advanceDays": 1}, headers=AUTH).status_code == 400
    assert client.post("/admin/clock", json={"now": "yesterday"}, headers=AUTH).status_code == 400
    assert client.post("/admin/clock", json={"now": "2026-11-01", "accountId": "nope"}, headers=AUTH).status_code == 404
    assert client.post("/admin/clock", json={"now": "2026-11-01T10:00:00Z"}, headers=AUTH).json()["now"] == "2026-11-01"


# ---------- admin/transactions ----------
def test_admin_transaction_defaults_and_validation(client):
    r = client.post("/admin/transactions", json={"accountId": "acc_eur", "amount": "-12.5"}, headers=AUTH)
    assert r.status_code == 201
    body = r.json()
    assert body["transactionAmount"] == {"amount": "-12.50", "currency": "EUR"}  # account currency by default
    assert body["proprietaryBankTransactionCode"] == "TRANSFER"
    assert client.post("/admin/transactions", json={"accountId": "acc_eur", "amount": "0"}, headers=AUTH).status_code == 400
    assert client.post("/admin/transactions", json={"accountId": "nope", "amount": "1"}, headers=AUTH).status_code == 404


def test_references_strictly_increase_per_account(client):
    refs = [post_line(client).json()["entryReference"] for _ in range(3)]
    assert refs == sorted(refs) and len(set(refs)) == 3
    assert post_line(client, accountId="acc_eur", currency="EUR").json()["entryReference"] == "E000000001"


# ---------- simulated execution targets ----------
def test_credit_line_application(client):
    client.post("/admin/clock", json={"now": "2026-11-21"}, headers=AUTH)
    r = client.post("/v1/credit-line-applications",
                    json={"accountId": "acc_pln", "limit": "25000", "tenorDays": 90}, headers=PSD2)
    assert r.status_code == 201
    body = r.json()
    assert body["reference"] == "SIM-CL-0001" and body["status"] == "accepted"
    assert body["availableFrom"] == "2026-11-22" and body["limit"] == "25000.00"
    assert client.post("/v1/credit-line-applications", json={"accountId": "acc_pln", "limit": "0", "tenorDays": 90},
                       headers=PSD2).status_code == 422
    assert client.post("/v1/credit-line-applications", json={"accountId": "x", "limit": "1", "tenorDays": 1},
                       headers=PSD2).status_code == 404


def test_fx_forward_and_payment_draft(client):
    fx = client.post("/v1/fx-forwards", json={"accountId": "acc_eur", "sellCurrency": "eur", "buyCurrency": "PLN",
                                              "notional": "18400", "rate": "4.2650", "valueDate": "2026-12-07"},
                     headers=PSD2)
    assert fx.status_code == 201 and fx.json()["reference"] == "SIM-FX-0001" and fx.json()["status"] == "booked"
    assert fx.json()["sellCurrency"] == "EUR"
    same = client.post("/v1/fx-forwards", json={"accountId": "acc_eur", "sellCurrency": "EUR", "buyCurrency": "EUR",
                                                "notional": "1", "rate": "1", "valueDate": "2026-12-07"}, headers=PSD2)
    assert same.status_code == 400

    pd = client.post("/v1/payment-drafts", json={"debtorAccount": "acc_pln", "creditorName": "Anna K. (SAMPLE)",
                                                 "amount": "189.00", "remittance": "Reimbursement"}, headers=PSD2)
    assert pd.status_code == 201 and pd.json()["reference"] == "SIM-PD-0001" and pd.json()["status"] == "draft"


def test_executions_are_listed_and_do_not_move_balances(client):
    before = client.get("/v1/accounts/acc_pln/balances", headers=PSD2).json()
    client.post("/v1/credit-line-applications", json={"accountId": "acc_pln", "limit": "1000", "tenorDays": 30}, headers=PSD2)
    client.post("/v1/payment-drafts", json={"debtorAccount": "acc_pln", "creditorName": "X", "amount": "5"}, headers=PSD2)
    assert client.get("/v1/accounts/acc_pln/balances", headers=PSD2).json() == before
    done = client.get("/admin/executions", headers=AUTH).json()["executions"]
    assert [e["reference"] for e in done] == ["SIM-CL-0001", "SIM-PD-0001"] and all(e["simulated"] for e in done)


def test_reset_restores_the_seed(client):
    post_line(client)
    client.post("/admin/clock", json={"now": "2026-11-01"}, headers=AUTH)
    client.post("/admin/reset", headers=AUTH)
    assert client.get("/v1/accounts/acc_pln/transactions", headers=PSD2).json()["transactions"]["booked"] == []
    assert client.get("/admin/clock", headers=AUTH).json() == {"now": None, "accounts": {}}


# ---------- load-csv ----------
def load(client, csv_text=MINI_CSV, **params):
    return client.post("/admin/load-csv", params=params, content=csv_text.encode("utf-8"),
                       headers={**AUTH, "Content-Type": "text/csv"})


def test_load_csv_makes_chronological_lines_and_keeps_the_chf_quirk(client):
    r = load(client, profile="commerzbank_csv", accountId="acc_pizzeria")
    assert r.status_code == 200 and r.json()["lines"] == 4
    assert r.json()["firstBookingDate"] == "2025-06-01" and r.json()["lastBookingDate"] == "2025-06-15"
    lines = client.get("/v1/accounts/acc_pizzeria/transactions", headers=PSD2).json()["transactions"]["booked"]
    assert [ln["entryReference"] for ln in lines] == ["E000000001", "E000000002", "E000000003", "E000000004"]
    assert [ln["bookingDate"] for ln in lines] == ["2025-06-01", "2025-06-02", "2025-06-02", "2025-06-15"]
    # within one day the file's reverse order is the chronological one: A before B
    assert [ln["remittanceInformationUnstructured"] for ln in lines[1:3]] == ["Fresh produce A", "Fresh produce B"]
    assert lines[0]["transactionAmount"] == {"amount": "1234.56", "currency": "EUR"}  # "1.234,56"
    assert lines[3]["transactionAmount"] == {"amount": "-4166.67", "currency": "CHF"}  # quirk kept as-is
    assert lines[0]["debtorAccount"] == {"iban": "DE92500500000959561143"}
    assert lines[3]["proprietaryBankTransactionCode"] == "INTERNATIONAL_WIRE_TRANSFER"
    iban = client.get("/v1/accounts", headers=PSD2).json()["accounts"][3]["iban"]
    assert iban == "DE89370400440532013000"


def test_load_csv_is_idempotent_and_respects_the_clock(client):
    load(client)
    assert load(client).json()["lines"] == 4  # replaces, does not append
    client.post("/admin/clock", json={"now": "2025-06-02", "accountId": "acc_pizzeria"}, headers=AUTH)
    shown = client.get("/v1/accounts/acc_pizzeria/transactions", headers=PSD2).json()["transactions"]["booked"]
    assert len(shown) == 3
    client.post("/admin/clock", json={"now": "2025-06-30", "accountId": "acc_pizzeria"}, headers=AUTH)
    assert len(client.get("/v1/accounts/acc_pizzeria/transactions",
                          params={"entryReferenceFrom": "E000000003"}, headers=PSD2).json()["transactions"]["booked"]) == 1


def test_load_csv_rejects_bad_input(client):
    assert load(client, profile="unknown").status_code == 400
    assert load(client, accountId="nope").status_code == 404
    assert load(client, csv_text='"a";"b"\n"1";"2"\n').status_code == 422
    assert client.post("/admin/load-csv", content=MINI_CSV.encode()).status_code == 401


# ---------- autoload at start ----------
def test_autoload_fills_the_account_at_start_and_after_reset(tmp_path):
    path = tmp_path / "pizzeria.csv"
    path.write_text(MINI_CSV, encoding="utf-8")
    c = TestClient(create_app(Store(), token=TOKEN, autoload_csv=str(path)))
    lines = c.get("/v1/accounts/acc_pizzeria/transactions", headers=PSD2).json()["transactions"]["booked"]
    assert len(lines) == 4  # a fresh bank is not empty
    # other accounts are untouched
    assert c.get("/v1/accounts/acc_pln/transactions", headers=PSD2).json()["transactions"]["booked"] == []
    c.post("/admin/transactions", json={"accountId": "acc_pln", "amount": "-1"}, headers=AUTH)
    c.post("/admin/clock", json={"now": "2025-06-01", "accountId": "acc_pizzeria"}, headers=AUTH)
    r = c.post("/admin/reset", headers=AUTH)
    assert r.json() == {"status": "reset", "autoloaded": True}
    assert len(c.get("/v1/accounts/acc_pizzeria/transactions", headers=PSD2).json()["transactions"]["booked"]) == 4
    assert c.get("/v1/accounts/acc_pln/transactions", headers=PSD2).json()["transactions"]["booked"] == []
    assert c.get("/admin/clock", headers=AUTH).json() == {"now": None, "accounts": {}}


def test_autoload_fails_fast_when_the_file_is_missing_or_the_account_unknown(tmp_path):
    with pytest.raises(RuntimeError, match="could not be loaded"):
        create_app(Store(), token=TOKEN, autoload_csv=str(tmp_path / "nope.csv"))
    path = tmp_path / "p.csv"
    path.write_text(MINI_CSV, encoding="utf-8")
    with pytest.raises(RuntimeError, match="not a known account"):
        create_app(Store(), token=TOKEN, autoload_csv=str(path), autoload_account="acc_nope")
    bad = tmp_path / "bad.csv"
    bad.write_text('"a";"b"\n"1";"2"\n', encoding="utf-8")
    with pytest.raises(RuntimeError, match="could not be loaded"):
        create_app(Store(), token=TOKEN, autoload_csv=str(bad))


# ---------- the organisers' real file (not in Git; set BANK_TEST_CSV to run) ----------
REAL = os.environ.get("BANK_TEST_CSV")


@pytest.mark.skipif(not (REAL and Path(REAL).exists()), reason="BANK_TEST_CSV not set")
def test_real_pizzeria_file(client):
    r = client.post("/admin/load-csv", content=Path(REAL).read_bytes(), headers={**AUTH, "Content-Type": "text/csv"})
    assert r.json()["lines"] == 1125
    seen, url = [], "/v1/accounts/acc_pizzeria/transactions?bookingStatus=booked"
    while url:
        body = client.get(url, headers=PSD2).json()
        seen += body["transactions"]["booked"]
        url = body.get("_links", {}).get("next", {}).get("href")
    assert len(seen) == 1125
    refs = [t["entryReference"] for t in seen]
    assert refs == sorted(refs) and len(set(refs)) == 1125
    assert sum(1 for t in seen if t["transactionAmount"]["currency"] == "CHF") == 12
    bal = client.get("/v1/accounts/acc_pizzeria/balances", headers=PSD2).json()["balances"][0]["balanceAmount"]["amount"]
    assert abs(float(bal) - 33266.35) < 0.05  # the organisers' year-end balance
    # the as-of date of the demo: 15 May 2025 hides everything after it
    client.post("/admin/clock", json={"now": "2025-05-15", "accountId": "acc_pizzeria"}, headers=AUTH)
    visible = client.get("/v1/accounts/acc_pizzeria/transactions", params={"limit": 1000}, headers=PSD2).json()
    assert max(t["bookingDate"] for t in visible["transactions"]["booked"]) <= "2025-05-15"
