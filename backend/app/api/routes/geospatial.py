"""Hyperlocal zone endpoints (Phase 8)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.models.common import ErrorResponse
from app.models.geospatial import ZoneRiskCollection
from app.services import geospatial_service

router = APIRouter(prefix="/zones", tags=["Zones"])

_DESCRIPTION = """
Zone-level risk as a GeoJSON `FeatureCollection`, ready for any mapping
library.

> **The bundled dataset is SYNTHETIC.** The polygons are arbitrary
> rectangular cells over Delhi, not real administrative, ward or census
> boundaries, and their demographics are invented. Replace with a real
> boundary file and real census, occupational, healthcare-access and
> NCRB/IMD mortality data before any operational use.

**Four things are kept separate**, because conflating them is how a heat
dashboard misleads:

1. `heat_hazard` — how hot it is
2. `vulnerability` — how badly this population copes (Phase 4)
3. `human_risk` — the two combined (Phase 5, existing weights)
4. `priority` — what to act on first

**Hazard is city-level, and the response says so.** The provider's global
model resolves to roughly 11 km, so every zone here falls inside one grid
cell. Fetching weather per zone would return identical numbers and imply a
spatial resolution that does not exist. What varies between zones is
**vulnerability** — which is precisely the argument for a heat-health system
over a weather app.

`priority` comes from a prototype matrix combining risk level with
vulnerability level, so a moderately hot but highly vulnerable zone is not
out-ranked by a hot but resilient one. It is not a published prioritisation
standard.

Features are returned sorted by `human_risk`, descending.
"""


@router.get(
    "/risk",
    response_model=ZoneRiskCollection,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid coordinates."},
        502: {"model": ErrorResponse, "description": "Weather provider failure."},
        503: {"model": ErrorResponse, "description": "Zone dataset missing."},
    },
    summary="Zone-level risk as GeoJSON",
    description=_DESCRIPTION,
)
async def zone_risk(
    latitude: Annotated[
        float | None,
        Query(
            ge=-90.0,
            le=90.0,
            description="Hazard sample point. Defaults to the first zone's centroid.",
        ),
    ] = None,
    longitude: Annotated[
        float | None, Query(ge=-180.0, le=180.0)
    ] = None,
) -> ZoneRiskCollection:
    return ZoneRiskCollection(
        **await geospatial_service.get_zone_risk(latitude, longitude)
    )
