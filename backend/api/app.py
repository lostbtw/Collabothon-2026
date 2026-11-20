"""The Ordo API (contracts/openapi.yaml), served under /api/v1.

Start locally: `uv run python -m backend api` (needs ORDO_DATABASE_URL; `python -m backend.db setup` first).
"""
from collections.abc import Iterator
from contextlib import asynccontextmanager

import psycopg
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from psycopg_pool import ConnectionPool
from starlette.exceptions import HTTPException as StarletteHTTPException

from backend import settings
from backend.db.seed import companies


class ApiError(Exception):
    """Raise to answer with the standard error shape {"error": {"code", "message"}}."""

    def __init__(self, status: int, code: str, message: str):
        self.status, self.code, self.message = status, code, message


def not_found(kind: str, id: str) -> ApiError:
    return ApiError(404, "not_found", f"No {kind} with id {id!r}")


def error_body(code: str, message: str) -> dict:
    return {"error": {"code": code, "message": message}}


def conn(request: Request) -> Iterator[psycopg.Connection]:
    with request.app.state.pool.connection() as c:
        yield c


router = APIRouter(prefix="/api/v1")


@router.get("/companies")
def list_companies(c: psycopg.Connection = Depends(conn)):
    return {"items": companies(c)}


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
    app.include_router(router)

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
