import copy
import json
from datetime import date
from types import SimpleNamespace

import httpx
import pytest

from backend.pipeline.extract import ExtractionError, docling, extract_document, model, run
from backend.pipeline.extract.tests.test_extract_document import HERO, schema_errors

TODAY = date(2026, 11, 21)
HERO_MARKDOWN = "ElektroMarkt Polska S.A. (SAMPLE)\nNIP 999-000-00-43\nSUMA PLN 1299,00\nPTU A 23% 242,90"
JPEG = b"\xff\xd8\xff\xe0 sample photo"
PDF = b"%PDF-1.7 sample"


class FakeDocling:
    def __init__(self, status_code=200, status="success", markdown=HERO_MARKDOWN, error=None):
        self.requests = []
        self.status_code, self.status, self.markdown, self.error = status_code, status, markdown, error

    def handler(self, request):
        self.requests.append(request)
        if self.error:
            raise self.error
        body = {"document": {"md_content": self.markdown}, "status": self.status, "errors": [],
                "processing_time": 1.0, "timings": {}}
        return httpx.Response(self.status_code, json=body)

    def client(self):
        return httpx.Client(base_url="http://docling.test", transport=httpx.MockTransport(self.handler))

    def form(self, index=0):
        return self.requests[index].read()


class FakeModel:
    def __init__(self, *contents, finish_reasons=None, error=None, usage=None):
        self.usage = usage
        self.contents = list(contents)
        self.finish_reasons = list(finish_reasons or ["stop"] * len(contents))
        self.calls = []
        self.error = error
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        self.calls.append(copy.deepcopy(kwargs))
        if self.error:
            raise self.error
        content = self.contents.pop(0)
        if not isinstance(content, str):
            content = json.dumps(content)
        message = SimpleNamespace(content=content)
        return SimpleNamespace(choices=[SimpleNamespace(message=message, finish_reason=self.finish_reasons.pop(0))],
                               usage=self.usage)


def extract(data=JPEG, content_type="image/jpeg", docling_fake=None, model_fake=None):
    docling_fake = docling_fake or FakeDocling()
    model_fake = model_fake or FakeModel(HERO)
    return extract_document(data, content_type, today=TODAY, docling_client=docling_fake.client(),
                            llm_client=model_fake)


def field_value(form, name):
    marker = f'name="{name}"\r\n\r\n'.encode()
    return [part.split(b"\r\n", 1)[0].decode() for part in form.split(marker)[1:]]


def test_photo_becomes_a_schema_valid_document():
    document = extract()
    assert schema_errors(document) == []
    assert document["totals"]["gross"] == {"amount": "1299.00", "currency": "PLN"}
    assert document["extraction"]["method"] == "docling_llm"
    assert document["status"] == "extracted"


def test_photo_is_sent_with_forced_ocr_in_polish_and_english():
    fake = FakeDocling()
    extract(docling_fake=fake)
    form = fake.form()
    assert fake.requests[0].url.path == "/v1/convert/file"
    assert field_value(form, "force_ocr") == ["true"]
    assert field_value(form, "do_ocr") == ["true"]
    assert field_value(form, "ocr_lang") == ["pl", "en"]
    assert field_value(form, "to_formats") == ["md"]
    assert b'filename="photo.jpg"' in form
    assert b"Content-Type: image/jpeg" in form


def test_pdf_keeps_its_text_layer():
    fake = FakeDocling()
    extract(PDF, "application/pdf", docling_fake=fake)
    form = fake.form()
    assert field_value(form, "force_ocr") == ["false"]
    assert field_value(form, "do_ocr") == ["true"]
    assert b'filename="document.pdf"' in form


@pytest.mark.parametrize("content_type", ["image/jpeg; name=x.jpg", "IMAGE/JPG", "image/png", "image/webp",
                                          "image/tiff"])
def test_supported_image_types(content_type):
    assert extract(content_type=content_type)["status"] == "extracted"


@pytest.mark.parametrize("content_type", ["image/heic", "text/plain", "", None])
def test_unsupported_types_raise_before_any_call(content_type):
    fake = FakeDocling()
    with pytest.raises(ExtractionError, match="unsupported content type"):
        extract(content_type=content_type, docling_fake=fake)
    assert fake.requests == []


def test_docling_error_status_raises():
    with pytest.raises(ExtractionError, match="answered 500"):
        extract(docling_fake=FakeDocling(status_code=500))


@pytest.mark.parametrize("status", ["failure", "skipped"])
def test_failed_conversion_raises(status):
    with pytest.raises(ExtractionError, match=f"conversion {status}"):
        extract(docling_fake=FakeDocling(status=status))


def test_unreachable_docling_raises():
    with pytest.raises(ExtractionError, match="unreachable"):
        extract(docling_fake=FakeDocling(error=httpx.ConnectError("refused")))


def test_partial_conversion_carries_a_warning():
    document = extract(docling_fake=FakeDocling(status="partial_success"))
    assert "The document was only partly converted" in document["extraction"]["warnings"]


def test_model_gets_a_json_schema_with_low_reasoning():
    fake = FakeModel(HERO)
    extract(model_fake=fake)
    call = fake.calls[0]
    assert call["response_format"]["type"] == "json_schema"
    assert call["response_format"]["json_schema"]["schema"] == model.SCHEMA
    assert call["reasoning_effort"] == "low"
    assert call["temperature"] == 0
    assert call["max_tokens"] == 4096
    assert HERO_MARKDOWN in call["messages"][-1]["content"]


def test_hero_answer_matches_the_model_schema():
    from jsonschema import Draft202012Validator

    assert list(Draft202012Validator(model.SCHEMA).iter_errors(HERO)) == []


def test_invalid_answer_gets_one_corrective_turn():
    fake = FakeModel("not json", HERO)
    document = extract(model_fake=fake)
    assert len(fake.calls) == 2
    assert fake.calls[1]["messages"][-2] == {"role": "assistant", "content": "not json"}
    assert document["status"] == "extracted"


def test_answer_cut_by_the_token_limit_is_retried():
    fake = FakeModel('{"doc_type": "rec', HERO, finish_reasons=["length", "stop"])
    extract(model_fake=fake)
    assert len(fake.calls) == 2


def test_answer_breaking_the_schema_twice_raises():
    broken = {**HERO, "gross": "1299"}
    with pytest.raises(ExtractionError, match="does not match the schema"):
        extract(model_fake=FakeModel(broken, broken))


def test_model_call_failure_raises():
    with pytest.raises(ExtractionError, match="model call failed"):
        extract(model_fake=FakeModel(error=TimeoutError("read timed out")))


def test_long_markdown_is_cut_with_a_warning():
    fake = FakeModel(HERO)
    document = extract(docling_fake=FakeDocling(markdown="x" * 30000), model_fake=fake)
    assert "The document text was cut at 24000 characters" in document["extraction"]["warnings"]
    assert "x" * 24001 not in fake.calls[0]["messages"][-1]["content"]


def test_run_reports_the_time_of_each_step():
    result = run(JPEG, "image/jpeg", today=TODAY, docling_client=FakeDocling().client(), llm_client=FakeModel(HERO))
    assert result.docling_seconds >= 0
    assert result.model_seconds >= 0
    assert result.markdown == HERO_MARKDOWN
    assert result.document["status"] == "extracted"


def test_default_docling_client_uses_the_environment(monkeypatch):
    monkeypatch.setenv("ORDO_DOCLING_URL", "http://docling.example:5001")
    monkeypatch.setenv("ORDO_DOCLING_API_KEY", "sample-key")
    monkeypatch.setenv("ORDO_DOCLING_TIMEOUT_SECONDS", "45")
    client = docling.default_client()
    assert str(client.base_url) == "http://docling.example:5001"
    assert client.headers["X-Api-Key"] == "sample-key"
    assert client.timeout.read == 45


def test_default_docling_url_is_the_in_cluster_service(monkeypatch):
    monkeypatch.delenv("ORDO_DOCLING_URL", raising=False)
    monkeypatch.delenv("ORDO_DOCLING_API_KEY", raising=False)
    client = docling.default_client()
    assert str(client.base_url).startswith("http://docling-serve.cfo-ai.svc.cluster.local:5001")
    assert "X-Api-Key" not in client.headers


def test_ocr_engine_and_image_scale_can_be_tuned(monkeypatch):
    monkeypatch.setenv("ORDO_DOCLING_OCR_ENGINE", "rapidocr")
    monkeypatch.setenv("ORDO_DOCLING_IMAGES_SCALE", "1.0")
    fake = FakeDocling()
    extract(docling_fake=fake)
    assert field_value(fake.form(), "ocr_engine") == ["rapidocr"]
    assert field_value(fake.form(), "images_scale") == ["1.0"]


def test_photo_uses_rapidocr_by_default(monkeypatch):
    monkeypatch.delenv("ORDO_DOCLING_OCR_ENGINE", raising=False)
    fake = FakeDocling()
    extract(docling_fake=fake)
    assert field_value(fake.form(), "ocr_engine") == ["rapidocr"]


def test_token_usage_is_summed_over_the_corrective_turn():
    usage = SimpleNamespace(prompt_tokens=900, completion_tokens=400,
                            completion_tokens_details=SimpleNamespace(reasoning_tokens=120))
    fake = FakeModel("not json", HERO, usage=usage)
    result = run(JPEG, "image/jpeg", today=TODAY, docling_client=FakeDocling().client(), llm_client=fake)
    assert result.model_tokens == {"calls": 2, "prompt": 1800, "completion": 800, "reasoning": 240}


def test_missing_usage_leaves_tokens_empty():
    result = run(JPEG, "image/jpeg", today=TODAY, docling_client=FakeDocling().client(), llm_client=FakeModel(HERO))
    assert result.model_tokens == {}
