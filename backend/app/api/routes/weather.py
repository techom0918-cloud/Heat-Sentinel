"""Weather endpoints.

Thin by design: parse, validate, delegate, return. No provider name, no URL,
no httpx import appears in this file.
"""

from typing import Annotated

from fastapi import APIRouter, Query

from app.core.config import settings
from app.models.common import ErrorResponse
from app.models.weather import CurrentWeatherResponse, ForecastResponse
from app.services import weather_service

router = APIRouter(prefix="/weather", tags=["Weather"])

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

DaysQuery = Annotated[
    int,
    Query(
        ge=1,
        le=settings.WEATHER_FORECAST_MAX_DAYS,
        description=(
            "Forecast horizon in days "
            f"(1 to {settings.WEATHER_FORECAST_MAX_DAYS})."
        ),
    ),
]

_ERROR_RESPONSES: dict[int | str, dict] = {
    422: {"model": ErrorResponse, "description": "Invalid query parameters."},
    502: {"model": ErrorResponse, "description": "Weather provider failure."},
}


@router.get(
    "/current",
    response_model=CurrentWeatherResponse,
    responses=_ERROR_RESPONSES,
    summary="Current weather for a coordinate",
    description=(
        "Returns current conditions for the nearest provider grid cell. "
        "Wind is reported in m/s and solar radiation in W/m^2, the units the "
        "Phase 3 thermal indices expect. Any variable the provider omits is "
        "returned as null rather than being estimated."
    ),
)
async def current_weather(
    lat: LatitudeQuery, lon: LongitudeQuery
) -> CurrentWeatherResponse:
    return await weather_service.get_current_weather(lat, lon)


@router.get(
    "/forecast",
    response_model=ForecastResponse,
    responses=_ERROR_RESPONSES,
    summary="Multi-day weather forecast for a coordinate",
    description=(
        "Returns a 1-5 day daily forecast. Daily humidity figures are derived "
        "from the hourly series because the provider publishes no daily "
        "humidity aggregate; `relative_humidity_at_max_temp` pairs humidity "
        "with the hottest hour of each day."
    ),
)
async def weather_forecast(
    lat: LatitudeQuery,
    lon: LongitudeQuery,
    days: DaysQuery = 5,
) -> ForecastResponse:
    return await weather_service.get_forecast(lat, lon, days)
