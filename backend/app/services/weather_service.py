"""Weather provider integration for Heat-Sentinel.

Provider strategy:
    1. Open-Meteo is the primary provider.
    2. WeatherAPI is used automatically when Open-Meteo fails.
    3. Successful responses are cached briefly to reduce provider traffic.

The rest of Heat-Sentinel only sees HeatSentinal's own response schemas.
"""

import asyncio
import logging
import os
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

_ML_HISTORY_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "wind_speed_10m",
    "shortwave_radiation",
)

# Cache TTLs.
CURRENT_CACHE_TTL = 10 * 60
FORECAST_CACHE_TTL = 30 * 60
HISTORY_CACHE_TTL = 60 * 60

_WEATHER_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}
_WEATHER_CACHE_LOCK = asyncio.Lock()


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_coordinates(latitude: float, longitude: float) -> None:
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
    maximum = settings.WEATHER_FORECAST_MAX_DAYS
    if not 1 <= days <= maximum:
        raise ValidationError(
            f"days must be between 1 and {maximum}.",
            details={"field": "days", "received": days, "maximum": maximum},
        )


# ---------------------------------------------------------------------------
# Provider configuration
# ---------------------------------------------------------------------------


def _weatherapi_key() -> str | None:
    """Read WeatherAPI key without requiring a config.py change."""
    value = os.getenv("WEATHERAPI_API_KEY")
    if value:
        return value.strip() or None
    return None


def _weatherapi_enabled() -> bool:
    return bool(_weatherapi_key())


def _cache_key(prefix: str, params: dict[str, Any]) -> str:
    parts = [prefix]
    for key in sorted(params):
        parts.append(f"{key}={params[key]}")
    return "|".join(parts)


async def _cache_get(
    key: str,
    ttl: int,
) -> dict[str, Any] | None:
    now = asyncio.get_running_loop().time()
    async with _WEATHER_CACHE_LOCK:
        item = _WEATHER_CACHE.get(key)
        if item is None:
            return None

        stored_at, payload = item
        if now - stored_at >= ttl:
            _WEATHER_CACHE.pop(key, None)
            return None

        return payload


async def _cache_set(
    key: str,
    payload: dict[str, Any],
) -> None:
    now = asyncio.get_running_loop().time()
    async with _WEATHER_CACHE_LOCK:
        _WEATHER_CACHE[key] = (now, payload)

        # Keep the in-process cache bounded.
        if len(_WEATHER_CACHE) > 500:
            oldest_key = min(
                _WEATHER_CACHE,
                key=lambda cache_key: _WEATHER_CACHE[cache_key][0],
            )
            _WEATHER_CACHE.pop(oldest_key, None)


# ---------------------------------------------------------------------------
# HTTP helpers
# ---------------------------------------------------------------------------


async def _request_json(
    url: str,
    params: dict[str, Any],
    provider: str,
) -> dict[str, Any]:
    """Request JSON and raise ExternalServiceError on transport/API failure."""
    timeout = settings.REQUEST_TIMEOUT_SECONDS

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, params=params)
    except httpx.TimeoutException as exc:
        logger.warning("%s timed out after %ss: %s", provider, timeout, exc)
        raise ExternalServiceError(
            "The weather provider did not respond in time.",
            details={
                "provider": provider,
                "timeout_s": timeout,
            },
        ) from exc
    except httpx.RequestError as exc:
        logger.warning("%s unreachable: %s", provider, exc)
        raise ExternalServiceError(
            "The weather provider could not be reached.",
            details={"provider": provider},
        ) from exc

    if response.status_code >= 400:
        reason = _extract_error_reason(response)
        logger.warning(
            "%s returned %s: %s",
            provider,
            response.status_code,
            reason,
        )
        raise ExternalServiceError(
            "The weather provider rejected the request.",
            details={
                "provider": provider,
                "status_code": response.status_code,
                "reason": reason,
            },
        )

    try:
        payload = response.json()
    except ValueError as exc:
        raise ExternalServiceError(
            "The weather provider returned a malformed response.",
            details={"provider": provider},
        ) from exc

    if not isinstance(payload, dict):
        raise ExternalServiceError(
            "The weather provider returned an unexpected payload shape.",
            details={"provider": provider},
        )

    return payload


def _extract_error_reason(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return response.text[:200]

    if isinstance(body, dict):
        if "reason" in body:
            return str(body["reason"])[:200]

        error = body.get("error")
        if isinstance(error, dict):
            message = error.get("message") or error.get("info")
            if message:
                return str(message)[:200]

    return response.text[:200]


async def _call_open_meteo(
    params: dict[str, Any],
    cache_ttl: int,
) -> dict[str, Any]:
    """Call Open-Meteo with cache."""
    cache_key = _cache_key("open-meteo", params)

    cached = await _cache_get(cache_key, cache_ttl)
    if cached is not None:
        logger.info("Weather cache hit: Open-Meteo")
        return cached

    payload = await _request_json(
        settings.WEATHER_API_URL,
        params,
        "open-meteo",
    )

    await _cache_set(cache_key, payload)
    return payload


# ---------------------------------------------------------------------------
# WeatherAPI fallback
# ---------------------------------------------------------------------------


def _weatherapi_base_params(latitude: float, longitude: float) -> dict[str, Any]:
    key = _weatherapi_key()
    if not key:
        raise ExternalServiceError(
            "WeatherAPI fallback is not configured.",
            details={"provider": "weatherapi"},
        )

    return {
        "key": key,
        "q": f"{latitude},{longitude}",
        "aqi": "no",
        "alerts": "no",
    }


def _normalize_weatherapi_location(
    payload: dict[str, Any],
) -> dict[str, Any]:
    location = payload.get("location")
    if not isinstance(location, dict):
        raise ExternalServiceError(
            "WeatherAPI returned no location.",
            details={"provider": "weatherapi"},
        )

    return {
        "latitude": location.get("lat"),
        "longitude": location.get("lon"),
        "elevation": None,
        "timezone": location.get("tz_id"),
    }


def _weatherapi_current_to_open_meteo_shape(
    payload: dict[str, Any],
) -> dict[str, Any]:
    location = _normalize_weatherapi_location(payload)
    current = payload.get("current")

    if not isinstance(current, dict):
        raise ExternalServiceError(
            "WeatherAPI returned no current conditions.",
            details={"provider": "weatherapi"},
        )

    local_time = current.get("last_updated") or (
        payload.get("location", {}) or {}
    ).get("localtime")

    if not isinstance(local_time, str):
        raise ExternalServiceError(
            "WeatherAPI returned no valid current timestamp.",
            details={"provider": "weatherapi"},
        )

    # WeatherAPI wind_kph -> m/s.
    wind_ms = _safe_float(current.get("wind_kph"))
    if wind_ms is not None:
        wind_ms /= 3.6

    return {
        **location,
        "current": {
            "time": local_time.replace(" ", "T"),
            "temperature_2m": current.get("temp_c"),
            "relative_humidity_2m": current.get("humidity"),
            "apparent_temperature": current.get("feelslike_c"),
            "is_day": current.get("is_day"),
            "precipitation": current.get("precip_mm"),
            "cloud_cover": current.get("cloud"),
            "surface_pressure": current.get("pressure_mb"),
            "wind_speed_10m": wind_ms,
            "wind_direction_10m": current.get("wind_degree"),
        },
        "hourly": {
            "time": [local_time.replace(" ", "T")],
            "shortwave_radiation": [None],
        },
    }


def _weatherapi_hour_to_open_meteo_shape(
    hour: dict[str, Any],
) -> dict[str, Any]:
    wind_ms = _safe_float(hour.get("wind_kph"))
    if wind_ms is not None:
        wind_ms /= 3.6

    return {
        "time": str(hour.get("time", "")).replace(" ", "T"),
        "temperature_2m": hour.get("temp_c"),
        "relative_humidity_2m": hour.get("humidity"),
        "wind_speed_10m": wind_ms,
        "shortwave_radiation": None,
    }


def _weatherapi_forecast_to_open_meteo_shape(
    payload: dict[str, Any],
) -> dict[str, Any]:
    location = _normalize_weatherapi_location(payload)
    forecast_root = payload.get("forecast")

    if not isinstance(forecast_root, dict):
        raise ExternalServiceError(
            "WeatherAPI returned no forecast.",
            details={"provider": "weatherapi"},
        )

    forecast_days = forecast_root.get("forecastday")
    if not isinstance(forecast_days, list):
        raise ExternalServiceError(
            "WeatherAPI returned no forecast days.",
            details={"provider": "weatherapi"},
        )

    daily: dict[str, list[Any]] = {
        "time": [],
        "temperature_2m_max": [],
        "temperature_2m_min": [],
        "apparent_temperature_max": [],
        "precipitation_sum": [],
        "wind_speed_10m_max": [],
        "shortwave_radiation_sum": [],
    }

    hourly: dict[str, list[Any]] = {
        "time": [],
        "temperature_2m": [],
        "relative_humidity_2m": [],
        "wind_speed_10m": [],
        "shortwave_radiation": [],
    }

    for day_item in forecast_days:
        if not isinstance(day_item, dict):
            continue

        raw_date = day_item.get("date")
        day = day_item.get("day") or {}

        if not isinstance(raw_date, str) or not isinstance(day, dict):
            continue

        daily["time"].append(raw_date)
        daily["temperature_2m_max"].append(day.get("maxtemp_c"))
        daily["temperature_2m_min"].append(day.get("mintemp_c"))
        daily["apparent_temperature_max"].append(day.get("maxwind_kph"))

        # WeatherAPI's day object does not expose apparent temperature max
        # directly in all plans. Use the daily max heat index when available.
        apparent_max = day.get("avgtemp_c")
        daily["apparent_temperature_max"][-1] = apparent_max

        daily["precipitation_sum"].append(day.get("totalprecip_mm"))

        max_wind_kph = _safe_float(day.get("maxwind_kph"))
        daily["wind_speed_10m_max"].append(
            max_wind_kph / 3.6 if max_wind_kph is not None else None
        )

        # WeatherAPI does not expose the Open-Meteo-style radiation sum on
        # the free/basic response, so leave it unavailable.
        daily["shortwave_radiation_sum"].append(None)

        hours = day_item.get("hour") or []
        if isinstance(hours, list):
            for hour in hours:
                if not isinstance(hour, dict):
                    continue
                normalized = _weatherapi_hour_to_open_meteo_shape(hour)
                for key in hourly:
                    hourly[key].append(normalized[key])

    return {
        **location,
        "daily": daily,
        "hourly": hourly,
    }


async def _call_weatherapi_current(
    latitude: float,
    longitude: float,
    cache_ttl: int,
) -> dict[str, Any]:
    params = _weatherapi_base_params(latitude, longitude)
    cache_key = _cache_key("weatherapi-current", params)

    cached = await _cache_get(cache_key, cache_ttl)
    if cached is not None:
        logger.info("Weather cache hit: WeatherAPI current")
        return cached

    payload = await _request_json(
        "https://api.weatherapi.com/v1/current.json",
        params,
        "weatherapi",
    )
    normalized = _weatherapi_current_to_open_meteo_shape(payload)
    await _cache_set(cache_key, normalized)
    return normalized


async def _call_weatherapi_forecast(
    latitude: float,
    longitude: float,
    days: int,
    cache_ttl: int,
) -> dict[str, Any]:
    # WeatherAPI documents forecast days as 1-14.
    if days > 14:
        raise ExternalServiceError(
            "WeatherAPI fallback supports at most 14 forecast days.",
            details={"provider": "weatherapi", "requested_days": days},
        )

    params = _weatherapi_base_params(latitude, longitude)
    params["days"] = days

    cache_key = _cache_key("weatherapi-forecast", params)

    cached = await _cache_get(cache_key, cache_ttl)
    if cached is not None:
        logger.info("Weather cache hit: WeatherAPI forecast")
        return cached

    payload = await _request_json(
        "https://api.weatherapi.com/v1/forecast.json",
        params,
        "weatherapi",
    )
    normalized = _weatherapi_forecast_to_open_meteo_shape(payload)
    await _cache_set(cache_key, normalized)
    return normalized


async def _call_weatherapi_history(
    latitude: float,
    longitude: float,
    past_days: int,
    forecast_days: int,
    cache_ttl: int,
) -> dict[str, Any]:
    # Keep this conservative: the fallback must not silently pretend that
    # one day of history is equivalent to the 92-day Open-Meteo request.
    if past_days > 1:
        raise ExternalServiceError(
            "WeatherAPI fallback cannot replace a multi-day historical request.",
            details={
                "provider": "weatherapi",
                "requested_past_days": past_days,
            },
        )

    params = _weatherapi_base_params(latitude, longitude)
    params["dt"] = datetime.now().date().isoformat()

    # History + future forecast cannot be represented by the WeatherAPI
    # history endpoint in the same shape as the primary request. For the
    # fallback path we use forecast data only when no historical data is
    # required beyond the supported one-day boundary.
    if forecast_days > 14:
        raise ExternalServiceError(
            "WeatherAPI fallback supports at most 14 forecast days.",
            details={
                "provider": "weatherapi",
                "requested_forecast_days": forecast_days,
            },
        )

    cache_key = _cache_key("weatherapi-history", params)

    cached = await _cache_get(cache_key, cache_ttl)
    if cached is not None:
        logger.info("Weather cache hit: WeatherAPI history")
        return cached

    payload = await _request_json(
        "https://api.weatherapi.com/v1/history.json",
        params,
        "weatherapi",
    )

    normalized = _weatherapi_forecast_to_open_meteo_shape(payload)
    await _cache_set(cache_key, normalized)
    return normalized


# ---------------------------------------------------------------------------
# Provider orchestration
# ---------------------------------------------------------------------------


async def _call_provider(
    params: dict[str, Any],
    *,
    cache_ttl: int,
    fallback_kind: str,
    latitude: float | None = None,
    longitude: float | None = None,
    days: int | None = None,
    past_days: int | None = None,
    forecast_days: int | None = None,
) -> tuple[dict[str, Any], str]:
    """Primary Open-Meteo call with automatic WeatherAPI fallback."""
    try:
        payload = await _call_open_meteo(params, cache_ttl)
        return payload, "open-meteo"
    except ExternalServiceError as primary_error:
        logger.warning(
            "Primary weather provider failed; trying WeatherAPI fallback. "
            "reason=%s",
            primary_error,
        )

        if not _weatherapi_enabled():
            raise primary_error

        try:
            if fallback_kind == "current":
                assert latitude is not None and longitude is not None
                payload = await _call_weatherapi_current(
                    latitude,
                    longitude,
                    cache_ttl,
                )
            elif fallback_kind == "forecast":
                assert latitude is not None and longitude is not None
                assert days is not None
                payload = await _call_weatherapi_forecast(
                    latitude,
                    longitude,
                    days,
                    cache_ttl,
                )
            elif fallback_kind == "history":
                assert latitude is not None and longitude is not None
                assert past_days is not None and forecast_days is not None
                payload = await _call_weatherapi_history(
                    latitude,
                    longitude,
                    past_days,
                    forecast_days,
                    cache_ttl,
                )
            else:
                raise primary_error

            return payload, "weatherapi"

        except ExternalServiceError:
            logger.exception("WeatherAPI fallback also failed.")
            raise primary_error


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if result != result:
        return None
    return result


def _safe_bool(value: Any) -> bool | None:
    if value is None:
        return None
    try:
        return bool(int(value))
    except (TypeError, ValueError):
        return None


def _parse_location(
    payload: dict[str, Any],
    provider: str,
) -> GeoLocation:
    latitude = _safe_float(payload.get("latitude"))
    longitude = _safe_float(payload.get("longitude"))

    if latitude is None or longitude is None:
        raise ExternalServiceError(
            "The weather provider response contained no location.",
            details={"provider": provider},
        )

    return GeoLocation(
        latitude=latitude,
        longitude=longitude,
        elevation_m=_safe_float(payload.get("elevation")),
        timezone=payload.get("timezone"),
    )


def _parse_time(
    raw: Any,
    field: str,
    provider: str,
) -> datetime:
    if not isinstance(raw, str):
        raise ExternalServiceError(
            "The weather provider response contained no valid timestamp.",
            details={"provider": provider, "field": field},
        )

    try:
        return datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ExternalServiceError(
            "The weather provider returned an unparseable timestamp.",
            details={
                "provider": provider,
                "value": raw[:40],
            },
        ) from exc


def _hourly_index_for(
    hourly_times: list[Any],
    target: datetime,
) -> int | None:
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

    target_hour = target.replace(
        minute=0,
        second=0,
        microsecond=0,
    )

    for index, moment in parsed:
        if moment == target_hour:
            return index

    nearest = min(
        parsed,
        key=lambda item: abs(item[1] - target),
    )
    return nearest[0]


def _value_at(
    series: Any,
    index: int | None,
) -> float | None:
    if index is None or not isinstance(series, list):
        return None
    if not 0 <= index < len(series):
        return None
    return _safe_float(series[index])


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def get_current_weather(
    latitude: float,
    longitude: float,
) -> CurrentWeatherResponse:
    validate_coordinates(latitude, longitude)

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": settings.WEATHER_TIMEZONE,
        "wind_speed_unit": "ms",
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
        "current": ",".join(_CURRENT_VARIABLES),
        "hourly": "shortwave_radiation",
        "forecast_days": 1,
    }

    payload, provider = await _call_provider(
        params,
        cache_ttl=CURRENT_CACHE_TTL,
        fallback_kind="current",
        latitude=latitude,
        longitude=longitude,
    )

    current = payload.get("current")
    if not isinstance(current, dict):
        raise ExternalServiceError(
            "The weather provider returned no current conditions.",
            details={"provider": provider},
        )

    observed_at = _parse_time(
        current.get("time"),
        "current.time",
        provider,
    )

    temperature = _safe_float(current.get("temperature_2m"))
    if temperature is None:
        raise ExternalServiceError(
            "The weather provider returned no temperature for this location.",
            details={
                "provider": provider,
                "latitude": latitude,
                "longitude": longitude,
            },
        )

    hourly = payload.get("hourly")
    solar = None

    if isinstance(hourly, dict):
        index = _hourly_index_for(
            hourly.get("time") or [],
            observed_at,
        )
        solar = _value_at(
            hourly.get("shortwave_radiation"),
            index,
        )

    return CurrentWeatherResponse(
        location=_parse_location(payload, provider),
        current=CurrentWeather(
            observed_at=observed_at,
            temperature_c=temperature,
            relative_humidity=_safe_float(
                current.get("relative_humidity_2m")
            ),
            apparent_temperature_c=_safe_float(
                current.get("apparent_temperature")
            ),
            wind_speed_ms=_safe_float(
                current.get("wind_speed_10m")
            ),
            wind_direction_deg=_safe_float(
                current.get("wind_direction_10m")
            ),
            precipitation_mm=_safe_float(
                current.get("precipitation")
            ),
            cloud_cover_pct=_safe_float(
                current.get("cloud_cover")
            ),
            surface_pressure_hpa=_safe_float(
                current.get("surface_pressure")
            ),
            solar_radiation_wm2=solar,
            is_day=_safe_bool(current.get("is_day")),
        ),
        provider=provider,
        retrieved_at=datetime.now(timezone.utc),
    )


async def get_forecast(
    latitude: float,
    longitude: float,
    days: int,
) -> ForecastResponse:
    validate_coordinates(latitude, longitude)
    validate_days(days)

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": settings.WEATHER_TIMEZONE,
        "wind_speed_unit": "ms",
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
        "daily": ",".join(_DAILY_VARIABLES),
        "hourly": ",".join(_HOURLY_VARIABLES),
        "forecast_days": days,
    }

    payload, provider = await _call_provider(
        params,
        cache_ttl=FORECAST_CACHE_TTL,
        fallback_kind="forecast",
        latitude=latitude,
        longitude=longitude,
        days=days,
    )

    daily = payload.get("daily")
    if not isinstance(daily, dict) or not isinstance(
        daily.get("time"),
        list,
    ):
        raise ExternalServiceError(
            "The weather provider returned no daily forecast.",
            details={"provider": provider},
        )

    hourly_by_date = _group_hourly_by_date(
        payload.get("hourly")
    )

    forecast: list[DailyForecast] = []

    for index, raw_date in enumerate(daily["time"]):
        try:
            day = date_type.fromisoformat(str(raw_date))
        except ValueError:
            logger.warning(
                "Skipping unparseable forecast date: %r",
                raw_date,
            )
            continue

        derived = hourly_by_date.get(day, {})

        radiation_sum = _value_at(
            daily.get("shortwave_radiation_sum"),
            index,
        )

        forecast.append(
            DailyForecast(
                date=day,
                temperature_max_c=_value_at(
                    daily.get("temperature_2m_max"),
                    index,
                ),
                temperature_min_c=_value_at(
                    daily.get("temperature_2m_min"),
                    index,
                ),
                apparent_temperature_max_c=_value_at(
                    daily.get("apparent_temperature_max"),
                    index,
                ),
                relative_humidity_mean=derived.get(
                    "humidity_mean"
                ),
                relative_humidity_at_max_temp=derived.get(
                    "humidity_at_peak"
                ),
                wind_speed_max_ms=_value_at(
                    daily.get("wind_speed_10m_max"),
                    index,
                ),
                precipitation_sum_mm=_value_at(
                    daily.get("precipitation_sum"),
                    index,
                ),
                solar_radiation_max_wm2=derived.get(
                    "radiation_max"
                ),
                solar_radiation_sum_mj=radiation_sum,
            )
        )

    if not forecast:
        raise ExternalServiceError(
            "The weather provider returned an empty forecast.",
            details={"provider": provider},
        )

    return ForecastResponse(
        location=_parse_location(payload, provider),
        days=len(forecast),
        forecast=forecast,
        provider=provider,
        retrieved_at=datetime.now(timezone.utc),
    )


async def get_hourly_history(
    latitude: float,
    longitude: float,
    past_days: int,
    forecast_days: int = 1,
) -> dict[str, Any]:
    validate_coordinates(latitude, longitude)

    if past_days < 1 or past_days > 92:
        raise ValidationError(
            "past_days must be between 1 and 92.",
            details={
                "field": "past_days",
                "received": past_days,
            },
        )

    if forecast_days < 1 or forecast_days > 16:
        raise ValidationError(
            "forecast_days must be between 1 and 16.",
            details={
                "field": "forecast_days",
                "received": forecast_days,
            },
        )

    params = {
        "latitude": latitude,
        "longitude": longitude,
        "timezone": settings.WEATHER_TIMEZONE,
        "wind_speed_unit": "ms",
        "temperature_unit": "celsius",
        "precipitation_unit": "mm",
        "hourly": ",".join(_ML_HISTORY_VARIABLES),
        "past_days": past_days,
        "forecast_days": forecast_days,
    }

    payload, provider = await _call_provider(
        params,
        cache_ttl=HISTORY_CACHE_TTL,
        fallback_kind="history",
        latitude=latitude,
        longitude=longitude,
        past_days=past_days,
        forecast_days=forecast_days,
    )

    hourly = payload.get("hourly")

    if not isinstance(hourly, dict) or not isinstance(
        hourly.get("time"),
        list,
    ):
        raise ExternalServiceError(
            "The weather provider returned no hourly history.",
            details={"provider": provider},
        )

    return {
        "location": _parse_location(payload, provider),
        "time": hourly.get("time") or [],
        "temperature": hourly.get("temperature_2m") or [],
        "humidity": hourly.get("relative_humidity_2m") or [],
        "wind_speed": hourly.get("wind_speed_10m") or [],
        "solar_radiation": hourly.get("shortwave_radiation") or [],
    }


def _group_hourly_by_date(
    hourly: Any,
) -> dict[date_type, dict[str, float | None]]:
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
            day,
            {
                "humidity": [],
                "temperature": [],
                "radiation": [],
            },
        )

        bucket["humidity"].append(
            _value_at(humidity_series, index)
        )
        bucket["temperature"].append(
            _value_at(temperature_series, index)
        )
        bucket["radiation"].append(
            _value_at(radiation_series, index)
        )

    result: dict[date_type, dict[str, float | None]] = {}

    for day, bucket in buckets.items():
        humidity = bucket["humidity"]
        temperature = bucket["temperature"]
        radiation = [
            value
            for value in bucket["radiation"]
            if value is not None
        ]

        present = [
            value
            for value in humidity
            if value is not None
        ]

        humidity_mean = (
            round(sum(present) / len(present), 1)
            if present
            else None
        )

        humidity_at_peak = None

        paired = [
            (temp, hum)
            for temp, hum in zip(
                temperature,
                humidity,
            )
            if temp is not None and hum is not None
        ]

        if paired:
            humidity_at_peak = max(
                paired,
                key=lambda item: item[0],
            )[1]

        result[day] = {
            "humidity_mean": humidity_mean,
            "humidity_at_peak": humidity_at_peak,
            "radiation_max": (
                max(radiation) if radiation else None
            ),
        }

    return result
