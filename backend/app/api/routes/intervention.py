"""Heat action simulator endpoints (Phase 9) and AI action optimizer (Phase 10)."""

from fastapi import APIRouter

from app.core.config import settings
from app.core.exceptions import ExternalServiceError
from app.models.common import ErrorResponse
from app.models.intervention import (
    InterventionCatalogue,
    InterventionCatalogueEntry,
    SimulationRequest,
    SimulationResponse,
)
from app.models.optimizer import OptimizerRequest, OptimizerResponse
from app.services import (
    geospatial_service,
    intervention_service,
    optimizer_service,
    thermal_service,
    weather_service,
)

router = APIRouter(prefix="/interventions", tags=["Interventions"])

_DESCRIPTION = """
Simulates the effect of heat actions on a zone's modelled risk.

> **This is a MODELLED SCENARIO.** It reports an estimated change in
> HeatSentinal's own risk score under explicit assumptions. It does **not**
> estimate deaths prevented, mortality reduction, or any medical outcome.
> The effect sizes are uncalibrated prototype assumptions — this repository
> contains no intervention evaluation data.

**How effects apply.** Each intervention acts on one channel:

| Channel | Interventions | Meaning |
|---|---|---|
| `VULNERABILITY` | cooling centres, water distribution | how badly the population copes |
| `EXPOSURE` | work-hour shift, shade, public alerts | how much heat load is taken on |

`effect = max_effect × coverage`. Multiple interventions on the same channel
combine **multiplicatively** — `∏(1 − effect)` — so stacking yields
diminishing returns and can never exceed a total reduction. An additive
model would let four measures sum past 100%.

Both baseline and simulated scores come from the same Phase 5 risk engine,
so they are directly comparable. Nothing retrains or touches the ML model.
"""


@router.post(
    "/simulate",
    response_model=SimulationResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Unknown zone."},
        422: {"model": ErrorResponse, "description": "Invalid intervention."},
        502: {"model": ErrorResponse, "description": "Weather provider failure."},
    },
    summary="Simulate heat interventions for a zone",
    description=_DESCRIPTION,
)
async def simulate(payload: SimulationRequest) -> SimulationResponse:
    weather_kwargs = await _zone_weather_kwargs(payload.zone_id)

    return SimulationResponse(
        **intervention_service.simulate(
            **weather_kwargs,
            interventions=[i.model_dump() for i in payload.interventions],
            zone_id=payload.zone_id,
        )
    )


async def _zone_weather_kwargs(zone_id: str) -> dict:
    """Current thermal + vulnerability inputs for one zone.

    Shared by /simulate and /optimize so both feed the same Phase 5/9 inputs
    from the same fetch. Raises 404 (unknown zone) or 502 (no humidity from
    the weather provider) via the standard exception handlers.
    """
    # Raises 404 with the available zone list if the id is unknown.
    feature = geospatial_service.get_zone(zone_id)
    vulnerability = geospatial_service.zone_vulnerability(feature)

    centroid = feature["properties"].get("centroid") or [77.2090, 28.6139]
    current = await weather_service.get_current_weather(centroid[1], centroid[0])
    observation = current.current

    humidity = observation.relative_humidity
    if humidity is None:
        raise ExternalServiceError(
            "The weather provider supplied no humidity, so a baseline risk "
            "cannot be established for this zone.",
            details={"zone_id": zone_id},
        )

    thermal = thermal_service.calculate_thermal_stress(
        temperature=observation.temperature_c,
        relative_humidity=humidity,
        wind_speed=observation.wind_speed_ms or 0.0,
        solar_radiation=observation.solar_radiation_wm2,
    )

    return {
        "temperature_c": observation.temperature_c,
        "relative_humidity": humidity,
        "wind_speed": observation.wind_speed_ms or 0.0,
        "solar_radiation": observation.solar_radiation_wm2,
        "heat_index": thermal.heat_index,
        "wbgt": thermal.wbgt,
        "utci": thermal.utci,
        "vulnerability_score": vulnerability.vulnerability_score,
    }


@router.get(
    "/types",
    response_model=InterventionCatalogue,
    summary="Supported interventions and their modelled effects",
    description=(
        "Lists every supported intervention with its channel and configured "
        "maximum effect at full coverage. Effect sizes are prototype "
        "assumptions, not validated effectiveness, and are configurable."
    ),
)
async def intervention_types() -> InterventionCatalogue:
    catalogue = intervention_service.INTERVENTION_CATALOGUE
    effects = settings.intervention_effects
    return InterventionCatalogue(
        interventions=[
            InterventionCatalogueEntry(
                type=kind,
                label=entry["label"],
                channel=entry["channel"],
                max_effect=effects[kind],
                assumption=entry["assumption"],
            )
            for kind, entry in sorted(catalogue.items())
        ],
        disclaimer=intervention_service.SIMULATION_DISCLAIMER,
    )


_OPTIMIZE_DESCRIPTION = """
Given a budget, available resources and allowed intervention types, chooses
the feasible plan that maximises **modelled** risk reduction.

> **This is a MODELLED RECOMMENDATION**, not a guaranteed optimum and not a
> medical claim. It does **not** estimate deaths prevented or mortality
> reduction, and it does **not** execute anything in the real world.

**Architecture.** This endpoint does not recompute intervention
effectiveness. It reuses the Phase 9 `/interventions/simulate` engine to
score every candidate plan, and adds only the piece Phase 9 does not have:
translating resource *units* (cooling centres, water tankers, field
workers) into the *coverage fraction* Phase 9 expects, via configured
prototype unit costs and coverage-per-unit.

**Method.** A deterministic greedy search: repeatedly add whichever single
resource unit yields the largest modelled risk reduction per unit of
budget, among interventions that are still affordable, still have resource
units available, and have not yet reached 100% modelled coverage. Stops
when no affordable, resourced unit improves risk. This is a transparent
heuristic, not exhaustive combinatorial search, which is exponential.

`WORK_HOUR_SHIFT`, `PUBLIC_ALERT` and `SHADE_REST_AREA` all draw on the
same `field_workers` pool, so the optimizer must trade them off against one
another for the same people.
"""


@router.post(
    "/optimize",
    response_model=OptimizerResponse,
    responses={
        404: {"model": ErrorResponse, "description": "Unknown zone."},
        422: {"model": ErrorResponse, "description": "Invalid request."},
        502: {"model": ErrorResponse, "description": "Weather provider failure."},
    },
    summary="Recommend the best feasible intervention plan for a zone",
    description=_OPTIMIZE_DESCRIPTION,
)
async def optimize(payload: OptimizerRequest) -> OptimizerResponse:
    weather_kwargs = await _zone_weather_kwargs(payload.zone_id)

    return OptimizerResponse(
        **optimizer_service.optimize(
            zone_id=payload.zone_id,
            budget=payload.budget,
            available_resources=payload.available_resources.model_dump(),
            allowed_interventions=payload.allowed_interventions,
            **weather_kwargs,
        )
    )
