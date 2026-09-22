"""Phase 10 -- 300m spatial risk endpoint.

A NEW endpoint, additive: `/zones/risk` (existing, synthetic demo zones)
is untouched. This serves the REAL 300m NCR grid's precomputed predictions.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from app.models.common import ErrorResponse
from app.models.heat_index import GridRiskResponse
from app.services import grid_risk_service

router = APIRouter(prefix="/grid", tags=["300m Grid Risk"])

_DESCRIPTION = """
Heat Index category for 300m NCR grid cells, from a precomputed batch
prediction (`ml/predict_grid_300m.py`) -- this endpoint never runs model
inference per request and never returns all 618,373 cells at once.

**Not live weather.** Each cell borrows weather from its nearest of 118
weather points (~10-25 km apart); `heat_index_source_weather_point` and
`nearest_weather_distance_km` say which one and how far. `geometry_available`
is `false` -- this returns cell centroids, not polygons.

Provide all four bbox parameters together, or none (whole grid, capped).
Results beyond the cap are dropped; `truncated` says so.
"""


@router.get(
    "/risk",
    response_model=GridRiskResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Incomplete bbox."},
        503: {"model": ErrorResponse, "description": "Batch predictions not generated yet."},
    },
    summary="300m grid Heat Index risk (precomputed, bbox-filterable)",
    description=_DESCRIPTION,
)
async def grid_risk(
    min_lat: Annotated[float | None, Query(ge=-90.0, le=90.0)] = None,
    max_lat: Annotated[float | None, Query(ge=-90.0, le=90.0)] = None,
    min_lon: Annotated[float | None, Query(ge=-180.0, le=180.0)] = None,
    max_lon: Annotated[float | None, Query(ge=-180.0, le=180.0)] = None,
) -> GridRiskResponse:
    return GridRiskResponse(
        **grid_risk_service.get_grid_risk(min_lat, max_lat, min_lon, max_lon)
    )
