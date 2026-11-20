#!/usr/bin/env python3
"""Spike 04: does a small rule-based matching engine survive "messy SME data"?
Generates a synthetic month for a fictional Polish company (seeded), with ground truth:
  - purchases paid from the company PLN account, company EUR account, the owner's
    private card, and employees' private cards (no bank line visible to us),
  - documents arriving 1-3 times (KSeF-style XML, e-mail PDF, phone photo) with OCR-like noise,
  - foreign-currency SaaS (USD) settled in PLN with a bank spread,
  - bank lines with no document, noisy card descriptors.
Then runs: dedup -> match document<->bank line -> classify who paid -> VAT/reimbursement flags.
Prints precision/recall against the ground truth. Stdlib only.
Usage: python3 matching_spike.py [seed]
"""
import random, re, sys, time, xml.etree.ElementTree as ET
from datetime import date, timedelta
from difflib import SequenceMatcher

seed = int(sys.argv[1]) if len(sys.argv) > 1 else 7
rnd = random.Random(seed); t0 = time.time()
COMPANY_NIP = "9990000014"   # SAMPLE, not a real company
NBP = {"PLN": 1.0, "EUR": 4.41, "USD": 3.91}
SELLERS = [  # ALL INVENTED. name on invoice, NIP (invented, prefix 999), card descriptor on bank statement, currency, typical gross, VAT rate
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

def ksef_xml(doc):
    """Minimal FA-style XML (structure approximates the KSeF logical schema; SAMPLE only)."""
    ns = "http://crd.gov.pl/wzor/2025/06/25/13775/"
    f = ET.Element(f"{{{ns}}}Faktura")
    p1 = ET.SubElement(f, f"{{{ns}}}Podmiot1"); di = ET.SubElement(p1, f"{{{ns}}}DaneIdentyfikacyjne")
    ET.SubElement(di, f"{{{ns}}}NIP").text = doc["seller_nip"]; ET.SubElement(di, f"{{{ns}}}Nazwa").text = doc["seller"]
    p2 = ET.SubElement(f, f"{{{ns}}}Podmiot2"); di2 = ET.SubElement(p2, f"{{{ns}}}DaneIdentyfikacyjne")
    ET.SubElement(di2, f"{{{ns}}}NIP").text = COMPANY_NIP
    fa = ET.SubElement(f, f"{{{ns}}}Fa")
    for tag, val in [("KodWaluty", doc["currency"]), ("P_1", doc["date"].isoformat()), ("P_2", doc["number"]),
                     ("P_13_1", f"{doc['net']:.2f}"), ("P_14_1", f"{doc['vat']:.2f}"), ("P_15", f"{doc['gross']:.2f}")]:
        ET.SubElement(fa, f"{{{ns}}}{tag}").text = val
    return ET.tostring(f, encoding="unicode")

def parse_ksef(xml):
    ns = {"k": "http://crd.gov.pl/wzor/2025/06/25/13775/"}; r = ET.fromstring(xml)
    g = lambda p: r.findtext(p, namespaces=ns)
    return {"seller": g("k:Podmiot1/k:DaneIdentyfikacyjne/k:Nazwa"), "seller_nip": g("k:Podmiot1/k:DaneIdentyfikacyjne/k:NIP"),
            "buyer_nip": g("k:Podmiot2/k:DaneIdentyfikacyjne/k:NIP"), "currency": g("k:Fa/k:KodWaluty"),
            "date": date.fromisoformat(g("k:Fa/k:P_1")), "number": g("k:Fa/k:P_2"),
            "gross": float(g("k:Fa/k:P_15")), "vat": float(g("k:Fa/k:P_14_1"))}

def ocr_noise(s):
    if rnd.random() < 0.3: s = s.replace("Sp. z o.o.", "SP Z O O").replace("S.A.", "SA")
    if rnd.random() < 0.15 and len(s) > 6: i = rnd.randrange(len(s)); s = s[:i] + s[i + 1:]
    return s

# ---------- generate ----------
truth, docs, bank = [], [], []
for i in range(60):
    seller, nip, desc, cur, typ, vr = rnd.choice(SELLERS)
    d = date(2026, 10, 1) + timedelta(days=rnd.randrange(30))
    gross = round(typ * rnd.uniform(0.85, 1.2), 2); vat = round(gross * vr / (1 + vr), 2)
    payer = rnd.choices(PAYERS, weights=[45, 10, 15, 30])[0]
    if payer == "company_eur" and cur != "EUR": payer = "company_pln"
    personal = payer in ("owner_private", "employee_private")
    buyer_is_company = (not personal) or rnd.random() < 0.35      # most private purchases are on the person's own name
    ev = {"id": i, "payer": payer, "buyer_is_company": buyer_is_company, "vat": vat, "gross": gross, "cur": cur, "bank_id": None}
    base = {"event": i, "seller": seller, "seller_nip": nip, "currency": cur, "date": d, "number": f"FV/{d:%m}/{1000+i}",
            "gross": gross, "vat": vat, "net": round(gross - vat, 2),
            "buyer_nip": COMPANY_NIP if buyer_is_company else None}
    # bank line (only if paid from an account we are connected to)
    if payer != "employee_private" and rnd.random() > 0.0:
        acct_cur = "EUR" if payer == "company_eur" else "PLN"
        amt = gross if cur == acct_cur else round(gross * NBP[cur] / NBP[acct_cur] * rnd.uniform(1.005, 1.035), 2)
        transfer = nip is not None and gross > 1000 and payer == "company_pln"
        bank.append({"id": f"B{len(bank)}", "account": payer, "date": d + timedelta(days=rnd.choice([0, 0, 1, 2, 3])),
                     "amount": -amt, "currency": acct_cur,
                     "text": (f"{seller} {base['number']}" if transfer else f"{desc} {rnd.randrange(1000,9999)}")})
        ev["bank_id"] = bank[-1]["id"]
    # documents: 0..3 copies via different channels
    if rnd.random() < 0.08 and not personal:
        ev["doc_missing"] = True                                   # bank line without any document
    else:
        channels = []
        if nip and buyer_is_company and cur == "PLN": channels.append("ksef")
        if rnd.random() < 0.7 or not channels: channels.append("email_pdf")
        if rnd.random() < 0.25: channels.append("photo")
        for ch in channels:
            doc = dict(base, id=f"D{len(docs)}", channel=ch,
                       sender=(rnd.choice(EMPLOYEES) if payer == "employee_private" else "owner@sample.test") if ch != "ksef" else None)
            if ch == "ksef": doc.update(parse_ksef(ksef_xml(base)), id=doc["id"], channel=ch, event=i, sender=None)
            else:
                doc["seller"] = ocr_noise(seller)
                if ch == "photo" and rnd.random() < 0.3: doc["number"] = None           # OCR missed the number
                if ch == "photo" and rnd.random() < 0.1: doc["gross"] = round(gross + rnd.choice([-0.9, 0.09, 1.0]), 2)
            docs.append(doc)
    truth.append(ev)
for k in range(8):   # unrelated bank noise: salaries, ZUS, incoming payments
    bank.append({"id": f"B{len(bank)}", "account": "company_pln", "date": date(2026, 10, 10) + timedelta(days=k),
                 "amount": rnd.choice([-8200.0, -3120.55, 14760.0, 9840.0]), "currency": "PLN", "text": rnd.choice(["WYNAGRODZENIE 10/2026", "ZUS SKLADKI", "FV 12/10/2026 KLIENT SAMPLE"])})
rnd.shuffle(docs); rnd.shuffle(bank)

# ---------- engine ----------
def norm(s): return re.sub(r"[^a-z0-9 ]", " ", (s or "").lower().replace("sp. z o.o.", "").replace("s.a.", ""))
def name_sim(a, b):
    a, b = norm(a), norm(b); ta, tb = set(a.split()), set(b.split())
    tok = len(ta & tb) / max(1, min(len(ta), len(tb)))
    return max(tok, SequenceMatcher(None, a, b).ratio())

# 1) dedup documents into purchase clusters
clusters = []
for d in docs:
    for c in clusters:
        h = c[0]
        same_no = d["number"] and h["number"] and d["number"] == h["number"] and (d["seller_nip"] == h["seller_nip"] or name_sim(d["seller"], h["seller"]) > 0.6)
        fuzzy = name_sim(d["seller"], h["seller"]) > 0.75 and abs(d["gross"] - h["gross"]) <= 1.0 and d["date"] == h["date"] and d["currency"] == h["currency"] \
                and not (d["number"] and h["number"] and d["number"] != h["number"])
        if same_no or fuzzy: c.append(d); break
    else: clusters.append([d])
PRIO = {"ksef": 0, "email_pdf": 1, "photo": 2}        # which copy is the "golden" record
golden = [sorted(c, key=lambda d: PRIO[d["channel"]])[0] for c in clusters]

# 2) match clusters to bank lines (greedy on score)
def score(doc, b):
    if b["amount"] >= 0: return 0, []
    why = []; s = 0.0; amt = -b["amount"]
    if doc["currency"] == b["currency"]:
        if abs(amt - doc["gross"]) <= 0.01: s += 0.5; why.append("amount exact")
        elif abs(amt - doc["gross"]) <= 1.0: s += 0.3; why.append("amount ~1 PLN")
        else: return 0, []
    else:
        exp = doc["gross"] * NBP[doc["currency"]] / NBP[b["currency"]]
        if 0.995 * exp <= amt <= 1.045 * exp: s += 0.35; why.append(f"FX amount within bank spread of NBP ({exp:.2f})")
        else: return 0, []
    lag = (b["date"] - doc["date"]).days
    if -1 <= lag <= 5: s += 0.2 - 0.02 * abs(lag); why.append(f"date lag {lag}d")
    else: return 0, []
    if doc["number"] and doc["number"].lower() in b["text"].lower(): s += 0.4; why.append("invoice number in transfer title")
    ns = name_sim(doc["seller"], b["text"]); s += 0.3 * ns
    if ns > 0.5: why.append(f"name similarity {ns:.2f}")
    return s, why
cands = sorted(((score(g, b), gi, b["id"]) for gi, g in enumerate(golden) for b in bank), key=lambda x: -x[0][0])
used_d, used_b, match = set(), set(), {}
for (s, why), gi, bid in cands:
    if s < 0.55 or gi in used_d or bid in used_b: continue
    used_d.add(gi); used_b.add(bid); match[gi] = (bid, round(min(s, 1.0), 2), why)
bank_by_id = {b["id"]: b for b in bank}

# 3) classify who paid + flags
results = []
for gi, g in enumerate(golden):
    m = match.get(gi)
    if m: paid_by = bank_by_id[m[0]]["account"]
    elif any(d["sender"] in EMPLOYEES for d in clusters[gi]): paid_by = "employee_private"
    else: paid_by = "unknown"
    flags = []
    if paid_by in ("employee_private", "owner_private"): flags.append("REIMBURSEMENT_OWED")
    if g["buyer_nip"] != COMPANY_NIP and g["vat"] > 0: flags.append(f"VAT_NOT_DEDUCTIBLE_{g['vat']:.2f}")
    results.append({"event": g["event"], "paid_by": paid_by, "flags": flags, "match": m, "copies": len(clusters[gi])})

# ---------- evaluate ----------
ev_by = {e["id"]: e for e in truth}
n_docs_events = len({d["event"] for d in docs})
pure = sum(len({d["event"] for d in c}) == 1 for c in clusters)
print(f"seed {seed}: {len(truth)} purchases, {len(docs)} documents ({sum(d['channel']=='ksef' for d in docs)} KSeF XML, "
      f"{sum(d['channel']=='email_pdf' for d in docs)} e-mail, {sum(d['channel']=='photo' for d in docs)} photo), {len(bank)} bank lines")
print(f"dedup: {len(docs)} documents -> {len(clusters)} clusters (true distinct purchases with a document: {n_docs_events}); pure clusters: {pure}/{len(clusters)}")
tp = sum(1 for r in results if r["match"] and ev_by[r["event"]]["bank_id"] == r["match"][0])
fp = sum(1 for r in results if r["match"] and ev_by[r["event"]]["bank_id"] != r["match"][0])
possible = sum(1 for e in truth if e["bank_id"] and any(d["event"] == e["id"] for d in docs))
print(f"doc<->bank matching: {tp} correct, {fp} wrong, {possible - tp} missed  => precision {tp/max(1,tp+fp):.0%}, recall {tp/max(1,possible):.0%}")
ok = sum(1 for r in results if r["paid_by"] == ev_by[r["event"]]["payer"])
print(f"who-paid classification: {ok}/{len(results)} correct ({ok/len(results):.0%})")
emp_true = {e["id"] for e in truth if e["payer"] == "employee_private" and any(d["event"] == e["id"] for d in docs)}
emp_pred = {r["event"] for r in results if r["paid_by"] == "employee_private"}
print(f"employee-paid detection: {len(emp_true & emp_pred)}/{len(emp_true)} found, {len(emp_pred - emp_true)} false alarms")
lost = sum(float(f.split('_')[-1]) for r in results for f in r["flags"] if f.startswith("VAT_NOT"))
true_lost = sum(e["vat"] for e in truth if not e["buyer_is_company"] and any(d["event"] == e["id"] for d in docs))
print(f"VAT not deductible flagged: {lost:,.2f} PLN-equivalent units (ground truth {true_lost:,.2f})")
orphans = [b for b in bank if b["id"] not in used_b and b["amount"] < 0 and "WYNAGR" not in b["text"] and "ZUS" not in b["text"]]
true_missing = sum(1 for e in truth if e.get("doc_missing"))
print(f"bank lines without document (-> 'missing document' queue): {len(orphans)} (ground truth {true_missing})")
ex = next(r for r in results if r["match"] and "FX" in " ".join(r["match"][2]))
print(f"example explanation: event {ex['event']} -> bank {ex['match'][0]} confidence {ex['match'][1]}: {'; '.join(ex['match'][2])}")
print(f"elapsed: {time.time() - t0:.2f}s")
