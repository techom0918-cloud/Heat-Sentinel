"""Early warning & alert endpoints (Phase 11)."""

from fastapi import APIRouter

from app.core.exceptions import ExternalServiceError
from app.models.alert import AlertRequest, AlertResponse
from app.models.common import ErrorResponse
from app.services import alert_service, forecast_service, geospatial_service

router = APIRouter(prefix="/alerts", tags=["Alerts"])

_DESCRIPTION = """
Evaluates a zone's existing Phase 7 forecast trajectory and Phase 4/8
vulnerability, and decides whether an early warning is required.

> **This is DECISION SUPPORT**, not a medical prediction. It does not
> predict deaths, and `recommended_actions` are decision-support text, not
> medical instructions. Nothing is dispatched automatically -- see
> `app/services/alert_service.py` for the (unimplemented, no-API-key)
> notification adapter seam.

**Rules**, thresholds in configuration, not hidden in code:

1. Alert required once the forecast **peak** reaches `ALERT_MIN_LEVEL`
   (default `HIGH`) or above.
2. Alert required if the forecast **escalates** above today's observed
   level, even under that threshold — e.g. `MODERATE → HIGH`.
3. `priority` is raised when the zone's vulnerability (Phase 4) is high.
4. `priority` reaches `CRITICAL` only when an `EXTREME` peak and high
   vulnerability combine.

Nothing here recomputes hazard or vulnerability — both are reused from
existing services.
"""


@router.post(
    "/evaluate",
    response_model=AlertResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Unknown zone."},
        422: {"model": ErrorResponse, "description": "Invalid request."},
        502: {"model": ErrorResponse, "description": "Weather provider failure."},
        503: {"model": ErrorResponse, "description": "No trained model."},
    },
    summary="Evaluate whether a zone needs an early warning",
    description=_DESCRIPTION,
)
async def evaluate(payload: AlertRequest) -> AlertResponse:
    # Raises 404 with the available zone list if the id is unknown.
    feature = geospatial_service.get_zone(payload.zone_id)
    vulnerability = geospatial_service.zone_vulnerability(feature)

    centroid = feature["properties"].get("centroid") or [77.2090, 28.6139]
    longitude, latitude = centroid[0], centroid[1]

    trajectory = await forecast_service.get_trajectory(
        latitude, longitude, payload.days
    )
    if not trajectory.get("forecast"):
        raise ExternalServiceError(
            "No forecast days were available to evaluate for this zone.",
            details={"zone_id": payload.zone_id},
        )

    return AlertResponse(
        **alert_service.evaluate_alert(
            zone_id=payload.zone_id,
            trajectory=trajectory,
            vulnerability_level=vulnerability.vulnerability_level,
        )
    )
