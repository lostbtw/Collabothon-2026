"""Owner Decisions: every one writes an Approval (the audit trail) and emits `approval.recorded`."""
from typing import Any

import psycopg

from backend.api.deps import ApiError, new_id, now_iso, owner_of
from backend.db.events import new_event, publish
from backend.db.store import Store

DECISIONS = {"approved", "approved_with_changes", "rejected"}


def record_approval(c: psycopg.Connection, *, company: str, subject_type: str, subject_id: str, decision: str,
                    channel: str = "dashboard", comment: str | None = None, changes: dict | None = None,
                    execution: dict[str, Any] | None = None) -> dict[str, Any]:
    if decision not in DECISIONS:
        raise ApiError(422, "invalid_request", f"decision must be one of {sorted(DECISIONS)}")
    approval = {
        "id": new_id("apr"),
        "subject_type": subject_type,
        "subject_id": subject_id,
        "decision": decision,
        "decided_by": owner_of(c, company),
        "decided_at": now_iso(),
        "channel": channel,
        "comment": comment,
        "changes": changes,
        "execution": execution or {"mode": "none", "status": "not_applicable"},
    }
    Store(c).add("approval", approval, company_id=company)
    publish(c, new_event("approval.recorded", company,
                         {"approval_id": approval["id"], "subject_type": subject_type, "subject_id": subject_id,
                          "decision": decision}, producer="api"))
    return approval


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
    company = s.company_of("match", match_id)
    if approval is None:
        approval = record_approval(c, company=company, subject_type="match", subject_id=match_id,
                                   decision=decision, channel=channel, comment=comment, changes=changes)
    status = "rejected" if decision == "rejected" else "confirmed"
    s.put("match", {**match, "status": status, "decided_by": approval["decided_by"],
                    "decided_at": approval["decided_at"]}, company_id=company)
    publish(c, new_event("match.decided", company,
                         {"match_id": match_id, "status": status, "approval_id": approval["id"]}, producer="api"))
    return approval
