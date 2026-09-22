"""Aggregates every versioned router into a single `api_router`.

Each new phase adds exactly two lines here: an import and an include_router
call. main.py never changes again.
"""

from fastapi import APIRouter

from app.api.routes import (
    alerts,
    auth,
    forecast,
    geospatial,
    grid,
    health,
    health_data,
    heat_index,
    intervention,
    personalization,
    risk,
    thermal,
    vulnerability,
    weather,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(weather.router)
api_router.include_router(thermal.router)
api_router.include_router(vulnerability.router)
api_router.include_router(risk.router)
api_router.include_router(forecast.router)
api_router.include_router(geospatial.router)
api_router.include_router(heat_index.router)
api_router.include_router(grid.router)
api_router.include_router(intervention.router)
api_router.include_router(alerts.router)
api_router.include_router(health_data.router)
api_router.include_router(personalization.router)
api_router.include_router(auth.router)

__all__ = ["api_router"]
