"""The Sandbox Bank on the Borsuk Labs scenario: exactly the entry references, dates and balances the plan refers to."""
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from bank_sim.app import create_app
from bank_sim.store import Store

OUT = Path(__file__).resolve().parents[2] / "scenario" / "out"
TOKEN = "test-token"
PSD2 = {"Authorization": f"Bearer {TOKEN}", "Consent-ID": "demo"}
ADMIN = {"Authorization": f"Bearer {TOKEN}"}

pytestmark = pytest.mark.skipif(not (OUT / "bank_acc_pln.csv").exists(), reason="role 4's scenario is not here")


@pytest.fixture(scope="module")
def bank():
    with TestClient(create_app(Store(), token=TOKEN, autoload_dir=str(OUT))) as client:
        yield client


def all_lines(bank, account):
    lines, url = [], f"/v1/accounts/{account}/transactions?bookingStatus=booked&limit=1000"
    while url:
        body = bank.get(url, headers=PSD2).json()
        lines += body["transactions"]["booked"]
        url = body.get("_links", {}).get("next", {}).get("href")
    return lines


def balance(bank, account):
    bal = bank.get(f"/v1/accounts/{account}/balances", headers=PSD2).json()["balances"]
    return bal[0]["balanceAmount"] if bal else None


def test_every_scenario_account_is_loaded_at_start(bank):
    assert {a: len(all_lines(bank, a)) for a in ("acc_pln", "acc_eur", "acc_owner")} == \
        {"acc_pln": 719, "acc_eur": 94, "acc_owner": 257}
    ibans = {a["resourceId"]: a["iban"] for a in bank.get("/v1/accounts", headers=PSD2).json()["accounts"]}
    assert ibans["acc_pln"] == "PL00999900000000000000010001"
    assert ibans["acc_eur"] == "PL00999900000000000000010002"
    assert ibans["acc_owner"] == "PL00999900000000000000090021"


def test_closing_balances_are_the_scenarios(bank):
    assert balance(bank, "acc_pln") == {"amount": "24730.15", "currency": "PLN"}
    assert balance(bank, "acc_eur") == {"amount": "3100.00", "currency": "EUR"}
    assert balance(bank, "acc_owner") is None


def test_every_bank_line_of_the_release_plan_exists_with_its_date(bank):
    plan = json.loads((OUT / "release_plan.json").read_text(encoding="utf-8"))
    by_account = {a: {ln["entryReference"]: ln for ln in all_lines(bank, a)} for a in ("acc_pln", "acc_eur", "acc_owner")}
    bank_items = [i for i in plan["items"] if i["channel"] == "bank"]
    assert len(bank_items) == 1070
    for item in bank_items:
        line = by_account[item["account"]].get(item["entry_reference"])
        assert line is not None, item
        assert line["bookingDate"] == item["scenario_date"], item


def test_every_bank_line_the_ground_truth_names_exists(bank):
    truth = json.loads((OUT / "ground_truth.json").read_text(encoding="utf-8"))
    refs = {a: {ln["entryReference"] for ln in all_lines(bank, a)} for a in ("acc_pln", "acc_eur", "acc_owner")}
    named = [d["bank_line"] for d in truth["documents"] if d.get("bank_line")]
    assert named
    missing = [b for b in named if b["entry_reference"] not in refs[b["account"]]]
    assert missing == []


def test_reset_reloads_the_scenario():
    with TestClient(create_app(Store(), token=TOKEN, autoload_dir=str(OUT))) as bank:
        bank.post("/admin/transactions", json={"accountId": "acc_pln", "amount": "-1"}, headers=ADMIN)
        bank.post("/admin/reset", headers=ADMIN)
        assert len(all_lines(bank, "acc_pln")) == 719
        assert balance(bank, "acc_pln")["amount"] == "24730.15"


def test_autoload_dir_errors(tmp_path):
    with pytest.raises(RuntimeError, match="is not a folder"):
        create_app(Store(), token=TOKEN, autoload_dir=str(tmp_path / "nope"))
    with pytest.raises(RuntimeError, match="no bank_acc_"):
        create_app(Store(), token=TOKEN, autoload_dir=str(tmp_path))
    (tmp_path / "bank_acc_unknown.csv").write_bytes((OUT / "bank_acc_eur.csv").read_bytes())
    with pytest.raises(RuntimeError, match="not a known account"):
        create_app(Store(), token=TOKEN, autoload_dir=str(tmp_path))
