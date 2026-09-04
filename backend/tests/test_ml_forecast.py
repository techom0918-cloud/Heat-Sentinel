"""Tests for the trained-model hazard forecast.

No test touches the network or requires the real artifact. A small model is
trained on synthetic features inside a fixture, so both the
model-present and model-absent paths are covered.
"""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import ml_service

FORECAST_URL = f"{settings.API_V1_PREFIX}/risk/forecast"
MODEL_URL = f"{settings.API_V1_PREFIX}/risk/model"
DELHI = {"latitude": 28.6139, "longitude": 77.2090}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@contextmanager
def mock_provider(payload=None, status_code: int = 200, exc=None):
    async def fake_get(self, url, *args, **kwargs):
        if exc is not None:
            raise exc
        request = httpx.Request("GET", url)
        return httpx.Response(status_code, json=payload, request=request)

    with patch.object(httpx.AsyncClient, "get", fake_get):
        yield


def history_payload(days: int = 35) -> dict:
    """Synthetic hourly history in the provider's response shape."""
    import numpy as np
    import pandas as pd

    stamps = pd.date_range("2026-05-01", periods=days * 24, freq="h")
    hour = stamps.hour.values
    doy = stamps.dayofyear.values
    temperature = (
        34 + 6 * np.sin(2 * np.pi * (hour - 9) / 24) + 0.02 * doy
    )
    humidity = np.clip(55 - 0.5 * (temperature - 34), 5, 99)

    return {
        "latitude": 28.625,
        "longitude": 77.25,
        "elevation": 216.0,
        "timezone": "Asia/Kolkata",
        "hourly": {
            "time": [s.strftime("%Y-%m-%dT%H:%M") for s in stamps],
            "temperature_2m": [round(float(v), 1) for v in temperature],
            "relative_humidity_2m": [round(float(v), 1) for v in humidity],
            "wind_speed_10m": [2.0] * len(stamps),
            "shortwave_radiation": [
                float(max(0.0, 800 * np.sin(np.pi * (h - 6) / 12))) for h in hour
            ],
        },
    }


@pytest.fixture(scope="module")
def trained_artifact(tmp_path_factory) -> Path:
    """Train a small model on synthetic data and dump a real artifact.

    Uses the pipeline's own feature engineering, so the artifact has the
    same shape the production one does.
    """
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import RandomForestClassifier

    pipeline = ml_service.load_pipeline_module()

    stamps = pd.date_range("2023-01-01", "2024-12-31", freq="h")
    hour = stamps.hour.values
    doy = stamps.dayofyear.values
    rng = np.random.default_rng(0)
    frame = pd.DataFrame(
        {
            "city": "TestCity",
            "timestamp": stamps,
            "temperature": (
                26
                + 9 * np.sin(2 * np.pi * (doy - 100) / 365.25)
                + 6 * np.sin(2 * np.pi * (hour - 9) / 24)
                + rng.normal(0, 1.2, len(stamps))
            ),
            "humidity": np.clip(
                60 + 15 * np.sin(2 * np.pi * (doy - 190) / 365.25), 5, 99
            ),
            "wind_speed": 2.0,
            "solar_radiation": np.clip(
                800 * np.sin(np.pi * (hour - 6) / 12), 0, None
            ),
        }
    )
    frame["heat_index"] = pipeline.calculate_heat_index(
        frame["temperature"], frame["humidity"]
    )
    frame["wbgt"] = pipeline.calculate_wbgt(
        frame["temperature"], frame["humidity"]
    )
    frame["utci"] = pipeline.calculate_utci(
        frame["temperature"], frame["humidity"], frame["wind_speed"]
    )

    engineered = pipeline.engineer_features(frame)
    features = pipeline.get_feature_columns(engineered)
    model = RandomForestClassifier(n_estimators=12, random_state=0)
    model.fit(engineered[features], engineered["target"])

    path = tmp_path_factory.mktemp("ml") / "heat_model.joblib"
    joblib.dump(
        {
            "model": model,
            "scaler": None,
            "features": features,
            "risk_levels": pipeline.RISK_LEVELS,
            "horizon_days": pipeline.HORIZON,
            "heat_index_edges": pipeline.HEAT_INDEX_EDGES,
            "test_metrics": {
                "accuracy": 0.76,
                "f1": 0.69,
                "POD": 0.918,
                "FAR": 0.105,
                "CSI": 0.829,
                "hits": 1035,
                "misses": 93,
                "false_alarms": 121,
            },
        },
        path,
    )
    return path


@pytest.fixture
def with_model(trained_artifact, monkeypatch):
    monkeypatch.setattr(
        settings, "ML_MODEL_PATH", str(trained_artifact), raising=False
    )
    ml_service.reset_caches()
    yield
    ml_service.reset_caches()


@pytest.fixture
def without_model(monkeypatch, tmp_path):
    monkeypatch.setattr(
        settings, "ML_MODEL_PATH", str(tmp_path / "absent.joblib"), raising=False
    )
    ml_service.reset_caches()
    yield
    ml_service.reset_caches()


# ---------------------------------------------------------------------------
# Model absent
# ---------------------------------------------------------------------------


def test_forecast_returns_503_without_artifact(
    client: TestClient, without_model
) -> None:
    """Degrade with a clear message, never a stack trace."""
    response = client.get(FORECAST_URL, params=DELHI)
    assert response.status_code == 503
    error = response.json()["error"]
    assert error["type"] == "model_unavailable"
    assert "heat_pipeline" in error["message"]


def test_model_status_reports_unavailable(
    client: TestClient, without_model
) -> None:
    body = client.get(MODEL_URL).json()
    assert body["available"] is False
    assert body["model_info"] is None
    assert "predict" in body["detail"]


def test_heuristic_endpoint_still_works_without_a_model(
    client: TestClient, without_model
) -> None:
    """The Phase 5 heuristic must not depend on the artifact."""
    response = client.post(
        f"{settings.API_V1_PREFIX}/risk/predict",
        json={
            "temperature_c": 42.0,
            "relative_humidity": 65.0,
            "heat_index": 49.2,
            "wbgt": 31.5,
            "utci": 43.1,
            "vulnerability_score": 0.78,
        },
    )
    assert response.status_code == 200


# ---------------------------------------------------------------------------
# Model present
# ---------------------------------------------------------------------------


def test_forecast_returns_a_prediction(client: TestClient, with_model) -> None:
    with mock_provider(history_payload()):
        response = client.get(FORECAST_URL, params=DELHI)

    assert response.status_code == 200
    body = response.json()

    assert body["predicted_category"] in body["model_info"]["risk_levels"]
    assert body["horizon_days"] == 3
    assert body["based_on"] < body["issued_for"]
    assert 0.0 <= body["confidence"] <= 1.0
    assert body["days_of_history_used"] >= 1


def test_forecast_publishes_test_metrics(client: TestClient, with_model) -> None:
    """Every prediction must carry the model's measured skill."""
    with mock_provider(history_payload()):
        body = client.get(FORECAST_URL, params=DELHI).json()

    metrics = body["model_info"]["test_metrics"]
    assert metrics["CSI"] == pytest.approx(0.829)
    assert metrics["POD"] == pytest.approx(0.918)
    assert metrics["misses"] == 93


def test_forecast_publishes_limitations(client: TestClient, with_model) -> None:
    with mock_provider(history_payload()):
        body = client.get(FORECAST_URL, params=DELHI).json()

    joined = " ".join(body["limitations"]).upper()
    assert "EXTREME" in joined
    assert "HAZARD" in joined
    assert "NOT A HEALTH" in joined or "NOT A MEDICALLY" in body["disclaimer"].upper()


def test_forecast_includes_persistence_baseline(
    client: TestClient, with_model
) -> None:
    """current_category lets a reader see what the model adds over persistence."""
    with mock_provider(history_payload()):
        body = client.get(FORECAST_URL, params=DELHI).json()
    assert body["current_category"] in body["model_info"]["risk_levels"]
    assert isinstance(body["current_heat_index_max"], float)


def test_class_probabilities_sum_to_one(client: TestClient, with_model) -> None:
    with mock_provider(history_payload()):
        body = client.get(FORECAST_URL, params=DELHI).json()
    assert sum(body["class_probabilities"].values()) == pytest.approx(1.0, abs=1e-3)


def test_model_status_reports_available(client: TestClient, with_model) -> None:
    body = client.get(MODEL_URL).json()
    assert body["available"] is True
    assert body["model_info"]["feature_count"] > 0
    assert "ERA5" in body["model_info"]["trained_on"]


# ---------------------------------------------------------------------------
# Failure paths
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "params",
    [
        {"latitude": 999, "longitude": 77.2},
        {"latitude": 28.6, "longitude": 500},
        {"latitude": 28.6},
    ],
)
def test_invalid_coordinates_return_422(
    client: TestClient, with_model, params
) -> None:
    assert client.get(FORECAST_URL, params=params).status_code == 422


def test_provider_timeout_returns_502(client: TestClient, with_model) -> None:
    with mock_provider(exc=httpx.TimeoutException("timed out")):
        response = client.get(FORECAST_URL, params=DELHI)
    assert response.status_code == 502
    assert response.json()["error"]["type"] == "external_service_error"


def test_insufficient_history_fails_cleanly(
    client: TestClient, with_model
) -> None:
    """Fewer than 14 complete days cannot produce the rolling features."""
    with mock_provider(history_payload(days=5)):
        response = client.get(FORECAST_URL, params=DELHI)
    assert response.status_code == 422
    assert "14" in response.json()["error"]["message"]


def test_empty_history_fails_cleanly(client: TestClient, with_model) -> None:
    payload = history_payload()
    payload["hourly"]["time"] = []
    with mock_provider(payload):
        assert client.get(FORECAST_URL, params=DELHI).status_code in (422, 502)


def test_malformed_artifact_is_rejected(client: TestClient, monkeypatch, tmp_path) -> None:
    """An artifact missing required keys must not half-work."""
    import joblib

    bad = tmp_path / "bad.joblib"
    joblib.dump({"model": None}, bad)
    monkeypatch.setattr(settings, "ML_MODEL_PATH", str(bad), raising=False)
    ml_service.reset_caches()

    response = client.get(FORECAST_URL, params=DELHI)
    assert response.status_code == 503
    assert "missing" in str(response.json()["error"]["details"]).lower()
    ml_service.reset_caches()


# ---------------------------------------------------------------------------
# Train / serve parity
# ---------------------------------------------------------------------------


def test_features_are_built_by_the_pipeline_not_reimplemented() -> None:
    """Reimplementing feature engineering would drift silently."""
    import ast

    module = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "ml_service.py"
    )
    source = module.read_text(encoding="utf-8")
    tree = ast.parse(source)

    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "engineer_features" in calls
    # The 84 feature names must not be hand-listed here.
    assert "_rmean_14" not in source
    assert "hot_streak" not in source


def test_design_matrix_matches_the_artifact_feature_order(
    with_model, trained_artifact
) -> None:
    """Positional mismatch yields confident, silently wrong predictions."""
    import joblib

    artifact = joblib.load(trained_artifact)
    loaded = ml_service.load_artifact()
    assert list(loaded["features"]) == list(artifact["features"])


def test_forecast_endpoints_are_in_the_openapi_schema(
    client: TestClient,
) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/v1/risk/forecast" in schema["paths"]
    assert "/api/v1/risk/model" in schema["paths"]
    for path in (
        "/api/v1/health",
        "/api/v1/weather/current",
        "/api/v1/thermal/calculate",
        "/api/v1/vulnerability/calculate",
        "/api/v1/risk/predict",
    ):
        assert path in schema["paths"]
