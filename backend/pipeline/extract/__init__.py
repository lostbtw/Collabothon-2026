import hashlib
from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from backend import settings, tracing

from . import docling, model
from .document import build_document
from .errors import ExtractionError

__all__ = ["ExtractionError", "Extraction", "extract_document", "run"]


@dataclass(frozen=True)
class Extraction:
    document: dict[str, Any]
    docling_seconds: float
    model_seconds: float
    markdown: str
    model_tokens: dict[str, int]


def run(data: bytes, content_type: str, *, today: date | None = None,
        docling_client: httpx.Client | None = None, llm_client: Any = None) -> Extraction:
    inputs = {"content_type": content_type, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    with tracing.span("extract_document", inputs) as root:
        with tracing.span("docling.convert", {"content_type": content_type}) as step:
            conversion = docling.convert(data, content_type, client=docling_client)
            tracing.outputs(step, {"markdown": conversion.markdown, "seconds": round(conversion.seconds, 2),
                                   "warnings": conversion.warnings})
        reading = model.read(conversion.markdown, client=llm_client)
        with tracing.span("build_document") as step:
            document = build_document(reading.answer, model=settings.llm_model(), today=today,
                                      warnings=[*conversion.warnings, *reading.warnings])
            extraction = document["extraction"]
            tracing.outputs(step, {"status": document["status"], "confidence": extraction["confidence"],
                                   "warnings": extraction["warnings"], "flags": document["flags"]})
        extraction["trace_id"] = tracing.trace_id()
        tracing.outputs(root, {"status": document["status"], "confidence": extraction["confidence"],
                               "gross": document["totals"]["gross"], "docling_seconds": round(conversion.seconds, 2),
                               "model_seconds": round(reading.seconds, 2), "model_tokens": reading.tokens})
    return Extraction(document=document, docling_seconds=conversion.seconds, model_seconds=reading.seconds,
                      markdown=conversion.markdown, model_tokens=reading.tokens)


def extract_document(data: bytes, content_type: str, *, today: date | None = None,
                     docling_client: httpx.Client | None = None, llm_client: Any = None) -> dict[str, Any]:
    return run(data, content_type, today=today, docling_client=docling_client, llm_client=llm_client).document
