from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import router
from app.core.config import settings
from app.core.exceptions import ConflictError, NotFoundError, SetuHaulError
from app.core.startup import apply_schema_if_needed

logger = logging.getLogger("setuhaul")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    apply_schema_if_needed()
    yield


app = FastAPI(
    title="SetuHaul",
    version="0.1.0",
    description=(
        "Deterministic logistics and warehouse appointment coordination APIs. "
        "Step 6 adds concurrency-safe resource allocation. "
        "Step 7 adds controlled proposals with revalidation and confirmation. "
        "Step 8 adds conversational AI that invokes existing deterministic services. "
        "Step 9 adds an optional read-only facility scheduling ranking engine."
    ),
    lifespan=lifespan,
)


@app.exception_handler(NotFoundError)
async def not_found_handler(_request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(ConflictError)
async def conflict_error_handler(_request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(SetuHaulError)
async def setuhaul_error_handler(_request: Request, exc: SetuHaulError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, (StarletteHTTPException, RequestValidationError)):
        raise exc
    correlation_id = request.headers.get("x-request-id") or request.headers.get("x-correlation-id")
    logger.exception(
        "Unhandled error method=%s path=%s correlation_id=%s type=%s",
        request.method,
        request.url.path,
        correlation_id,
        type(exc).__name__,
    )
    return JSONResponse(status_code=500, content={"detail": "Internal Server Error"})


_cors_origins = [origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins or ["http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
