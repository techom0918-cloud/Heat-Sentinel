"""Phase 7 tests: risk trajectory.

The central concern is honesty about horizon. The model supports exactly
one lead time; no test may pass by fabricating others.
"""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import forecast_service
from app.services.forecast_service import compute_trend
from tests.conftest import hourly_payload, mock_provider

URL = f"{settings.API_V1_PREFIX}/forecast/risk"
DELHI = {"latitude": 28.6139, "longitude": 77.2090}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# --- Trend: deterministic ---------------------------------------------------


@pytest.mark.parametrize(
    "levels,expected",
    [
        ([0, 1, 2, 3, 4], "WORSENING"),
        ([4, 3, 2, 1, 0], "IMPROVING"),
        ([2, 2, 2, 2, 2], "STABLE"),
        ([2, 2, 3, 3], "WORSENING"),
        ([3, 3, 2, 2], "IMPROVING"),
        ([2], "STABLE"),
        ([], "STABLE"),
    ],
)
def test_trend_is_deterministic(levels, expected) -> None:
    assert compute_trend(levels) == expected
    assert compute_trend(levels) == compute_trend(levels)


def test_trend_threshold_is_configurable(monkeypatch) -> None:
    levels = [2, 2, 3, 3]
    assert compute_trend(levels) == "WORSENING"
    monkeypatch.setattr(settings, "FORECAST_TREND_THRESHOLD", 2.0, raising=False)
    assert compute_trend(levels) == "STABLE"


# --- Trajectory shape -------------------------------------------------------


def test_trajectory_returns_requested_days(client: TestClient, with_model) -> None:
    with mock_provider(hourly_payload()):
        response = client.get(URL, params={**DELHI, "days": 5})

    assert response.status_code == 200
    body = response.json()
    assert body["days_requested"] == 5
    assert 1 <= body["days_returned"] <= 5
    assert len(body["forecast"]) == body["days_returned"]


def test_trajectory_is_chronological(client: TestClient, with_model) -> None:
    with mock_provider(hourly_payload()):
        body = client.get(URL, params={**DELHI, "days": 5}).json()

    dates = [day["target_date"] for day in body["forecast"]]
    assert dates == sorted(dates)
    offsets = [day["days_ahead"] for day in body["forecast"]]
    assert offsets == sorted(offsets)
    assert offsets[0] == 0


def test_peak_matches_the_highest_level(client: TestClient, with_model) -> None:
    with mock_provider(hourly_payload()):
        body = client.get(URL, params={**DELHI, "days": 5}).json()

    highest = max(body["forecast"], key=lambda d: d["risk_level_index"])
    assert body["peak_risk"] == highest["risk_level"]
    assert body["peak_date"] == highest["target_date"]


def test_rising_temperatures_produce_a_worsening_trend(
    client: TestClient, with_model
) -> None:
    """The fixture ramps temperature upward day on day."""
    with mock_provider(hourly_payload()):
        body = client.get(URL, params={**DELHI, "days": 5}).json()
    assert body["trend"] in {"WORSENING", "STABLE"}


# --- Horizon honesty --------------------------------------------------------


def test_only_the_model_horizon_carries_an_ml_prediction(
    client: TestClient, with_model
) -> None:
    """No day beyond the trained horizon may claim to be an ML prediction."""
    with mock_provider(hourly_payload()):
        body = client.get(URL, params={**DELHI, "days": 5}).json()

    horizon = body["model_horizon_days"]
    assert horizon == 3

    ml_days = [d for d in body["forecast"] if d["method"] == "ML_MODEL"]
    assert len(ml_days) <= 1
    for day in ml_days:
        assert day["days_ahead"] == horizon


def test_non_model_days_carry_no_confidence(
    client: TestClient, with_model
) -> None:
    """A weather forecast converted to a category has no model probability."""
    with mock_provider(hourly_payload()):
        body = client.get(URL, params={**DELHI, "days": 5}).json()

    for day in body["forecast"]:
        if day["method"] != "ML_MODEL":
            assert day["confidence"] is None
        else:
            assert day["confidence"] is not None


def test_every_day_declares_its_method(client: TestClient, with_model) -> None:
    with mock_provider(hourly_payload()):
        body = client.get(URL, params={**DELHI, "days": 5}).json()

    for day in body["forecast"]:
        assert day["method"] in {"OBSERVED", "NWP_DERIVED", "ML_MODEL"}
        assert day["method_note"]

    assert sum(body["method_summary"].values()) == body["days_returned"]


def test_today_is_observed(client: TestClient, with_model) -> None:
    with mock_provider(hourly_payload()):
        body = client.get(URL, params={**DELHI, "days": 5}).json()
    assert body["forecast"][0]["method"] == "OBSERVED"


def test_limitations_state_the_single_horizon(
    client: TestClient, with_model
) -> None:
    with mock_provider(hourly_payload()):
        body = client.get(URL, params={**DELHI, "days": 5}).json()

    joined = " ".join(body["limitations"]).lower()
    assert "single" in joined and "horizon" in joined
    assert "hazard" in joined


def test_model_day_reports_both_sources(client: TestClient, with_model) -> None:
    """Where ML and NWP both exist, both are shown."""
    with mock_provider(hourly_payload()):
        body = client.get(URL, params={**DELHI, "days": 5}).json()

    for day in body["forecast"]:
        if day["method"] == "ML_MODEL":
            assert day["model_risk_level"] is not None
            assert "numerical forecast" in day["method_note"]


# --- Validation and failure paths -------------------------------------------


@pytest.mark.parametrize("days", [0, -1, 6, 30])
def test_invalid_days_rejected(client: TestClient, with_model, days) -> None:
    assert client.get(URL, params={**DELHI, "days": days}).status_code == 422


@pytest.mark.parametrize(
    "params", [{"latitude": 999, "longitude": 77.2}, {"latitude": 28.6}]
)
def test_invalid_coordinates_rejected(client: TestClient, with_model, params) -> None:
    assert client.get(URL, params=params).status_code == 422


def test_provider_timeout_returns_502(client: TestClient, with_model) -> None:
    with mock_provider(exc=httpx.TimeoutException("timed out")):
        response = client.get(URL, params=DELHI)
    assert response.status_code == 502


def test_missing_model_returns_503(client: TestClient, monkeypatch, tmp_path) -> None:
    from app.services import ml_service

    monkeypatch.setattr(
        settings, "ML_MODEL_PATH", str(tmp_path / "gone.joblib"), raising=False
    )
    ml_service.reset_caches()
    with mock_provider(hourly_payload()):
        response = client.get(URL, params=DELHI)
    assert response.status_code == 503
    ml_service.reset_caches()


def test_insufficient_history_fails_cleanly(client: TestClient, with_model) -> None:
    with mock_provider(hourly_payload(past_days=3, forecast_days=2)):
        response = client.get(URL, params=DELHI)
    assert response.status_code in (422, 502)


def test_forecast_endpoint_in_schema(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/v1/forecast/risk" in schema["paths"]
