from __future__ import annotations

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import grid_risk_service


def _sample_predictions(n=30):
    rows = []
    for i in range(n):
        rows.append({
            "cell_id": f"NCR300_{i:07d}",
            "latitude": 28.5 + i * 0.01,
            "longitude": 77.0 + i * 0.01,
            "predicted_category": ["LOW", "MODERATE", "HIGH", "VERY_HIGH"][i % 4],
            "probability_LOW": 0.1, "probability_MODERATE": 0.2,
            "probability_HIGH": 0.3, "probability_VERY_HIGH": 0.4,
            "heat_index_source_weather_point": "WP_001",
            "nearest_weather_distance_km": 5.0,
            "weather_timestamp": pd.Timestamp("2025-06-15T14:00:00+05:30"),
            "batch_generated_at": pd.Timestamp("2025-06-15T15:00:00+05:30"),
        })
    return pd.DataFrame(rows)


@pytest.fixture
def with_grid_predictions(tmp_path, monkeypatch):
    path = tmp_path / "grid_predictions_300m.parquet"
    _sample_predictions().to_parquet(path)
    monkeypatch.setattr(
        settings, "HEAT_INDEX_GRID_PREDICTIONS_PATH", str(path), raising=False
    )
    monkeypatch.setattr(settings, "GRID_RISK_MAX_CELLS", 10, raising=False)
    grid_risk_service.reset_cache()
    yield
    grid_risk_service.reset_cache()


@pytest.fixture
def client():
    return TestClient(app)


def test_grid_predictions_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(
        settings, "HEAT_INDEX_GRID_PREDICTIONS_PATH", str(tmp_path / "nope.parquet"),
        raising=False,
    )
    grid_risk_service.reset_cache()
    with pytest.raises(grid_risk_service.GridPredictionsUnavailableError):
        grid_risk_service.get_grid_risk(None, None, None, None)
    grid_risk_service.reset_cache()


def test_whole_grid_capped(with_grid_predictions):
    result = grid_risk_service.get_grid_risk(None, None, None, None)
    assert result["total_cells_in_bbox"] == 30
    assert result["count"] == 10
    assert result["truncated"] is True
    assert result["geometry_available"] is False


def test_bbox_filters(with_grid_predictions):
    result = grid_risk_service.get_grid_risk(28.5, 28.55, 77.0, 77.05)
    assert result["count"] <= 6
    for cell in result["cells"]:
        assert 28.5 <= cell["latitude"] <= 28.55


def test_incomplete_bbox_rejected(with_grid_predictions):
    from app.core.exceptions import HeatSentinalError

    with pytest.raises(HeatSentinalError):
        grid_risk_service.get_grid_risk(28.5, None, None, None)


def test_api_grid_risk(client, with_grid_predictions):
    r = client.get("/api/v1/grid/risk", params={
        "min_lat": 28.5, "max_lat": 28.6, "min_lon": 77.0, "max_lon": 77.1,
    })
    assert r.status_code == 200
    body = r.json()
    assert body["geometry_available"] is False
    assert "weather_resolution" in body


def test_api_grid_risk_unavailable(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        settings, "HEAT_INDEX_GRID_PREDICTIONS_PATH", str(tmp_path / "nope.parquet"),
        raising=False,
    )
    grid_risk_service.reset_cache()
    r = client.get("/api/v1/grid/risk")
    assert r.status_code == 503
    grid_risk_service.reset_cache()
