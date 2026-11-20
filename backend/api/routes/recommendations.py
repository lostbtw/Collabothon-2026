"""Inbox, Recommendations, Decisions, Approvals and the "What I did on my own" feed (role 5)."""
from typing import Any

import psycopg
from fastapi import APIRouter, Body, Depends

from backend.api.deps import company_id, conn, get_or_404, store
from backend.api.recommendations import decide_recommendation
from backend.db.store import Store

router = APIRouter()

OPEN = ("new", "seen")
SEVERITY_ORDER = {"critical": 0, "warning": 1, "info": 2}


@router.get("/inbox")
def inbox(company: str = Depends(company_id), s: Store = Depends(store)):
    open_recs = s.list("recommendation", company_id=company, status=list(OPEN))
    items = sorted(
        (r for r in open_recs if r["control_level"] == "approval_required"),
        key=lambda r: (SEVERITY_ORDER.get(r["severity"], 9), r.get("valid_until") or "9999"),
    )
    today = max((r["created_at"][:10] for r in s.list("recommendation", company_id=company)), default="")
    counts = {
        "approval_required": len(items),
        "recommendation": sum(1 for r in open_recs if r["control_level"] == "recommendation"),
        "analysed_autonomously_today": sum(
            1 for r in s.list("recommendation", company_id=company, control_level="analysed_autonomously")
            if r["created_at"][:10] == today
        ) + sum(1 for m in s.list("match", company_id=company, status="auto_confirmed")
                if (m.get("created_at") or "")[:10] == today),
    }
    return {"items": items, "counts": counts}


@router.get("/recommendations")
def list_recommendations(company: str = Depends(company_id), status: str | None = None, agent: str | None = None,
                         control_level: str | None = None, s: Store = Depends(store)):
    where = {k: v for k, v in {"status": status, "agent": agent, "control_level": control_level}.items() if v}
    return {"items": s.list("recommendation", company_id=company, **where)}


@router.get("/recommendations/{id}")
def get_recommendation(id: str, s: Store = Depends(store)):
    return get_or_404(s, "recommendation", id)


@router.post("/recommendations/{id}/decision")
def recommendation_decision(id: str, body: dict[str, Any] = Body(...), c: psycopg.Connection = Depends(conn)):
    return decide_recommendation(c, id, body)


@router.get("/approvals")
def list_approvals(company: str = Depends(company_id), s: Store = Depends(store)):
    return {"items": s.list("approval", company_id=company)}


@router.get("/activity")
def activity(company: str = Depends(company_id), since: str | None = None, s: Store = Depends(store)):
    """What the agents did alone (control level analysed_autonomously). Undo of an auto-confirmed match is a
    reject through /matches/{id}/decision, so each item names its subject."""
    items = []
    for m in s.list("match", company_id=company, status="auto_confirmed"):
        reason = "; ".join(r["detail"] for r in m.get("reasons", [])[:2])
        items.append({
            "at": m.get("created_at") or m.get("decided_at") or "",
            "agent": "ingestion",
            "text": f"Matched {m['document_id']} to {m.get('transaction_id') or 'no bank line'} automatically"
                    + (f" ({reason})" if reason else ""),
            "subject": {"type": "match", "id": m["id"]},
            "evidence": [{"kind": "match", "id": m["id"], "label": "Match", "url": f"/matches/{m['id']}"},
                         {"kind": "document", "id": m["document_id"], "label": "Document",
                          "url": f"/documents/{m['document_id']}"}],
        })
    for r in s.list("recommendation", company_id=company, control_level="analysed_autonomously"):
        items.append({"at": r["created_at"], "agent": r["agent"], "text": r["title"],
                      "subject": {"type": "recommendation", "id": r["id"]}, "evidence": r["evidence"]})
    items = [i for i in items if not since or i["at"] >= since]
    return {"items": sorted(items, key=lambda i: i["at"], reverse=True)}
