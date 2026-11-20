"""Duplicate detection and golden record (ticket #40, spec #3 "Dedup"). Deterministic, no LLM.

The same purchase can arrive as KSeF XML, a PDF by e-mail and a phone photo. One copy is kept as the golden
record; the others get `status = duplicate` and `duplicate_of = <golden id>` and stay as evidence.

- D1 strong: same seller tax id (or seller name similarity > 0.6) and the same invoice number.
- D2 fuzzy: name similarity > 0.75, gross within 1.00, same issue date, same currency, and not two different
  invoice numbers.
- D3 file: identical file content (sha256) is dropped at RawItem level, before any reading.

Golden priority: KSeF XML > accounting API > PDF > photo; ties go to the earlier copy. Every merge is done by the
system on its own (control level `analysed_autonomously`) and is reported through `document.duplicate_detected`,
so it shows in "What I did on my own" and can be undone.
"""
import re

from .match import name_similarity
from .normalise.money import to_decimal

STRONG_NAME = 0.6
FUZZY_NAME = 0.75


# ---------- D3: identical files ----------

def drop_identical_files(raw_items: list[dict]) -> tuple[list[dict], list[dict]]:
    """(kept, dropped): a RawItem whose sha256 was already seen is dropped (the first one fetched stays)."""
    seen, kept, dropped = set(), [], []
    for item in sorted(raw_items, key=lambda r: (r.get("fetched_at") or "", r["id"])):
        digest = item.get("sha256")
        if digest and digest in seen:
            dropped.append(item)
            continue
        if digest:
            seen.add(digest)
        kept.append(item)
    return kept, dropped


# ---------- D1 / D2 ----------

def _number(doc) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", doc.get("number") or "").upper()


def _nip(doc) -> str:
    return re.sub(r"[^0-9]", "", (doc["seller"].get("tax_id") or "").upper().removeprefix("PL"))


def duplicate_reason(a: dict, b: dict) -> str | None:
    """Why `a` and `b` are the same purchase ("D1 ..." / "D2 ..."), or None."""
    if a["company_id"] != b["company_id"] or a.get("direction") != b.get("direction"):
        return None
    num_a, num_b = _number(a), _number(b)
    same_seller_id = bool(_nip(a)) and _nip(a) == _nip(b)
    sim = name_similarity(a["seller"]["name"], b["seller"]["name"])
    if num_a and num_a == num_b and (same_seller_id or sim > STRONG_NAME):
        how = f"same seller tax id {a['seller'].get('tax_id')}" if same_seller_id else f"seller names alike ({sim:.2f})"
        return f"D1: same invoice number {a.get('number')}, {how}"
    ga, gb = a["totals"]["gross"], b["totals"]["gross"]
    if (sim > FUZZY_NAME and ga["currency"] == gb["currency"]
            and abs(to_decimal(ga["amount"]) - to_decimal(gb["amount"])) <= 1
            and a.get("issue_date") and a.get("issue_date") == b.get("issue_date")
            and not (num_a and num_b and num_a != num_b)):
        return (f"D2: seller names alike ({sim:.2f}), same date {a['issue_date']}, "
                f"gross {ga['amount']} vs {gb['amount']} {ga['currency']}")
    return None


def priority(doc: dict) -> int:
    """Lower is better: KSeF XML 0, accounting API 1, PDF / e-mail 2, photo 3."""
    channel = doc.get("channel")
    method = (doc.get("extraction") or {}).get("method")
    if channel == "ksef" or method == "xml_parse":
        return 0
    if channel == "accounting_api" or method == "api":
        return 1
    if channel == "photo" or method == "llm_vision":
        return 3
    return 2


def _rank(doc: dict):
    return priority(doc), doc.get("created_at") or "", doc["id"]


# ---------- clustering ----------

def deduplicate(documents: list[dict]) -> dict:
    """Group documents into purchases and pick the golden record of each.

    Returns {"documents": updated copies (golden ones untouched, others status duplicate + duplicate_of),
             "merges": [{"document_id", "duplicate_of", "reason", "control_level"}] (one per duplicate),
             "clusters": [[golden id, duplicate ids...], ...]}.
    Documents a person already rejected are left alone.
    """
    active = [d for d in documents if d.get("status") != "rejected"]
    clusters: list[list[dict]] = []
    reason_of: dict[str, str] = {}
    for doc in sorted(active, key=_rank):
        for cluster in clusters:
            reason = next((r for other in cluster if (r := duplicate_reason(doc, other))), None)
            if reason:
                cluster.append(doc)
                reason_of[doc["id"]] = reason
                break
        else:
            clusters.append([doc])

    updated, merges = {d["id"]: d for d in documents}, []
    for cluster in clusters:
        golden = min(cluster, key=_rank)
        if golden.get("status") == "duplicate":
            updated[golden["id"]] = {**golden, "status": "extracted", "duplicate_of": None}
        for doc in cluster:
            if doc is golden:
                continue
            updated[doc["id"]] = {**doc, "status": "duplicate", "duplicate_of": golden["id"]}
            merges.append({"document_id": doc["id"], "duplicate_of": golden["id"],
                           "reason": reason_of.get(doc["id"]) or duplicate_reason(doc, golden) or "same purchase",
                           "control_level": "analysed_autonomously"})
    return {"documents": [updated[d["id"]] for d in documents], "merges": merges,
            "clusters": [[min(c, key=_rank)["id"]] + [d["id"] for d in c if d is not min(c, key=_rank)]
                         for c in clusters]}


def add_document(new: dict, existing: list[dict]) -> dict:
    """Live path: one new Document against the company's existing ones.

    Returns {"documents": the new document and any existing ones that changed, "merges": [...],
             "golden_changed": old golden id if the new copy outranks it (e.g. KSeF XML after a photo), else None}.
    A changed golden record means its Match must be re-run on the new golden (role 5 re-points the card).
    """
    pool = [d for d in existing if d["company_id"] == new["company_id"] and d.get("status") != "rejected"]
    hit = next((d for d in pool if duplicate_reason(new, d)), None)
    if hit is None:
        return {"documents": [new], "merges": [], "golden_changed": None}
    golden_id = hit.get("duplicate_of") or hit["id"]
    golden = next((d for d in pool if d["id"] == golden_id), hit)
    members = [d for d in pool if d["id"] == golden_id or d.get("duplicate_of") == golden_id]
    result = deduplicate(members + [new])
    changed = [d for d in result["documents"]
               if d["id"] == new["id"] or d != next(m for m in members if m["id"] == d["id"])]
    merges = [m for m in result["merges"] if m["document_id"] in {d["id"] for d in changed}]
    new_golden = result["clusters"][0][0] if result["clusters"] else golden_id
    return {"documents": changed, "merges": merges,
            "golden_changed": golden_id if new_golden != golden_id else None}


def duplicate_detected_payload(merge: dict) -> dict:
    """Small payload for the `document.duplicate_detected` event (contracts/events.md)."""
    return {"document_id": merge["document_id"], "duplicate_of": merge["duplicate_of"], "reason": merge["reason"]}
