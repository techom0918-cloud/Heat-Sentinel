"""Health / liveness endpoints."""

import time

from fastapi import APIRouter

from app.core.config import settings
from app.models.common import HealthDetailsResponse, HealthResponse

router = APIRouter(prefix="/health", tags=["Health"])

# Captured at import time; used to report process uptime.
_STARTED_AT = time.monotonic()


@router.get(
    "",
    response_model=HealthResponse,
    summary="Liveness check",
    description="Returns 'healthy' whenever the API process is serving traffic.",
)
async def health() -> HealthResponse:
    return HealthResponse(status="healthy")


@router.get(
    "/details",
    response_model=HealthDetailsResponse,
    summary="Detailed health check",
    description=(
        "Extended health payload with build and runtime metadata. Useful for "
        "deployment checks and for the status widget on the React dashboard."
    ),
)
async def health_details() -> HealthDetailsResponse:
    return HealthDetailsResponse(
        status="healthy",
        service=settings.APP_NAME,
        version=settings.APP_VERSION,
        api_version=settings.API_V1_PREFIX.strip("/").split("/")[-1],
        debug=settings.DEBUG,
        uptime_seconds=round(time.monotonic() - _STARTED_AT, 3),
    )
