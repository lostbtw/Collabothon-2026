import functools
import io
import json
import os
import ssl
import sys
import time

import httpx
import jsonschema

SERVICE_CA = "/var/run/secrets/kubernetes.io/serviceaccount/service-ca.crt"


def setting(names, default):
    for name in names:
        if os.environ.get(name):
            return os.environ[name]
    return default


BASE_URL = setting(["ORDO_LLM_BASE_URL", "LLM_BASE_URL"], "https://gpt-oss-20b-predictor.cfo-ai.svc.cluster.local:8443/v1")
MODEL = setting(["ORDO_LLM_MODEL", "LLM_MODEL"], "gpt-oss-20b")
API_KEY = setting(["ORDO_LLM_API_KEY", "LLM_TOKEN"], "")
CA_FILE = os.environ.get("ORDO_LLM_CA_FILE", SERVICE_CA)
DOCLING_URL = setting(["ORDO_DOCLING_URL"], "http://docling-serve.cfo-ai.svc.cluster.local:5001")
DOCLING_API_KEY = setting(["ORDO_DOCLING_API_KEY"], "")

MONEY = r"^-?\d+\.\d{2}$"

BALANCE_TOOL = {
    "type": "function",
    "function": {
        "name": "get_account_balance",
        "description": "Current balance of one of the company's bank accounts.",
        "parameters": {
            "type": "object",
            "properties": {"account_id": {"type": "string", "description": "Account id, for example ACC-PLN-01."}},
            "required": ["account_id"],
            "additionalProperties": False,
        },
    },
}

BALANCE_RESULT = {
    "account_id": "ACC-PLN-01",
    "balance": {"amount": "18450.20", "currency": "PLN"},
    "as_of": "2026-11-20",
    "sample": True,
}

BALANCE_ANSWER_SCHEMA = {
    "type": "object",
    "properties": {
        "account_id": {"type": "string"},
        "amount": {"type": "string", "pattern": MONEY},
        "currency": {"type": "string", "enum": ["PLN", "EUR", "USD"]},
        "summary": {"type": "string"},
    },
    "required": ["account_id", "amount", "currency", "summary"],
    "additionalProperties": False,
}

RECEIPT_MARKDOWN = """# HURTOWNIA BIUROWA SAMPLE SP. Z O.O.
ul. Testowa 1, 00-000 Warszawa (SAMPLE)

## Faktura VAT nr FV/SAMPLE/11/2026
Data wystawienia: 2026-11-18
Nabywca: Borsuk Labs SAMPLE

| Pozycja | Ilość | Netto | VAT | Brutto |
|---|---|---|---|---|
| Papier A4, karton | 4 | 240.00 | 55.20 | 295.20 |
| Toner do drukarki | 1 | 60.00 | 13.80 | 73.80 |

Razem netto: 300.00 PLN
VAT 23%: 69.00 PLN
Razem brutto: 369.00 PLN
"""

RECEIPT_SCHEMA = {
    "type": "object",
    "properties": {
        "vendor": {"type": "string"},
        "invoice_number": {"type": "string"},
        "issue_date": {"type": "string", "pattern": r"^\d{4}-\d{2}-\d{2}$"},
        "currency": {"type": "string", "enum": ["PLN", "EUR", "USD"]},
        "net": {"type": "string", "pattern": MONEY},
        "vat": {"type": "string", "pattern": MONEY},
        "gross": {"type": "string", "pattern": MONEY},
        "vat_rate": {"type": "integer", "enum": [23, 8, 5, 0]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
    },
    "required": ["vendor", "invoice_number", "issue_date", "currency", "net", "vat", "gross", "vat_rate", "confidence"],
    "additionalProperties": False,
}

EXTRACT_SYSTEM = (
    "You read invoices and receipts for a small company's bookkeeping. "
    "Answer only with the JSON object the schema asks for. "
    "Money is a decimal string with two decimals. "
    "confidence is how sure you are that every field is right, from 0 to 1."
)

RECEIPT_IMAGE_LINES = [
    "HURTOWNIA BIUROWA SAMPLE SP. Z O.O.",
    "ul. Testowa 1, 00-000 Warszawa",
    "PARAGON FISKALNY        SAMPLE",
    "2026-11-18 12:41",
    "Papier A4 karton  4 x 60,00   240,00 A",
    "Toner             1 x 60,00    60,00 A",
    "SPRZEDAZ OPODATK. A          300,00",
    "PTU A 23,00%                  69,00",
    "SUMA PLN                     369,00",
]


@functools.cache
def llm():
    from openai import DefaultHttpx2Client, OpenAI

    verify = ssl.create_default_context(cafile=CA_FILE) if CA_FILE else True
    return OpenAI(
        base_url=BASE_URL,
        api_key=API_KEY or "missing",
        max_retries=0,
        timeout=300,
        http_client=DefaultHttpx2Client(verify=verify),
    )


def json_or_none(text):
    if not text or not text.strip():
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def schema_errors(content, schema):
    data = json_or_none(content)
    if data is None:
        return ["content is not JSON"]
    return sorted(error.message for error in jsonschema.Draft202012Validator(schema).iter_errors(data))


def reasoning_of(message):
    extra = message.model_extra or {}
    return extra.get("reasoning_content") or extra.get("reasoning")


def reasoning_is_free(reasoning):
    return bool(reasoning and reasoning.strip()) and json_or_none(reasoning) is None


def json_schema_format(name, schema):
    return {"type": "json_schema", "json_schema": {"name": name, "schema": schema, "strict": True}}


def describe(response):
    choice = response.choices[0]
    return {
        "finish_reason": choice.finish_reason,
        "content": choice.message.content,
        "reasoning": reasoning_of(choice.message),
        "tool_calls": [
            {"id": call.id, "name": call.function.name, "arguments": call.function.arguments}
            for call in choice.message.tool_calls or []
        ],
        "usage": response.usage.model_dump() if response.usage else None,
    }


def check_chat(evidence):
    evidence["models"] = [model.id for model in llm().models.list().data]
    response = llm().chat.completions.create(
        model=MODEL,
        messages=[{"role": "user", "content": "In one sentence, what does a cash-flow forecast tell a small company owner?"}],
        reasoning_effort="low",
        max_tokens=1024,
    )
    evidence["answer"] = describe(response)
    content = response.choices[0].message.content
    return MODEL in evidence["models"] and bool(content and content.strip())


def check_tools(evidence):
    messages = [
        {"role": "system", "content": "You are the finance assistant of Borsuk Labs SAMPLE. Look up account data with the tools and never guess numbers."},
        {"role": "user", "content": "What is the current balance of account ACC-PLN-01?"},
    ]
    first = llm().chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=[BALANCE_TOOL],
        tool_choice="auto",
        reasoning_effort="medium",
        max_tokens=2048,
    )
    evidence["tool_request"] = describe(first)
    message = first.choices[0].message
    calls = message.tool_calls or []
    if len(calls) != 1 or calls[0].function.name != "get_account_balance":
        evidence["tool_call_ok"] = False
        return False
    call = calls[0]
    arguments = json_or_none(call.function.arguments) or {}
    evidence["tool_call_ok"] = arguments.get("account_id") == BALANCE_RESULT["account_id"]
    messages.append({
        "role": "assistant",
        "content": message.content,
        "tool_calls": [{"id": call.id, "type": "function", "function": {"name": call.function.name, "arguments": call.function.arguments}}],
    })
    messages.append({"role": "tool", "tool_call_id": call.id, "content": json.dumps(BALANCE_RESULT)})
    second = llm().chat.completions.create(
        model=MODEL,
        messages=messages,
        tools=[BALANCE_TOOL],
        tool_choice="auto",
        reasoning_effort="medium",
        max_tokens=2048,
        response_format=json_schema_format("balance_answer", BALANCE_ANSWER_SCHEMA),
    )
    evidence["final_request"] = describe(second)
    final = second.choices[0].message
    errors = schema_errors(final.content, BALANCE_ANSWER_SCHEMA)
    answer = json_or_none(final.content)
    evidence["final_schema_errors"] = errors
    evidence["final_reasoning_free"] = reasoning_is_free(reasoning_of(final))
    evidence["final_amount_matches_tool"] = isinstance(answer, dict) and answer.get("amount") == BALANCE_RESULT["balance"]["amount"]
    return evidence["tool_call_ok"] and not errors


def structured_extraction(evidence, messages):
    response = llm().chat.completions.create(
        model=MODEL,
        messages=messages,
        reasoning_effort="low",
        max_tokens=4096,
        response_format=json_schema_format("receipt", RECEIPT_SCHEMA),
    )
    evidence["response"] = describe(response)
    message = response.choices[0].message
    errors = schema_errors(message.content, RECEIPT_SCHEMA)
    answer = json_or_none(message.content)
    evidence["schema_errors"] = errors
    evidence["reasoning_free"] = reasoning_is_free(reasoning_of(message))
    evidence["gross_matches_document"] = isinstance(answer, dict) and answer.get("gross") == "369.00"
    return not errors and evidence["reasoning_free"]


def check_schema(evidence):
    return structured_extraction(evidence, [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {"role": "user", "content": "Extract the fields from this document:\n\n" + RECEIPT_MARKDOWN},
    ])


def check_multiturn(evidence):
    return structured_extraction(evidence, [
        {"role": "system", "content": EXTRACT_SYSTEM},
        {"role": "user", "content": "I am going to send you an invoice to read."},
        {"role": "assistant", "content": "Send it and I will extract the fields."},
        {"role": "user", "content": "Here it is:\n\n" + RECEIPT_MARKDOWN},
    ])


def receipt_png():
    from PIL import Image, ImageDraw, ImageFont

    font = ImageFont.load_default(size=30)
    image = Image.new("RGB", (900, 120 + 48 * len(RECEIPT_IMAGE_LINES)), "white")
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(RECEIPT_IMAGE_LINES):
        draw.text((50, 60 + 48 * index), line, fill="black", font=font)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


def check_docling(evidence):
    headers = {"X-Api-Key": DOCLING_API_KEY} if DOCLING_API_KEY else {}
    image = receipt_png()
    with httpx.Client(base_url=DOCLING_URL, headers=headers, timeout=300) as client:
        health = client.get("/health")
        evidence["health"] = {"status_code": health.status_code, "body": health.text[:200]}
        started = time.monotonic()
        response = client.post(
            "/v1/convert/file",
            files={"files": ("receipt-sample.png", image, "image/png")},
            data={
                "to_formats": "md",
                "do_ocr": "true",
                "force_ocr": "true",
                "ocr_lang": ["pl", "en"],
                "image_export_mode": "placeholder",
            },
        )
        evidence["convert_seconds"] = round(time.monotonic() - started, 2)
    evidence["status_code"] = response.status_code
    if response.status_code != 200:
        evidence["body"] = response.text[:1000]
        return False
    body = response.json()
    markdown = (body.get("document") or {}).get("md_content") or ""
    evidence["status"] = body.get("status")
    evidence["processing_time"] = body.get("processing_time")
    evidence["errors"] = body.get("errors")
    evidence["markdown"] = markdown
    evidence["gross_found"] = "369" in markdown
    return health.status_code == 200 and body.get("status") == "success" and evidence["gross_found"]


CHECKS = {
    "chat": check_chat,
    "tools": check_tools,
    "schema": check_schema,
    "multiturn": check_multiturn,
    "docling": check_docling,
}


def main(argv):
    names = argv or list(CHECKS)
    unknown = [name for name in names if name not in CHECKS]
    if unknown:
        print(f"unknown checks: {' '.join(unknown)}; choose from: {' '.join(CHECKS)}", file=sys.stderr)
        return 2
    print(json.dumps({
        "llm_base_url": BASE_URL,
        "model": MODEL,
        "llm_api_key_set": bool(API_KEY),
        "ca_file": CA_FILE or "system trust",
        "docling_url": DOCLING_URL,
        "docling_api_key_set": bool(DOCLING_API_KEY),
    }, indent=2))
    failed = []
    for name in names:
        evidence = {}
        started = time.monotonic()
        try:
            ok = CHECKS[name](evidence)
        except Exception as error:
            ok = False
            evidence["error"] = f"{type(error).__name__}: {error}"
        print(f"\n{'PASS' if ok else 'FAIL'} {name} ({time.monotonic() - started:.1f}s)")
        print(json.dumps(evidence, indent=2, ensure_ascii=False, default=str))
        if not ok:
            failed.append(name)
    summary = f"\n{len(names) - len(failed)}/{len(names)} passed"
    print(summary + (f"; failed: {' '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
