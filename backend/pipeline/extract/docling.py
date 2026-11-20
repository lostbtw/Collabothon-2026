import os
import time
from dataclasses import dataclass, field

import httpx

from .errors import ExtractionError

DEFAULT_URL = "http://docling-serve.cfo-ai.svc.cluster.local:5001"
PDF = "application/pdf"
IMAGES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/pjpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/tiff": "tiff",
    "image/tif": "tiff",
}
OCR_LANGS = ["pl", "en"]


@dataclass(frozen=True)
class Conversion:
    markdown: str
    seconds: float
    warnings: list[str] = field(default_factory=list)


def media_type(content_type: str | None) -> str:
    kind = (content_type or "").split(";", 1)[0].strip().lower()
    if kind != PDF and kind not in IMAGES:
        raise ExtractionError(f"unsupported content type: {content_type!r}")
    return kind


def options(kind: str) -> dict[str, str | list[str]]:
    form: dict[str, str | list[str]] = {
        "to_formats": "md",
        "do_ocr": "true",
        "force_ocr": "false" if kind == PDF else "true",
        "ocr_engine": os.environ.get("ORDO_DOCLING_OCR_ENGINE", "easyocr"),
        "ocr_lang": OCR_LANGS,
        "table_mode": "fast",
        "include_images": "false",
        "image_export_mode": "placeholder",
    }
    if os.environ.get("ORDO_DOCLING_IMAGES_SCALE"):
        form["images_scale"] = os.environ["ORDO_DOCLING_IMAGES_SCALE"]
    return form


def default_client() -> httpx.Client:
    key = os.environ.get("ORDO_DOCLING_API_KEY")
    return httpx.Client(base_url=os.environ.get("ORDO_DOCLING_URL") or DEFAULT_URL,
                        headers={"X-Api-Key": key} if key else {},
                        timeout=float(os.environ.get("ORDO_DOCLING_TIMEOUT_SECONDS", "60")))


def convert(data: bytes, content_type: str, *, client: httpx.Client | None = None) -> Conversion:
    kind = media_type(content_type)
    filename = "document.pdf" if kind == PDF else f"photo.{IMAGES[kind]}"
    owned = client is None
    client = client or default_client()
    started = time.monotonic()
    try:
        response = client.post("/v1/convert/file", files={"files": (filename, data, kind)}, data=options(kind))
    except httpx.HTTPError as error:
        raise ExtractionError(f"docling-serve unreachable: {type(error).__name__}: {error}") from error
    finally:
        if owned:
            client.close()
    seconds = time.monotonic() - started
    if response.status_code != 200:
        raise ExtractionError(f"docling-serve answered {response.status_code}: {response.text[:300]}")
    try:
        body = response.json()
    except ValueError as error:
        raise ExtractionError("docling-serve answered with something that is not JSON") from error
    status = body.get("status")
    if status not in ("success", "partial_success"):
        raise ExtractionError(f"docling-serve conversion {status}: {body.get('errors')}")
    warnings = ["The document was only partly converted"] if status == "partial_success" else []
    markdown = (body.get("document") or {}).get("md_content") or ""
    return Conversion(markdown=markdown, seconds=seconds, warnings=warnings)
