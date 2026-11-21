"""A seeded generated month of contract-shaped Documents and Transactions with ground truth; all names invented."""
import random
from datetime import date, timedelta

COMPANY = {"id": "co_world", "tax_id": "9990000014"}
NBP = {"PLN": 1.0, "EUR": 4.41, "USD": 3.91}
SELLERS = [
    ("Chmura Polska Sp. z o.o.", "9990000020", "CHMURAPL*CLOUD 4F2K", "PLN", 610.0, 0.23),
    ("Serwerownia Odra Sp. z o.o.", "9990000037", "SERWEROWNIA ODRA WROCLAW", "PLN", 184.5, 0.23),
    ("PixelBoard Inc.", None, "PIXELBOARD.COM* SAN FRANCISCO", "USD", 45.0, 0.0),
    ("TokenRoute Inc.", None, "TOKENROUTE.AI", "USD", 120.0, 0.0),
    ("Notely Labs Inc.", None, "NOTELY LABS INC", "USD", 96.0, 0.0),
    ("ElektroMarkt Polska S.A.", "9990000043", "ELEKTROMARKT LODZ", "PLN", 1299.0, 0.23),
    ("Koleje Wschodnie S.A.", "9990000126", "KOLEJE WSCH BILET", "PLN", 169.0, 0.08),
    ("Rechenwerk Online GmbH", None, "RECHENWERK ONLINE GMBH", "EUR", 58.9, 0.0),
    ("Biuro Rachunkowe Abakus", "9990000132", "BR ABAKUS", "PLN", 1230.0, 0.23),
    ("Coworking Hala Sp. z o.o.", "9990000149", "COWORKING HALA", "PLN", 2460.0, 0.23),
    ("Targowisko.pl sp. z o.o.", "9990000155", "TARGOWISKO POZNAN", "PLN", 349.0, 0.23),
    ("Kreska Design Pty Ltd", None, "KRESKA* I04512", "EUR", 11.99, 0.0),
]
PAYERS = ["company_pln", "company_eur", "owner_private", "employee_private"]
EMPLOYEES = ["a.nowak@sample.test", "j.kowalski@sample.test", "m.wisniewska@sample.test"]
OWNER = "owner@sample.test"
PEOPLE = [{"person_id": f"per_e{i}", "name": f"Employee {i} (SAMPLE)", "email": e, "role": "employee"}
          for i, e in enumerate(EMPLOYEES)] + [
    {"person_id": "per_owner", "name": "Owner (SAMPLE)", "email": OWNER, "role": "owner"}]
ACCOUNTS = [
    {"id": "acc_w_pln", "company_id": "co_world", "kind": "company_bank", "currency": "PLN", "card_last4": []},
    {"id": "acc_w_eur", "company_id": "co_world", "kind": "company_bank", "currency": "EUR", "card_last4": []},
    {"id": "acc_w_owner", "company_id": "co_world", "kind": "owner_private", "currency": "PLN", "card_last4": []},
]
ACCOUNT_OF = {"company_pln": "acc_w_pln", "company_eur": "acc_w_eur", "owner_private": "acc_w_owner"}
PAID_BY = {"company_pln": "company_account", "company_eur": "company_account", "owner_private": "owner_private",
           "employee_private": "employee_private"}


def _m(x: float, ccy: str) -> dict:
    return {"amount": f"{x:.2f}", "currency": ccy}


CHANNEL = {"ksef": "ksef", "email_pdf": "email", "photo": "photo"}
METHOD = {"ksef": "xml_parse", "email_pdf": "docling_llm", "photo": "llm_vision"}


def _generate(seed: int):
    rnd = random.Random(seed)

    def ocr_noise(s):
        if rnd.random() < 0.3:
            s = s.replace("Sp. z o.o.", "SP Z O O").replace("S.A.", "SA")
        if rnd.random() < 0.15 and len(s) > 6:
            i = rnd.randrange(len(s))
            s = s[:i] + s[i + 1:]
        return s

    docs, bank, truth, senders, all_copies = [], [], [], {}, []
    for i in range(60):
        seller, nip, desc, cur, typ, vr = rnd.choice(SELLERS)
        d = date(2026, 10, 1) + timedelta(days=rnd.randrange(30))
        gross = round(typ * rnd.uniform(0.85, 1.2), 2)
        vat = round(gross * vr / (1 + vr), 2)
        payer = rnd.choices(PAYERS, weights=[45, 10, 15, 30])[0]
        if payer == "company_eur" and cur != "EUR":
            payer = "company_pln"
        personal = payer in ("owner_private", "employee_private")
        buyer_is_company = (not personal) or rnd.random() < 0.35
        number = f"FV/{d:%m}/{1000 + i}"
        txn_id = None
        if payer != "employee_private" and rnd.random() > 0.0:
            acct_cur = "EUR" if payer == "company_eur" else "PLN"
            amt = gross if cur == acct_cur else round(gross * NBP[cur] / NBP[acct_cur] * rnd.uniform(1.005, 1.035), 2)
            transfer = nip is not None and gross > 1000 and payer == "company_pln"
            booked = d + timedelta(days=rnd.choice([0, 0, 1, 2, 3]))
            text = f"{seller} {number}" if transfer else f"{desc} {rnd.randrange(1000, 9999)}"
            original = None
            if cur != acct_cur:
                text += f" {gross:.2f} {cur}"
                original = _m(-gross, cur)
            txn_id = f"txn_B{len(bank)}"
            bank.append({"id": txn_id, "account_id": ACCOUNT_OF[payer], "booking_date": booked.isoformat(),
                         "original_amount": original,
                         "amount": _m(-amt, acct_cur), "amount_base": _m(-amt, acct_cur), "description": text,
                         "counterparty_name_raw": text, "counterparty_account": None, "card_last4": None,
                         "transaction_type": "transfer_out" if transfer else "card_payment",
                         "recurring_series_id": None, "match_status": "unmatched"})
        doc_id = None
        if not (rnd.random() < 0.08 and not personal):
            channels = []
            if nip and buyer_is_company and cur == "PLN":
                channels.append("ksef")
            if rnd.random() < 0.7 or not channels:
                channels.append("email_pdf")
            if rnd.random() < 0.25:
                channels.append("photo")
            copies = []
            for ch in channels:
                sender = None if ch == "ksef" else (rnd.choice(EMPLOYEES) if payer == "employee_private" else OWNER)
                name, num, g = seller, number, gross
                if ch != "ksef":
                    name = ocr_noise(seller)
                    if ch == "photo" and rnd.random() < 0.3:
                        num = None
                    if ch == "photo" and rnd.random() < 0.1:
                        g = round(gross + rnd.choice([-0.9, 0.09, 1.0]), 2)
                copies.append((ch, sender, name, num, g))
            doc_id = f"doc_E{i}"
            foreign = cur != "PLN"
            senders[doc_id] = next((c[1] for c in copies if c[1]), None)
            for k, (ch, sender, name, num, g) in enumerate(copies):
                doc = {
                    "id": doc_id if k == 0 else f"{doc_id}_c{k}", "company_id": "co_world", "direction": "purchase",
                    "doc_type": "invoice", "channel": CHANNEL[ch], "extraction": {"method": METHOD[ch]},
                    "created_at": f"{d.isoformat()}T{8 + k:02d}:00:00Z" if ch != "ksef" else f"{d.isoformat()}T23:00:00Z",
                    "number": num, "issue_date": d.isoformat(), "due_date": None,
                    "seller": {"name": name, "tax_id": nip},
                    "buyer": {"tax_id": COMPANY["tax_id"] if buyer_is_company else None, "is_company": buyer_is_company},
                    "totals": {"gross": _m(g, cur), "vat": _m(vat, cur),
                               "gross_base": _m(round(g * NBP[cur], 2), "PLN"),
                               "fx": {"rate": f"{NBP[cur]}", "rate_date": d.isoformat(), "source": "stand-in",
                                      "rule": "pl_tax_prev_business_day"} if foreign else None},
                    "vat_lines": [], "lines": [],
                    "payment": {"method": "unknown", "card_last4": None, "bank_account": None},
                    "submitted_by": None, "flags": [], "status": "extracted", "category_suggestion": None,
                }
                all_copies.append((doc, i))
                if k == 0:
                    docs.append(doc)
        truth.append({"event": i, "doc_id": doc_id, "txn_id": txn_id, "paid_by": PAID_BY[payer],
                      "doc_missing": doc_id is None and txn_id is not None,
                      "vat_lost": round(vat * NBP[cur], 2) if (not buyer_is_company and vat > 0) else 0.0})
    for k in range(8):
        v = rnd.choice([-8200.0, -3120.55, 14760.0, 9840.0])
        t = rnd.choice(["WYNAGRODZENIE 10/2026", "ZUS SKLADKI", "FV 12/10/2026 KLIENT SAMPLE"])
        v = abs(v) if t.startswith("FV") else -abs(v)
        bank.append({"id": f"txn_N{k}", "account_id": "acc_w_pln",
                     "booking_date": (date(2026, 10, 10) + timedelta(days=k)).isoformat(),
                     "amount": _m(v, "PLN"), "amount_base": _m(v, "PLN"), "description": t,
                     "counterparty_name_raw": t, "counterparty_account": None, "card_last4": None,
                     "transaction_type": "transfer_in" if v > 0 else "transfer_out", "recurring_series_id": None,
                     "match_status": "unmatched"})
    rnd.shuffle(docs)
    rnd.shuffle(bank)
    rnd.shuffle(all_copies)
    return docs, bank, senders, truth, all_copies


def build(seed: int):
    return _generate(seed)[:4]


def build_copies(seed: int):
    return _generate(seed)[4]
