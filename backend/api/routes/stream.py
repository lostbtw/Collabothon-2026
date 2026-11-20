"""GET /events/stream: Server-Sent Events, each message's data an Event envelope.

On connect it replays contracts/fixtures/event.json (so live toasts work before the pipeline exists; switch off
with ORDO_SSE_REPLAY_FIXTURES=0), then relays every new outbox event of the company as it is written.
"""
import json
import time
from collections.abc import Iterator
from pathlib import Path

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse

from backend import settings
from backend.api.deps import company_id
from backend.db.events import events_after

router = APIRouter()

FIXTURE_EVENTS = Path(__file__).resolve().parents[3] / "contracts" / "fixtures" / "event.json"
POLL_SECONDS = 1.0
KEEPALIVE_SECONDS = 15.0


def _message(event: dict) -> str:
    return f"id: {event['id']}\nevent: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


@router.get("/events/stream")
def stream(request: Request, company: str = Depends(company_id),
           max_events: int | None = Query(None, description="Close after this many events (tests, debugging)")):
    pool = request.app.state.pool

    def generate() -> Iterator[str]:
        sent = 0
        if settings.sse_replay_fixtures():
            for event in json.loads(FIXTURE_EVENTS.read_text(encoding="utf-8")):
                if event["company_id"] != company:
                    continue
                yield _message(event)
                sent += 1
                if max_events is not None and sent >= max_events:
                    return
        with pool.connection() as c:
            last = c.execute("select coalesce(max(seq), 0) from outbox").fetchone()[0]
        idle = 0.0
        while True:
            with pool.connection() as c:
                batch = events_after(c, last, company)
            for seq, event in batch:
                last = seq
                yield _message(event)
                sent += 1
                if max_events is not None and sent >= max_events:
                    return
            if not batch:
                time.sleep(POLL_SECONDS)
                idle += POLL_SECONDS
                if idle >= KEEPALIVE_SECONDS:
                    idle = 0.0
                    yield ": keepalive\n\n"
            else:
                idle = 0.0

    return StreamingResponse(generate(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
