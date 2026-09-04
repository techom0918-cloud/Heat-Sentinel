"""Phase 2 tests: weather endpoints, validation, provider failure handling.

Every test mocks the provider. The suite must pass with no network access --
a test that silently depends on Open-Meteo being up is a test that fails at
the worst possible moment.
"""

from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app

CURRENT_URL = f"{settings.API_V1_PREFIX}/weather/current"
FORECAST_URL = f"{settings.API_V1_PREFIX}/weather/forecast"

# Delhi, used throughout as a representative Indian coordinate.
DELHI = {"lat": 28.6139, "lon": 77.2090}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# Provider mocking
# ---------------------------------------------------------------------------


@contextmanager
def mock_provider(payload=None, status_code: int = 200, exc=None):
    """Patch httpx so no test ever touches the network."""

    async def fake_get(self, url, *args, **kwargs):
        if exc is not None:
            raise exc
        request = httpx.Request("GET", url)
        return httpx.Response(status_code, json=payload, request=request)

    with patch.object(httpx.AsyncClient, "get", fake_get):
        yield


def current_payload(**overrides) -> dict:
    """A realistic Open-Meteo `current` response."""
    current = {
        "time": "2026-09-04T14:30",
        "interval": 900,
        "temperature_2m": 34.2,
        "relative_humidity_2m": 62,
        "apparent_temperature": 41.8,
        "is_day": 1,
        "precipitation": 0.0,
        "cloud_cover": 75,
        "surface_pressure": 991.2,
        "wind_speed_10m": 2.8,
        "wind_direction_10m": 118,
    }
    current.update(overrides)
    return {
        "latitude": 28.625,
        "longitude": 77.25,
        "elevation": 216.0,
        "timezone": "Asia/Kolkata",
        "utc_offset_seconds": 19800,
        "current": current,
        "hourly": {
            "time": [
                "2026-09-04T12:00",
                "2026-09-04T13:00",
                "2026-09-04T14:00",
                "2026-09-04T15:00",
            ],
            "shortwave_radiation": [580.0, 640.0, 612.0, 430.0],
        },
    }


def forecast_payload(days: int = 3) -> dict:
    """A realistic Open-Meteo daily + hourly response."""
    dates = [f"2026-09-{4 + offset:02d}" for offset in range(days)]

    hourly_times: list[str] = []
    hourly_temp: list[float] = []
    hourly_rh: list[float] = []
    hourly_rad: list[float] = []
    for day_index, day in enumerate(dates):
        for hour in range(24):
            hourly_times.append(f"{day}T{hour:02d}:00")
            # Peak at 15:00 so humidity_at_max_temp is deterministic.
            hourly_temp.append(28.0 + day_index + max(0, 12 - abs(15 - hour)))
            hourly_rh.append(80.0 - max(0, 12 - abs(15 - hour)) * 2)
            hourly_rad.append(0.0 if hour < 6 or hour > 18 else 100.0 * hour)

    return {
        "latitude": 28.625,
        "longitude": 77.25,
        "elevation": 216.0,
        "timezone": "Asia/Kolkata",
        "daily": {
            "time": dates,
            "temperature_2m_max": [40.0 + i for i in range(days)],
            "temperature_2m_min": [27.0 + i for i in range(days)],
            "apparent_temperature_max": [46.0 + i for i in range(days)],
            "precipitation_sum": [0.0] * days,
            "wind_speed_10m_max": [3.4] * days,
            "shortwave_radiation_sum": [21.5] * days,
        },
        "hourly": {
            "time": hourly_times,
            "temperature_2m": hourly_temp,
            "relative_humidity_2m": hourly_rh,
            "wind_speed_10m": [2.0] * len(hourly_times),
            "shortwave_radiation": hourly_rad,
        },
    }


# ---------------------------------------------------------------------------
# Valid requests
# ---------------------------------------------------------------------------


def test_current_weather_returns_parsed_conditions(client: TestClient) -> None:
    with mock_provider(current_payload()):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 200
    body = response.json()

    assert body["provider"] == "open-meteo"
    assert body["location"]["timezone"] == "Asia/Kolkata"
    assert body["location"]["elevation_m"] == 216.0

    current = body["current"]
    assert current["temperature_c"] == 34.2
    assert current["relative_humidity"] == 62.0
    assert current["wind_speed_ms"] == 2.8
    assert current["precipitation_mm"] == 0.0
    assert current["is_day"] is True


def test_current_weather_picks_solar_radiation_for_the_right_hour(
    client: TestClient,
) -> None:
    """Observation at 14:30 must take the 14:00 radiation value, not 12:00."""
    with mock_provider(current_payload()):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 200
    assert response.json()["current"]["solar_radiation_wm2"] == 612.0


def test_forecast_returns_requested_number_of_days(client: TestClient) -> None:
    with mock_provider(forecast_payload(days=5)):
        response = client.get(FORECAST_URL, params={**DELHI, "days": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["days"] == 5
    assert len(body["forecast"]) == 5
    assert body["forecast"][0]["date"] == "2026-09-04"
    assert body["forecast"][0]["temperature_max_c"] == 40.0


def test_forecast_derives_daily_humidity_from_hourly_series(
    client: TestClient,
) -> None:
    """Open-Meteo has no daily humidity aggregate; we compute it ourselves."""
    with mock_provider(forecast_payload(days=2)):
        response = client.get(FORECAST_URL, params={**DELHI, "days": 2})

    assert response.status_code == 200
    day = response.json()["forecast"][0]

    assert day["relative_humidity_mean"] is not None
    # Fixture peaks temperature at 15:00, where RH is 80 - 12*2 = 56.
    assert day["relative_humidity_at_max_temp"] == 56.0
    assert day["solar_radiation_max_wm2"] == 1800.0


def test_forecast_defaults_to_five_days(client: TestClient) -> None:
    with mock_provider(forecast_payload(days=5)):
        response = client.get(FORECAST_URL, params=DELHI)

    assert response.status_code == 200
    assert response.json()["days"] == 5


# ---------------------------------------------------------------------------
# Coordinate and range validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("latitude", [-90.1, 91, 1000, -200])
def test_invalid_latitude_is_rejected(
    client: TestClient, latitude: float
) -> None:
    response = client.get(CURRENT_URL, params={"lat": latitude, "lon": 77.2})
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "request_validation_error"


@pytest.mark.parametrize("longitude", [-180.5, 180.1, 999])
def test_invalid_longitude_is_rejected(
    client: TestClient, longitude: float
) -> None:
    response = client.get(CURRENT_URL, params={"lat": 28.6, "lon": longitude})
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "request_validation_error"


@pytest.mark.parametrize("days", [0, -1, 6, 30])
def test_invalid_days_is_rejected(client: TestClient, days: int) -> None:
    response = client.get(FORECAST_URL, params={**DELHI, "days": days})
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "request_validation_error"


def test_boundary_coordinates_are_accepted(client: TestClient) -> None:
    with mock_provider(current_payload()):
        response = client.get(CURRENT_URL, params={"lat": -90, "lon": 180})
    assert response.status_code == 200


def test_missing_coordinates_are_rejected(client: TestClient) -> None:
    response = client.get(CURRENT_URL)
    assert response.status_code == 422


def test_non_numeric_coordinates_are_rejected(client: TestClient) -> None:
    response = client.get(CURRENT_URL, params={"lat": "hot", "lon": 77.2})
    assert response.status_code == 422


def test_service_validates_independently_of_fastapi() -> None:
    """Phase 7 will call the service directly, with no HTTP layer to guard it."""
    import asyncio

    from app.core.exceptions import ValidationError
    from app.services import weather_service

    with pytest.raises(ValidationError):
        asyncio.run(weather_service.get_current_weather(120.0, 77.0))

    with pytest.raises(ValidationError):
        asyncio.run(weather_service.get_forecast(28.6, 77.2, 99))


# ---------------------------------------------------------------------------
# Provider failure handling
# ---------------------------------------------------------------------------


def test_provider_timeout_returns_502(client: TestClient) -> None:
    with mock_provider(exc=httpx.TimeoutException("timed out")):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["type"] == "external_service_error"
    assert "time" in error["message"].lower()


def test_provider_connection_error_returns_502(client: TestClient) -> None:
    with mock_provider(exc=httpx.ConnectError("dns failure")):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "external_service_error"


def test_provider_http_error_returns_502_with_reason(
    client: TestClient,
) -> None:
    payload = {"error": True, "reason": "Cannot initialize WeatherVariable"}
    with mock_provider(payload, status_code=400):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 502
    error = response.json()["error"]
    assert error["type"] == "external_service_error"
    assert "WeatherVariable" in error["details"]["reason"]


def test_provider_payload_without_current_block_returns_502(
    client: TestClient,
) -> None:
    with mock_provider({"latitude": 28.6, "longitude": 77.2}):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "external_service_error"


def test_missing_temperature_returns_502(client: TestClient) -> None:
    """Temperature is load-bearing for every later phase; never fabricate it."""
    with mock_provider(current_payload(temperature_2m=None)):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 502


def test_missing_optional_values_become_null_not_zero(
    client: TestClient,
) -> None:
    payload = current_payload(relative_humidity_2m=None, wind_speed_10m=None)
    with mock_provider(payload):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 200
    current = response.json()["current"]
    assert current["relative_humidity"] is None
    assert current["wind_speed_ms"] is None
    assert current["temperature_c"] == 34.2


def test_empty_forecast_returns_502(client: TestClient) -> None:
    payload = forecast_payload(days=1)
    payload["daily"]["time"] = []
    with mock_provider(payload):
        response = client.get(FORECAST_URL, params={**DELHI, "days": 1})

    assert response.status_code == 502


# ---------------------------------------------------------------------------
# Provider isolation
# ---------------------------------------------------------------------------


def test_wind_is_requested_in_metres_per_second() -> None:
    """WBGT and UTCI are defined on m/s. km/h would be silently wrong."""
    from app.services.weather_service import _base_params

    assert _base_params(28.6, 77.2)["wind_speed_unit"] == "ms"


def test_only_the_service_imports_the_http_client() -> None:
    """Requirement 8/9: no provider calls outside weather_service.py.

    Inspects real import statements via AST rather than grepping the source,
    so prose in a docstring cannot trip the check.
    """
    import ast
    from pathlib import Path

    forbidden = {"httpx", "requests", "urllib", "urllib3", "aiohttp"}
    routes = Path(__file__).resolve().parents[1] / "app" / "api" / "routes"

    for module in routes.glob("*.py"):
        tree = ast.parse(module.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])

        leaked = imported & forbidden
        assert not leaked, f"{module.name} imports an HTTP client: {leaked}"


def test_weather_endpoints_are_in_the_openapi_schema(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/v1/weather/current" in schema["paths"]
    assert "/api/v1/weather/forecast" in schema["paths"]
