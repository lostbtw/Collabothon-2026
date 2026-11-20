#!/usr/bin/env python3
"""Borsuk Labs (SAMPLE) invoices as KSeF FA(3) XML, issued 1 Dec 2025 - 31 Oct 2026.

Takes the invoice data that bank_2026.py attaches to the bank lines, so amounts and dates always
agree with the bank CSVs. Adds the invoices that have no bank line: October sales still open on
21 Nov (Meblostyl, Nordwind) and 6 cash purchases (M8).

Only Polish sellers and Borsuk Labs' own sales invoices are FA(3). Foreign vendors (SaaS, Lingua
Bridge, EUR card purchases) and private receipts are not KSeF invoices, so they are not here.

Usage: python3 sim/scenario/fa3_2026.py [--xsd DIR]
  --xsd DIR  validate every file with xmllint against the FA(3) schema in DIR
             (schemat.xsd from https://crd.gov.pl/wzor/2025/06/25/13775/, with its imports)
Output: out/fa3/<YYYY-MM>/<id>.xml and out/fa3_index.json
"""
import json
import shutil
import subprocess
import sys
from collections import defaultdict
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from xml.sax.saxutils import escape

from bank_2026 import build
from world import ACCOUNTS, NIP

OUT = Path(__file__).parent / "out"
FIRST, LAST = date(2025, 12, 1), date(2026, 10, 31)
NS = "http://crd.gov.pl/wzor/2025/06/25/13775/"
CENT = Decimal("0.01")

BORSUK = {"name": "Borsuk Labs sp. z o.o. (SAMPLE)", "nip": NIP,
          "addr": ("ul. Piotrkowska 990 lok. 4B", "90-999 Łódź"), "country": "PL"}


def nip(n):
    """Invented 999-prefixed NIP with a valid check digit."""
    while True:
        digits = f"999{n:06d}"
        check = sum(w * int(d) for w, d in zip((6, 5, 7, 2, 3, 4, 5, 6, 7), digits)) % 11
        if check < 10:
            return digits + str(check)
        n += 1


# Bank name -> party: (invoice name, NIP or None, street, city, line on the invoice, VAT rate, number prefix)
_PARTIES = [
    ("COWORKING PIOTRKOWSKA SP Z O O (SAMPLE)", "Coworking Piotrkowska sp. z o.o. (SAMPLE)", None,
     "ul. Piotrkowska 990", "90-999 Łódź", "Najem stanowiska biurowego", "23", None),
    ("BIURO RACHUNKOWE KALINOWSKA (SAMPLE)", "Biuro Rachunkowe Kalinowska (SAMPLE)", None,
     "ul. Zielona 912", "90-998 Łódź", "Obsługa księgowa", "23", None),
    ("ANNA WRONA (SAMPLE)", "Anna Wrona Software (SAMPLE)", None, "ul. Lipowa 901/2", "90-997 Łódź", None, "23", None),
    ("PIOTR LIS (SAMPLE)", "Piotr Lis IT (SAMPLE)", None, "ul. Gdańska 905", "90-996 Łódź", None, "23", None),
    ("KAROLINA MAZUR (SAMPLE)", "Karolina Mazur Design (SAMPLE)", None, "ul. Wólczańska 977", "90-995 Łódź",
     None, "23", None),
    ("MICHAL DUDEK (SAMPLE)", "Michał Dudek QA (SAMPLE)", None, "ul. Kościuszki 966", "90-994 Łódź", None, "23", None),
    ("PALIWEX SP Z O O (SAMPLE)", "Paliwex sp. z o.o. (SAMPLE)", None, "ul. Pabianicka 912", "93-999 Łódź",
     "Paliwo PB95", "23", "PX"),
    ("NORDPETRO S.A. (SAMPLE)", "Nordpetro S.A. (SAMPLE)", None, "ul. Rokicińska 921", "92-999 Łódź",
     "Olej napędowy ON", "23", "NP"),
    ("BISTRO PIOTRKOWSKA 90 (SAMPLE)", "Bistro Piotrkowska 90 s.c. (SAMPLE)", None, "ul. Piotrkowska 990/1",
     "90-999 Łódź", "Usługa gastronomiczna", "8", "BP"),
    ("SUSHI KAMIEN (SAMPLE)", "Sushi Kamień sp. z o.o. (SAMPLE)", None, "ul. Narutowicza 950", "90-993 Łódź",
     "Usługa gastronomiczna", "8", "SK"),
    ("KAWIARNIA ZIARNO (SAMPLE)", "Kawiarnia Ziarno (SAMPLE)", None, "ul. 6 Sierpnia 940", "90-992 Łódź",
     "Kawa i wypieki", "8", "KZ"),
    ("KOSZYK 24 SP Z O O (SAMPLE)", "Koszyk 24 sp. z o.o. (SAMPLE)", None, "ul. Zgierska 930", "91-999 Łódź",
     "Artykuły spożywcze do biura", "5", "K24"),
    ("BIUROSFERA SP Z O O (SAMPLE)", "Biurosfera sp. z o.o. (SAMPLE)", None, "ul. Fabryczna 920", "00-999 Warszawa",
     "Materiały biurowe", "23", "BS"),
    ("KURIERON SP Z O O (SAMPLE)", "Kurieron sp. z o.o. (SAMPLE)", None, "ul. Logistyczna 910", "05-999 Stryków",
     "Usługa kurierska", "23", "KR"),
    ("TAXIGO SP Z O O (SAMPLE)", "Taxigo sp. z o.o. (SAMPLE)", None, "ul. Taksówkowa 900", "00-998 Warszawa",
     "Przewóz osób", "8", "TG"),
    ("PARKUJ.PL SP Z O O (SAMPLE)", "Parkuj.pl sp. z o.o. (SAMPLE)", None, "ul. Postojowa 990", "30-999 Kraków",
     "Opłata parkingowa", "23", "PK"),
    ("SKLEPIK.PL SP Z O O (SAMPLE)", "Sklepik.pl sp. z o.o. (SAMPLE)", None, "ul. Handlowa 980", "61-999 Poznań",
     "Akcesoria komputerowe", "23", "SP"),
    ("RAILEXPRESS S.A. (SAMPLE)", "RailExpress S.A. (SAMPLE)", None, "ul. Dworcowa 970", "00-997 Warszawa",
     "Bilet kolejowy", "8", "RE"),
    ("DOMENOWO SP Z O O (SAMPLE)", "Domenowo sp. z o.o. (SAMPLE)", None, "ul. Serwerowa 960", "50-999 Wrocław",
     "Domena i hosting", "23", "DM"),
    ("ELEKTROMARKT POLSKA S.A. (SAMPLE)", "ElektroMarkt Polska S.A. (SAMPLE)", "9990000043",
     "ul. Pabianicka 945", "93-998 Łódź", "Sprzęt komputerowy", "23", "EM"),
    ("DEVCAMP SP Z O O (SAMPLE)", "DevCamp sp. z o.o. (SAMPLE)", None, "ul. Konferencyjna 950", "00-996 Warszawa",
     "Bilety konferencyjne", "23", "DC"),
    ("ERGO MEBLE SP Z O O (SAMPLE)", "Ergo Meble sp. z o.o. (SAMPLE)", None, "ul. Meblowa 940", "62-999 Swarzędz",
     "Krzesła biurowe", "23", None),
    ("KANCELARIA PRAWNA LEX (SAMPLE)", "Kancelaria Prawna Lex (SAMPLE)", None, "al. Kościuszki 930",
     "90-991 Łódź", "Obsługa prawna", "23", None),
    ("HOTEL CENTRUM WARSZAWA (SAMPLE)", "Hotel Centrum Warszawa sp. z o.o. (SAMPLE)", None, "ul. Hotelowa 920",
     "00-995 Warszawa", "Usługa hotelowa", "8", "HC"),
    ("DRUKARNIA PIKSEL (SAMPLE)", "Drukarnia Piksel (SAMPLE)", None, "ul. Drukarska 910", "90-990 Łódź",
     "Druk materiałów reklamowych", "23", "DP"),
    # Clients (Borsuk Labs sells to them).
    ("PIEKARNIA ZLOTY KLOS SP Z O O (SAMPLE)", "Piekarnia Złoty Kłos sp. z o.o. (SAMPLE)", None,
     "ul. Chlebowa 990", "95-999 Zgierz", "Utrzymanie i rozwój sklepu internetowego", "23", None),
    ("KADROWNIA SP Z O O (SAMPLE)", "Kadrownia sp. z o.o. (SAMPLE)", None, "ul. Kadrowa 980", "90-989 Łódź",
     "Rozwój systemu kadrowego", "23", None),
    ("MEBLOSTYL SP Z O O (SAMPLE)", "Meblostyl sp. z o.o. (SAMPLE)", None, "ul. Stolarska 970", "97-999 Tomaszów",
     "Usługi programistyczne: konfigurator mebli", "23", None),
]
PARTIES = {key: {"name": name, "nip": fixed or nip(1000 + 37 * i), "addr": (street, city), "country": "PL",
                 "line": line, "rate": rate, "prefix": prefix}
           for i, (key, name, fixed, street, city, line, rate, prefix) in enumerate(_PARTIES)}
# EU client: services to an EU business, VAT settled by the buyer (np II, art. 100(1)(4), reverse charge).
PARTIES["NORDWIND LOGISTIK GMBH (SAMPLE)"] = {
    "name": "Nordwind Logistik GmbH (SAMPLE)", "vat_eu": ("DE", "000000000"), "country": "DE",
    "addr": ("Hafenstraße 999", "20999 Hamburg"), "line": "Software development services", "rate": "np II"}

# Invoices with no bank line.
EXTRA = [
    # October sales still open on 21 Nov (story items si_meblostyl and si_nordwind).
    {"direction": "sale", "pay": "transfer", "party": "MEBLOSTYL SP Z O O (SAMPLE)", "number": "2026/10/042",
     "issue": date(2026, 10, 31), "due": date(2026, 11, 27), "gross": Decimal("36900.00")},
    {"direction": "sale", "pay": "transfer", "party": "NORDWIND LOGISTIK GMBH (SAMPLE)", "number": "2026/10/044",
     "issue": date(2026, 10, 15), "due": date(2026, 11, 14), "gross": Decimal("18400.00"), "currency": "EUR"},
] + [
    # M8: document without bank line, not from an employee (paid in cash from the office float).
    {"direction": "purchase", "pay": "cash", "party": "DRUKARNIA PIKSEL (SAMPLE)", "issue": day, "paid": day,
     "gross": Decimal(gross), "line": line, "messiness": ["M8"]}
    for day, gross, line in [
        (date(2026, 2, 11), "184.50", "Wizytówki 500 szt."), (date(2026, 3, 18), "615.00", "Roll-up reklamowy"),
        (date(2026, 5, 6), "246.00", "Ulotki A5 1000 szt."), (date(2026, 6, 24), "369.00", "Naklejki z logo"),
        (date(2026, 8, 12), "159.90", "Wizytówki 250 szt."), (date(2026, 9, 9), "492.00", "Plakaty konferencyjne"),
    ]
]


def money(x):
    return Decimal(x).quantize(CENT, ROUND_HALF_UP)


def collect():
    docs = []
    for d in build().docs + EXTRA:
        if not FIRST <= d["issue"] <= LAST:
            continue  # November documents come as PDFs and photos (next step)
        d = dict(d)
        bank = d.get("bank")
        if bank:
            d["gross"] = abs(bank["amount"])
            d.setdefault("currency", bank["currency"])
            if bank["account"] == "acc_owner":
                d.setdefault("messiness", ["M3"])
        d.setdefault("currency", "PLN")
        docs.append(d)
    docs.sort(key=lambda d: (d["issue"], d["direction"], d["party"], d.get("number") or "",
                             (d.get("bank") or {}).get("booking_date") or d["issue"]))

    counters = defaultdict(int)
    per_day = defaultdict(int)
    for d in docs:
        party = PARTIES[d["party"]]
        if not d.get("number"):  # retail invoices: per-seller counter
            counters[d["party"]] += 1
            d["number"] = f"FV/{party['prefix']}/{counters[d['party']]:05d}/{d['issue']:%m/%Y}"
        per_day[d["issue"]] += 1
        d["id"] = f"fa3_{d['issue']:%Y%m%d}_{per_day[d['issue']]:02d}"
        rate = party["rate"]
        d["rate"] = rate
        if rate.startswith("np"):
            d["net"], d["vat"] = d["gross"], Decimal("0.00")
        else:
            d["net"] = money(d["gross"] / (1 + Decimal(rate) / 100))
            d["vat"] = d["gross"] - d["net"]
        d["line"] = d.get("line") or party["line"]
    return docs


def party_xml(p, seller):
    if seller:
        ident = f"<NIP>{p['nip']}</NIP><Nazwa>{escape(p['name'])}</Nazwa>"
    elif "vat_eu" in p:
        ident = f"<KodUE>{p['vat_eu'][0]}</KodUE><NrVatUE>{p['vat_eu'][1]}</NrVatUE><Nazwa>{escape(p['name'])}</Nazwa>"
    else:
        ident = f"<NIP>{p['nip']}</NIP><Nazwa>{escape(p['name'])}</Nazwa>"
    addr = (f"<Adres><KodKraju>{p['country']}</KodKraju><AdresL1>{escape(p['addr'][0])}</AdresL1>"
            f"<AdresL2>{escape(p['addr'][1])}</AdresL2></Adres>")
    tag = "Podmiot1" if seller else "Podmiot2"
    tail = "" if seller else "    <JST>2</JST><GV>2</GV>\n"
    return f"  <{tag}>\n    <DaneIdentyfikacyjne>{ident}</DaneIdentyfikacyjne>\n    {addr}\n{tail}  </{tag}>\n"


RATE_FIELDS = {"23": ("P_13_1", "P_14_1"), "8": ("P_13_2", "P_14_2"), "5": ("P_13_3", "P_14_3"),
               "np I": ("P_13_8", None), "np II": ("P_13_9", None)}


def to_xml(d):
    party = PARTIES[d["party"]]
    seller, buyer = (party, BORSUK) if d["direction"] == "purchase" else (BORSUK, party)
    net_f, vat_f = RATE_FIELDS[d["rate"]]
    sums = f"<{net_f}>{d['net']}</{net_f}>" + (f"<{vat_f}>{d['vat']}</{vat_f}>" if vat_f else "")
    reverse_charge = "1" if d["rate"] == "np II" else "2"
    if d["pay"] in ("card", "cash"):
        form = "2" if d["pay"] == "card" else "1"
        pay = f"<Zaplacono>1</Zaplacono><DataZaplaty>{d['paid']}</DataZaplaty><FormaPlatnosci>{form}</FormaPlatnosci>"
    else:
        if d["direction"] == "sale":
            account = ACCOUNTS["acc_eur" if d["currency"] == "EUR" else "acc_pln"]["iban"]
        else:
            account = d["party_account"]
        pay = (f"<TerminPlatnosci><Termin>{d['due']}</Termin></TerminPlatnosci><FormaPlatnosci>6</FormaPlatnosci>"
               f"<RachunekBankowy><NrRB>{account}</NrRB></RachunekBankowy>")
    unit = "usł." if d["direction"] == "sale" or d["pay"] == "transfer" else "szt."
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<Faktura xmlns="{NS}">\n'
        '  <Naglowek>\n'
        '    <KodFormularza kodSystemowy="FA (3)" wersjaSchemy="1-0E">FA</KodFormularza>\n'
        '    <WariantFormularza>3</WariantFormularza>\n'
        f'    <DataWytworzeniaFa>{d["issue"]}T09:00:00Z</DataWytworzeniaFa>\n'
        '    <SystemInfo>Ordo demo scenario (SAMPLE)</SystemInfo>\n'
        '  </Naglowek>\n'
        + party_xml(seller, True) + party_xml(buyer, False) +
        '  <Fa>\n'
        f'    <KodWaluty>{d["currency"]}</KodWaluty>\n'
        f'    <P_1>{d["issue"]}</P_1>\n'
        f'    <P_2>{escape(d["number"])}</P_2>\n'
        f'    <P_6>{d["issue"]}</P_6>\n'
        f'    {sums}\n'
        f'    <P_15>{d["gross"]}</P_15>\n'
        f'    <Adnotacje><P_16>2</P_16><P_17>2</P_17><P_18>{reverse_charge}</P_18><P_18A>2</P_18A>'
        '<Zwolnienie><P_19N>1</P_19N></Zwolnienie><NoweSrodkiTransportu><P_22N>1</P_22N></NoweSrodkiTransportu>'
        '<P_23>2</P_23><PMarzy><P_PMarzyN>1</P_PMarzyN></PMarzy></Adnotacje>\n'
        '    <RodzajFaktury>VAT</RodzajFaktury>\n'
        '    <FaWiersz>\n'
        f'      <NrWierszaFa>1</NrWierszaFa><P_7>{escape(d["line"])}</P_7><P_8A>{unit}</P_8A><P_8B>1</P_8B>'
        f'<P_9A>{d["net"]}</P_9A><P_11>{d["net"]}</P_11><P_12>{d["rate"]}</P_12>\n'
        '    </FaWiersz>\n'
        f'    <Platnosc>{pay}</Platnosc>\n'
        '  </Fa>\n'
        '</Faktura>\n'
    )


def index_entry(d, path):
    party = PARTIES[d["party"]]
    bank = d.get("bank")
    return {
        "id": d["id"], "file": str(path.relative_to(OUT)), "number": d["number"], "direction": d["direction"],
        "issue_date": d["issue"].isoformat(), "due_date": d["due"].isoformat() if d.get("due") else None,
        "counterparty": party["name"], "counterparty_tax_id": party.get("nip") or "".join(party["vat_eu"]),
        "description": d["line"], "vat_rate": d["rate"],
        "net": {"amount": f"{d['net']}", "currency": d["currency"]},
        "vat": {"amount": f"{d['vat']}", "currency": d["currency"]},
        "gross": {"amount": f"{d['gross']}", "currency": d["currency"]},
        "payment": d["pay"],
        "bank_line": None if not bank else {
            "account": bank["account"], "booking_date": bank["booking_date"].isoformat(),
            "reference": bank["reference"], "amount": {"amount": f"{bank['amount']}", "currency": bank["currency"]}},
        "messiness": d.get("messiness", []),
    }


def main():
    docs = collect()
    target = OUT / "fa3"
    if target.exists():
        shutil.rmtree(target)
    index = []
    for d in docs:
        path = target / f"{d['issue']:%Y-%m}" / f"{d['id']}.xml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(to_xml(d), encoding="utf-8")
        index.append(index_entry(d, path))
    (OUT / "fa3_index.json").write_text(json.dumps(index, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    by_dir = defaultdict(int)
    for e in index:
        by_dir[e["direction"]] += 1
    print(f"out/fa3: {len(index)} invoices ({by_dir['purchase']} purchases, {by_dir['sale']} sales), "
          f"{sum(1 for e in index if e['bank_line'] is None)} without bank line")

    if "--xsd" in sys.argv:
        xsd = Path(sys.argv[sys.argv.index("--xsd") + 1]) / "schemat.xsd"
        files = sorted(str(p) for p in target.rglob("*.xml"))
        result = subprocess.run(["xmllint", "--noout", "--schema", str(xsd), *files], capture_output=True, text=True)
        bad = [line for line in result.stderr.splitlines() if not line.endswith(" validates")]
        if bad:
            raise SystemExit("FA(3) validation FAILED:\n" + "\n".join(bad[:20]))
        print(f"FA(3) schema: {len(files)} files validate")


if __name__ == "__main__":
    main()
