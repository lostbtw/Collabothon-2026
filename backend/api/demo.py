"""The M3 and M4 demo flows, step by step and timed: `uv run python -m backend.api.demo hero|liquidity|all`.

Runs against the API at --api (default http://localhost:8080/api/v1) and, for the stand-in steps, the database at
ORDO_DATABASE_URL. A step that another role's code must do for real (mailbox connector, extraction, who paid,
finance engine, frontend) runs on its stand-in and names the ticket that replaces it, so the same script is the
acceptance run on the cluster once those land.

    hero      (M3)  receipt from Jan -> Document + Match -> reimbursement card -> approve -> forecast re-issued
    liquidity (M4)  forecast alert -> credit-line card -> approve with 25,000 -> SIMULATED reference -> new forecast;
                    pizzeria: "We are closed 1-30 June" in the chat -> forecast event
"""
import argparse
import copy
import sys
import time
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
import psycopg

from backend.agents import liquidity
from backend.agents.main import process_pending
from backend.db.events import new_event, publish
from backend.db.fixtures import read
from backend.db.store import Store
from backend.settings import database_url

HERO_BUDGET_SECONDS = 30


@dataclass
class Step:
    name: str
    ok: bool
    detail: str
    seconds: float
    stand_in_until: list[int] = field(default_factory=list)


@dataclass
class Run:
    flow: str
    steps: list[Step] = field(default_factory=list)
    started: float = field(default_factory=time.monotonic)

    def step(self, name: str, ok: bool, detail: str, stand_in_until: list[int] | None = None) -> bool:
        self.steps.append(Step(name, ok, detail, round(time.monotonic() - self.started, 2), stand_in_until or []))
        return ok

    @property
    def ok(self) -> bool:
        return all(s.ok for s in self.steps)

    def report(self) -> str:
        lines = [f"== {self.flow}"]
        for s in self.steps:
            mark = "OK  " if s.ok else "FAIL"
            note = f"  [stand-in until {', '.join(f'#{n}' for n in s.stand_in_until)}]" if s.stand_in_until else ""
            lines.append(f"{mark} {s.seconds:6.2f}s  {s.name}: {s.detail}{note}")
        lines.append(f"{'PASS' if self.ok else 'FAIL'} in {self.steps[-1].seconds if self.steps else 0:.2f}s")
        return "\n".join(lines)


def _wait(fetch, until, timeout: float = 10.0, every: float = 0.25):
    deadline = time.monotonic() + timeout
    while True:
        value = fetch()
        if until(value) or time.monotonic() >= deadline:
            return value
        time.sleep(every)


def hero(api: httpx.Client, conn: psycopg.Connection, company: str = "co_borsuk") -> Run:
    """M3: Jan forwards a receipt photo; the reimbursement card appears; the owner approves; the forecast moves."""
    run = Run("M3 hero flow")
    tag = uuid.uuid4().hex[:6]
    before = api.get("/forecast/latest", params={"company_id": company}).json()["id"]

    # Stand-in for mailbox connector (#33), extraction (#17) and who-paid (#25): what they write, written here.
    raw = {**copy.deepcopy(next(r for r in read("raw_item") if r["id"] == "raw_mail412a1")), "id": f"raw_hero{tag}",
           "idempotency_key": uuid.uuid4().hex + uuid.uuid4().hex}
    document = {**copy.deepcopy(next(d for d in read("document") if d["id"] == "doc_rcpt412")), "id": f"doc_hero{tag}",
                "raw_item_ids": [raw["id"]]}
    match = {**copy.deepcopy(next(m for m in read("match") if m["id"] == "mat_412")), "id": f"mat_hero{tag}",
             "document_id": document["id"]}
    s = Store(conn)
    s.add("raw_item", raw, company_id=company)
    s.add("document", document, company_id=company)
    s.add("match", match, company_id=company)
    publish(conn, new_event("match.suggested", company, {"match_id": match["id"], "document_id": document["id"],
                                                         "paid_by": match["paid_by"], "score": match["score"]},
                            producer="matcher", correlation_id=raw["id"]))
    seen = api.get(f"/documents/{document['id']}")
    run.step("receipt read into a Document", seen.status_code == 200,
             f"{document['seller']['name']}, {document['totals']['gross']['amount']} {document['totals']['gross']['currency']}",
             stand_in_until=[33, 17])

    banner = next((m for m in seen.json().get("matches", []) if m["id"] == match["id"]), None) if seen.status_code == 200 else None
    run.step("who-paid banner", bool(banner and banner["paid_by"] == "employee_private"),
             f"paid by {banner and banner['paid_by']}, owed {banner and banner['consequences']['reimbursement_owed']['amount']}",
             stand_in_until=[25])

    process_pending(conn)  # the agents process; on the cluster it runs on its own
    card = _wait(lambda: next((r for r in api.get("/inbox", params={"company_id": company}).json()["items"]
                               if (r.get("subject") or {}).get("id") == document["id"]), None), bool)
    if not run.step("reimbursement card in the inbox", bool(card), card["title"] if card else "no card"):
        return run

    approval = api.post(f"/recommendations/{card['id']}/decision", json={"decision": "approved"})
    body = approval.json()
    reference = (body.get("execution") or {}).get("reference")
    run.step("owner approves: SIMULATED payment draft", approval.status_code == 200 and bool(reference),
             f"{reference}: {(body.get('execution') or {}).get('result')}", stand_in_until=[36])

    after = api.get("/forecast/latest", params={"company_id": company}).json()
    run.step("forecast moves", after["id"] != before,
             f"{before} -> {after['id']}, low {after['min_balance']['amount']['amount']} on {after['min_balance']['date']}",
             stand_in_until=[27, 28])
    run.step(f"phone to forecast under {HERO_BUDGET_SECONDS} s", time.monotonic() - run.started < HERO_BUDGET_SECONDS,
             f"{time.monotonic() - run.started:.2f} s (stand-in timing; the mailbox poll adds up to 20 s)")
    return run


def liquidity_flow(api: httpx.Client, conn: psycopg.Connection) -> Run:
    """M4: alert -> credit-line card -> approve with 25,000 -> SIMULATED -> new forecast; pizzeria June event."""
    run = Run("M4 liquidity flow")
    company = "co_borsuk"
    forecast = api.get("/forecast/latest", params={"company_id": company}).json()
    alert = next(iter(forecast.get("alerts", [])), None)
    run.step("forecast with a cash-gap alert", bool(alert),
             f"low {forecast['min_balance']['amount']['amount']} on {forecast['min_balance']['date']}"
             + (f", gap {alert['date_from']}..{alert['date_to']}" if alert else ""), stand_in_until=[28, 44])

    liquidity.on_forecast_updated(conn, {"company_id": company, "occurred_at": forecast["generated_at"],
                                         "payload": {"forecast_id": forecast["id"]}})
    card = next((r for r in api.get("/inbox", params={"company_id": company}).json()["items"]
                 if r["type"] == "credit_line"), None)
    if not run.step("credit-line card with the explanation", bool(card),
                    f"{card['title']} ({card['explanation']['generated_by']['wording']} wording, "
                    f"{len(card['explanation']['why'])} reasons, {len(card['explanation']['alternatives'])} alternatives)"
                    if card else "no card"):
        return run

    limit = {"amount": "25000.00", "currency": card["proposed_action"]["params"]["limit"]["currency"]}
    response = api.post(f"/recommendations/{card['id']}/decision", json={
        "decision": "approved_with_changes", "changes": {"proposed_action.params.limit": limit}, "comment": "25k is enough"})
    execution = response.json().get("execution") or {}
    run.step("edit 30,000 -> 25,000 and approve: SIMULATED", response.status_code == 200
             and (execution.get("reference") or "").startswith("SIM-CL-") and "25,000" in (execution.get("result") or ""),
             f"{execution.get('reference')}: {execution.get('result')}", stand_in_until=[36])

    after = api.get("/forecast/latest", params={"company_id": company}).json()
    run.step("chart redraws from a new forecast", after["id"] != forecast["id"],
             f"{after['id']}, low {after['min_balance']['amount']['amount']} (above zero once #44 computes the scenario)",
             stand_in_until=[44])

    answer = api.post("/chat", json={"message": "We are closed 1–30 June", "company_id": "co_amalfi"}).json()
    run.step("pizzeria: chat June event stored", any(t["tool"] == "add_forecast_event" for t in answer.get("tool_calls", [])),
             answer.get("answer", ""), stand_in_until=[28])
    return run


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m backend.api.demo")
    parser.add_argument("flow", choices=["hero", "liquidity", "all"])
    parser.add_argument("--api", default="http://localhost:8080/api/v1")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    runs = []
    with httpx.Client(base_url=args.api, timeout=60) as api, psycopg.connect(database_url()) as conn:
        if args.flow in ("hero", "all"):
            runs.append(hero(api, conn))
        if args.flow in ("liquidity", "all"):
            runs.append(liquidity_flow(api, conn))
    for r in runs:
        print(r.report())
    return 0 if all(r.ok for r in runs) else 1


if __name__ == "__main__":
    sys.exit(main())
