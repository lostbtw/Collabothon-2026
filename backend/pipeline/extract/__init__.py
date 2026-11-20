from dataclasses import dataclass
from datetime import date
from typing import Any

import httpx

from backend import settings

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


def run(data: bytes, content_type: str, *, today: date | None = None,
        docling_client: httpx.Client | None = None, llm_client: Any = None) -> Extraction:
    conversion = docling.convert(data, content_type, client=docling_client)
    reading = model.read(conversion.markdown, client=llm_client)
    document = build_document(reading.answer, model=settings.llm_model(), today=today,
                              warnings=[*conversion.warnings, *reading.warnings])
    return Extraction(document=document, docling_seconds=conversion.seconds, model_seconds=reading.seconds,
                      markdown=conversion.markdown)


def extract_document(data: bytes, content_type: str, *, today: date | None = None,
                     docling_client: httpx.Client | None = None, llm_client: Any = None) -> dict[str, Any]:
    return run(data, content_type, today=today, docling_client=docling_client, llm_client=llm_client).document
