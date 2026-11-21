"""Sources, sync runs, raw items and the fallback upload."""
import hashlib

import psycopg
from fastapi import APIRouter, Depends, File, Form, UploadFile
from fastapi.responses import Response

from backend.api.deps import ApiError, company_id, conn, get_or_404, new_id, now_iso, store
from backend.db.events import new_event, publish
from backend.db.store import Store

router = APIRouter()

PLACEHOLDER_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" width="400" height="560" viewBox="0 0 400 560">'
    '<rect width="400" height="560" fill="#f4f4f5"/>'
    '<text x="200" y="270" font-family="sans-serif" font-size="18" text-anchor="middle" fill="#71717a">SAMPLE</text>'
    '<text x="200" y="300" font-family="sans-serif" font-size="13" text-anchor="middle" fill="#a1a1aa">'
    "original not stored on this server</text></svg>"
)


@router.get("/sources")
def list_sources(company: str = Depends(company_id), s: Store = Depends(store)):
    return {"items": s.list("source", company_id=company)}


@router.post("/sources/{id}/sync", status_code=202)
def sync_now(id: str, s: Store = Depends(store)):
    source = get_or_404(s, "source", id)
    latest = s.list("sync_run", source_id=id, limit=1)
    if latest and latest[0]["status"] == "running":
        raise ApiError(409, "conflict", f"A run of {id} is already in progress")
    run = {
        "id": new_id("run"),
        "source_id": id,
        "connector": source["connector"],
        "trigger": "manual",
        "started_at": now_iso(),
        "status": "running",
    }
    s.add("sync_run", run, company_id=source["company_id"])
    return run


@router.get("/sync-runs")
def list_sync_runs(source_id: str | None = None, limit: int = 20, s: Store = Depends(store)):
    where = {"source_id": source_id} if source_id else {}
    return {"items": s.list("sync_run", limit=limit, **where)}


@router.get("/raw-items/{id}")
def get_raw_item(id: str, s: Store = Depends(store)):
    return get_or_404(s, "raw_item", id)


@router.get("/raw-items/{id}/content")
def raw_item_content(id: str, s: Store = Depends(store), c: psycopg.Connection = Depends(conn)):
    get_or_404(s, "raw_item", id)
    row = c.execute("select content_type, bytes from raw_item_content where raw_item_id = %s", (id,)).fetchone()
    if row:
        return Response(content=bytes(row[1]), media_type=row[0])
    return Response(content=PLACEHOLDER_SVG, media_type="image/svg+xml")


@router.post("/uploads", status_code=201)
async def upload(
    file: UploadFile = File(...),
    submitted_by: str | None = Form(None),
    company: str = Depends(company_id),
    c: psycopg.Connection = Depends(conn),
):
    data = await file.read()
    digest = hashlib.sha256(data).hexdigest()
    item = {
        "id": new_id("raw"),
        "source_id": "src_upload",
        "sync_run_id": new_id("run"),
        "kind": "upload",
        "external_id": file.filename or "upload",
        "idempotency_key": hashlib.sha256(f"upload:src_upload:{digest}".encode()).hexdigest(),
        "fetched_at": now_iso(),
        "received_at": now_iso(),
        "content_type": file.content_type or "application/octet-stream",
        "sha256": digest,
        "size_bytes": len(data),
        "metadata": {"filename": file.filename, "submitted_by": submitted_by},
        "processing_status": "queued",
    }
    s = Store(c)
    if not s.add("raw_item", item, company_id=company):
        return s.list("raw_item", idempotency_key=item["idempotency_key"])[0]
    c.execute(
        "insert into raw_item_content (raw_item_id, content_type, bytes) values (%s, %s, %s)",
        (item["id"], item["content_type"], data),
    )
    publish(c, new_event("raw_item.received", company,
                         {"raw_item_id": item["id"], "kind": "upload", "source_id": "src_upload"},
                         producer="api", correlation_id=item["id"]))
    return item
