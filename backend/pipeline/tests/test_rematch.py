"""Re-matching data an older matcher paired: each monthly invoice gets its own month's transfer back, owner decisions
stay, stale cards are retired, and a second run changes nothing."""
from backend.db.fixtures import load_fixtures
from backend.db.store import Store
from backend.pipeline.handlers import rematch
from backend.pipeline.main import make_context
from backend.pipeline.tests.test_match import MonthlyInvoicesOfTheSameAmount as Monthly


def shifted_match(month: int, txn_month: int) -> dict:
    """What the old matcher saved: the invoice of `month` holding the transfer of `txn_month`."""
    return {"id": f"mat_aw_{month:02d}", "match_type": "document_transaction", "document_id": f"doc_aw_{month:02d}",
            "transaction_id": f"txn_aw_{txn_month:02d}", "score": 1.0, "reasons": [], "paid_by": "company_account",
            "consequences": {"vat_deductible": True}, "status": "suggested"}


def own_line(s: Store, month: int) -> str | None:
    m = next((m for m in s.list("match", document_id=f"doc_aw_{month:02d}") if m["status"] != "rejected"), None)
    return m and m.get("transaction_id")


def test_shifted_pairings_are_put_right_once(db):
    load_fixtures(db)
    s = Store(db)
    for month in (4, 5, 6):
        s.put("document", {**Monthly.invoice(month), "company_id": "co_borsuk", "raw_item_ids": [f"raw_aw_{month:02d}"]}, company_id="co_borsuk")
        s.put("transaction", {**Monthly.transfer(month), "account_id": "acc_pln", "match_status": "suggested"}, company_id="co_borsuk")
    s.put("match", shifted_match(4, 5), company_id="co_borsuk")
    s.put("match", shifted_match(5, 6), company_id="co_borsuk")
    s.put("match", {**shifted_match(6, 6), "transaction_id": None, "match_type": "document_no_transaction"}, company_id="co_borsuk")
    s.put("recommendation", {"id": "rec_old_card", "company_id": "co_borsuk", "type": "confirm_match", "status": "new",
                             "subject": {"kind": "match", "id": "mat_aw_04", "label": "old pairing"}}, company_id="co_borsuk")

    ctx = make_context(db)
    assert rematch(ctx, "co_borsuk") >= 3
    db.commit()

    assert [own_line(s, m) for m in (4, 5, 6)] == ["txn_aw_04", "txn_aw_05", "txn_aw_06"]
    assert all(s.get("transaction", f"txn_aw_{m:02d}")["match_status"] in ("suggested", "matched") for m in (4, 5, 6))
    assert s.get("recommendation", "rec_old_card")["status"] == "superseded"
    assert rematch(ctx, "co_borsuk") == 0  # idempotent


def test_an_owner_decision_is_kept(db):
    load_fixtures(db)
    s = Store(db)
    for month in (4, 5):
        s.put("document", {**Monthly.invoice(month), "company_id": "co_borsuk", "raw_item_ids": [f"raw_aw_{month:02d}"]}, company_id="co_borsuk")
        s.put("transaction", {**Monthly.transfer(month), "account_id": "acc_pln", "match_status": "matched"}, company_id="co_borsuk")
    s.put("match", {**shifted_match(4, 5), "status": "confirmed", "decided_by": {"role": "owner", "name": "Owner"}}, company_id="co_borsuk")

    rematch(make_context(db), "co_borsuk")
    db.commit()

    assert own_line(s, 4) == "txn_aw_05"  # the owner confirmed it: Ordo does not overrule
    assert own_line(s, 5) is None  # its own transfer is held by that decision; an earlier one cannot pay it
