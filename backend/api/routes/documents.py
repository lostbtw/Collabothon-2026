"""Documents and Matches (role 3's data, served by role 5)."""
from typing import Any

import psycopg
from fastapi import APIRouter, Body, Depends

from backend.api import contract
from backend.api.decisions import decide_match, record_approval
from backend.api.deps import ApiError, company_id, conn, get_or_404, store
from backend.db.events import new_event, publish
from backend.db.store import Store

router = APIRouter()

EDITABLE = {"totals", "issue_date", "sale_date", "due_date", "seller", "buyer", "category_suggestion"}


@router.get("/documents")
def list_documents(company: str = Depends(company_id), status: str | None = None, flag: str | None = None,
                   direction: str | None = None, q: str | None = None, cursor: str | None = None,
                   s: Store = Depends(store)):
    where = {k: v for k, v in {"status": status, "direction": direction}.items() if v}
    items = s.list("document", company_id=company, **where)
    if flag:
        items = [d for d in items if flag in d.get("flags", [])]
    if q:
        needle = q.lower()
        items = [d for d in items if needle in (d.get("number") or "").lower()
                 or needle in (d.get("seller", {}).get("name") or "").lower()]
    return {"items": items, "next_cursor": None}


@router.get("/documents/{id}")
def get_document(id: str, s: Store = Depends(store)):
    document = get_or_404(s, "document", id)
    duplicates = [d for d in s.list("document", company_id=document["company_id"]) if d.get("duplicate_of") == id]
    return {"document": document, "duplicates": duplicates, "matches": s.list("match", document_id=id)}


@router.patch("/documents/{id}")
def correct_document(id: str, patch: dict[str, Any] = Body(...), c: psycopg.Connection = Depends(conn)):
    """The owner corrects extracted fields; stored as an Approval with the changes."""
    s = Store(c)
    document = get_or_404(s, "document", id)
    unknown = set(patch) - EDITABLE
    if unknown:
        raise ApiError(422, "invalid_request", f"Not editable: {sorted(unknown)}")
    updated = dict(document)
    for field, value in patch.items():
        if field == "category_suggestion" and isinstance(value, dict):
            value = {**(document.get("category_suggestion") or {}), **value, "confidence": 1.0}
        updated[field] = value
    problems = contract.entity_errors("document", updated)
    if problems:
        raise ApiError(422, "invalid_request", "; ".join(problems[:5]))
    approval = record_approval(c, company=document["company_id"], subject_type="document", subject_id=id,
                               decision="approved_with_changes", changes=patch)
    s.put("document", updated)
    # The corrected document goes through the matcher again (dedup, match, who paid), as after extraction.
    publish(c, new_event("document.extracted", document["company_id"],
                         {"document_id": id, "status": updated["status"], "gross": updated["totals"]["gross"],
                          "seller": updated["seller"]["name"], "flags": updated.get("flags", [])},
                         producer="api", correlation_id=(updated.get("raw_item_ids") or [None])[0],
                         causation_id=approval["id"]))
    return updated


@router.get("/matches")
def list_matches(company: str = Depends(company_id), status: str | None = None, s: Store = Depends(store)):
    where = {"status": status} if status else {}
    return {"items": s.list("match", company_id=company, **where)}


@router.post("/matches/{id}/decision")
def match_decision(id: str, body: dict[str, Any] = Body(...), c: psycopg.Connection = Depends(conn)):
    return decide_match(c, id, body.get("decision"), channel=body.get("channel") or "dashboard",
                        comment=body.get("comment"), changes=body.get("changes"))
