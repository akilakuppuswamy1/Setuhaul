from fastapi import APIRouter

from app.api.appointments import router as appointments_router
from app.api.carriers import router as carriers_router
from app.api.conversations import router as conversations_router
from app.api.drivers import router as drivers_router
from app.api.facilities import router as facilities_router
from app.api.operations import router as operations_router
from app.api.shipments import router as shipments_router
from app.api.vehicles import router as vehicles_router

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "setuhaul"}


router.include_router(carriers_router)
router.include_router(drivers_router)
router.include_router(vehicles_router)
router.include_router(shipments_router)
router.include_router(facilities_router)
router.include_router(appointments_router)
router.include_router(operations_router)
router.include_router(conversations_router)
