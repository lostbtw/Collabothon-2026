"""Owner Decisions: every one writes an Approval (the audit trail) and emits `approval.recorded`."""
from typing import Any

import psycopg

from backend.api.deps import ApiError, new_id, now_iso, owner_of
from backend.db.events import new_event, publish
from backend.db.store import Store

DECISIONS = {"approved", "approved_with_changes", "rejected"}
DECIDABLE_MATCH = {"suggested", "auto_confirmed"}  # auto_confirmed: the owner may still undo it


def draft_approval(c: psycopg.Connection, *, company: str, subject_type: str, subject_id: str, decision: str,
                   channel: str = "dashboard", comment: str | None = None, changes: dict | None = None) -> dict[str, Any]:
    """The Approval of a Decision before it is stored (execution not yet known)."""
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
    """Write the Approval (the audit record) and emit `approval.recorded`."""
    Store(c).add("approval", approval, company_id=company)
    publish(c, new_event("approval.recorded", company,
                         {"approval_id": approval["id"], "subject_type": approval["subject_type"],
                          "subject_id": approval["subject_id"], "decision": approval["decision"]}, producer="api"))
    return approval


def record_approval(c: psycopg.Connection, *, company: str, subject_type: str, subject_id: str, decision: str,
                    channel: str = "dashboard", comment: str | None = None, changes: dict | None = None) -> dict[str, Any]:
    """A Decision with nothing to execute: draft and store in one step."""
    approval = draft_approval(c, company=company, subject_type=subject_type, subject_id=subject_id, decision=decision,
                              channel=channel, comment=comment, changes=changes)
    return store_approval(c, approval, company)


def decide_match(c: psycopg.Connection, match_id: str, decision: str, *, channel: str = "dashboard",
                 comment: str | None = None, changes: dict | None = None, approval: dict | None = None) -> dict[str, Any]:
    """Confirm or reject a Match; emits `match.decided` so role 4 books (or does not book) its ledger entries.

    `approval` is given when the Match is decided by a Decision on its Recommendation (one tap, D-20): that one
    Approval covers both, so no second Approval exists for the purchase.
    """
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
    """A Match decided directly also closes the open ingestion Recommendations about it, so the purchase cannot
    be approved a second time from the inbox."""
    s = Store(c)
    company = s.company_of("match", match["id"])
    for rec in s.list("recommendation", company_id=company, agent="ingestion", status=["new", "seen"]):
        subject = rec.get("subject") or {}
        if (subject.get("kind"), subject.get("id")) in {("match", match["id"]), ("document", match["document_id"])}:
            s.put("recommendation", {**rec, "status": status, "approval_id": approval["id"]})
            publish(c, new_event("recommendation.status_changed", company,
                                 {"recommendation_id": rec["id"], "status": status}, producer="api"))
