"""Weather schemas.

These describe HeatSentinal's *own* weather contract, not Open-Meteo's.
The provider payload is translated into these models inside
`app.services.weather_service`, so swapping provider (IMD, NCMRWF, ERA5)
later changes only that one file and never touches routes or downstream
engines.

Unit convention, fixed here once for the whole system:

    temperature         degrees Celsius
    relative humidity   percent (0-100)
    wind speed          metres per second   <- not km/h
    precipitation       millimetres
    solar radiation     watts per square metre (instantaneous)
                        megajoules per square metre (daily total)

Wind is requested in m/s explicitly because the Phase 3 thermal indices
(WBGT, UTCI) are defined on m/s. Feeding them km/h would silently produce
wrong-but-plausible numbers, which is the worst kind of bug in a system
that issues health warnings.
"""

from datetime import date as date_type
from datetime import datetime

from pydantic import BaseModel, Field


class GeoLocation(BaseModel):
    """Resolved location echoed back by the provider."""

    latitude: float = Field(..., description="Latitude in decimal degrees.")
    longitude: float = Field(..., description="Longitude in decimal degrees.")
    elevation_m: float | None = Field(
        None, description="Elevation of the resolved grid cell, in metres."
    )
    timezone: str | None = Field(
        None, description="IANA timezone resolved for the coordinates."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "latitude": 28.625,
                "longitude": 77.375,
                "elevation_m": 216.0,
                "timezone": "Asia/Kolkata",
            }
        }
    }


class CurrentWeather(BaseModel):
    """Observed conditions at (or nearest to) the requested time.

    Every field except `observed_at` and `temperature_c` is optional. A
    provider can and does omit variables for some grid cells, and a missing
    value must never be silently substituted with a plausible number.
    """

    observed_at: datetime = Field(..., description="Local observation time.")
    temperature_c: float = Field(..., description="Air temperature at 2 m.")
    relative_humidity: float | None = Field(
        None, ge=0, le=100, description="Relative humidity at 2 m, percent."
    )
    apparent_temperature_c: float | None = Field(
        None,
        description=(
            "Provider's own feels-like value. Informational only -- "
            "HeatSentinal computes its own indices in Phase 3."
        ),
    )
    wind_speed_ms: float | None = Field(
        None, ge=0, description="Wind speed at 10 m, metres per second."
    )
    wind_direction_deg: float | None = Field(
        None, ge=0, le=360, description="Wind direction at 10 m, degrees."
    )
    precipitation_mm: float | None = Field(
        None, ge=0, description="Precipitation for the current interval."
    )
    cloud_cover_pct: float | None = Field(
        None, ge=0, le=100, description="Total cloud cover, percent."
    )
    surface_pressure_hpa: float | None = Field(
        None, description="Surface pressure, hectopascals."
    )
    solar_radiation_wm2: float | None = Field(
        None,
        ge=0,
        description=(
            "Shortwave solar radiation, W/m^2, taken from the hourly series "
            "at the hour matching `observed_at`. Null when unavailable."
        ),
    )
    is_day: bool | None = Field(
        None, description="True during local daylight hours."
    )


class CurrentWeatherResponse(BaseModel):
    """Envelope returned by GET /api/v1/weather/current."""

    location: GeoLocation
    current: CurrentWeather
    provider: str = Field(..., description="Upstream data provider.")
    retrieved_at: datetime = Field(
        ..., description="UTC time HeatSentinal fetched this record."
    )


class DailyForecast(BaseModel):
    """One forecast day.

    Open-Meteo publishes no daily humidity aggregate, so
    `relative_humidity_mean` and `relative_humidity_at_max_temp` are derived
    from the hourly series by the weather service. The second one exists
    because heat stress peaks when temperature peaks -- pairing daily max
    temperature with daily mean humidity would understate afternoon risk.
    """

    date: date_type = Field(..., description="Local calendar date.")
    temperature_max_c: float | None = None
    temperature_min_c: float | None = None
    apparent_temperature_max_c: float | None = None
    relative_humidity_mean: float | None = Field(
        None, ge=0, le=100, description="Mean of hourly RH across the day."
    )
    relative_humidity_at_max_temp: float | None = Field(
        None,
        ge=0,
        le=100,
        description="RH at the hour of that day's highest temperature.",
    )
    wind_speed_max_ms: float | None = Field(None, ge=0)
    precipitation_sum_mm: float | None = Field(None, ge=0)
    solar_radiation_max_wm2: float | None = Field(
        None, ge=0, description="Peak hourly shortwave radiation, W/m^2."
    )
    solar_radiation_sum_mj: float | None = Field(
        None, ge=0, description="Daily shortwave radiation total, MJ/m^2."
    )


class ForecastResponse(BaseModel):
    """Envelope returned by GET /api/v1/weather/forecast."""

    location: GeoLocation
    days: int = Field(..., ge=1, description="Number of days returned.")
    forecast: list[DailyForecast]
    provider: str
    retrieved_at: datetime
