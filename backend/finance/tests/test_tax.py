"""Polish tax rules. Pure tests: no database, no LLM."""
from datetime import date
from decimal import Decimal

import pytest

from backend.finance.tax import (
    due_date, gross_from_net, pit4_advance, pln_unit, tax_components, tax_document, zus_payment,
)

D = Decimal
PLN_RATES = {"PLN": D(1), "EUR": D("4.41")}
EUR_P = D(1) / D("4.41")


def pay(net, p=D(1)):
    gross = gross_from_net(D(net), p)
    return gross, pit4_advance(gross, D(0), p)[0], zus_payment(gross)


@pytest.mark.parametrize("net, gross, pit, zus", [
    ("8200.00", "11544.82", "865", "4843.76"),
    ("7400.00", "10371.27", "744", "4351.38"),
    ("7000.00", "9784.49", "683", "4105.19"),
    ("2000.00", "2547.00", "0", "1068.62"),
])
def test_pay_in_pln(net, gross, pit, zus):
    assert pay(net) == (D(gross), D(pit), D(zus))


def test_pit4_base_of_net_8200_is_9712():
    assert pit4_advance(D("11544.82"), D(0)) == (D(865), D(9712))


def test_the_part_above_120000_a_year_is_taxed_at_32_percent():
    assert pit4_advance(D("11544.82"), D("115000"))[0] == D(1808)


def test_pay_in_eur_converts_the_pln_constants():
    gross = gross_from_net(D("2850.00"), EUR_P)
    assert gross == D("4071.01")
    assert pit4_advance(gross, D(0), EUR_P)[0] == D(347)
    assert zus_payment(gross) == D("1708.04")


def test_pln_unit():
    assert pln_unit("PLN", {}) == 1
    assert pln_unit("EUR", {"PLN": D("0.25")}) == D("0.25")
    assert pln_unit("EUR", {}) == D(1) / D("4.41")


@pytest.mark.parametrize("dom, y, m, expected", [
    (25, 2026, 10, date(2026, 11, 25)),
    (25, 2026, 11, date(2026, 12, 28)),
    (15, 2026, 10, date(2026, 11, 16)),
    (20, 2026, 11, date(2026, 12, 21)),
    (20, 2026, 12, date(2027, 1, 20)),
])
def test_due_dates(dom, y, m, expected):
    assert due_date(dom, y, m) == expected


def doc(id_, direction, day, net, vat, currency="PLN", vat_currency=None, **extra):
    return {
        "id": id_, "direction": direction, "doc_type": "invoice", "status": "approved", "number": id_.upper(),
        "issue_date": day, "sale_date": day,
        "totals": {"net": {"amount": net, "currency": currency},
                   "vat": {"amount": vat, "currency": vat_currency or currency}},
        "flags": [], **extra,
    }


def components(docs, salaries=(), as_of=date(2026, 11, 21), end=date(2027, 1, 5)):
    return tax_components(as_of=as_of, end=end, base="PLN", rates=PLN_RATES,
                          documents=[t for t in map(tax_document, docs) if t], salaries=list(salaries))


def by_id(comps):
    return {c["id"]: c for c in comps}


OCTOBER = [
    doc("s1", "sale", "2026-10-31", "30000.00", "6900.00"),
    doc("p1", "purchase", "2026-10-25", "7967.48", "1832.52"),
    doc("p2", "purchase", "2026-10-20", "1056.10", "242.90", doc_type="receipt"),
    doc("s2", "sale", "2026-10-15", "18400.00", "0.00", currency="EUR"),
]


def test_tax_document_skips_duplicates_and_documents_without_a_date_or_net():
    base = doc("d1", "sale", "2026-10-31", "100.00", "23.00")
    assert tax_document(base)["month"] == "2026-10"
    assert tax_document({**base, "status": "duplicate"}) is None
    assert tax_document({**base, "status": "rejected"}) is None
    assert tax_document({**base, "issue_date": None, "sale_date": None}) is None
    assert tax_document({**base, "totals": {}}) is None


def test_tax_document_marks_non_deductible_purchases():
    flagged = doc("d2", "purchase", "2026-10-31", "100.00", "23.00", flags=["vat_not_deductible"])
    assert tax_document(flagged)["deductible"] is False
    assert tax_document(doc("d3", "purchase", "2026-10-31", "100.00", "23.00", doc_type="receipt"))["deductible"] is False
    assert tax_document(doc("d4", "purchase", "2026-10-31", "100.00", "23.00"))["deductible"] is True


def test_vat_of_a_closed_month_is_output_minus_deductible_input():
    c = by_id(components(OCTOBER))["c_tax_vat_202610"]

    assert c["kind"] == "tax"
    assert c["amount_base"] == {"amount": "-5067.00", "currency": "PLN"}
    assert c["dates"] == ["2026-11-25"]
    assert c["confidence"] == 0.9
    assert c["label"] == "VAT for October 2026"
    assert c["evidence"][0]["kind"] == "rule"
    assert c["evidence"][1]["kind"] == "document"
    assert "output VAT 6,900.00 − deductible input VAT 1,832.52" in c["schedule"]
    assert c["explainer"] == "VAT you charged clients minus VAT you paid suppliers"
    assert [(s["op"], s["amount"] and s["amount"]["amount"]) for s in c["breakdown"]] == [
        ("start", "6900.00"), ("minus", "1832.52"), ("equals", "5067.00")]


def test_vat_loss_of_a_month_is_carried_forward():
    docs = [doc("p0", "purchase", "2026-09-10", "10000.00", "2300.00"),
            doc("s1", "sale", "2026-10-31", "30000.00", "6900.00")]
    comps = by_id(components(docs))

    assert comps["c_tax_vat_202610"]["amount_base"]["amount"] == "-4600.00"
    assert "c_tax_vat_202609" not in comps


def test_vat_of_an_open_month_is_an_estimate_from_the_closed_months():
    docs = [doc(f"s{m}", "sale", f"2026-{m:02d}-15", "10000.00", "2300.00") for m in (8, 9, 10)]
    c = by_id(components(docs))["c_tax_vat_202611"]

    assert c["label"].endswith(" (estimate)")
    assert c["confidence"] == 0.6
    assert c["dates"] == ["2026-12-28"]
    assert c["amount_base"]["amount"] == "-2300.00"
    assert "mean of the last 3 closed months" in c["schedule"]
    assert c["evidence"][0]["kind"] == "rule"
    assert {e["id"] for e in c["evidence"][1:]} == {"s8", "s9", "s10"}
    assert c["breakdown"][-1] == {"label": "November is not over yet: the VAT is the average of Aug, Sep and Oct",
                                  "op": "note", "amount": None}


def test_cit_advance_is_cumulative_and_open_months_are_estimated():
    docs = [
        doc("s1", "sale", "2026-01-15", "100000.00", "0.00"),
        doc("p1", "purchase", "2026-01-20", "60000.00", "0.00"),
        doc("p2", "purchase", "2026-02-10", "10000.00", "0.00"),
        doc("s3", "sale", "2026-03-10", "20000.00", "0.00"),
    ]
    comps = components(docs, as_of=date(2026, 4, 1), end=date(2026, 5, 31))
    cit = [c for c in comps if c["id"].startswith("c_tax_cit")]

    assert [c["id"] for c in cit] == ["c_tax_cit_202603", "c_tax_cit_202604"]
    assert cit[0]["amount_base"]["amount"] == "-900.00"
    assert cit[0]["dates"] == ["2026-04-20"]
    assert cit[0]["confidence"] == 0.9
    assert cit[1]["amount_base"]["amount"] == "-1500.00"
    assert cit[1]["dates"] == ["2026-05-20"]
    assert cit[1]["label"].endswith(" (estimate)")


def test_foreign_documents_count_for_cit_but_not_for_vat():
    docs = [doc("s1", "sale", "2026-10-15", "1000.00", "0.00", currency="EUR")]
    comps = by_id(components(docs, as_of=date(2026, 11, 1), end=date(2026, 12, 31)))

    assert not any(i.startswith("c_tax_vat") for i in comps)
    assert comps["c_tax_cit_202610"]["amount_base"]["amount"] == "-397.00"


JAN = {"day": date(2026, 11, 30), "key": "jan", "name": "Jan", "net": D("8200.00"),
       "evidence": {"kind": "transaction", "id": "t1", "label": "Salary Jan"}}


def test_payroll_gives_pit4_and_zus():
    comps = by_id(components([], [JAN]))
    pit4, zus = comps["c_tax_pit4_202611"], comps["c_tax_zus_202611"]

    assert pit4["kind"] == "tax"
    assert pit4["amount_base"]["amount"] == "-865.00"
    assert pit4["dates"] == ["2026-12-21"]
    assert zus["kind"] == "social_security"
    assert zus["amount_base"]["amount"] == "-4843.76"
    assert zus["dates"] == ["2026-12-15"]
    assert pit4["evidence"][0]["kind"] == "rule"
    assert pit4["evidence"][1]["id"] == "t1"


def test_pit4_threshold_counts_year_to_date_base_of_each_person_and_resets_in_january():
    high = [{**JAN, "day": date(2026, m, 28), "net": D("16000.00")} for m in range(1, 13)]
    high.append({**JAN, "day": date(2027, 1, 28), "net": D("16000.00")})
    comps = by_id(components([], high, as_of=date(2026, 1, 1), end=date(2027, 2, 28)))
    amount = lambda month: -D(comps[f"c_tax_pit4_{month}"]["amount_base"]["amount"])

    assert amount("202612") > amount("202601")
    assert amount("202701") == amount("202601")


def test_components_follow_role_5_parsing_rules():
    comps = components(OCTOBER, [JAN])
    assert comps
    for c in comps:
        assert c["label"].split(" for ")[0].split(",")[0] in ("VAT", "CIT advance", "PIT-4", "ZUS")
        assert len(c["dates"]) == 1
        assert c["evidence"]


def test_components_have_exactly_the_contract_keys():
    keys = {"id", "label", "kind", "amount_base", "schedule", "dates", "confidence", "evidence", "explainer", "breakdown"}
    comps = components(OCTOBER, [JAN])
    assert comps
    assert all(set(c) == keys for c in comps)


def test_nothing_to_compute_gives_no_components():
    assert components([]) == []


def test_every_breakdown_ends_at_the_amount_to_pay():
    comps = components(OCTOBER, [JAN])
    assert {c["id"].split("_")[2] for c in comps} >= {"vat", "cit", "pit4", "zus"}
    for c in comps:
        steps = c["breakdown"]
        assert [x for x in steps if x["op"] != "note"][0]["op"] == "start"
        last = [s for s in steps if s["op"] == "equals"][-1]
        assert last["amount"]["amount"] == c["amount_base"]["amount"].lstrip("-")
        assert all(s["amount"] is None for s in steps if s["op"] == "note")
