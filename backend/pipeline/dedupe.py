"""Duplicate detection and golden record: one copy per purchase is kept, the others become `duplicate` evidence."""
import re

from .match import name_similarity
from .normalise.money import to_decimal

STRONG_NAME = 0.6
FUZZY_NAME = 0.75


def drop_identical_files(raw_items: list[dict]) -> tuple[list[dict], list[dict]]:
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


def _number(doc) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", doc.get("number") or "").upper()


def _nip(doc) -> str:
    return re.sub(r"[^0-9]", "", (doc["seller"].get("tax_id") or "").upper().removeprefix("PL"))


def duplicate_reason(a: dict, b: dict) -> str | None:
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
    channel = doc.get("channel")
    method = (doc.get("extraction") or {}).get("method")
    if channel == "ksef" or method == "xml_parse":
        return 0
    if channel == "accounting_api" or method == "api":
        return 1
    if channel in ("photo", "upload") or method == "llm_vision":
        return 3
    return 2


def _rank(doc: dict):
    confidence = (doc.get("extraction") or {}).get("confidence")
    return priority(doc), -(confidence if confidence is not None else 0.0), doc.get("created_at") or "", doc["id"]


def deduplicate(documents: list[dict]) -> dict:
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
    return {"document_id": merge["document_id"], "duplicate_of": merge["duplicate_of"], "reason": merge["reason"]}
