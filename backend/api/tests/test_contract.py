"""Seam: HTTP API against contracts/openapi.yaml. Every path answers with a body that validates against its schema."""
import pytest

from backend.api import contract
from backend.db.fixtures import load_fixtures

BORSUK = {"company_id": "co_borsuk"}

CALLS = [
    ("get", "/health", "/health", {}, 200),
    ("get", "/companies", "/companies", {}, 200),
    ("get", "/sources", "/sources", {"params": BORSUK}, 200),
    ("post", "/sources/{id}/sync", "/sources/src_mail/sync", {}, 202),
    ("get", "/sync-runs", "/sync-runs", {"params": {"source_id": "src_mail"}}, 200),
    ("get", "/raw-items/{id}", "/raw-items/raw_mail412", {}, 200),
    ("get", "/raw-items/{id}/content", "/raw-items/raw_mail412a1/content", {}, 200),
    ("post", "/uploads", "/uploads", {"files": {"file": ("receipt.jpg", b"\xff\xd8SAMPLE", "image/jpeg")}, "data": {"submitted_by": "per_jan"}}, 201),
    ("get", "/documents", "/documents", {"params": {**BORSUK, "direction": "purchase"}}, 200),
    ("get", "/documents/{id}", "/documents/doc_rcpt412", {}, 200),
    ("patch", "/documents/{id}", "/documents/doc_pixel11", {"json": {"category_suggestion": {"category": "software_subscriptions"}}}, 200),
    ("get", "/accounts", "/accounts", {"params": BORSUK}, 200),
    ("get", "/transactions", "/transactions", {"params": BORSUK}, 200),
    ("get", "/transactions/{id}", "/transactions/txn_731", {}, 200),
    ("get", "/counterparties", "/counterparties", {"params": BORSUK}, 200),
    ("get", "/matches", "/matches", {"params": BORSUK}, 200),
    ("post", "/matches/{id}/decision", "/matches/mat_pixel11/decision", {"json": {"decision": "approved"}}, 200),
    ("get", "/inbox", "/inbox", {"params": BORSUK}, 200),
    ("get", "/ledger", "/ledger", {"params": BORSUK}, 200),
    ("get", "/ledger/summary", "/ledger/summary", {"params": {**BORSUK, "group_by": "category"}}, 200),
    ("get", "/ledger/export", "/ledger/export", {"params": BORSUK}, 200),
    ("get", "/forecast/latest", "/forecast/latest", {"params": BORSUK}, 200),
    ("get", "/forecast/{id}", "/forecast/fc_20261121a", {}, 200),
    ("post", "/forecast/recompute", "/forecast/recompute", {"params": BORSUK}, 200),
    ("post", "/forecast/events", "/forecast/events", {"json": {"label": "Closed for holidays", "date_from": "2026-12-24", "date_to": "2026-12-27", "effect": "no_revenue", "source": "owner_form"}}, 201),
    ("post", "/forecast/scenario", "/forecast/scenario", {"json": {"credit_line": {"limit": {"amount": "30000.00", "currency": "PLN"}, "from": "2026-11-28"}}}, 200),
    ("get", "/recommendations", "/recommendations", {"params": BORSUK}, 200),
    ("get", "/recommendations/{id}", "/recommendations/rec_cl01", {}, 200),
    ("post", "/recommendations/{id}/decision", "/recommendations/rec_fx01/decision", {"json": {"decision": "rejected", "comment": "not now"}}, 200),
    ("get", "/approvals", "/approvals", {"params": BORSUK}, 200),
    ("get", "/activity", "/activity", {"params": BORSUK}, 200),
    ("post", "/chat", "/chat", {"json": {"message": "Why will I be short in December?", "company_id": "co_borsuk"}}, 200),
    ("post", "/chat/transcribe", "/chat/transcribe", {"files": {"file": ("question.webm", b"SAMPLE", "audio/webm")}, "data": {"language": "pl"}}, 503),
    ("get", "/fx/rates", "/fx/rates", {"params": {"currency": "EUR", "date": "2026-11-20"}}, 200),
    ("get", "/fx/exposure", "/fx/exposure", {"params": BORSUK}, 200),
    ("patch", "/transactions/{id}", "/transactions/txn_731", {"params": BORSUK, "json": {"category": "software_subscriptions"}}, 200),
    ("get", "/settings", "/settings", {"params": BORSUK}, 200),
    ("patch", "/settings", "/settings", {"params": BORSUK, "json": {"alerts": {"late_client_days": 10}}}, 200),
    ("get", "/people", "/people", {"params": BORSUK}, 200),
    ("post", "/people", "/people", {"params": BORSUK, "json": {"name": "Ewa Nowak (SAMPLE)", "email": "ewa@borsuk-labs.sample", "role": "employee"}}, 201),
    ("get", "/people/costs", "/people/costs", {"params": {**BORSUK, "month": "2026-10"}}, 200),
    ("get", "/clients", "/clients", {"params": {**BORSUK, "month": "2026-10"}}, 200),
    ("get", "/subscriptions", "/subscriptions", {"params": BORSUK}, 200),
    ("get", "/rules", "/rules", {"params": BORSUK}, 200),
    ("delete", "/rules/{id}", "/rules/rule_nope", {"params": BORSUK}, 404),
    ("get", "/chat/sessions", "/chat/sessions", {"params": BORSUK}, 200),
    ("get", "/chat/sessions/{id}", "/chat/sessions/chat_nope", {"params": BORSUK}, 404),
    ("get", "/balance/history", "/balance/history", {"params": BORSUK}, 200),
]
STREAM = "/events/stream"


@pytest.fixture
def demo(client, db):
    load_fixtures(db)
    return client


def test_every_contract_path_is_exercised():
    covered = {(m, p) for m, p, *_ in CALLS} | {("get", STREAM)}
    in_spec = {(m, p) for p, ops in contract.openapi()["paths"].items() for m in ops}
    assert in_spec == covered


@pytest.mark.parametrize("method,path,url,kwargs,status", CALLS, ids=[f"{c[0].upper()} {c[1]}" for c in CALLS])
def test_path_answers_with_a_body_valid_against_its_schema(demo, method, path, url, kwargs, status):
    response = demo.request(method.upper(), "/api/v1" + url, **kwargs)

    assert response.status_code == status, response.text
    schema = contract.response_schema(method, path, status)
    if schema is not None:
        assert contract.errors(response.json(), schema) == []


@pytest.mark.parametrize("url", ["/documents/doc_nope", "/forecast/fc_20261121b", "/recommendations/rec_nope", "/transactions/txn_nope", "/raw-items/raw_nope"])
def test_unknown_ids_answer_404_with_the_standard_error_shape(demo, url):
    response = demo.get("/api/v1" + url)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "not_found"
    assert set(response.json()["error"]) <= {"code", "message", "retryable"}


def test_health_reports_the_configured_model_url(db_url, db, monkeypatch):
    from fastapi.testclient import TestClient

    from backend.api.app import create_app

    monkeypatch.setenv("ORDO_LLM_BASE_URL", "http://vllm.ordo.svc:8000/v1")
    with TestClient(create_app(database_url=db_url)) as c:
        body = c.get("/api/v1/health").json()

    assert body["status"] == "ok"
    assert body["llm"]["base_url"] == "http://vllm.ordo.svc:8000/v1"
