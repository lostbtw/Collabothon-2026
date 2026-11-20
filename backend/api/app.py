"""The Ordo API (contracts/openapi.yaml), served under /api/v1.

Start locally: `uv run python -m backend.db setup --fixtures` then `uv run python -m backend api`.
Entity endpoints read the database through the Store, so fixtures loaded as demo data and real data written by
connectors, pipeline and finance engine are served the same way. Computations that belong to another role and do
not exist yet answer from `stand_ins.py`.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import settings
from backend.api.deps import ApiError, error_body
from backend.api.routes import bank, chat, documents, forecast, ledger, recommendations, sources, stream, system


def create_app(database_url: str | None = None) -> FastAPI:
    url = database_url or settings.database_url()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.pool = ConnectionPool(url, min_size=1, max_size=10, open=True)
        try:
            yield
        finally:
            app.state.pool.close()

    app = FastAPI(title="Ordo API", version="0.1.0", lifespan=lifespan)
    for module in (system, sources, documents, bank, ledger, forecast, recommendations, chat, stream):
        app.include_router(module.router, prefix="/api/v1")

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, exc: ApiError):
        return JSONResponse(error_body(exc.code, exc.message), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        code = "not_found" if exc.status_code == 404 else f"http_{exc.status_code}"
        return JSONResponse(error_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        return JSONResponse(error_body("invalid_request", str(exc.errors())[:500]), status_code=422)

    return app
