"""What the owner's screens need beyond the contract entities: settings, people, learned rules, costs per person,
clients, subscriptions, chat history and the balance over time.

Plain arithmetic on the company's own data (bank lines, documents, matches, counterparties): no model, money as
Decimal and decimal strings (hard rules 4 and 6). Read by backend/api/routes/owner.py; the receivables agent
(backend/agents/receivables.py) reuses `clients`.
"""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

import psycopg

from backend.api.money import amount_of, money
from backend.db.store import Store
from backend.finance.engine import SETTLED, rates_for
from backend.finance.series import name_key
from backend.finance.settings import DEFAULT_PAYMENT_DAYS

SUBSCRIPTION_CATEGORIES = {"software_subscriptions", "cloud_hosting"}
NOT_COSTS = {"reimbursements", "owner_private"}
# Spending that varies by nature: repeats only count as a monthly payment when a recurring series says so.
VARIABLE = {"travel", "meals_representation", "equipment", "other", "marketing_ads"}
DEFAULT_PAY_TYPE = {"owner": "board_fee", "employee": "salary", "contractor": "invoice"}
PART_LABEL = {"salaries": "salary", "contractors": "invoice", "social_security": "social security", "other": "not explained"}
CATEGORIES = {"revenue_services", "salaries", "contractors", "social_security", "taxes", "rent_office",
              "software_subscriptions", "cloud_hosting", "equipment", "travel", "marketing_ads", "professional_services",
              "bank_fees", "meals_representation", "reimbursements", "owner_private", "financing", "investment_outflow",
              "other"}


def _plain(name: str | None) -> str:
    """name_key without the "(SAMPLE)" marker of invented names."""
    return name_key(re.sub(r"\(SAMPLE\)", "", name or "", flags=re.I))


def _company(conn: psycopg.Connection, company_id: str) -> dict[str, Any]:
    row = conn.execute("select id, name, base_currency, country, as_of_date, tax_id from companies where id = %s",
                       (company_id,)).fetchone()
    id_, name, base, country, as_of, tax_id = row
    return {"id": id_, "name": name, "base_currency": base, "country": country, "as_of_date": str(as_of), "tax_id": tax_id}


def month_range(month: str) -> tuple[str, str]:
    year, mon = (int(x) for x in month.split("-"))
    nxt = date(year + mon // 12, mon % 12 + 1, 1)
    return f"{month}-01", (nxt - timedelta(days=1)).isoformat()


def _out(t: dict) -> Decimal:
    """Money that left, as a positive number (0 for money in)."""
    v = amount_of(t["amount_base"])
    return -v if v < 0 else Decimal(0)


def _in(t: dict) -> Decimal:
    v = amount_of(t["amount_base"])
    return v if v > 0 else Decimal(0)


# ---- Settings -------------------------------------------------------------------------------------------------

def settings(conn: psycopg.Connection, company_id: str) -> dict[str, Any]:
    c = _company(conn, company_id)
    row = conn.execute("select vat_period, accountant_email, safety_buffer, late_client_days, weekly_summary "
                       "from company_settings where company_id = %s", (company_id,)).fetchone()
    vat_period, accountant, buffer, late_days, weekly = row or ("monthly", None, None, 7, False)
    if buffer is None:  # no buffer set by the owner: the one the forecast uses
        forecast = Store(conn).list("forecast", company_id=company_id, limit=1)
        buffer = amount_of(forecast[0].get("safety_buffer")) if forecast and forecast[0].get("safety_buffer") else None
    return {
        "company": {"id": c["id"], "name": c["name"], "tax_id": c["tax_id"], "base_currency": c["base_currency"],
                    "vat_period": vat_period, "accountant_email": accountant},
        "alerts": {"safety_buffer": money(buffer, c["base_currency"]) if buffer is not None else None,
                   "late_client_days": late_days, "weekly_summary": weekly},
    }


def patch_settings(conn: psycopg.Connection, company_id: str, body: dict[str, Any]) -> dict[str, Any]:
    company = body.get("company") or {}
    alerts = body.get("alerts") or {}
    unknown = (set(company) - {"name", "tax_id", "vat_period", "accountant_email"}) | \
              (set(alerts) - {"safety_buffer", "late_client_days", "weekly_summary"})
    if unknown:
        raise ValueError(f"cannot change {sorted(unknown)}")
    if company.get("vat_period") not in (None, "monthly", "quarterly"):
        raise ValueError("vat_period is monthly or quarterly")
    if "late_client_days" in alerts and (not isinstance(alerts["late_client_days"], int) or alerts["late_client_days"] < 1):
        raise ValueError("late_client_days is a whole number of days, at least 1")
    for field in ("name", "tax_id"):
        if field in company:
            value = company[field]
            if field == "name" and not (value or "").strip():
                raise ValueError("the company needs a name")
            conn.execute(f"update companies set {field} = %s where id = %s",
                         ((value or "").strip() or None if field == "tax_id" else value.strip(), company_id))
    current = settings(conn, company_id)
    merged = {
        "vat_period": company.get("vat_period", current["company"]["vat_period"]),
        "accountant_email": company.get("accountant_email", current["company"]["accountant_email"]) or None,
        "safety_buffer": amount_of(alerts["safety_buffer"]) if alerts.get("safety_buffer") else
                         (amount_of(current["alerts"]["safety_buffer"]) if current["alerts"]["safety_buffer"] else None),
        "late_client_days": alerts.get("late_client_days", current["alerts"]["late_client_days"]),
        "weekly_summary": bool(alerts.get("weekly_summary", current["alerts"]["weekly_summary"])),
    }
    conn.execute(
        """insert into company_settings (company_id, vat_period, accountant_email, safety_buffer, late_client_days, weekly_summary)
           values (%(c)s, %(vat_period)s, %(accountant_email)s, %(safety_buffer)s, %(late_client_days)s, %(weekly_summary)s)
           on conflict (company_id) do update set vat_period = excluded.vat_period, accountant_email = excluded.accountant_email,
             safety_buffer = excluded.safety_buffer, late_client_days = excluded.late_client_days,
             weekly_summary = excluded.weekly_summary""",
        {"c": company_id, **merged},
    )
    conn.commit()
    return settings(conn, company_id)


# ---- People ---------------------------------------------------------------------------------------------------

PERSON_COLUMNS = "id, name, email, role, pay_type, card_last4, statement_names, tax_id, iban"


def _person(row: tuple) -> dict[str, Any]:
    id_, name, email, role, pay_type, cards, statements, tax_id, iban = row
    return {"id": id_, "name": name, "email": email, "role": role, "pay_type": pay_type or DEFAULT_PAY_TYPE.get(role),
            "card_last4": list(cards or []), "statement_names": list(statements or []), "tax_id": tax_id, "iban": iban}


def people(conn: psycopg.Connection, company_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(f"select {PERSON_COLUMNS} from people where company_id = %s "
                        "order by case role when 'owner' then 0 when 'employee' then 1 else 2 end, name", (company_id,))
    return [_person(r) for r in rows.fetchall()]


def add_person(conn: psycopg.Connection, company_id: str, body: dict[str, Any]) -> dict[str, Any]:
    name, email, role = (body.get("name") or "").strip(), (body.get("email") or "").strip().lower(), body.get("role")
    if not name or not email or role not in ("owner", "employee", "contractor"):
        raise ValueError("a person needs a name, an e-mail and a role (owner, employee or contractor)")
    if conn.execute("select 1 from people where lower(email) = %s", (email,)).fetchone():
        raise ValueError(f"someone with the e-mail {email} is already listed")
    base = "per_" + (re.sub(r"[^a-z0-9]+", "_", _plain(name)).strip("_") or "person")
    pid, n = base, 1
    while conn.execute("select 1 from people where id = %s", (pid,)).fetchone():
        n += 1
        pid = f"{base}_{n}"
    cards = [c.strip()[-4:] for c in body.get("card_last4") or [] if c and c.strip()]
    statements = [s.strip().upper() for s in body.get("statement_names") or [] if s and s.strip()]
    conn.execute(f"insert into people ({PERSON_COLUMNS}, company_id) values (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                 (pid, name, email, role, body.get("pay_type") or DEFAULT_PAY_TYPE[role], cards, statements,
                  body.get("tax_id"), body.get("iban"), company_id))
    conn.commit()
    return next(p for p in people(conn, company_id) if p["id"] == pid)


def person_of(t: dict, team: list[dict], counterparties: dict[str, dict]) -> dict | None:
    """The person a bank line pays: the counterparty is linked to them, or the line names them."""
    cp = counterparties.get(t.get("counterparty_id") or "") or {}
    if cp.get("person_id"):
        hit = next((p for p in team if p["id"] == cp["person_id"]), None)
        if hit:
            return hit
    text = f" {_plain(cp.get('name'))} {_plain(t.get('counterparty_name_raw'))} "
    for p in team:
        keys = [_plain(p["name"])] + [_plain(s) for s in p["statement_names"]]
        if any(k and f" {k} " in text for k in keys):
            return p
    return None


# ---- Learned rules --------------------------------------------------------------------------------------------

def rules(conn: psycopg.Connection, company_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """select r.id, r.raw, r.counterparty_id, coalesce(c.doc->>'name', r.raw), r.category, r.learned_at
           from category_rules r left join counterparties c on c.id = r.counterparty_id
           where r.company_id = %s order by r.learned_at desc""", (company_id,)).fetchall()
    return [{"id": i, "raw": raw, "counterparty_id": cp, "counterparty_name": name, "category": cat,
             "learned_at": at.strftime("%Y-%m-%dT%H:%M:%SZ")} for i, raw, cp, name, cat, at in rows]


def learn_rule(conn: psycopg.Connection, company_id: str, raw: str | None, counterparty_id: str | None, category: str) -> None:
    """The owner changed a type: remember it for this spelling and make it the counterparty's default category,
    which the pipeline uses first for the next line (categorise(): "history")."""
    raw = (raw or "").strip()
    if not raw or category not in CATEGORIES:
        return
    rule_id = "rule_" + re.sub(r"[^a-z0-9]+", "_", name_key(raw)).strip("_")[:40]
    conn.execute(
        """insert into category_rules (id, company_id, raw, counterparty_id, category) values (%s, %s, %s, %s, %s)
           on conflict (company_id, raw) do update set category = excluded.category,
             counterparty_id = excluded.counterparty_id, learned_at = now()""",
        (rule_id, company_id, raw.upper(), counterparty_id, category))
    s = Store(conn)
    cp = s.get("counterparty", counterparty_id) if counterparty_id else None
    if cp and cp.get("default_category") != category:
        s.put("counterparty", {**cp, "default_category": category}, company_id=company_id)
    conn.commit()


def delete_rule(conn: psycopg.Connection, company_id: str, rule_id: str) -> bool:
    row = conn.execute("delete from category_rules where id = %s and company_id = %s returning counterparty_id, category",
                       (rule_id, company_id)).fetchone()
    if not row:
        return False
    counterparty_id, category = row
    s = Store(conn)
    cp = s.get("counterparty", counterparty_id) if counterparty_id else None
    if cp and cp.get("default_category") == category:  # forget it: the next line is sorted from scratch
        s.put("counterparty", {**cp, "default_category": None}, company_id=company_id)
    conn.commit()
    return True


def set_transaction_category(conn: psycopg.Connection, company_id: str, transaction_id: str, category: str) -> dict:
    if category not in CATEGORIES:
        raise ValueError(f"unknown category {category!r}")
    s = Store(conn)
    t = s.get("transaction", transaction_id)
    if t is None or s.company_of("transaction", transaction_id) != company_id:
        raise LookupError(transaction_id)
    t = {**t, "category": category}
    s.put("transaction", t, company_id=company_id)
    learn_rule(conn, company_id, t.get("counterparty_name_raw"), t.get("counterparty_id"), category)
    return t


# ---- Costs per person -----------------------------------------------------------------------------------------

def people_costs(conn: psycopg.Connection, company_id: str, month: str) -> dict[str, Any]:
    s = Store(conn)
    base = _company(conn, company_id)["base_currency"]
    start, end = month_range(month)
    team = people(conn, company_id)
    counterparties = {c["id"]: c for c in s.list("counterparty", company_id=company_id)}
    lines = [t for t in s.list("transaction", company_id=company_id) if start <= t["booking_date"] <= end]

    paid: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    count: dict[str, int] = defaultdict(int)
    for t in lines:
        if _out(t) == 0 or t.get("category") in NOT_COSTS or t.get("category") == "social_security":
            continue
        p = person_of(t, team, counterparties)
        if p:
            paid[p["id"]][t.get("category") or "other"] += _out(t)
            count[p["id"]] += 1

    # What the company owes people for things they paid themselves: receipts not paid back yet.
    paid_back = {r.get("subject", {}).get("id") for r in s.list("recommendation", company_id=company_id, type="reimburse_employee")
                 if r["status"] in ("approved", "executed_simulated")}
    owed: dict[str, Decimal] = defaultdict(Decimal)
    receipts: dict[str, int] = defaultdict(int)
    for m in s.list("match", company_id=company_id):
        due = m.get("consequences", {}).get("reimbursement_owed")
        if m["status"] == "rejected" or not due or m["document_id"] in paid_back:
            continue
        payer = m.get("consequences", {}).get("reimbursement_to") or m.get("payer") or {}
        p = next((x for x in team if x["id"] == payer.get("person_id") or (payer.get("email") or "").lower() == x["email"].lower()), None)
        if p:
            owed[p["id"]] += amount_of(due)
            receipts[p["id"]] += 1

    social = sum((_out(t) for t in lines if t.get("category") == "social_security"), Decimal(0))
    costs = sum((_out(t) for t in lines if t.get("category") not in NOT_COSTS), Decimal(0))
    items = []
    for p in team:
        if not paid.get(p["id"]) and not owed.get(p["id"]):
            continue
        total = sum(paid[p["id"]].values(), Decimal(0))
        parts = [{"label": PART_LABEL.get(cat, cat.replace("_", " ")), "amount": money(v, base)} for cat, v in paid[p["id"]].items()]
        items.append({"person_id": p["id"], "name": p["name"], "role": p["role"], "pay_type": p["pay_type"],
                      "paid": money(total, base), "payments": count[p["id"]], "owed": money(owed[p["id"]], base),
                      "receipts_owed": receipts[p["id"]], **({"parts": parts} if len(parts) > 1 else {})})
    staff = sum((amount_of(i["paid"]) for i in items), Decimal(0)) + social
    return {"items": items, "totals": {"staff": money(staff, base), "social_security": money(social, base),
                                       "share_of_costs": round(float(staff / costs), 2) if costs else 0.0}}


# ---- Clients --------------------------------------------------------------------------------------------------

def clients(conn: psycopg.Connection, company_id: str, month: str, *, persist_delays: bool = True) -> dict[str, Any]:
    s = Store(conn)
    company = _company(conn, company_id)
    base, as_of = company["base_currency"], company["as_of_date"]
    start, end = month_range(month)
    counterparties = {c["id"]: c for c in s.list("counterparty", company_id=company_id)}
    # One client can be several counterparties ("Piekarnia Złoty Kłos sp. z o.o." on the invoice, "PIEKARNIA ZLOTY
    # KLOS SP Z O O" on the bank line): clients are grouped by the folded name. The company itself is no client.
    own = _plain(company["name"])
    ids_by_key: dict[str, list[str]] = defaultdict(list)
    for c in sorted(counterparties.values(), key=lambda c: (c.get("kind") != "customer", c["id"])):
        ids_by_key[_plain(c["name"])].append(c["id"])
    documents = [d for d in s.list("document", company_id=company_id, direction="sale") if d.get("status") not in ("duplicate", "rejected")]
    # An invoice with a bank line matched to it is paid: the money is on the account, even while the owner has not
    # checked the match yet (status "suggested"). Only a rejected match leaves it open.
    settled = {m["document_id"]: m for m in s.list("match", company_id=company_id)
               if m.get("status") in SETTLED | {"suggested"} and m.get("transaction_id")}
    lines = s.list("transaction", company_id=company_id)

    def key_of(party: dict) -> str:
        cp = counterparties.get(party.get("counterparty_id") or "")
        return _plain(cp["name"] if cp else party.get("name"))

    names: dict[str, str] = {}
    delays: dict[str, list[int]] = defaultdict(list)
    open_docs: dict[str, list[dict]] = defaultdict(list)
    currencies = {d["totals"]["gross"]["currency"] for d in documents}
    rates = rates_for(base, currencies, date.fromisoformat(as_of), conn)
    for d in documents:
        k = key_of(d.get("buyer") or {})
        names.setdefault(k, (d.get("buyer") or {}).get("name") or k)
        issued = d.get("issue_date") or d.get("sale_date")
        due = d.get("due_date") or (issued and (date.fromisoformat(issued) + timedelta(days=DEFAULT_PAYMENT_DAYS)).isoformat())
        m = settled.get(d["id"])
        if m:
            t = s.get("transaction", m["transaction_id"])
            if t and due and t["booking_date"] <= as_of:
                delays[k].append(max((date.fromisoformat(t["booking_date"]) - date.fromisoformat(due)).days, 0))
            continue
        if not issued or issued > as_of:
            continue
        gross = d["totals"]["gross"]
        gross_base = d["totals"].get("gross_base") or (money(amount_of(gross) * rates[gross["currency"]], base) if gross["currency"] in rates else None)
        if gross_base is None:
            continue
        open_docs[k].append({"document_id": d["id"], "number": d.get("number"), "gross": gross, "gross_base": gross_base,
                             "due_date": due, "days_late": max((date.fromisoformat(as_of) - date.fromisoformat(due)).days, 0) if due else 0})

    paid: dict[str, Decimal] = defaultdict(Decimal)
    for t in lines:
        if not (start <= t["booking_date"] <= end) or _in(t) == 0:
            continue
        cp = counterparties.get(t.get("counterparty_id") or "") or {}
        if t.get("category") != "revenue_services" and cp.get("kind") != "customer":
            continue
        k = _plain(cp.get("name") or t.get("counterparty_name_raw"))
        if not k or k == own:
            continue  # money moved between the company's own accounts
        names.setdefault(k, cp.get("name") or t.get("counterparty_name_raw") or k)
        paid[k] += _in(t)

    income = sum(paid.values(), Decimal(0))
    items = []
    for k in sorted((set(paid) | set(open_docs)) - {own, ""}):
        cp = (counterparties.get(ids_by_key[k][0]) if ids_by_key.get(k) else None) or {}
        typical = round(sum(delays[k]) / len(delays[k])) if delays.get(k) else cp.get("typical_payment_delay_days")
        if persist_delays and cp and delays.get(k) and cp.get("typical_payment_delay_days") != typical:
            s.put("counterparty", {**cp, "typical_payment_delay_days": typical}, company_id=company_id)
        invoices = sorted(open_docs.get(k, []), key=lambda i: i["due_date"] or "")
        currency = invoices[0]["gross"]["currency"] if invoices else base
        items.append({"counterparty_id": cp.get("id") or f"name:{k}", "name": names.get(k, k), "currency": currency, "paid_in_month": money(paid[k], base),
                      "open_invoices": invoices, "open_total_base": money(sum((amount_of(i["gross_base"]) for i in invoices), Decimal(0)), base),
                      "typical_payment_delay_days": typical,
                      "share_of_income": round(float(paid[k] / income), 2) if income else 0.0})
    items.sort(key=lambda c: (-amount_of(c["open_total_base"]) - amount_of(c["paid_in_month"])))
    open_total = sum((amount_of(c["open_total_base"]) for c in items), Decimal(0))
    late = sum((amount_of(i["gross_base"]) for c in items for i in c["open_invoices"] if i["days_late"] > 0), Decimal(0))
    return {"items": items, "totals": {"paid_in_month": money(income, base), "open_base": money(open_total, base), "late_base": money(late, base)}}


# ---- Subscriptions --------------------------------------------------------------------------------------------

def _payer(t: dict, accounts: dict[str, dict]) -> dict[str, str]:
    acc = accounts.get(t.get("account_id") or "") or {}
    if acc.get("kind") == "owner_private":
        return {"kind": "person", "label": "Owner's private card"}
    if t.get("card_last4"):
        return {"kind": "card", "label": f"Company card ending {t['card_last4']}"}
    return {"kind": "account", "label": acc.get("name") or "Company account"}


def _months_back(month: str, n: int) -> list[str]:
    """The `n` months up to and including `month`, oldest first."""
    year, mon = (int(x) for x in month.split("-"))
    out = []
    for _ in range(n):
        out.append(f"{year}-{mon:02d}")
        year, mon = (year - 1, 12) if mon == 1 else (year, mon - 1)
    return out[::-1]


def subscriptions(conn: psycopg.Connection, company_id: str, month: str | None = None, scope: str = "subscriptions") -> dict[str, Any]:
    """What the company pays every month, seen from `month` (default: the as-of month).

    scope "subscriptions": tools and services (subscription categories); scope "all": every payment that repeats,
    rent, salaries, contractors and taxes included. A payment repeats when it went to the same name in at least two
    of the three months up to `month` (or belongs to a recurring series). Receipts people paid with their own cards
    count too. `monthly` is what was paid in `month`, or the last month's amount when it is not paid yet
    (`paid_in_month` false)."""
    s = Store(conn)
    company = _company(conn, company_id)
    base = company["base_currency"]
    month = month or company["as_of_date"][:7]
    window = _months_back(month, 3)
    accounts = {a["id"]: a for a in s.list("account", company_id=company_id)}
    counterparties = {c["id"]: c for c in s.list("counterparty", company_id=company_id)}
    team = people(conn, company_id)
    wanted = (lambda cat: cat in SUBSCRIPTION_CATEGORIES) if scope != "all" else (lambda cat: cat not in NOT_COSTS)
    payments: dict[str, list[dict]] = defaultdict(list)
    names: dict[str, str] = {}
    category: dict[str, str] = {}
    for t in s.list("transaction", company_id=company_id):
        if t["booking_date"][:7] not in window or _out(t) == 0:
            continue
        cp = counterparties.get(t.get("counterparty_id") or "") or {}
        cat = t.get("category") or cp.get("default_category") or "other"
        if cat == "other":
            person = person_of(t, team, counterparties)
            cat = ("contractors" if person["role"] == "contractor" else "salaries") if person else cat
        if not wanted(cat):
            continue
        name = cp.get("name") or t.get("counterparty_name_raw") or t["description"]
        k = _plain(name)
        names.setdefault(k, name)
        category.setdefault(k, cat)
        orig = t.get("original_amount") or (t["amount"] if t["amount"]["currency"] != base else None)
        payments[k].append({"month": t["booking_date"][:7], "amount": _out(t), "payer": _payer(t, accounts),
                            "original": {"amount": f"{abs(amount_of(orig)):.2f}", "currency": orig["currency"]} if orig else None,
                            "series": t.get("recurring_series_id"), "recurring": bool(cp.get("is_recurring"))})
    docs = {d["id"]: d for d in s.list("document", company_id=company_id)}
    for m in s.list("match", company_id=company_id):
        d = docs.get(m["document_id"])
        if not d or m["status"] == "rejected" or m.get("paid_by") not in ("employee_private", "owner_private"):
            continue
        cat = (d.get("category_suggestion") or {}).get("category")
        if not cat or not wanted(cat) or (d.get("issue_date") or "")[:7] not in window:
            continue
        k = _plain(d["seller"]["name"])
        names.setdefault(k, d["seller"]["name"])
        category.setdefault(k, cat)
        first = re.sub(r"\(SAMPLE\)", "", (m.get("payer") or {}).get("name") or "").split()
        label = "Owner's private card" if m["paid_by"] == "owner_private" else f"{first[0]}'s card" if first else "An employee's card"
        gross = d["totals"].get("gross_base") or d["totals"]["gross"]
        payments[k].append({"month": (d.get("issue_date") or "")[:7], "amount": amount_of(gross), "payer": {"kind": "person", "label": label},
                            "original": d["totals"]["gross"] if d["totals"].get("gross_base") else None, "series": None, "recurring": False,
                            "private": True})

    items, total = [], Decimal(0)
    for k, ps in payments.items():
        months = sorted({p["month"] for p in ps if p["month"]})
        scheduled = any(p["series"] or p["recurring"] for p in ps)
        if len(months) < 2 and not scheduled:
            continue
        if category[k] in VARIABLE and not scheduled:
            continue  # a restaurant or a shop seen twice is not a monthly payment
        paid_now = month in months
        latest_month = month if paid_now else months[-1]
        latest = [p for p in ps if p["month"] == latest_month]
        earlier = [m_ for m_ in months if m_ < latest_month]
        previous = [p for p in ps if earlier and p["month"] == earlier[-1]]
        monthly = sum((p["amount"] for p in latest), Decimal(0))
        before = sum((p["amount"] for p in previous), Decimal(0)) if previous else None
        payers = list({p["payer"]["label"]: p["payer"] for p in latest}.values())
        flags = []
        if before and monthly > before * Decimal("1.01") and len(payers) == 1 and category[k] not in VARIABLE:
            flags.append("price_up")
        if len(payers) > 1 and category[k] in SUBSCRIPTION_CATEGORIES:
            flags.append("paid_twice")
        if any(p.get("private") or p["payer"]["label"] == "Owner's private card" for p in latest):
            flags.append("paid_privately")
        item = {"counterparty_id": next((cid for cid, c in counterparties.items() if _plain(c["name"]) == k), k),
                "name": names[k], "category": category[k], "monthly": money(monthly, base), "paid_in_month": paid_now,
                "original": latest[0]["original"] if len(latest) == 1 else None,
                "paid_by": payers, "flags": flags, "series_ids": sorted({p["series"] for p in ps if p["series"]})}
        if before is not None:
            item["previous_monthly"] = money(before, base)
        if "paid_twice" in flags:
            item["duplicate_cost"] = money(min(p["amount"] for p in latest), base)
        items.append(item)
        total += monthly
    items.sort(key=lambda i: -amount_of(i["monthly"]))
    return {"items": items, "monthly_total": money(total, base)}


# ---- Chat history ---------------------------------------------------------------------------------------------

def chat_sessions(conn: psycopg.Connection, company_id: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """select session_id, max(at), count(*),
                  (select content from chat_messages f where f.session_id = m.session_id and f.role = 'user' order by seq limit 1)
           from chat_messages m where company_id = %s group by session_id order by max(at) desc""", (company_id,)).fetchall()
    out = []
    for sid, last, n, first in rows:
        title = (first or "Chat").strip().replace("\n", " ")
        out.append({"session_id": sid, "title": title if len(title) <= 60 else title[:59] + "…",
                    "last_at": last.strftime("%Y-%m-%dT%H:%M:%SZ"), "messages": n})
    return out


def chat_session(conn: psycopg.Connection, company_id: str, session_id: str) -> dict[str, Any] | None:
    rows = conn.execute("select role, content, at from chat_messages where company_id = %s and session_id = %s order by seq",
                        (company_id, session_id)).fetchall()
    if not rows:
        return None
    return {"session_id": session_id, "messages": [{"role": r, "content": c, "at": a.strftime("%Y-%m-%dT%H:%M:%SZ")} for r, c, a in rows]}


# ---- Balance over time and a summary from the bank ----------------------------------------------------------

def balance_history(conn: psycopg.Connection, company_id: str, days: int = 91) -> dict[str, Any] | None:
    """Cash in the company's accounts at the end of each day before the as-of date, worked back from each account's
    reported balance over its bank lines. Foreign accounts at the as-of day's rate. Only days that change are listed."""
    s = Store(conn)
    company = _company(conn, company_id)
    base, as_of = company["base_currency"], date.fromisoformat(company["as_of_date"])
    accounts = [a for a in s.list("account", company_id=company_id) if a.get("include_in_liquidity") and a.get("balance")]
    if not accounts:
        return None
    rates = rates_for(base, {a["currency"] for a in accounts}, as_of, conn)
    lines = s.list("transaction", company_id=company_id)
    start = as_of - timedelta(days=days)
    totals: dict[date, Decimal] = defaultdict(Decimal)
    for acc in accounts:
        if acc["currency"] not in rates:
            continue
        reported_on = (acc.get("balance_at") or company["as_of_date"])[:10]
        booked: dict[str, Decimal] = defaultdict(Decimal)  # what each day added to this account, up to the report
        for t in lines:
            if t["account_id"] == acc["id"] and t["booking_date"] <= reported_on:
                booked[t["booking_date"]] += amount_of(t["amount"])
        # Walk back from the report: the balance at the end of a day is the reported balance minus what came later.
        later = sum((v for d, v in booked.items() if d > (start + timedelta(days=days - 1)).isoformat()), Decimal(0))
        for n in range(days - 1, -1, -1):
            day = start + timedelta(days=n)
            totals[day] += (amount_of(acc["balance"]) - later) * rates[acc["currency"]]
            later += booked.get(day.isoformat(), Decimal(0))
    points, last = [], None
    for day in sorted(totals):
        value = money(totals[day], base)["amount"]
        if value != last:
            points.append({"date": day.isoformat(), "balance": value})
            last = value
    return {"currency": base, "points": points}


def bank_summary(conn: psycopg.Connection, company_id: str, from_: str | None, to: str | None) -> list[dict[str, Any]]:
    """Bank lines summed per category, for months whose payments are not in the books yet."""
    base = _company(conn, company_id)["base_currency"]
    s = Store(conn)
    team = people(conn, company_id)
    counterparties = {c["id"]: c for c in s.list("counterparty", company_id=company_id)}
    sums: dict[str, Decimal] = defaultdict(Decimal)
    counts: dict[str, int] = defaultdict(int)
    for t in s.list("transaction", company_id=company_id):
        if (from_ and t["booking_date"] < from_) or (to and t["booking_date"] > to):
            continue
        key = t.get("category") or "other"
        if key == "other" and _out(t) > 0:
            # A payment to someone on the people list is staff, as on the costs-per-person screen.
            person = person_of(t, team, counterparties)
            if person:
                key = "contractors" if person["role"] == "contractor" else "salaries"
        sums[key] += amount_of(t["amount_base"])
        counts[key] += 1
    return [{"key": k, "amount_base": money(v, base), "change_pct": None, "entries": counts[k]} for k, v in sorted(sums.items(), key=lambda kv: kv[1])]
