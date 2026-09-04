"""Open-Meteo integration.

This is the ONLY module in HeatSentinal that knows Open-Meteo exists.
Routes call `get_current_weather` / `get_forecast` and receive HeatSentinal's
own schemas. Replacing the provider (IMD, NCMRWF, ERA5 reanalysis) means
rewriting this file and nothing else.

Two provider quirks are handled here rather than leaking downstream:

1.  Open-Meteo defaults wind speed to km/h. WBGT and UTCI are defined on
    m/s, so `wind_speed_unit=ms` is sent explicitly on every request.

2.  Open-Meteo publishes no daily relative-humidity aggregate, and solar
    radiation is not offered as a `current` variable. Both are derived here
    from the hourly series.
"""

import logging
from datetime import date as date_type
from datetime import datetime, timezone
from typing import Any

import httpx

from app.core.config import settings
from app.core.exceptions import ExternalServiceError, ValidationError
from app.models.weather import (
    CurrentWeather,
    CurrentWeatherResponse,
    DailyForecast,
    ForecastResponse,
    GeoLocation,
)

logger = logging.getLogger(__name__)

# Requested from the `current` block. Every name here is a documented
# Open-Meteo current variable.
_CURRENT_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "apparent_temperature",
    "is_day",
    "precipitation",
    "cloud_cover",
    "surface_pressure",
    "wind_speed_10m",
    "wind_direction_10m",
)

# Requested from the `hourly` block. Solar radiation lives here because it
# is not exposed as a current variable.
_HOURLY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "shortwave_radiation",
)

_DAILY_VARIABLES = (
    "temperature_2m_max",
    "temperature_2m_min",
    "apparent_temperature_max",
    "precipitation_sum",
    "wind_speed_10m_max",
    "shortwave_radiation_sum",
)

# Exactly the four variables heat_pipeline.py fetched for training. Adding
# or reordering these would break train/serve parity.
_ML_HISTORY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "shortwave_radiation",
)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_coordinates(latitude: float, longitude: float) -> None:
    """Reject coordinates outside the valid geographic range.

    Duplicated deliberately: FastAPI already validates query parameters, but
    Phase 7 will call this service directly from other services, where no
    HTTP layer exists to check anything.
    """
    if not -90.0 <= latitude <= 90.0:
        raise ValidationError(
            "Latitude must be between -90 and 90 degrees.",
            details={"field": "lat", "received": latitude},
        )
    if not -180.0 <= longitude <= 180.0:
        raise ValidationError(
            "Longitude must be between -180 and 180 degrees.",
            details={"field": "lon", "received": longitude},
        )


def validate_days(days: int) -> None:
    """Reject forecast horizons outside the supported range."""
    maximum = settings.WEATHER_FORECAST_MAX_DAYS
    if not 1 <= days <= maximum:
        raise ValidationError(
            f"days must be between 1 and {maximum}.",
            details={"field": "days", "received": days, "maximum": maximum},
        )


# ---------------------------------------------------------------------------
# HTTP transport
# ---------------------------------------------------------------------------


async def _call_provider(params: dict[str, Any]) -> dict[str, Any]:
    """Issue one request to the provider and return the decoded payload.

    Every failure mode is converted to ExternalServiceError so callers never
    have to know that httpx or Open-Meteo are involved.
    """
    url = settings.WEATHER_API_URL
    timeout = settings.REQUEST_TIMEOUT_SECONDS

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params)
    except httpx.TimeoutException as exc:
        logger.warning("Weather provider timed out after %ss: %s", timeout, exc)
        raise ExternalServiceError(
            "The weather provider did not respond in time.",
            details={"provider": settings.WEATHER_PROVIDER, "timeout_s": timeout},
        ) from exc
    except httpx.RequestError as exc:
        logger.warning("Weather provider unreachable: %s", exc)
        raise ExternalServiceError(
            "The weather provider could not be reached.",
            details={"provider": settings.WEATHER_PROVIDER},
        ) from exc

    if response.status_code >= 400:
        # Open-Meteo reports its own errors as {"error": true, "reason": ...}
        reason = _extract_error_reason(response)
        logger.warning(
            "Weather provider returned %s: %s", response.status_code, reason
        )
        raise ExternalServiceError(
            "The weather provider rejected the request.",
            details={
                "provider": settings.WEATHER_PROVIDER,
                "status_code": response.status_code,
                "reason": reason,
            },
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ExternalServiceError(
            "The weather provider returned a malformed response.",
            details={"provider": settings.WEATHER_PROVIDER},
        ) from exc

    if not isinstance(payload, dict):
        raise ExternalServiceError(
            "The weather provider returned an unexpected payload shape.",
            details={"provider": settings.WEATHER_PROVIDER},
        )

    return payload


def _extract_error_reason(response: httpx.Response) -> str:
    """Pull the provider's error text out of a failed response, safely."""
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]
    if isinstance(body, dict) and "reason" in body:
        return str(body["reason"])[:200]
    return response.text[:200]


def _base_params(latitude: float, longitude: float) -> dict[str, Any]:
    """Parameters common to every provider request."""
    return {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": settings.WEATHER_TIMEZONE,
        "wind_speed_unit": "ms",
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
    }


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    """Coerce a provider value to float, returning None for gaps.

    Open-Meteo uses JSON null for missing readings; some mirrors use the
    string "NaN". Both become None rather than a fabricated number.
    """
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:  # NaN
        return None
    return result


def _safe_bool(value: Any) -> bool | None:
    """Open-Meteo encodes is_day as 1/0."""
    if value is None:
        return None
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return None


def _parse_location(payload: dict[str, Any]) -> GeoLocation:
    """Read the resolved grid cell back out of the payload."""
    latitude = _safe_float(payload.get("latitude"))
    longitude = _safe_float(payload.get("longitude"))
    if latitude is None or longitude is None:
        raise ExternalServiceError(
            "The weather provider response contained no location.",
            details={"provider": settings.WEATHER_PROVIDER},
        )
    return GeoLocation(
        latitude=latitude,
        longitude=longitude,
        elevation_m=_safe_float(payload.get("elevation")),
        timezone=payload.get("timezone"),
    )


def _parse_time(raw: Any, field: str) -> datetime:
    """Parse an Open-Meteo local timestamp such as '2026-09-04T14:30'."""
    if not isinstance(raw, str):
        raise ExternalServiceError(
            "The weather provider response contained no valid timestamp.",
            details={"provider": settings.WEATHER_PROVIDER, "field": field},
        )
    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ExternalServiceError(
            "The weather provider returned an unparseable timestamp.",
            details={"provider": settings.WEATHER_PROVIDER, "value": raw[:40]},
        ) from exc


def _hourly_index_for(hourly_times: list[Any], target: datetime) -> int | None:
    """Index of the hourly slot matching `target`, else the nearest one.

    Current readings are timestamped to the sub-hour (e.g. 14:30) while the
    hourly series is on the hour, so an exact string match is not enough.
    """
    parsed: list[tuple[int, datetime]] = []
    for index, raw in enumerate(hourly_times):
        if not isinstance(raw, str):
            continue
        try:
            parsed.append((index, datetime.fromisoformat(raw)))
        except ValueError:
            continue

    if not parsed:
        return None

    target_hour = target.replace(minute=0, second=0, microsecond=0)
    for index, moment in parsed:
        if moment == target_hour:
            return index

    nearest = min(parsed, key=lambda item: abs(item[1] - target))
    return nearest[0]


def _value_at(series: Any, index: int | None) -> float | None:
    """Read one element from an hourly series, tolerating gaps."""
    if index is None or not isinstance(series, list):
        return None
    if not 0 <= index < len(series):
        return None
    return _safe_float(series[index])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_current_weather(
    latitude: float, longitude: float
) -> CurrentWeatherResponse:
    """Fetch current conditions for one coordinate pair."""
    validate_coordinates(latitude, longitude)

    params = _base_params(latitude, longitude)
    params["current"] = ",".join(_CURRENT_VARIABLES)
    params["hourly"] = "shortwave_radiation"
    params["forecast_days"] = 1

    payload = await _call_provider(params)

    current = payload.get("current")
    if not isinstance(current, dict):
        raise ExternalServiceError(
            "The weather provider returned no current conditions.",
            details={"provider": settings.WEATHER_PROVIDER},
        )

    observed_at = _parse_time(current.get("time"), "current.time")

    temperature = _safe_float(current.get("temperature_2m"))
    if temperature is None:
        # Temperature is the one variable the whole system depends on.
        raise ExternalServiceError(
            "The weather provider returned no temperature for this location.",
            details={
                "provider": settings.WEATHER_PROVIDER,
                "latitude": latitude,
                "longitude": longitude,
            },
        )

    hourly = payload.get("hourly")
    solar = None
    if isinstance(hourly, dict):
        index = _hourly_index_for(hourly.get("time") or [], observed_at)
        solar = _value_at(hourly.get("shortwave_radiation"), index)

    return CurrentWeatherResponse(
        location=_parse_location(payload),
        current=CurrentWeather(
            observed_at=observed_at,
            temperature_c=temperature,
            relative_humidity=_safe_float(current.get("relative_humidity_2m")),
            apparent_temperature_c=_safe_float(
                current.get("apparent_temperature")
            ),
            wind_speed_ms=_safe_float(current.get("wind_speed_10m")),
            wind_direction_deg=_safe_float(current.get("wind_direction_10m")),
            precipitation_mm=_safe_float(current.get("precipitation")),
            cloud_cover_pct=_safe_float(current.get("cloud_cover")),
            surface_pressure_hpa=_safe_float(current.get("surface_pressure")),
            solar_radiation_wm2=solar,
            is_day=_safe_bool(current.get("is_day")),
        ),
        provider=settings.WEATHER_PROVIDER,
        retrieved_at=datetime.now(timezone.utc),
    )


async def get_forecast(
    latitude: float, longitude: float, days: int
) -> ForecastResponse:
    """Fetch a 1-5 day forecast for one coordinate pair."""
    validate_coordinates(latitude, longitude)
    validate_days(days)

    params = _base_params(latitude, longitude)
    params["daily"] = ",".join(_DAILY_VARIABLES)
    params["hourly"] = ",".join(_HOURLY_VARIABLES)
    params["forecast_days"] = days

    payload = await _call_provider(params)

    daily = payload.get("daily")
    if not isinstance(daily, dict) or not isinstance(daily.get("time"), list):
        raise ExternalServiceError(
            "The weather provider returned no daily forecast.",
            details={"provider": settings.WEATHER_PROVIDER},
        )

    hourly_by_date = _group_hourly_by_date(payload.get("hourly"))

    forecast: list[DailyForecast] = []
    for index, raw_date in enumerate(daily["time"]):
        try:
            day = date_type.fromisoformat(str(raw_date))
        except ValueError:
            logger.warning("Skipping unparseable forecast date: %r", raw_date)
            continue

        derived = hourly_by_date.get(day, {})
        radiation_sum = _value_at(daily.get("shortwave_radiation_sum"), index)

        forecast.append(
            DailyForecast(
                date=day,
                temperature_max_c=_value_at(
                    daily.get("temperature_2m_max"), index
                ),
                temperature_min_c=_value_at(
                    daily.get("temperature_2m_min"), index
                ),
                apparent_temperature_max_c=_value_at(
                    daily.get("apparent_temperature_max"), index
                ),
                relative_humidity_mean=derived.get("humidity_mean"),
                relative_humidity_at_max_temp=derived.get("humidity_at_peak"),
                wind_speed_max_ms=_value_at(
                    daily.get("wind_speed_10m_max"), index
                ),
                precipitation_sum_mm=_value_at(
                    daily.get("precipitation_sum"), index
                ),
                solar_radiation_max_wm2=derived.get("radiation_max"),
                solar_radiation_sum_mj=radiation_sum,
            )
        )

    if not forecast:
        raise ExternalServiceError(
            "The weather provider returned an empty forecast.",
            details={"provider": settings.WEATHER_PROVIDER},
        )

    return ForecastResponse(
        location=_parse_location(payload),
        days=len(forecast),
        forecast=forecast,
        provider=settings.WEATHER_PROVIDER,
        retrieved_at=datetime.now(timezone.utc),
    )


async def get_hourly_history(
    latitude: float, longitude: float, past_days: int
) -> dict[str, Any]:
    """Fetch recent hourly observations for one coordinate pair.

    Returns the raw hourly series rather than a HeatSentinal schema, because
    the only consumer is the ML feature builder, which needs the same shape
    the training pipeline saw. Provider isolation is preserved: this is
    still the only module issuing the request.
    """
    validate_coordinates(latitude, longitude)
    if past_days < 1 or past_days > 92:
        raise ValidationError(
            "past_days must be between 1 and 92.",
            details={"field": "past_days", "received": past_days},
        )

    params = _base_params(latitude, longitude)
    params["hourly"] = ",".join(_ML_HISTORY_VARIABLES)
    params["past_days"] = past_days
    params["forecast_days"] = 1

    payload = await _call_provider(params)

    hourly = payload.get("hourly")
    if not isinstance(hourly, dict) or not isinstance(hourly.get("time"), list):
        raise ExternalServiceError(
            "The weather provider returned no hourly history.",
            details={"provider": settings.WEATHER_PROVIDER},
        )

    return {
        "location": _parse_location(payload),
        "time": hourly.get("time") or [],
        "temperature": hourly.get("temperature_2m") or [],
        "humidity": hourly.get("relative_humidity_2m") or [],
        "wind_speed": hourly.get("wind_speed_10m") or [],
        "solar_radiation": hourly.get("shortwave_radiation") or [],
    }


def _group_hourly_by_date(
    hourly: Any,
) -> dict[date_type, dict[str, float | None]]:
    """Derive per-day humidity and radiation figures from the hourly series.

    Open-Meteo has no daily humidity aggregate, so it is computed here:

      humidity_mean      arithmetic mean of that day's hourly RH values
      humidity_at_peak   RH at the hour of that day's highest temperature
      radiation_max      highest hourly shortwave radiation that day

    `humidity_at_peak` matters because heat stress peaks with temperature.
    Pairing a daily maximum temperature with a daily *mean* humidity would
    understate afternoon risk in humid coastal districts.
    """
    if not isinstance(hourly, dict):
        return {}

    times = hourly.get("time")
    if not isinstance(times, list):
        return {}

    humidity_series = hourly.get("relative_humidity_2m")
    temperature_series = hourly.get("temperature_2m")
    radiation_series = hourly.get("shortwave_radiation")

    buckets: dict[date_type, dict[str, list[Any]]] = {}
    for index, raw in enumerate(times):
        if not isinstance(raw, str):
            continue
        try:
            day = datetime.fromisoformat(raw).date()
        except ValueError:
            continue
        bucket = buckets.setdefault(
            day, {"humidity": [], "temperature": [], "radiation": []}
        )
        bucket["humidity"].append(_value_at(humidity_series, index))
        bucket["temperature"].append(_value_at(temperature_series, index))
        bucket["radiation"].append(_value_at(radiation_series, index))

    result: dict[date_type, dict[str, float | None]] = {}
    for day, bucket in buckets.items():
        humidity = bucket["humidity"]
        temperature = bucket["temperature"]
        radiation = [value for value in bucket["radiation"] if value is not None]

        present = [value for value in humidity if value is not None]
        humidity_mean = (
            round(sum(present) / len(present), 1) if present else None
        )

        humidity_at_peak = None
        paired = [
            (temp, hum)
            for temp, hum in zip(temperature, humidity)
            if temp is not None and hum is not None
        ]
        if paired:
            humidity_at_peak = max(paired, key=lambda item: item[0])[1]

        result[day] = {
            "humidity_mean": humidity_mean,
            "humidity_at_peak": humidity_at_peak,
            "radiation_max": max(radiation) if radiation else None,
        }

    return result
