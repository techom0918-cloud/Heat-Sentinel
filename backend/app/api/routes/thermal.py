"""Thermal stress endpoints.

Thin by design. `/thermal/current` composes two services:

    thermal route -> weather_service -> thermal_service -> response

There is no HTTP client import in this file. The Open-Meteo request lives
only in weather_service.py.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.exceptions import ExternalServiceError
from app.models.common import ErrorResponse
from app.models.thermal import (
    ThermalCalculationRequest,
    ThermalCurrentResponse,
    ThermalStressResult,
)
from app.services import thermal_service, weather_service

router = APIRouter(prefix="/thermal", tags=["Thermal Stress"])

LatitudeQuery = Annotated[
    float,
    Query(
        ge=-90.0,
        le=90.0,
        description="Latitude in decimal degrees (-90 to 90).",
        examples=[28.6139],
    ),
]

LongitudeQuery = Annotated[
    float,
    Query(
        ge=-180.0,
        le=180.0,
        description="Longitude in decimal degrees (-180 to 180).",
        examples=[77.2090],
    ),
]

_ERROR_RESPONSES: dict[int | str, dict] = {
    422: {"model": ErrorResponse, "description": "Invalid input."},
    502: {"model": ErrorResponse, "description": "Weather provider failure."},
}

_DESCRIPTION = """
Computes three human thermal-stress indicators from weather conditions.

**Units** — temperature °C, relative humidity %, wind speed m/s,
solar radiation W/m².

**Heat Index** — *recognised calculation*. US NWS algorithm: the simple
Steadman form below ~80 °F, the Rothfusz (1990) regression above it, plus
the published low-humidity and high-humidity corrections. Assumes shade and
light wind. Fitted for roughly 80–112 °F.

**WBGT** — *approximation, not full outdoor WBGT*. Wet-bulb temperature is
estimated with Stull (2011), then the shade form `0.7·Tw + 0.3·Ta` is
applied. True outdoor WBGT is `0.7·Tnw + 0.2·Tg + 0.1·Ta` and needs an
instrument-measured black-globe temperature. **Solar radiation is accepted
but deliberately unused** — deriving a globe temperature from irradiance
would require an unvalidated model, and the result would read as
occupational WBGT while having none of its measurement basis. For the same
reason `wbgt_category` is always `NOT_CLASSIFIED`: ISO 7243 and ACGIH limits
are defined on outdoor WBGT and depend on metabolic rate and
acclimatisation.

**UTCI** — *reference implementation*. Computed by `pythermalcomfort`, which
implements the ISB Commission 6 polynomial. Mean radiant temperature is
assumed equal to air temperature (shade assumption), so heat load in direct
sunlight is understated. Returns `null` outside the model's applicability
limits — note that air temperature above 50 °C, which occurs in India, falls
outside them.

**`heat_index_category` is a prototype band**, not a medical classification.
Edges default to 27/32/41/54 °C and are configurable.

None of these values is a medical assessment of any individual.
"""


@router.post(
    "/calculate",
    response_model=ThermalStressResult,
    responses=_ERROR_RESPONSES,
    summary="Calculate thermal stress from supplied conditions",
    description=_DESCRIPTION,
)
async def calculate_thermal(
    payload: ThermalCalculationRequest,
) -> ThermalStressResult:
    return thermal_service.calculate_thermal_stress(
        temperature=payload.temperature,
        relative_humidity=payload.relative_humidity,
        wind_speed=payload.wind_speed,
        solar_radiation=payload.solar_radiation,
    )


@router.get(
    "/current",
    response_model=ThermalCurrentResponse,
    responses=_ERROR_RESPONSES,
    summary="Current weather plus thermal stress for a coordinate",
    description=(
        "Retrieves current weather through the weather service, then runs it "
        "through the thermal engine. Returns both.\n\n" + _DESCRIPTION
    ),
)
async def current_thermal(
    latitude: LatitudeQuery,
    longitude: LongitudeQuery,
) -> ThermalCurrentResponse:
    weather = await weather_service.get_current_weather(latitude, longitude)
    current = weather.current

    if current.relative_humidity is None:
        raise ExternalServiceError(
            "The weather provider supplied no relative humidity for this "
            "location, so thermal stress cannot be calculated.",
            details={
                "provider": weather.provider,
                "latitude": latitude,
                "longitude": longitude,
            },
        )

    thermal = thermal_service.calculate_thermal_stress(
        temperature=current.temperature_c,
        relative_humidity=current.relative_humidity,
        wind_speed=current.wind_speed_ms or 0.0,
        solar_radiation=current.solar_radiation_wm2,
    )

    if current.wind_speed_ms is None:
        thermal.notes.append(
            "Provider supplied no wind speed; 0 m/s was used, which the UTCI "
            "step then raised to its minimum."
        )

    return ThermalCurrentResponse(
        location=weather.location.model_dump(),
        observed_at=current.observed_at.isoformat(),
        weather=current.model_dump(mode="json"),
        thermal=thermal,
        provider=weather.provider,
    )
