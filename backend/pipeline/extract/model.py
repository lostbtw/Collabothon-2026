import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from backend import settings

from .errors import ExtractionError

MAX_MARKDOWN = 24000
MAX_TOKENS = 4096
MONEY = r"^-?\d+\.\d{2}$"
DATE = r"^\d{4}-\d{2}-\d{2}$"
FIELD_KEYS = ("gross", "net", "vat", "issue_date", "number", "seller_tax_id", "buyer_tax_id")


def _nullable(schema: dict[str, Any]) -> dict[str, Any]:
    return {**schema, "type": [schema["type"], "null"]}


def _object(properties: dict[str, Any]) -> dict[str, Any]:
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


TEXT = {"type": ["string", "null"]}
MONEY_FIELD = _nullable({"type": "string", "pattern": MONEY})
DATE_FIELD = _nullable({"type": "string", "pattern": DATE})
SCORE = {"type": "number", "minimum": 0, "maximum": 1}
PARTY = _object({"name": TEXT, "tax_id": TEXT, "country": TEXT, "address": TEXT})

SCHEMA = _object({
    "doc_type": {"type": "string",
                 "enum": ["invoice", "simplified_invoice", "receipt", "proforma", "credit_note", "other"]},
    "number": TEXT,
    "issue_date": DATE_FIELD,
    "sale_date": DATE_FIELD,
    "due_date": DATE_FIELD,
    "seller": PARTY,
    "buyer": PARTY,
    "currency": _nullable({"type": "string", "pattern": r"^[A-Z]{3}$"}),
    "gross": MONEY_FIELD,
    "net": MONEY_FIELD,
    "vat": MONEY_FIELD,
    "vat_lines": {"type": "array", "items": _object({"rate": TEXT, "vat": MONEY_FIELD, "gross": MONEY_FIELD})},
    "lines": {"type": "array", "items": _object({"description": {"type": "string"},
                                                  "quantity": {"type": ["number", "null"]},
                                                  "unit_price": MONEY_FIELD, "net": MONEY_FIELD,
                                                  "vat_rate": TEXT})},
    "payment_method": {"type": "string", "enum": ["card", "transfer", "cash", "direct_debit", "unknown"]},
    "card_last4": _nullable({"type": "string", "pattern": r"^\d{4}$"}),
    "bank_account": TEXT,
    "confidence": SCORE,
    "field_confidence": _object({key: SCORE for key in FIELD_KEYS}),
})

SYSTEM = (
    "You read invoices and receipts for a small Polish company's bookkeeping. "
    "The document comes as Markdown converted by OCR, so expect broken lines and misread characters. "
    "Do not deliberate: think in at most one short sentence, then write the answer. "
    "Answer only with the JSON object the schema asks for. "
    "Copy only values that are printed on the document; use null for anything that is not printed, "
    "and never calculate a value that is missing. "
    "Money is a decimal string with a dot and two decimals, without currency signs or thousands separators. "
    "Dates are YYYY-MM-DD. Currency is the ISO code; zl and PLN mean PLN. "
    "gross is the total to pay (SUMA, Razem brutto, Do zaplaty, Total). "
    "On a Polish fiscal receipt PTU is the VAT: each PTU letter is a vat_line whose rate is the percentage printed "
    "next to that letter (Kwota PTU B 8,00% means rate 8), whose vat is the Kwota PTU amount and whose gross is "
    "the Sprzed. opod. amount of the same letter. On an invoice each VAT rate row is a vat_line with its VAT and "
    "gross (brutto) amounts. vat_lines rate is the printed rate: 23, 8, 5, 0, zw, np or oo. "
    "lines are at most the first 10 items. "
    "tax_id is the NIP, VAT id or USt-IdNr as printed. country is the two-letter code. "
    "card_last4 is the last four digits of a masked card number. "
    "confidence is how sure you are that every field is right, from 0 to 1; "
    "field_confidence gives the same for each named field, low when OCR text around it looks damaged."
)


@dataclass(frozen=True)
class ModelReading:
    answer: dict[str, Any]
    seconds: float
    warnings: list[str] = field(default_factory=list)
    tokens: dict[str, int] = field(default_factory=dict)


def default_client() -> Any:
    from openai import DefaultHttpx2Client, OpenAI

    return OpenAI(base_url=settings.llm_base_url(), api_key=settings.llm_token(),
                  timeout=float(os.environ.get("ORDO_EXTRACT_LLM_TIMEOUT_SECONDS", "60")), max_retries=0,
                  http_client=DefaultHttpx2Client(verify=settings.llm_verify()))


def response_format() -> dict[str, Any]:
    return {"type": "json_schema", "json_schema": {"name": "document_fields", "schema": SCHEMA, "strict": True}}


def read(markdown: str, *, client: Any = None) -> ModelReading:
    warnings = []
    if len(markdown) > MAX_MARKDOWN:
        markdown = markdown[:MAX_MARKDOWN]
        warnings.append(f"The document text was cut at {MAX_MARKDOWN} characters")
    client = client or default_client()
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": "Extract the fields from this document:\n\n" + markdown}]
    started = time.monotonic()
    tokens: dict[str, int] = {}
    answer, problems, content = _ask(client, messages, tokens)
    if problems:
        messages += [{"role": "assistant", "content": content or ""},
                     {"role": "user", "content": "Your answer does not match the required JSON: "
                      + "; ".join(problems)[:500] + ". Answer again with the JSON object only."}]
        answer, problems, _ = _ask(client, messages, tokens)
    if problems:
        raise ExtractionError("model answer does not match the schema: " + "; ".join(problems)[:300])
    return ModelReading(answer=answer, seconds=time.monotonic() - started, warnings=warnings, tokens=tokens)


def _ask(client: Any, messages: list[dict[str, str]],
         tokens: dict[str, int]) -> tuple[dict[str, Any] | None, list[str], str | None]:
    try:
        response = client.chat.completions.create(
            model=settings.llm_model(), messages=messages, response_format=response_format(),
            reasoning_effort="low", temperature=0, max_tokens=MAX_TOKENS)
    except Exception as error:
        raise ExtractionError(f"model call failed: {type(error).__name__}: {error}") from error
    _count(tokens, response)
    choice = response.choices[0]
    content = choice.message.content
    if choice.finish_reason == "length":
        return None, [f"the answer was cut off after {MAX_TOKENS} tokens"], content
    try:
        answer = json.loads(content or "")
    except ValueError:
        return None, ["the answer is not JSON"], content
    problems = sorted(f"{'/'.join(map(str, e.absolute_path)) or 'answer'}: {e.message}"
                      for e in Draft202012Validator(SCHEMA).iter_errors(answer))
    return (None if problems else answer), problems, content


def _count(tokens: dict[str, int], response: Any) -> None:
    usage = getattr(response, "usage", None)
    if usage is None:
        return
    details = getattr(usage, "completion_tokens_details", None)
    counts = {"calls": 1, "prompt": getattr(usage, "prompt_tokens", 0) or 0,
              "completion": getattr(usage, "completion_tokens", 0) or 0,
              "reasoning": getattr(details, "reasoning_tokens", 0) or 0}
    for key, value in counts.items():
        tokens[key] = tokens.get(key, 0) + value
