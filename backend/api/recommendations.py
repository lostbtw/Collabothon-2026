"""The Recommendation state machine: new -> seen -> approved -> executed_simulated | rejected | expired | superseded."""
from typing import Any

import psycopg

from backend.api.decisions import record_approval
from backend.api.deps import ApiError
from backend.db.events import new_event, publish
from backend.db.store import Store

OPEN = {"new", "seen"}


def decide_recommendation(c: psycopg.Connection, rec_id: str, body: dict[str, Any]) -> dict[str, Any]:
    s = Store(c)
    rec = s.get("recommendation", rec_id)
    if rec is None:
        raise ApiError(404, "not_found", f"No recommendation with id {rec_id!r}")
    if rec["status"] not in OPEN:
        raise ApiError(409, "not_decidable", f"{rec_id} is {rec['status']}; only new or seen recommendations can be decided")
    if rec["control_level"] != "approval_required" and body.get("decision") != "rejected":
        raise ApiError(409, "not_decidable", f"{rec_id} is a {rec['control_level']}; there is nothing to approve")
    decision = body.get("decision")
    approval = record_approval(c, company=rec["company_id"], subject_type="recommendation", subject_id=rec_id,
                               decision=decision, channel=body.get("channel") or "dashboard",
                               comment=body.get("comment"), changes=body.get("changes"))
    status = "rejected" if decision == "rejected" else "approved"
    s.put("recommendation", {**rec, "status": status, "approval_id": approval["id"]})
    publish(c, new_event("recommendation.status_changed", rec["company_id"],
                         {"recommendation_id": rec_id, "status": status}, producer="api"))
    return approval
