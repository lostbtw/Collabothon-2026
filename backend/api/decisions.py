"""Owner Decisions: every one writes an Approval (the audit trail) and emits `approval.recorded`."""
from typing import Any

import psycopg

from backend.api.deps import ApiError, new_id, now_iso, owner_of
from backend.db.events import new_event, publish
from backend.db.store import Store

DECISIONS = {"approved", "approved_with_changes", "rejected"}
DECIDABLE_MATCH = {"suggested", "auto_confirmed"}


def draft_approval(c: psycopg.Connection, *, company: str, subject_type: str, subject_id: str, decision: str,
                   channel: str = "dashboard", comment: str | None = None, changes: dict | None = None) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ApiError(422, "invalid_request", f"decision must be one of {sorted(DECISIONS)}")
    if channel not in {"dashboard", "chat"}:
        raise ApiError(422, "invalid_request", "channel must be dashboard or chat")
    return {
        "id": new_id("apr"),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "decision": decision,
        "decided_by": owner_of(c, company),
        "decided_at": now_iso(),
        "channel": channel,
        "comment": comment,
        "changes": changes,
        "execution": {"mode": "none", "status": "not_applicable"},
    }


def store_approval(c: psycopg.Connection, approval: dict[str, Any], company: str) -> dict[str, Any]:
    Store(c).add("approval", approval, company_id=company)
    publish(c, new_event("approval.recorded", company,
                         {"approval_id": approval["id"], "subject_type": approval["subject_type"],
                          "subject_id": approval["subject_id"], "decision": approval["decision"]}, producer="api"))
    return approval


def record_approval(c: psycopg.Connection, *, company: str, subject_type: str, subject_id: str, decision: str,
                    channel: str = "dashboard", comment: str | None = None, changes: dict | None = None) -> dict[str, Any]:
    approval = draft_approval(c, company=company, subject_type=subject_type, subject_id=subject_id, decision=decision,
                              channel=channel, comment=comment, changes=changes)
    return store_approval(c, approval, company)


def decide_match(c: psycopg.Connection, match_id: str, decision: str, *, channel: str = "dashboard",
                 comment: str | None = None, changes: dict | None = None, approval: dict | None = None) -> dict[str, Any]:
    s = Store(c)
    match = s.get("match", match_id)
    if match is None:
        raise ApiError(404, "not_found", f"No match with id {match_id!r}")
    if match["status"] not in DECIDABLE_MATCH:
        raise ApiError(409, "not_decidable", f"{match_id} is already {match['status']}")
    company = s.company_of("match", match_id)
    status = "rejected" if decision == "rejected" else "confirmed"
    if approval is None:
        approval = record_approval(c, company=company, subject_type="match", subject_id=match_id,
                                   decision=decision, channel=channel, comment=comment, changes=changes)
        _close_open_recommendations_of(c, match, approval, "rejected" if decision == "rejected" else "approved")
    s.put("match", {**match, "status": status, "decided_by": approval["decided_by"],
                    "decided_at": approval["decided_at"]}, company_id=company)
    publish(c, new_event("match.decided", company,
                         {"match_id": match_id, "status": status, "approval_id": approval["id"]}, producer="api"))
    return approval


def _close_open_recommendations_of(c: psycopg.Connection, match: dict[str, Any], approval: dict[str, Any], status: str) -> None:
    """Close the open ingestion cards of a directly decided Match, so it cannot be approved twice."""
    s = Store(c)
    company = s.company_of("match", match["id"])
    for rec in s.list("recommendation", company_id=company, agent="ingestion", status=["new", "seen"]):
        subject = rec.get("subject") or {}
        if (subject.get("kind"), subject.get("id")) in {("match", match["id"]), ("document", match["document_id"])}:
            s.put("recommendation", {**rec, "status": status, "approval_id": approval["id"]})
            publish(c, new_event("recommendation.status_changed", company,
                                 {"recommendation_id": rec["id"], "status": status}, producer="api"))
