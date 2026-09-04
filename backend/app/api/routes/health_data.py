"""Health / mortality data integration & validation endpoints (Phase 12)."""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.config import settings
from app.models.common import ErrorResponse
from app.models.health_data import HealthDataResponse, ValidationResponse
from app.services import health_data_service

router = APIRouter(prefix="/health-data", tags=["Health Data"])

_DATA_DESCRIPTION = """
Historical, government-reported heat-wave mortality observations, loaded
from `backend/data/health/`.

> This is **DATA INTEGRATION**, not a prediction. Nothing here retrains or
> touches the ML model, and no observation is fabricated: a row with a
> value that was not reported is excluded from `observations` and counted
> under `missing_value_rows`, never coerced to zero.

Each observation carries its original `source` string, unmodified, and a
`data_status` of `GOVERNMENT_REPORTED` for the bundled dataset. Filter by
`year` and/or `state`.
"""

_VALIDATION_DESCRIPTION = """
A descriptive summary of the observed mortality data: yearly totals,
top regions by reported deaths, and a count of "high-risk" state-years
(reported deaths at or above `high_risk_threshold`).

> **Only what the data supports.** This repository has no historical
> model-prediction series matched to this dataset's years and states, so
> this endpoint does **not** compute a confusion matrix, probability of
> detection, precision/recall, or a correlation against model output —
> doing so would mean fabricating the missing side of the comparison.
> `notes` says this explicitly. `health_data_service
> .compare_predictions_to_observations` implements that comparison in
> full for the day a real matched prediction series exists.

Correlation is never presented as causation, and results never claim a
mortality reduction.
"""


@router.get(
    "",
    response_model=HealthDataResponse,
    responses={503: {"model": ErrorResponse, "description": "Dataset unavailable."}},
    summary="Historical heat-wave mortality observations",
    description=_DATA_DESCRIPTION,
)
async def health_data(
    year: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    state: Annotated[str | None, Query(min_length=1)] = None,
) -> HealthDataResponse:
    dataset = health_data_service.load_health_dataset()
    observations = health_data_service.list_observations(year=year, state=state)

    return HealthDataResponse(
        data_status="GOVERNMENT_REPORTED",
        source_file=dataset["source_file"],
        records_returned=len(observations),
        records_loaded_total=dataset["records_loaded_total"],
        rejected_rows=dataset["rejected_rows"],
        missing_value_rows=dataset["missing_value_rows"],
        observations=observations,
        notes=[
            "Real government-reported data (see each observation's `source`"
            " field). Not a synthetic or demo dataset.",
            "Annual, state/UT-level counts only -- no district-level, daily,"
            " or per-event granularity is available in this repository.",
        ],
    )


@router.get(
    "/validation",
    response_model=ValidationResponse,
    responses={503: {"model": ErrorResponse, "description": "Dataset unavailable."}},
    summary="Descriptive summary of observed mortality data",
    description=_VALIDATION_DESCRIPTION,
)
async def health_data_validation(
    year_from: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    year_to: Annotated[int | None, Query(ge=1900, le=2100)] = None,
    state: Annotated[str | None, Query(min_length=1)] = None,
    high_risk_threshold: Annotated[
        int | None,
        Query(ge=0, description="Overrides HEALTH_HIGH_RISK_DEATH_THRESHOLD."),
    ] = None,
) -> ValidationResponse:
    observations = health_data_service.list_observations(state=state)
    if year_from is not None:
        observations = [o for o in observations if o["year"] >= year_from]
    if year_to is not None:
        observations = [o for o in observations if o["year"] <= year_to]

    threshold = (
        high_risk_threshold
        if high_risk_threshold is not None
        else settings.HEALTH_HIGH_RISK_DEATH_THRESHOLD
    )
    return ValidationResponse(
        **health_data_service.summarise(
            observations=observations, high_risk_threshold=threshold
        )
    )
