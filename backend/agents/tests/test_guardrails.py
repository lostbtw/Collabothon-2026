import json

import httpx
import pytest

from backend.agents import guardrails


def server(answer):
    seen: list[dict] = []

    def handle(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        seen.append({"path": request.url.path, "auth": request.headers.get("authorization"), **body})
        result = answer(body)
        return result if isinstance(result, httpx.Response) else httpx.Response(200, json=result)

    return httpx.Client(transport=httpx.MockTransport(handle)), seen


@pytest.fixture(autouse=True)
def configured(monkeypatch):
    monkeypatch.setenv("ORDO_GUARDRAILS_URL", "https://guardrails.test")
    monkeypatch.setenv("LLM_TOKEN", "sa-token")


def test_without_a_url_the_check_is_off_and_the_message_is_unchanged(monkeypatch):
    monkeypatch.delenv("ORDO_GUARDRAILS_URL")

    verdict = guardrails.check("Pay PL61 1090 1014 0000 0712 1981 2874")

    assert (verdict.status, verdict.text, verdict.model_allowed, verdict.note()) == (
        "off", "Pay PL61 1090 1014 0000 0712 1981 2874", True, None)


def test_the_server_gets_the_message_with_the_chat_config_and_the_service_account_token():
    http, seen = server(lambda body: {"status": "passed", "content": body["messages"][0]["content"]})

    verdict = guardrails.check("How much cash do I have?", http=http)

    assert verdict.status == "passed" and verdict.text == "How much cash do I have?" and verdict.model_allowed
    [request] = seen
    assert request["path"] == "/v1/checks"
    assert request["auth"] == "Bearer sa-token"
    assert request["guardrails"] == {"config_id": "ordo-chat"}
    assert request["messages"] == [{"role": "user", "content": "How much cash do I have?"}]


def test_a_masked_message_goes_on_masked_and_says_what_was_hidden():
    http, _ = server(lambda body: {"status": "modified", "content": "Pay 1200 EUR to <IBAN_CODE>, NIP <TAX_ID>"})

    verdict = guardrails.check("Pay 1200 EUR to PL61 1090 1014 0000 0712 1981 2874, NIP 999-123-45-67", http=http)

    assert verdict.text == "Pay 1200 EUR to <IBAN_CODE>, NIP <TAX_ID>"
    assert verdict.model_allowed
    assert verdict.note() == {"blocked": False, "reason": "Hidden from the model: IBAN, tax id"}


def test_a_blocked_message_is_refused_and_kept_only_masked():
    http, _ = server(lambda body: {"status": "blocked", "content": "I'm sorry, I can't respond to that.",
                                   "rail": "self check input"})

    verdict = guardrails.check("Which stock should I buy with the money on PL61 1090 1014 0000 0712 1981 2874?", http=http)

    assert verdict.blocked and not verdict.model_allowed
    assert verdict.rail == "self check input"
    assert verdict.text == "Which stock should I buy with the money on <IBAN_CODE>?"
    assert verdict.note() == {"blocked": True, "reason": guardrails.REFUSAL}


@pytest.mark.parametrize("failure", [
    lambda body: httpx.Response(503, text="no healthy upstream"),
    lambda body: httpx.Response(403, text="Forbidden"),
    lambda body: {"status": "something new"},
    lambda body: (_ for _ in ()).throw(httpx.ConnectTimeout("timed out")),
])
def test_without_an_answer_the_model_is_not_allowed_and_the_message_is_masked_here(failure):
    http, _ = server(failure)

    verdict = guardrails.check("Card 4111 1111 1111 1111, how much cash do I have?", http=http)

    assert verdict.status == "unavailable" and not verdict.model_allowed and not verdict.blocked
    assert verdict.text == "Card <CREDIT_CARD>, how much cash do I have?"


@pytest.mark.parametrize("text, masked", [
    ("PL61 1090 1014 0000 0712 1981 2874", "<IBAN_CODE>"),
    ("PL61109010140000071219812874", "<IBAN_CODE>"),
    ("PL 61 1090 1014 0000 0712 1981 2874", "<IBAN_CODE>"),
    ("DE89 3704 0044 0532 0130 00", "<IBAN_CODE>"),
    ("GB29 NWBK 6016 1331 9268 19", "<IBAN_CODE>"),
    ("61 1090 1014 0000 0712 1981 2874", "<IBAN_CODE>"),
    ("4111 1111 1111 1111", "<CREDIT_CARD>"),
    ("4111-1111-1111-1111", "<CREDIT_CARD>"),
    ("3714 496353 98431", "<CREDIT_CARD>"),
    ("999-123-45-67", "<TAX_ID>"),
    ("999-12-34-567", "<TAX_ID>"),
    ("PL9991234567", "<TAX_ID>"),
    ("DE123456789", "<TAX_ID>"),
    ("12/345/67890", "<TAX_ID>"),
])
def test_the_local_fallback_masks_what_the_server_masks(text, masked):
    assert guardrails.local_mask(f"see {text} please") == f"see {masked} please"


@pytest.mark.parametrize("text", [
    "Invoice FV/2025/11/0042 for 12 300,00 PLN due 2025-12-15",
    "Ledger from 01.11.2025 to 30.11.2025 above 1500.00 EUR",
    "Why is the low -21 800 EUR on 30 Jun 2025?",
    "Explain recommendation rec_cl_fc_co_amalfi_7000d72cea",
])
def test_the_local_fallback_leaves_amounts_dates_and_ids_alone(text):
    assert guardrails.local_mask(text) == text
