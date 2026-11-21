"""Simulated executor against the real Sandbox Bank (sim/bank, in-process) and the real tables."""
import copy
import sys
from pathlib import Path

import httpx
import pytest
from fastapi.testclient import TestClient

from backend.db.fixtures import load_fixtures, read
from backend.executor.simulated import ExecutionFailed, ExecutionRefused, execute_action

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "sim" / "bank"))
from bank_sim.app import create_app as create_bank  # noqa: E402
from bank_sim.store import Store as BankStore  # noqa: E402

TOKEN = "test-token"
ADMIN = {"Authorization": f"Bearer {TOKEN}"}
PSD2 = {**ADMIN, "Consent-ID": "demo"}
APPROVAL = {"id": "apr_test01", "decided_at": "2026-11-21T10:20:00Z"}


@pytest.fixture
def bank():
    with TestClient(create_bank(BankStore(), token=TOKEN)) as client:
        yield client


@pytest.fixture
def demo(db):
    load_fixtures(db)
    return db


def action_of(rec_id: str, **param_changes) -> dict:
    rec = next(r for r in read("recommendation") if r["id"] == rec_id)
    action = copy.deepcopy(rec["proposed_action"])
    action["params"].update(param_changes)
    return action


def run(db, bank, action, **kw):
    return execute_action(db, APPROVAL, action, "co_borsuk", client=bank, token=TOKEN, **kw)


def bank_executions(bank):
    return bank.get("/admin/executions", headers=ADMIN).json()["executions"]


def simulated_events(db):
    return [r[0] for r in db.execute("select payload from outbox where type = 'execution.simulated' order by seq")]


def test_credit_line_with_the_owners_lower_limit(demo, bank):
    out = run(demo, bank, action_of("rec_cl01", limit={"amount": "25000.00", "currency": "PLN"}))
    assert out["reference"].startswith("SIM-CL-")
    assert out["result"].startswith("SIMULATED: ") and "25,000 PLN" in out["result"] and "60 days" in out["result"]
    [done] = bank_executions(bank)
    assert done["type"] == "credit_line_application" and done["limit"] == "25000.00"
    assert done["accountId"] == "acc_pln" and done["tenorDays"] == 60 and done["reference"] == out["reference"]
    assert simulated_events(demo) == [{"approval_id": "apr_test01", "reference": out["reference"], "result": out["result"]}]


def test_reimbursement_becomes_a_payment_draft_to_the_employee(demo, bank):
    out = run(demo, bank, action_of("rec_412"))
    assert out["reference"].startswith("SIM-PD-")
    [done] = bank_executions(bank)
    assert done["type"] == "payment_draft" and done["status"] == "draft"
    assert done["creditorName"] == "Jan Kowalski (SAMPLE)"
    assert done["amount"] == "1299.00" and done["requestedExecutionDate"] == "2026-11-30"
    assert done["debtorAccount"] == "acc_pln" and done["remittance"] == "Zwrot kosztow - monitor 20.11.2026"
    assert "1,299 PLN" in out["result"] and "Jan Kowalski" in out["result"]


def test_fx_forward_is_booked(demo, bank):
    out = run(demo, bank, action_of("rec_fx01"))
    assert out["reference"].startswith("SIM-FX-")
    [done] = bank_executions(bank)
    assert (done["sellCurrency"], done["buyCurrency"], done["notional"], done["rate"], done["valueDate"]) == \
        ("USD", "PLN", "40000.00", "4.0491", "2027-01-05")
    assert done["status"] == "booked" and done["accountId"] == "acc_pln"
    assert "40,000 USD" in out["result"]


def test_a_mode_other_than_simulated_is_refused_before_anything_happens(demo, bank):
    with pytest.raises(ExecutionRefused, match="SIMULATED"):
        run(demo, bank, action_of("rec_cl01"), execution_mode="permitted")
    assert bank_executions(bank) == [] and simulated_events(demo) == []


def test_tax_pocket_is_a_payment_draft_to_the_tax_pocket(demo, bank):
    out = run(demo, bank, {"kind": "move_to_tax_pocket", "params": {"amount": {"amount": "14300.00", "currency": "PLN"}}})
    [done] = bank_executions(bank)
    assert done["creditorName"] == "Tax pocket (SAMPLE)" and done["amount"] == "14300.00"
    assert out["reference"].startswith("SIM-PD-")


def test_actions_without_a_bank_target_stay_in_ordo(demo, bank):
    out = run(demo, bank, {"kind": "send_email_draft", "params": {"to": "client@example.test"}})
    assert out["reference"].startswith("SIM-EM-2026-") and "not sent" in out["result"]
    assert bank_executions(bank) == []
    assert len(simulated_events(demo)) == 1


def test_unknown_or_empty_actions_are_refused(demo, bank):
    for action in ({"kind": "none", "params": {}}, {"kind": "buy_bitcoin", "params": {}}, None):
        with pytest.raises(ExecutionRefused):
            run(demo, bank, action)
    assert simulated_events(demo) == []


def test_executions_never_move_a_balance(demo, bank):
    before = bank.get("/v1/accounts/acc_pln/balances", headers=PSD2).json()
    run(demo, bank, action_of("rec_cl01"))
    run(demo, bank, action_of("rec_412"))
    assert bank.get("/v1/accounts/acc_pln/balances", headers=PSD2).json() == before


def test_unreachable_bank_fails_and_emits_nothing(demo):
    def down(request):
        raise httpx.ConnectError("connection refused", request=request)

    with httpx.Client(base_url="http://bank.invalid", transport=httpx.MockTransport(down)) as client:
        with pytest.raises(ExecutionFailed, match="unreachable"):
            execute_action(demo, APPROVAL, action_of("rec_cl01"), "co_borsuk", client=client, token=TOKEN)
    assert simulated_events(demo) == []


def test_bank_refusal_is_reported(demo, bank):
    with pytest.raises(ExecutionFailed, match="HTTP 404"):
        run(demo, bank, action_of("rec_cl01", account_id="acc_nope"))
    with pytest.raises(ExecutionFailed, match="HTTP 401"):
        execute_action(demo, APPROVAL, action_of("rec_cl01"), "co_borsuk", client=bank, token="wrong")
    assert simulated_events(demo) == []


def test_missing_parameters_are_refused(demo, bank):
    with pytest.raises(ExecutionRefused, match="limit"):
        run(demo, bank, {"kind": "apply_credit_line", "params": {}})
    with pytest.raises(ExecutionRefused, match="forward needs"):
        run(demo, bank, {"kind": "book_fx_forward", "params": {"notional": {"amount": "1", "currency": "USD"}}})
