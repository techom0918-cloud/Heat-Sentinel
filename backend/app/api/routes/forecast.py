"""Risk trajectory endpoint (Phase 7)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.config import settings
from app.models.common import ErrorResponse
from app.models.forecast import TrajectoryResponse
from app.services import forecast_service

router = APIRouter(prefix="/forecast", tags=["Forecast"])

_DESCRIPTION = """
Risk trajectory across the next few days, with each day labelled by the
method that produced it.

**The honest constraint.** The trained artifact stores `horizon_days: 3`.
It was fitted on one target — the heat category exactly three days after the
feature date. It does not predict day 1, 2, 4 or 5, and this endpoint does
not pretend otherwise.

| `method` | Meaning | Confidence |
|---|---|---|
| `OBSERVED` | Category from observed weather (today) | — |
| `NWP_DERIVED` | Category computed from the provider's numerical weather forecast, using the same Heat Index bands the model was trained against. A forecast, but not an ML one. | — |
| `ML_MODEL` | The trained model at its supported 3-day horizon | model class probability |

At the model's horizon both values exist. Both are reported —
`model_risk_level` alongside the NWP-derived value in `method_note`. Where
they disagree, that disagreement is information.

**`trend`** is computed deterministically: the mean category level of the
later half of the trajectory minus the earlier half, against a configurable
threshold. `WORSENING`, `STABLE` or `IMPROVING`.

Categories describe heat **hazard**, not health outcomes.
"""


@router.get(
    "/risk",
    response_model=TrajectoryResponse,
    responses={
        422: {"model": ErrorResponse, "description": "Invalid input."},
        502: {"model": ErrorResponse, "description": "Weather provider failure."},
        503: {"model": ErrorResponse, "description": "No trained model."},
    },
    summary="Risk trajectory over the forecast horizon",
    description=_DESCRIPTION,
)
async def risk_trajectory(
    latitude: Annotated[float, Query(ge=-90.0, le=90.0, examples=[28.6139])],
    longitude: Annotated[float, Query(ge=-180.0, le=180.0, examples=[77.2090])],
    days: Annotated[
        int,
        Query(
            ge=1,
            le=settings.FORECAST_MAX_DAYS,
            description=f"Days to return (1-{settings.FORECAST_MAX_DAYS}).",
        ),
    ] = 5,
) -> TrajectoryResponse:
    return TrajectoryResponse(
        **await forecast_service.get_trajectory(latitude, longitude, days)
    )
