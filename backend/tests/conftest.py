"""Shared fixtures for Phase 7-9 tests."""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest

from app.core.config import settings
from app.services import ml_service


@contextmanager
def mock_provider(payload=None, exc=None, status_code: int = 200):
    """Patch httpx so no test touches the network."""

    async def fake_get(self, url, *args, **kwargs):
        if exc is not None:
            raise exc
        return httpx.Response(
            status_code, json=payload, request=httpx.Request("GET", url)
        )

    with patch.object(httpx.AsyncClient, "get", fake_get):
        yield


def hourly_payload(past_days: int = 35, forecast_days: int = 6) -> dict:
    """Hourly series spanning past and forecast days, provider-shaped."""
    import numpy as np
    import pandas as pd

    end = pd.Timestamp.today().normalize() + pd.Timedelta(days=forecast_days)
    start = pd.Timestamp.today().normalize() - pd.Timedelta(days=past_days)
    stamps = pd.date_range(start, end, freq="h", inclusive="left")

    hour = stamps.hour.values
    day_index = (stamps - start).days.values
    # Rising ramp so the trajectory has a clear worsening trend.
    temperature = (
        30 + 0.25 * day_index + 7 * np.sin(2 * np.pi * (hour - 9) / 24)
    )
    humidity = np.clip(60 - 0.4 * (temperature - 30), 5, 99)

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


def current_payload(**overrides) -> dict:
    """Provider-shaped current-conditions payload."""
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
            "time": ["2026-09-04T14:00"],
            "shortwave_radiation": [700.0],
        },
    }


@pytest.fixture(scope="session")
def trained_artifact(tmp_path_factory) -> Path:
    """A real multiclass model artifact, built with the actual pipeline."""
    import joblib
    import numpy as np
    import pandas as pd
    from sklearn.ensemble import RandomForestClassifier

    pipeline = ml_service.load_pipeline_module()

    stamps = pd.date_range("2022-01-01", "2024-12-31", freq="h")
    hour, doy = stamps.hour.values, stamps.dayofyear.values
    rng = np.random.default_rng(11)
    frame = pd.DataFrame(
        {
            "city": "T",
            "timestamp": stamps,
            "temperature": (
                27
                + 10 * np.sin(2 * np.pi * (doy - 100) / 365.25)
                + 7 * np.sin(2 * np.pi * (hour - 9) / 24)
                + rng.normal(0, 1.3, len(stamps))
            ),
            "humidity": np.clip(
                60 + 18 * np.sin(2 * np.pi * (doy - 190) / 365.25), 5, 99
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
    model = RandomForestClassifier(n_estimators=15, random_state=0)
    model.fit(engineered[features], engineered["target"])

    path = tmp_path_factory.mktemp("phase789") / "heat_model.joblib"
    joblib.dump(
        {
            "model": model,
            "scaler": None,
            "features": features,
            "risk_levels": pipeline.RISK_LEVELS,
            "horizon_days": pipeline.HORIZON,
            "heat_index_edges": pipeline.HEAT_INDEX_EDGES,
            "test_metrics": {"CSI": 0.868},
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
