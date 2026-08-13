from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.router import router
from app.core.exceptions import NotFoundError, SetuHaulError

app = FastAPI(
    title="SetuHaul",
    version="0.1.0",
    description=(
        "Deterministic logistics and warehouse appointment coordination APIs. "
        "Step 3 exposes business data retrieval only — no operational decision logic."
    ),
)


@app.exception_handler(NotFoundError)
async def not_found_handler(_request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(SetuHaulError)
async def setuhaul_error_handler(_request: Request, exc: SetuHaulError) -> JSONResponse:
    return JSONResponse(status_code=400, content={"detail": str(exc)})


app.include_router(router)
