"""Counterparty resolution with alias learning, and categories (ticket #41, spec #3).

Resolution order for a bank line or a document:
  1. exact tax id   2. exact IBAN   3. alias table (normalised raw name)
  4. name similarity > 0.8: a *suggestion* only. The line stays `counterparty_unresolved` until the owner confirms
     a Match between it and a document; that confirmation stores the raw spelling as an alias (`learn_from_match`),
     so the next line with that spelling resolves at step 3 on its own.
  5. otherwise a new Counterparty; its kind comes from rules, then the model if one is configured.

Category order (D-09): counterparty's default category (history) -> keyword rules -> model constrained to the
Category enum -> "other". The model is optional (`choose` is None when ORDO_LLM_ENABLED=0 or in tests).
"""
import logging
import os
import re
from typing import Callable

from .match import name_similarity

log = logging.getLogger("ordo.pipeline.counterparty")

SUGGEST = 0.8
CATEGORIES = ["revenue_services", "salaries", "contractors", "social_security", "taxes", "rent_office",
              "software_subscriptions", "cloud_hosting", "equipment", "travel", "marketing_ads",
              "professional_services", "bank_fees", "meals_representation", "reimbursements", "owner_private",
              "financing", "investment_outflow", "other"]
KINDS = ["supplier", "customer", "employee", "owner", "tax_authority", "social_security", "bank",
         "payment_processor", "other"]

# first match wins; checked against "name + description", lower case
CATEGORY_RULES = [
    ("salaries", ("salary", "wynagrodzenie", "gehalt", "lohn ")),
    ("social_security", ("zus", "krankenkasse", "social security", "sozialversicherung")),
    ("taxes", ("tax office", "tax prepayment", "urząd skarbowy", "urzad skarbowy", "finanzamt", "stadtkasse",
               " vat ", "pit-", "cit-")),
    ("investment_outflow", ("silent partnership", "capital tranche")),
    ("financing", ("loan", "kredyt", "credit line", "leasing")),
    ("rent_office", ("rent payment", "czynsz", "miete", "coworking", "commercial space")),
    ("bank_fees", ("bank fee", "opłata za", "oplata za", "prowizja", "gebühr", "account fee")),
    ("cloud_hosting", ("hosting", "cloud", "serwer", "server", "vps", "chmura")),
    ("software_subscriptions", ("subscription", "abonament", "licencja", "license", "saas", "team plan")),
    ("travel", ("bilet", "koleje", "train", "flight", "hotel", "taxi", "uber", "pkp")),
    ("marketing_ads", ("google ads", "facebook ads", "meta ads", "reklama", "advertising")),
    ("professional_services", ("biuro rachunkowe", "accounting", "kancelaria", "legal", "consulting")),
    ("meals_representation", ("restauracja", "restaurant", "kawiarnia", "cafe", "catering")),
    ("equipment", ("monitor", "laptop", "drukark", "printer", "toner", "keyboard", "klawiatur")),
]
KIND_RULES = [
    ("tax_authority", ("tax office", "urząd skarbowy", "urzad skarbowy", "finanzamt", "stadtkasse")),
    ("social_security", ("zus", "krankenkasse", "sozialversicherung", "social health fund")),
    ("payment_processor", ("global pay", "card settlement", "paypal", "stripe", "sumup", "customers (debit)")),
    ("bank", ("bank fee", " bank ")),
]
DEFAULT_CATEGORY_BY_KIND = {"tax_authority": "taxes", "social_security": "social_security",
                            "payment_processor": "revenue_services", "employee": "salaries", "bank": "bank_fees"}


# ---------- normalising ----------

def normalise_alias(raw: str | None) -> str:
    """'PIXELBOARD.COM* SAN FRANCISCO 1452' -> 'PIXELBOARD COM SAN FRANCISCO' (reference numbers dropped)."""
    tokens = re.sub(r"[^0-9A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]+", " ", raw or "").upper().split()
    return " ".join(t for t in tokens if not any(ch.isdigit() for ch in t))


def _nip(tax_id) -> str:
    return re.sub(r"[^0-9A-Z]", "", (tax_id or "").upper()).removeprefix("PL")


def _iban(text) -> str:
    s = re.sub(r"[^0-9A-Za-z]", "", text or "").upper()
    return s[2:] if len(s) > 2 and s[:2].isalpha() else s


def _slug(name: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]+", "_", normalise_alias(name).lower())).strip("_")[:40] or "unknown"


# ---------- resolution ----------

def resolve(counterparties: list[dict], *, name: str | None, tax_id: str | None = None,
            iban: str | None = None) -> tuple[str, dict | None, float]:
    """(how, counterparty, similarity): how is 'tax_id' | 'iban' | 'alias' | 'suggested' | 'none'."""
    nip, account, alias = _nip(tax_id), _iban(iban), normalise_alias(name)
    if nip:
        hit = next((c for c in counterparties if _nip(c.get("tax_id")) == nip), None)
        if hit:
            return "tax_id", hit, 1.0
    if account:
        hit = next((c for c in counterparties if account in {_iban(i) for i in c.get("ibans") or []}), None)
        if hit:
            return "iban", hit, 1.0
    if alias:
        # learned aliases win over names: a confirmed spelling beats a counterparty auto-created from that spelling
        hit = next((c for c in counterparties if alias in {normalise_alias(a) for a in (c.get("aliases") or [])}),
                   None) or next((c for c in counterparties if normalise_alias(c["name"]) == alias), None)
        if hit:
            return "alias", hit, 1.0
        best, best_sim = None, 0.0
        for c in counterparties:
            sim = max([name_similarity(c["name"], name)] + [name_similarity(a, name) for a in c.get("aliases") or []])
            if sim > best_sim:
                best, best_sim = c, sim
        if best is not None and best_sim > SUGGEST:
            return "suggested", best, best_sim
    return "none", None, 0.0


def guess_kind(text: str, incoming: bool, choose: Callable | None = None) -> str:
    lowered = f" {text.lower()} "
    for kind, words in KIND_RULES:
        if any(w in lowered for w in words):
            return kind
    if choose:
        picked = choose(f"What kind of business partner is this? Bank or invoice text: {text}", KINDS)
        if picked in KINDS:
            return picked
    return "customer" if incoming else "supplier"


def new_counterparty(company_id: str, *, name: str, tax_id: str | None, country: str | None, iban: str | None,
                     kind: str, raw_alias: str | None, existing_ids: set[str]) -> dict:
    base = f"cp_{_slug(name)}"
    cp_id, n = base, 2
    while cp_id in existing_ids:
        cp_id, n = f"{base}_{n}", n + 1
    alias = normalise_alias(raw_alias)
    return {"id": cp_id, "company_id": company_id, "name": name, "aliases": [alias] if alias else [],
            "tax_id": tax_id or None, "country": country or None, "ibans": [iban] if iban else [], "kind": kind,
            "default_category": DEFAULT_CATEGORY_BY_KIND.get(kind), "is_recurring": False,
            "typical_payment_delay_days": None, "person_id": None}


def with_alias(cp: dict, raw: str | None) -> dict:
    alias = normalise_alias(raw)
    aliases = list(cp.get("aliases") or [])
    if alias and alias not in aliases and alias != normalise_alias(cp["name"]):
        aliases.append(alias)
    return {**cp, "aliases": aliases}


# ---------- categories ----------

def categorise(text: str, *, counterparty: dict | None, incoming: bool,
               choose: Callable | None = None) -> tuple[str, str, float]:
    """(category, method 'history'|'rule'|'llm', confidence). Always a value of the Category enum."""
    if counterparty and counterparty.get("default_category") in CATEGORIES:
        return counterparty["default_category"], "history", 0.95
    lowered = f" {text.lower()} "
    for category, words in CATEGORY_RULES:
        if any(w in lowered for w in words):
            return category, "rule", 0.85
    if choose:
        picked = choose(f"Which accounting category fits this {'incoming' if incoming else 'outgoing'} item? {text}",
                        CATEGORIES)
        if picked in CATEGORIES:
            return picked, "llm", 0.7
    return ("revenue_services" if incoming else "other"), "rule", 0.5


# ---------- the optional model (D-09: constrained to the enum) ----------

def model_chooser() -> Callable | None:
    """choose(question, choices) -> one of choices, via the cluster's vLLM (guided choice). None when disabled."""
    if os.environ.get("ORDO_LLM_ENABLED", "1") == "0":
        return None
    try:
        from backend import settings
        from backend.agents.llm import default_client
        client = default_client()
    except Exception:  # noqa: BLE001 - no model available: rules only
        return None
    if client is None:
        return None

    def choose(question: str, choices: list[str]) -> str | None:
        try:
            response = client.chat.completions.create(
                model=settings.llm_model(), temperature=0, max_tokens=20,
                messages=[{"role": "user", "content": f"{question}\nAnswer with exactly one of: {', '.join(choices)}"}],
                extra_body={"guided_choice": choices})
            answer = (response.choices[0].message.content or "").strip()
            return answer if answer in choices else None
        except Exception as exc:  # noqa: BLE001 - the model is a helper, never a blocker
            log.warning("category model call failed: %s", exc)
            return None

    return choose


# ---------- applying it to entities ----------

def apply_to_transaction(txn: dict, counterparties: list[dict], company_id: str, choose=None) -> tuple[dict, dict | None]:
    """(updated Transaction, Counterparty to store or None). Sets counterparty_id, category, data_quality."""
    incoming = not txn["amount_base"]["amount"].startswith("-")
    raw = txn.get("counterparty_name_raw") or txn.get("description") or ""
    how, cp, _ = resolve(counterparties, name=raw, iban=txn.get("counterparty_account"))
    to_store = None
    dq = [d for d in txn.get("data_quality") or [] if d != "counterparty_unresolved"]
    if how in ("tax_id", "iban", "alias"):
        counterparty_id = cp["id"]
    elif how == "suggested":
        counterparty_id = None  # confirmed through the Match (learn_from_match), not guessed
        dq.append("counterparty_unresolved")
    else:
        kind = guess_kind(f"{raw} {txn.get('description') or ''}", incoming, choose)
        cp = new_counterparty(company_id, name=raw.strip() or "Unknown", tax_id=None, country=None,
                              iban=txn.get("counterparty_account"), kind=kind, raw_alias=raw,
                              existing_ids={c["id"] for c in counterparties})
        counterparty_id, to_store = cp["id"], cp
    category, _, _ = categorise(f"{raw} {txn.get('description') or ''}",
                                counterparty=cp if counterparty_id else None, incoming=incoming, choose=choose)
    return {**txn, "counterparty_id": counterparty_id, "category": category, "data_quality": dq}, to_store


def apply_to_document(doc: dict, counterparties: list[dict], company_id: str, choose=None) -> tuple[dict, dict | None]:
    """(updated Document, Counterparty to store or None). Resolves the seller of a purchase / the buyer of a sale."""
    side = "seller" if doc["direction"] == "purchase" else "buyer"
    party = doc[side]
    how, cp, _ = resolve(counterparties, name=party.get("name"), tax_id=party.get("tax_id"),
                         iban=(doc.get("payment") or {}).get("bank_account") if side == "seller" else None)
    to_store = None
    if how in ("tax_id", "iban", "alias"):
        counterparty_id = cp["id"]
        if how != "alias":
            cp = with_alias(cp, party.get("name"))
            to_store = cp if cp != next(c for c in counterparties if c["id"] == cp["id"]) else None
    elif how == "suggested" and not party.get("tax_id"):
        counterparty_id = None  # OCR spelling without a tax id: learned when the owner confirms the Match
    else:
        text = " ".join(line.get("description") or "" for line in doc.get("lines") or [])
        kind = guess_kind(f"{party.get('name')} {text}", side == "buyer", choose)
        cp = new_counterparty(company_id, name=party.get("name") or "Unknown", tax_id=party.get("tax_id"),
                              country=party.get("country"), iban=(doc.get("payment") or {}).get("bank_account"),
                              kind=kind, raw_alias=party.get("name"), existing_ids={c["id"] for c in counterparties})
        counterparty_id, to_store = cp["id"], cp
    updated = {**doc, side: {**party, "counterparty_id": counterparty_id}}
    if not doc.get("category_suggestion"):
        text = f"{party.get('name')} " + " ".join(line.get("description") or "" for line in doc.get("lines") or [])
        category, method, confidence = categorise(text, counterparty=cp if counterparty_id else None,
                                                  incoming=side == "buyer", choose=choose)
        updated["category_suggestion"] = {"category": category, "confidence": confidence, "method": method}
    return updated, to_store


def learn_from_match(document: dict, txn: dict, counterparties: list[dict], company_id: str):
    """The owner confirmed that this document and this bank line are one purchase: both spellings belong to one
    counterparty. Returns (counterparties to store, updated document or None, updated transaction or None).
    A counterparty auto-created earlier from the bank spelling gives that alias up to the confirmed one."""
    side = "seller" if document["direction"] == "purchase" else "buyer"
    party = document[side]
    by_id = {c["id"]: c for c in counterparties}
    cp = by_id.get(party.get("counterparty_id")) or by_id.get(txn.get("counterparty_id"))
    if cp is None:
        cp = new_counterparty(company_id, name=party.get("name") or txn.get("counterparty_name_raw") or "Unknown",
                              tax_id=party.get("tax_id"), country=party.get("country"),
                              iban=txn.get("counterparty_account"),
                              kind="customer" if side == "buyer" else "supplier", raw_alias=party.get("name"),
                              existing_ids=set(by_id))
    cp = with_alias(with_alias(cp, txn.get("counterparty_name_raw")), party.get("name"))
    learned = (document.get("category_suggestion") or {}).get("category")
    if not cp.get("default_category") and learned in CATEGORIES and learned != "other":
        cp = {**cp, "default_category": learned}  # the next line from this counterparty is categorised by history
    if txn.get("counterparty_account") and _iban(txn["counterparty_account"]) not in {_iban(i) for i in cp["ibans"]}:
        cp = {**cp, "ibans": [*cp["ibans"], txn["counterparty_account"]]}
    to_store = [cp]
    old = by_id.get(txn.get("counterparty_id"))
    if old and old["id"] != cp["id"]:
        spelling = normalise_alias(txn.get("counterparty_name_raw"))
        to_store.append({**old, "aliases": [a for a in old.get("aliases") or [] if normalise_alias(a) != spelling]})
    doc_out = None if party.get("counterparty_id") == cp["id"] else \
        {**document, side: {**party, "counterparty_id": cp["id"]}}
    dq = [d for d in txn.get("data_quality") or [] if d != "counterparty_unresolved"]
    txn_out = None if txn.get("counterparty_id") == cp["id"] and dq == txn.get("data_quality") else \
        {**txn, "counterparty_id": cp["id"], "data_quality": dq}
    return to_store, doc_out, txn_out
