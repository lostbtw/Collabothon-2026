"""Recommendations: the only way they are written, and the state machine of an owner Decision on one.

States (recommendation.schema.json): new -> seen -> approved | rejected | expired | superseded,
then approved -> executed_simulated. Execution is always simulated in this build; `permitted` is refused.
"""
import copy
from typing import Any

import psycopg

from backend.api import contract, ports
from backend.api.decisions import decide_match, draft_approval, store_approval
from backend.api.deps import ApiError
from backend.db.events import new_event, publish
from backend.db.store import Store

OPEN = {"new", "seen"}
EDITABLE_PREFIX = "proposed_action.params."


class InvalidRecommendation(ValueError):
    pass


def save_recommendation(c: psycopg.Connection, rec: dict[str, Any]) -> bool:
    """Store a new Recommendation and emit `recommendation.created`. False when an open one already exists for the
    same (type, subject). Refuses one without both labels, an explanation or evidence, or with execution `permitted`."""
    if rec.get("execution_mode") == "permitted":
        raise InvalidRecommendation("execution_mode 'permitted' is not enabled in this build")
    problems = contract.entity_errors("recommendation", rec)
    if problems:
        raise InvalidRecommendation("; ".join(problems[:5]))
    if not Store(c).add("recommendation", rec):
        return False
    publish(c, new_event("recommendation.created", rec["company_id"],
                         {"recommendation_id": rec["id"], "type": rec["type"], "control_level": rec["control_level"]},
                         producer="agents"))
    return True


def _apply_changes(rec: dict[str, Any], changes: dict[str, Any] | None) -> dict[str, Any]:
    effective = copy.deepcopy(rec)
    for path, value in (changes or {}).items():
        if path in {"execution_mode", "proposed_action.execution_mode"} and value == "permitted":
            raise ApiError(409, "execution_not_permitted", "Real execution is not enabled in this build; every action runs SIMULATED")
        if not path.startswith(EDITABLE_PREFIX):
            raise ApiError(422, "invalid_request", f"Only the action's parameters can be changed, not {path!r}")
        node = effective
        *parents, leaf = path.split(".")
        for part in parents:
            node = node.setdefault(part, {})
        node[leaf] = value
    return effective


def _subject_match(s: Store, rec: dict[str, Any]) -> str | None:
    """The Match this Recommendation decides (one tap, D-20): its subject, or, for an ingestion card about a
    Document, that Document's open Match. Hints (control level recommendation) decide nothing: dismissing
    "mark as private?" must not reject the Match."""
    if rec["control_level"] != "approval_required":
        return None
    subject = rec.get("subject") or {}
    if subject.get("kind") == "match":
        return subject["id"]
    if subject.get("kind") == "document" and rec["agent"] == "ingestion":
        open_matches = s.list("match", document_id=subject["id"], status="suggested")
        return open_matches[0]["id"] if open_matches else None
    return None


def decide_recommendation(c: psycopg.Connection, rec_id: str, body: dict[str, Any]) -> dict[str, Any]:
    s = Store(c)
    rec = s.get("recommendation", rec_id)
    if rec is None:
        raise ApiError(404, "not_found", f"No recommendation with id {rec_id!r}")
    decision = body.get("decision")
    if rec["status"] not in OPEN:
        raise ApiError(409, "not_decidable", f"{rec_id} is {rec['status']}; only new or seen recommendations can be decided")
    if rec["execution_mode"] == "permitted":
        raise ApiError(409, "execution_not_permitted", "Real execution is not enabled in this build")
    if rec["control_level"] != "approval_required" and decision != "rejected":
        raise ApiError(409, "not_decidable", f"{rec_id} is a {rec['control_level']}; there is nothing to approve")
    changes = body.get("changes") or None
    effective = _apply_changes(rec, changes)
    if decision == "approved" and changes:
        decision = "approved_with_changes"

    company = rec["company_id"]
    approval = draft_approval(c, company=company, subject_type="recommendation", subject_id=rec_id, decision=decision,
                              channel=body.get("channel") or "dashboard", comment=body.get("comment"), changes=changes)

    action = effective.get("proposed_action")
    runs = decision != "rejected" and rec["execution_mode"] == "simulated" and action and action["kind"] != "none"
    if runs:
        try:
            done = ports.execute(c, approval, action, company)
            approval["execution"] = {"mode": "simulated", "status": "done", "executed_at": approval["decided_at"],
                                     "reference": done["reference"], "result": done["result"], "effects": []}
        except Exception as exc:  # the decision stands; the failure is shown on the card
            approval["execution"] = {"mode": "simulated", "status": "failed", "executed_at": None,
                                     "result": f"SIMULATED execution failed: {exc}", "effects": []}
    store_approval(c, approval, company)

    match_id = _subject_match(s, rec)
    if match_id:
        decide_match(c, match_id, decision, approval=approval)

    if runs and approval["execution"]["status"] == "done":
        forecast = ports.recompute_forecast(c, company, f"{approval['execution']['result']} ({approval['execution']['reference']})")
        if forecast:
            approval["execution"]["effects"] = [{"kind": "forecast", "id": forecast["id"],
                                                 "label": "Forecast after the simulated action",
                                                 "url": f"/forecast/{forecast['id']}"}]
            s.put("approval", approval, company_id=company)
        status = "executed_simulated"
    else:
        status = "rejected" if decision == "rejected" else "approved"

    s.put("recommendation", {**rec, "status": status, "approval_id": approval["id"]})
    publish(c, new_event("recommendation.status_changed", company,
                         {"recommendation_id": rec_id, "status": status}, producer="api"))
    return approval
