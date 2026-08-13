from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.router import router
from app.core.exceptions import ConflictError, NotFoundError, SetuHaulError

app = FastAPI(
    title="SetuHaul",
    version="0.1.0",
    description=(
        "Deterministic logistics and warehouse appointment coordination APIs. "
        "Step 6 adds concurrency-safe resource allocation. "
        "Step 7 adds controlled proposals with revalidation and confirmation."
    ),
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


app.include_router(router)
