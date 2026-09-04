"""Phase 3 tests: thermal stress engine.

No test touches the network. The weather provider is mocked for the
`/thermal/current` integration tests.

Expected values are derived from the implemented published formulas, never
invented. NWS reference-table cases are asserted with a tolerance because
the published chart is rounded to whole degrees Fahrenheit and the Rothfusz
regression carries a stated error of about +/- 1.3 F.
"""

from contextlib import contextmanager
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import thermal_service
from app.services.thermal_service import (
    _heat_index_fahrenheit,
    celsius_to_fahrenheit,
    fahrenheit_to_celsius,
    heat_index_category,
    heat_index_celsius,
    utci_celsius,
    wbgt_shade_celsius,
    wet_bulb_stull_celsius,
)

CALCULATE_URL = f"{settings.API_V1_PREFIX}/thermal/calculate"
CURRENT_URL = f"{settings.API_V1_PREFIX}/thermal/current"

DELHI = {"latitude": 28.6139, "longitude": 77.2090}

ACCEPTANCE_INPUT = {
    "temperature": 42.0,
    "relative_humidity": 60.0,
    "wind_speed": 2.0,
    "solar_radiation": 500.0,
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@contextmanager
def mock_weather(payload=None, status_code: int = 200, exc=None):
    """Patch the HTTP client so weather integration tests stay offline."""

    async def fake_get(self, url, *args, **kwargs):
        if exc is not None:
            raise exc
        request = httpx.Request("GET", url)
        return httpx.Response(status_code, json=payload, request=request)

    with patch.object(httpx.AsyncClient, "get", fake_get):
        yield


def weather_payload(**overrides) -> dict:
    current = {
        "time": "2026-09-04T14:30",
        "interval": 900,
        "temperature_2m": 42.0,
        "relative_humidity_2m": 60.0,
        "apparent_temperature": 51.0,
        "is_day": 1,
        "precipitation": 0.0,
        "cloud_cover": 10,
        "surface_pressure": 991.2,
        "wind_speed_10m": 2.0,
        "wind_direction_10m": 118,
    }
    current.update(overrides)
    return {
        "latitude": 28.625,
        "longitude": 77.25,
        "elevation": 216.0,
        "timezone": "Asia/Kolkata",
        "current": current,
        "hourly": {
            "time": ["2026-09-04T13:00", "2026-09-04T14:00"],
            "shortwave_radiation": [640.0, 700.0],
        },
    }


# ---------------------------------------------------------------------------
# 1. Heat Index
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "temp_f,rh,expected_f",
    [
        (80, 40, 80),
        (86, 90, 105),
        (90, 60, 100),
        (100, 50, 120),
        (110, 40, 136),
    ],
)
def test_heat_index_matches_nws_reference_table(temp_f, rh, expected_f) -> None:
    """Chart is rounded to whole degrees; Rothfusz error is about +/-1.3 F."""
    assert _heat_index_fahrenheit(temp_f, rh) == pytest.approx(
        expected_f, abs=2.0
    )


def test_rothfusz_is_not_applied_in_cool_conditions() -> None:
    """Below ~80 F the simple form must be used, not the regression.

    Rothfusz at 20 C / 50% RH returns a wildly wrong value; the simple form
    returns something close to the air temperature.
    """
    result = heat_index_celsius(20.0, 50.0)
    assert 17.0 < result < 22.0


def test_low_humidity_correction_reduces_heat_index() -> None:
    """RH < 13% with 80-112 F triggers a downward adjustment."""
    dry = heat_index_celsius(35.0, 10.0)
    without_trigger = heat_index_celsius(35.0, 14.0)
    assert dry < without_trigger


def test_high_humidity_correction_increases_heat_index() -> None:
    """RH > 85% with 80-87 F triggers an upward adjustment."""
    assert heat_index_celsius(30.0, 90.0) > heat_index_celsius(30.0, 84.0)


def test_heat_index_rises_with_humidity() -> None:
    values = [heat_index_celsius(38.0, rh) for rh in (20, 40, 60, 80)]
    assert values == sorted(values)


def test_heat_index_rises_with_temperature() -> None:
    values = [heat_index_celsius(t, 60.0) for t in (30, 34, 38, 42)]
    assert values == sorted(values)


def test_unit_conversions_round_trip() -> None:
    assert celsius_to_fahrenheit(0.0) == pytest.approx(32.0)
    assert celsius_to_fahrenheit(100.0) == pytest.approx(212.0)
    assert fahrenheit_to_celsius(celsius_to_fahrenheit(37.5)) == pytest.approx(
        37.5
    )


# ---------------------------------------------------------------------------
# 2. Wet bulb and WBGT
# ---------------------------------------------------------------------------


def test_wet_bulb_never_exceeds_air_temperature() -> None:
    for temperature in (10.0, 25.0, 35.0, 45.0):
        for humidity in (10.0, 50.0, 95.0):
            assert (
                wet_bulb_stull_celsius(temperature, humidity) <= temperature + 0.5
            )


def test_wet_bulb_approaches_air_temperature_at_saturation() -> None:
    """At ~100% RH, wet bulb and dry bulb converge."""
    assert wet_bulb_stull_celsius(30.0, 99.0) == pytest.approx(30.0, abs=1.0)


def test_wbgt_uses_the_documented_shade_weighting() -> None:
    """WBGT = 0.7*Tw + 0.3*Ta, exactly as in heat_pipeline.py."""
    temperature, humidity = 42.0, 60.0
    wet_bulb = wet_bulb_stull_celsius(temperature, humidity)
    expected = 0.7 * wet_bulb + 0.3 * temperature
    assert wbgt_shade_celsius(temperature, humidity) == pytest.approx(expected)


def test_wbgt_lies_between_wet_bulb_and_air_temperature() -> None:
    temperature, humidity = 40.0, 50.0
    wet_bulb = wet_bulb_stull_celsius(temperature, humidity)
    assert wet_bulb < wbgt_shade_celsius(temperature, humidity) < temperature


def test_wbgt_ignores_solar_radiation() -> None:
    """Solar radiation must not change WBGT -- see the documented reason."""
    low = thermal_service.calculate_thermal_stress(40.0, 55.0, 2.0, 0.0)
    high = thermal_service.calculate_thermal_stress(40.0, 55.0, 2.0, 1000.0)
    assert low.wbgt == high.wbgt
    assert low.solar_radiation == 0.0
    assert high.solar_radiation == 1000.0


def test_wbgt_is_never_classified() -> None:
    """ISO 7243 / ACGIH limits apply to outdoor WBGT, not this shade form."""
    result = thermal_service.calculate_thermal_stress(42.0, 60.0, 2.0)
    assert result.wbgt_category == "NOT_CLASSIFIED"


# ---------------------------------------------------------------------------
# 3. UTCI
# ---------------------------------------------------------------------------


def test_utci_returns_value_and_official_category() -> None:
    value, category, _ = utci_celsius(42.0, 60.0, 2.0)
    assert value is not None
    assert value > 42.0  # humid heat pushes UTCI above air temperature
    assert category != "NOT_AVAILABLE"


def test_utci_wind_is_clamped_to_model_limits() -> None:
    _, _, low_notes = utci_celsius(35.0, 50.0, 0.1)
    assert any("minimum" in note for note in low_notes)

    _, _, high_notes = utci_celsius(35.0, 50.0, 40.0)
    assert any("capped" in note for note in high_notes)


def test_utci_unavailable_above_model_temperature_limit() -> None:
    """Indian extremes exceed 50 C; UTCI must decline rather than extrapolate."""
    value, category, notes = utci_celsius(52.0, 30.0, 2.0)
    assert value is None
    assert category == "NOT_AVAILABLE"
    assert notes


def test_utci_never_substitutes_a_fake_formula() -> None:
    """With the library absent, UTCI is null -- not an invented number."""
    with patch.object(thermal_service, "UTCI_AVAILABLE", False):
        value, category, notes = utci_celsius(42.0, 60.0, 2.0)
    assert value is None
    assert category == "NOT_AVAILABLE"
    assert any("pythermalcomfort" in note for note in notes)


def test_higher_wind_lowers_utci_in_heat() -> None:
    calm, _, _ = utci_celsius(40.0, 40.0, 1.0)
    breezy, _, _ = utci_celsius(40.0, 40.0, 6.0)
    assert breezy < calm


# ---------------------------------------------------------------------------
# 4. Categories
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "heat_index,expected",
    [
        (20.0, "LOW"),
        (26.9, "LOW"),
        (27.0, "MODERATE"),
        (31.9, "MODERATE"),
        (32.0, "HIGH"),
        (40.9, "HIGH"),
        (41.0, "VERY_HIGH"),
        (53.9, "VERY_HIGH"),
        (54.0, "EXTREME"),
        (80.0, "EXTREME"),
    ],
)
def test_heat_index_category_edges(heat_index, expected) -> None:
    """Edges 27/32/41/54 C, matching heat_pipeline.py."""
    assert heat_index_category(heat_index) == expected


def test_category_edges_come_from_configuration() -> None:
    assert settings.heat_index_bounds_list == [27.0, 32.0, 41.0, 54.0]
    assert settings.heat_index_categories_list == [
        "LOW",
        "MODERATE",
        "HIGH",
        "VERY_HIGH",
        "EXTREME",
    ]
    assert (
        len(settings.heat_index_categories_list)
        == len(settings.heat_index_bounds_list) + 1
    )


# ---------------------------------------------------------------------------
# 5. POST /thermal/calculate
# ---------------------------------------------------------------------------


def test_calculate_returns_all_three_indices(client: TestClient) -> None:
    response = client.post(CALCULATE_URL, json=ACCEPTANCE_INPUT)
    assert response.status_code == 200

    body = response.json()
    assert body["temperature"] == 42.0
    assert body["relative_humidity"] == 60.0
    assert body["wind_speed"] == 2.0
    assert body["heat_index"] is not None
    assert body["wbgt"] is not None
    assert body["utci"] is not None


def test_acceptance_case_is_numerically_sensible(client: TestClient) -> None:
    """42 C / 60% RH must read as severe on every index."""
    response = client.post(CALCULATE_URL, json=ACCEPTANCE_INPUT)
    body = response.json()

    assert body["heat_index"] > 42.0
    assert body["heat_index_category"] == "EXTREME"
    # Shade WBGT sits between wet bulb and air temperature.
    assert body["wet_bulb_temperature"] < body["wbgt"] < 42.0
    assert body["utci"] > 42.0
    assert "HEAT_STRESS" in body["utci_category"]


def test_calculate_reports_assumptions_and_methods(client: TestClient) -> None:
    body = client.post(CALCULATE_URL, json=ACCEPTANCE_INPUT).json()

    assert len(body["assumptions"]) >= 5
    joined = " ".join(body["assumptions"]).lower()
    assert "shade approximation" in joined
    assert "mean radiant temperature" in joined

    indices = {method["index"] for method in body["methods"]}
    assert indices == {"heat_index", "wbgt", "utci"}

    classifications = {
        method["index"]: method["classification"] for method in body["methods"]
    }
    assert classifications["heat_index"] == "RECOGNISED_CALCULATION"
    assert classifications["wbgt"] == "APPROXIMATION"
    assert classifications["utci"] == "REFERENCE_IMPLEMENTATION"


def test_extreme_heat_index_is_flagged_as_extrapolation(
    client: TestClient,
) -> None:
    """Beyond the 137 F chart the regression is extrapolating; say so."""
    body = client.post(CALCULATE_URL, json=ACCEPTANCE_INPUT).json()
    assert any("extrapolat" in note.lower() for note in body["notes"])


def test_wind_speed_defaults_to_zero(client: TestClient) -> None:
    response = client.post(
        CALCULATE_URL, json={"temperature": 35.0, "relative_humidity": 50.0}
    )
    assert response.status_code == 200
    assert response.json()["wind_speed"] == 0.0


def test_calculation_is_deterministic() -> None:
    """Phase 5 and the ML pipeline must get identical numbers."""
    first = thermal_service.calculate_thermal_stress(41.5, 58.0, 3.2, 620.0)
    second = thermal_service.calculate_thermal_stress(41.5, 58.0, 3.2, 620.0)
    assert first.model_dump() == second.model_dump()


# ---------------------------------------------------------------------------
# 6. Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    [
        {"temperature": 200.0, "relative_humidity": 50.0},
        {"temperature": -200.0, "relative_humidity": 50.0},
        {"temperature": 35.0, "relative_humidity": 101.0},
        {"temperature": 35.0, "relative_humidity": -1.0},
        {"temperature": 35.0, "relative_humidity": 50.0, "wind_speed": -2.0},
        {"temperature": 35.0, "relative_humidity": 50.0, "solar_radiation": -5.0},
        {"relative_humidity": 50.0},
        {"temperature": "hot", "relative_humidity": 50.0},
    ],
)
def test_invalid_input_returns_422(client: TestClient, payload) -> None:
    response = client.post(CALCULATE_URL, json=payload)
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "request_validation_error"


def test_extreme_but_legitimate_heat_is_accepted(client: TestClient) -> None:
    """51 C happens in India. Validation must not block it."""
    response = client.post(
        CALCULATE_URL, json={"temperature": 51.0, "relative_humidity": 25.0}
    )
    assert response.status_code == 200
    assert response.json()["heat_index"] is not None


def test_service_validates_independently_of_fastapi() -> None:
    from app.core.exceptions import ValidationError

    with pytest.raises(ValidationError):
        thermal_service.calculate_thermal_stress(200.0, 50.0)
    with pytest.raises(ValidationError):
        thermal_service.calculate_thermal_stress(35.0, 150.0)
    with pytest.raises(ValidationError):
        thermal_service.calculate_thermal_stress(35.0, 50.0, -1.0)


# ---------------------------------------------------------------------------
# 7. GET /thermal/current -- weather integration
# ---------------------------------------------------------------------------


def test_current_combines_weather_and_thermal(client: TestClient) -> None:
    with mock_weather(weather_payload()):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 200
    body = response.json()

    assert body["provider"] == "open-meteo"
    assert body["location"]["timezone"] == "Asia/Kolkata"
    assert body["weather"]["temperature_c"] == 42.0
    assert body["thermal"]["temperature"] == 42.0
    assert body["thermal"]["heat_index"] is not None
    assert body["thermal"]["wbgt"] is not None
    assert body["thermal"]["utci"] is not None


def test_current_passes_provider_solar_radiation_through(
    client: TestClient,
) -> None:
    with mock_weather(weather_payload()):
        body = client.get(CURRENT_URL, params=DELHI).json()
    assert body["thermal"]["solar_radiation"] == 700.0


def test_current_rejects_invalid_coordinates(client: TestClient) -> None:
    response = client.get(
        CURRENT_URL, params={"latitude": 999, "longitude": 77.2}
    )
    assert response.status_code == 422


def test_current_propagates_provider_timeout(client: TestClient) -> None:
    with mock_weather(exc=httpx.TimeoutException("timed out")):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 502
    assert response.json()["error"]["type"] == "external_service_error"


def test_current_fails_cleanly_when_humidity_is_missing(
    client: TestClient,
) -> None:
    """No humidity means no thermal stress -- never guess a value."""
    with mock_weather(weather_payload(relative_humidity_2m=None)):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 502
    assert "humidity" in response.json()["error"]["message"].lower()


def test_current_handles_missing_wind(client: TestClient) -> None:
    with mock_weather(weather_payload(wind_speed_10m=None)):
        response = client.get(CURRENT_URL, params=DELHI)

    assert response.status_code == 200
    body = response.json()
    assert body["thermal"]["wind_speed"] == 0.0
    assert any("wind" in note.lower() for note in body["thermal"]["notes"])


def test_thermal_route_does_not_import_an_http_client() -> None:
    """Requirement 4: no Open-Meteo call inside thermal.py."""
    import ast
    from pathlib import Path

    forbidden = {"httpx", "requests", "urllib", "urllib3", "aiohttp"}
    module = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "api"
        / "routes"
        / "thermal.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not imported & forbidden


def test_thermal_service_makes_no_network_calls() -> None:
    """The engine must stay pure so the ML pipeline can reuse it offline."""
    import ast
    from pathlib import Path

    module = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "thermal_service.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])

    assert not imported & {"httpx", "requests", "urllib", "aiohttp"}


# ---------------------------------------------------------------------------
# 8. Phases 1 and 2 still work
# ---------------------------------------------------------------------------


def test_thermal_endpoints_are_in_the_openapi_schema(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/v1/thermal/calculate" in schema["paths"]
    assert "/api/v1/thermal/current" in schema["paths"]
    # Phase 1 and 2 routes must survive.
    assert "/api/v1/health" in schema["paths"]
    assert "/api/v1/weather/current" in schema["paths"]
    assert "/api/v1/weather/forecast" in schema["paths"]
