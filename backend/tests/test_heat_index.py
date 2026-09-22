"""Tests for Phase 8 (heat_index_service) and Phase 11 (SHAP explanation).

Follows the repo's existing convention (see conftest.py's `trained_artifact`
/ `with_model` for ml_service): build a REAL small bundle with the actual
imputer/model classes rather than mocking them away, so a broken
predict/explain path fails here instead of only in production.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from lightgbm import LGBMClassifier
from sklearn.impute import SimpleImputer

from app.core.config import settings
from app.main import app
from app.services import heat_index_service

FEATURES = [
    "temperature_2m_c", "relative_humidity_pct", "wind_speed_10m_ms",
    "shortwave_radiation_wm2", "month", "hour", "latitude", "longitude",
    "lst_mean_c_mean", "ndvi_mean_mean", "elevation_mean_m_mean",
]
CLASSES = ["LOW", "MODERATE", "HIGH", "VERY_HIGH"]


def _make_bundle(tmp_path):
    """A tiny but REAL bundle: same keys, same object types, as the
    production heat_index_model.joblib, just trained on synthetic rows."""
    import joblib

    rng = np.random.default_rng(0)
    n = 400
    temp = rng.uniform(20, 48, n)
    rh = rng.uniform(10, 95, n)
    df = pd.DataFrame({
        "temperature_2m_c": temp,
        "relative_humidity_pct": rh,
        "wind_speed_10m_ms": rng.uniform(0, 8, n),
        "shortwave_radiation_wm2": rng.uniform(0, 900, n),
        "month": rng.integers(1, 13, n),
        "hour": rng.integers(0, 24, n),
        "latitude": rng.uniform(28.0, 29.0, n),
        "longitude": rng.uniform(76.5, 77.5, n),
        "lst_mean_c_mean": temp + rng.normal(0, 2, n),
        "ndvi_mean_mean": rng.uniform(-0.1, 0.6, n),
        "elevation_mean_m_mean": rng.uniform(180, 300, n),
    })
    # Simple synthetic label rule so all 4 classes actually appear.
    hi_proxy = temp + 0.3 * (rh - 40)
    labels = pd.Series(
        pd.cut(hi_proxy, bins=[-np.inf, 27, 32, 41, np.inf], labels=CLASSES)
    ).astype(str)

    imputer = SimpleImputer(strategy="median").fit(df[FEATURES])
    model = LGBMClassifier(n_estimators=20, num_leaves=7, verbose=-1, random_state=0)
    model.fit(imputer.transform(df[FEATURES]), labels)

    bundle = {
        "model": model, "imputer": imputer,
        "feature_names": FEATURES, "class_names": sorted(labels.unique().tolist()),
    }
    path = tmp_path / "heat_index_model.joblib"
    joblib.dump(bundle, path)

    metadata = {
        "target_classes_all": ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"],
        "classes_with_no_training_data": ["EXTREME"],
        "training_period": [2022], "validation_period": [2023],
        "test_period": [2024, 2025], "metrics": {"validation": {"macro_f1": 0.9}},
    }
    meta_path = tmp_path / "model_metadata.json"
    import json
    meta_path.write_text(json.dumps(metadata))
    return path, meta_path


@pytest.fixture
def with_heat_index_model(tmp_path, monkeypatch):
    model_path, meta_path = _make_bundle(tmp_path)
    monkeypatch.setattr(settings, "HEAT_INDEX_MODEL_PATH", str(model_path), raising=False)
    monkeypatch.setattr(settings, "HEAT_INDEX_METADATA_PATH", str(meta_path), raising=False)
    heat_index_service.reset_caches()
    yield
    heat_index_service.reset_caches()


@pytest.fixture
def client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Model loading
# ---------------------------------------------------------------------------


def test_model_loads(with_heat_index_model):
    bundle = heat_index_service.load_bundle()
    assert set(bundle) >= {"model", "imputer", "feature_names", "class_names"}
    assert heat_index_service.bundle_is_available() is True


def test_model_missing_reports_unavailable(monkeypatch, tmp_path):
    monkeypatch.setattr(
        settings, "HEAT_INDEX_MODEL_PATH", str(tmp_path / "nope.joblib"), raising=False
    )
    heat_index_service.reset_caches()
    assert heat_index_service.bundle_is_available() is False
    with pytest.raises(heat_index_service.HeatIndexModelUnavailableError):
        heat_index_service.load_bundle()
    heat_index_service.reset_caches()


def test_model_info_reads_metadata(with_heat_index_model):
    info = heat_index_service.model_info()
    assert info["classes_with_no_training_data"] == ["EXTREME"]
    assert "10-25 km" in info["weather_resolution"]


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------


def test_valid_prediction(with_heat_index_model):
    result = heat_index_service.predict_one({
        "temperature_2m_c": 44.0, "relative_humidity_pct": 55.0,
        "wind_speed_10m_ms": 2.0, "shortwave_radiation_wm2": 800.0,
        "month": 6, "hour": 14, "latitude": 28.6, "longitude": 77.2,
        "lst_mean_c_mean": 46.0, "ndvi_mean_mean": 0.15,
        "elevation_mean_m_mean": 220.0,
    })
    assert result["predicted_category"] in CLASSES
    assert abs(sum(result["probabilities"].values()) - 1.0) < 1e-6
    assert result["features_missing_and_imputed"] == []


def test_missing_features_are_imputed_and_reported(with_heat_index_model):
    result = heat_index_service.predict_one({"temperature_2m_c": 44.0})
    assert result["predicted_category"] in CLASSES
    assert "relative_humidity_pct" in result["features_missing_and_imputed"]
    assert "temperature_2m_c" not in result["features_missing_and_imputed"]


def test_extra_features_are_ignored_not_errored(with_heat_index_model):
    result = heat_index_service.predict_one({
        "temperature_2m_c": 44.0, "some_unrelated_key": 999,
    })
    assert "some_unrelated_key" in result["features_ignored"]


def test_feature_mismatch_in_batch_raises(with_heat_index_model):
    bad_df = pd.DataFrame({"temperature_2m_c": [44.0]})  # missing most features
    with pytest.raises(heat_index_service.HeatIndexFeatureError):
        heat_index_service.predict_batch(bad_df)


def test_batch_prediction_matches_single(with_heat_index_model):
    row = {f: 30.0 for f in FEATURES}
    single = heat_index_service.predict_one(row)
    batch = heat_index_service.predict_batch(pd.DataFrame([row]))
    assert batch.iloc[0]["predicted_category"] == single["predicted_category"]


def test_row_by_row_matches_batch(with_heat_index_model):
    rng = np.random.default_rng(7)
    df = pd.DataFrame({f: rng.uniform(0, 50, 25) for f in FEATURES})
    batch = heat_index_service.predict_batch(df)
    row_by_row = heat_index_service.predict_row_by_row(df)
    assert (row_by_row["predicted_category"] == batch["predicted_category"]).all()
    prob_cols = [c for c in batch.columns if c.startswith("probability_")]
    diff = (row_by_row[prob_cols] - batch[prob_cols]).abs().to_numpy().max()
    assert diff < 1e-9


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------


def test_api_model_status(client, with_heat_index_model):
    r = client.get("/api/v1/heat-index/model")
    assert r.status_code == 200
    assert r.json()["available"] is True


def test_api_model_status_when_unavailable(client, monkeypatch, tmp_path):
    monkeypatch.setattr(
        settings, "HEAT_INDEX_MODEL_PATH", str(tmp_path / "nope.joblib"), raising=False
    )
    heat_index_service.reset_caches()
    r = client.get("/api/v1/heat-index/model")
    assert r.status_code == 200
    assert r.json()["available"] is False
    heat_index_service.reset_caches()


def test_api_predict(client, with_heat_index_model):
    r = client.post("/api/v1/heat-index/predict", json={"features": {
        "temperature_2m_c": 44.0, "relative_humidity_pct": 55.0,
    }})
    assert r.status_code == 200
    body = r.json()
    assert body["predicted_category"] in CLASSES
    assert "weather_resolution" in body


def test_api_predict_invalid_input(client, with_heat_index_model):
    r = client.post("/api/v1/heat-index/predict", json={"features": "not-a-dict"})
    assert r.status_code == 422


def test_api_explain(client, with_heat_index_model):
    r = client.post("/api/v1/heat-index/explain", json={"features": {
        "temperature_2m_c": 44.0, "relative_humidity_pct": 55.0,
    }})
    assert r.status_code == 200
    body = r.json()
    assert len(body["top_factors"]) > 0
    assert body["top_factors"][0]["direction"] in {"increases_risk", "decreases_risk"}
    # ranked by impact, descending
    impacts = [f["impact"] for f in body["top_factors"]]
    assert impacts == sorted(impacts, reverse=True)
