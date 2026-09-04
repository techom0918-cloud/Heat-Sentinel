"""Heat action simulator endpoints (Phase 9)."""

from fastapi import APIRouter

from app.core.config import settings
from app.models.common import ErrorResponse
from app.models.intervention import (
    InterventionCatalogue,
    InterventionCatalogueEntry,
    SimulationRequest,
    SimulationResponse,
)
from app.services import (
    geospatial_service,
    intervention_service,
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
    # Raises 404 with the available zone list if the id is unknown.
    feature = geospatial_service.get_zone(payload.zone_id)
    vulnerability = geospatial_service.zone_vulnerability(feature)

    centroid = feature["properties"].get("centroid") or [77.2090, 28.6139]
    current = await weather_service.get_current_weather(centroid[1], centroid[0])
    observation = current.current

    humidity = observation.relative_humidity
    if humidity is None:
        from app.core.exceptions import ExternalServiceError

        raise ExternalServiceError(
            "The weather provider supplied no humidity, so a baseline risk "
            "cannot be established for this zone.",
            details={"zone_id": payload.zone_id},
        )

    thermal = thermal_service.calculate_thermal_stress(
        temperature=observation.temperature_c,
        relative_humidity=humidity,
        wind_speed=observation.wind_speed_ms or 0.0,
        solar_radiation=observation.solar_radiation_wm2,
    )

    return SimulationResponse(
        **intervention_service.simulate(
            temperature_c=observation.temperature_c,
            relative_humidity=humidity,
            wind_speed=observation.wind_speed_ms or 0.0,
            solar_radiation=observation.solar_radiation_wm2,
            heat_index=thermal.heat_index,
            wbgt=thermal.wbgt,
            utci=thermal.utci,
            vulnerability_score=vulnerability.vulnerability_score,
            interventions=[i.model_dump() for i in payload.interventions],
            zone_id=payload.zone_id,
        )
    )


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
