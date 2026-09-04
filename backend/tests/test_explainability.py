"""Phase 6 tests: SHAP explainability.

No network. A real XGBoost artifact is trained on synthetic features inside
a fixture, so SHAP runs against a genuine multiclass tree model rather than
a mock.
"""

from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import explainability_service, ml_service
from app.services.explainability_service import (
    ExplainerUnavailableError,
    _normalise_shap_output,
    build_summary,
    feature_label,
    feature_theme,
)

FORECAST_URL = f"{settings.API_V1_PREFIX}/risk/forecast"
MODEL_URL = f"{settings.API_V1_PREFIX}/risk/model"
DELHI = {"latitude": 28.6139, "longitude": 77.2090}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@contextmanager
def mock_provider(payload=None, exc=None):
    async def fake_get(self, url, *args, **kwargs):
        if exc is not None:
            raise exc
        return httpx.Response(200, json=payload, request=httpx.Request("GET", url))

    with patch.object(httpx.AsyncClient, "get", fake_get):
        yield


def history_payload(days: int = 35) -> dict:
    import numpy as np
    import pandas as pd

    stamps = pd.date_range("2026-05-01", periods=days * 24, freq="h")
    hour = stamps.hour.values
    doy = stamps.dayofyear.values
    temperature = 34 + 6 * np.sin(2 * np.pi * (hour - 9) / 24) + 0.02 * doy
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
def xgb_artifact(tmp_path_factory) -> Path:
    """A real multiclass XGBoost artifact, matching the production estimator."""
    import joblib
    import numpy as np
    import pandas as pd
    from xgboost import XGBClassifier

    pipeline = ml_service.load_pipeline_module()

    stamps = pd.date_range("2022-01-01", "2024-12-31", freq="h")
    hour = stamps.hour.values
    doy = stamps.dayofyear.values
    rng = np.random.default_rng(7)
    frame = pd.DataFrame(
        {
            "city": "TestCity",
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
    model = XGBClassifier(
        n_estimators=40,
        max_depth=5,
        objective="multi:softprob",
        verbosity=0,
        random_state=0,
    )
    model.fit(engineered[features], engineered["target"])

    path = tmp_path_factory.mktemp("shap") / "heat_model.joblib"
    joblib.dump(
        {
            "model": model,
            "scaler": None,
            "features": features,
            "risk_levels": pipeline.RISK_LEVELS,
            "horizon_days": pipeline.HORIZON,
            "heat_index_edges": pipeline.HEAT_INDEX_EDGES,
            "test_metrics": {"CSI": 0.868, "POD": 0.945, "misses": 143},
        },
        path,
    )
    return path


@pytest.fixture
def with_model(xgb_artifact, monkeypatch):
    monkeypatch.setattr(
        settings, "ML_MODEL_PATH", str(xgb_artifact), raising=False
    )
    ml_service.reset_caches()
    explainability_service.reset_caches()
    yield
    ml_service.reset_caches()
    explainability_service.reset_caches()


# ---------------------------------------------------------------------------
# Service loads, feature alignment
# ---------------------------------------------------------------------------


def test_explainer_loads(with_model) -> None:
    assert explainability_service.explainer_is_available() is True
    assert explainability_service.get_explainer() is not None


def test_explainer_is_cached_not_rebuilt(with_model) -> None:
    """Rebuilding per request is the expensive mistake."""
    assert explainability_service.get_explainer() is (
        explainability_service.get_explainer()
    )


def test_model_has_the_expected_feature_count(with_model) -> None:
    assert len(ml_service.load_artifact()["features"]) == 84


def test_feature_names_stay_aligned(client: TestClient, with_model) -> None:
    artifact_features = list(ml_service.load_artifact()["features"])
    with mock_provider(history_payload()):
        body = client.get(
            FORECAST_URL, params={**DELHI, "explain": "true", "top_factors": 84}
        ).json()

    returned = [f["feature"] for f in body["explanation"]["top_factors"]]
    assert set(returned) == set(artifact_features)
    assert body["explanation"]["features_considered"] == len(artifact_features)


def test_mismatched_design_matrix_fails_clearly(with_model) -> None:
    """Silently misattributing SHAP values would be worse than an error."""
    import pandas as pd

    bad = pd.DataFrame([{"not_a_feature": 1.0}])
    with pytest.raises(ExplainerUnavailableError) as excinfo:
        explainability_service.explain_prediction(bad, 0, "LOW")
    assert "feature list" in str(excinfo.value)


def test_explainer_fails_clearly_without_a_model(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        settings, "ML_MODEL_PATH", str(tmp_path / "absent.joblib"), raising=False
    )
    ml_service.reset_caches()
    explainability_service.reset_caches()
    assert explainability_service.explainer_is_available() is False
    ml_service.reset_caches()
    explainability_service.reset_caches()


# ---------------------------------------------------------------------------
# Explanation content
# ---------------------------------------------------------------------------


def test_explanation_returns_top_factors(client: TestClient, with_model) -> None:
    with mock_provider(history_payload()):
        response = client.get(FORECAST_URL, params={**DELHI, "explain": "true"})

    assert response.status_code == 200
    explanation = response.json()["explanation"]
    assert len(explanation["top_factors"]) == 10
    assert explanation["summary"]
    assert explanation["explained_class"] == response.json()["predicted_category"]


def test_factors_sorted_by_absolute_impact(
    client: TestClient, with_model
) -> None:
    with mock_provider(history_payload()):
        body = client.get(
            FORECAST_URL, params={**DELHI, "explain": "true", "top_factors": 25}
        ).json()

    impacts = [f["impact"] for f in body["explanation"]["top_factors"]]
    assert impacts == sorted(impacts, reverse=True)
    assert all(i >= 0 for i in impacts)


def test_direction_matches_the_sign_of_the_shap_value(
    client: TestClient, with_model
) -> None:
    with mock_provider(history_payload()):
        body = client.get(
            FORECAST_URL, params={**DELHI, "explain": "true", "top_factors": 40}
        ).json()

    for factor in body["explanation"]["top_factors"]:
        expected = (
            "increases_risk" if factor["shap_value"] > 0 else "decreases_risk"
        )
        assert factor["direction"] == expected
        assert factor["impact"] == pytest.approx(abs(factor["shap_value"]))


def test_factor_values_come_from_the_design_matrix(
    client: TestClient, with_model
) -> None:
    with mock_provider(history_payload()):
        body = client.get(
            FORECAST_URL, params={**DELHI, "explain": "true", "top_factors": 84}
        ).json()

    by_name = {f["feature"]: f for f in body["explanation"]["top_factors"]}
    assert by_name["cat_today"]["value"] >= 0
    assert isinstance(by_name["heat_index_max"]["value"], float)


def test_explanation_is_attributed_to_the_predicted_class(
    client: TestClient, with_model
) -> None:
    """Summing unrelated class contributions would be wrong."""
    with mock_provider(history_payload()):
        body = client.get(FORECAST_URL, params={**DELHI, "explain": "true"}).json()

    assert (
        body["explanation"]["explained_class_index"]
        == body["predicted_class_index"]
    )


def test_explanation_carries_a_non_causal_caveat(
    client: TestClient, with_model
) -> None:
    with mock_provider(history_payload()):
        body = client.get(FORECAST_URL, params={**DELHI, "explain": "true"}).json()

    caveat = body["explanation"]["caveat"].lower()
    assert "causal" in caveat
    assert "medical" in caveat


# ---------------------------------------------------------------------------
# Explanation must not change the prediction
# ---------------------------------------------------------------------------


def test_explaining_does_not_change_the_prediction(
    client: TestClient, with_model
) -> None:
    """The model stays the source of truth."""
    with mock_provider(history_payload()):
        plain = client.get(FORECAST_URL, params=DELHI).json()
    with mock_provider(history_payload()):
        explained = client.get(
            FORECAST_URL, params={**DELHI, "explain": "true"}
        ).json()

    for key in (
        "predicted_category",
        "predicted_class_index",
        "confidence",
        "current_category",
        "current_heat_index_max",
        "class_probabilities",
    ):
        assert plain[key] == explained[key]


def test_explanation_is_absent_unless_requested(
    client: TestClient, with_model
) -> None:
    """SHAP is the expensive part; it must not run by default."""
    with mock_provider(history_payload()):
        body = client.get(FORECAST_URL, params=DELHI).json()
    assert body["explanation"] is None


def test_design_matrix_is_not_leaked_into_the_response(
    client: TestClient, with_model
) -> None:
    with mock_provider(history_payload()):
        body = client.get(FORECAST_URL, params={**DELHI, "explain": "true"}).json()
    assert "_design" not in body


# ---------------------------------------------------------------------------
# Multiclass shape normalisation
# ---------------------------------------------------------------------------


def test_normalise_handles_samples_features_classes() -> None:
    import numpy as np

    array = np.zeros((1, 84, 5))
    array[0, 3, 2] = 0.9
    result = _normalise_shap_output(array, 84, 5, class_index=2)
    assert len(result) == 84
    assert result[3] == pytest.approx(0.9)


def test_normalise_handles_classes_samples_features() -> None:
    import numpy as np

    array = np.zeros((5, 1, 84))
    array[2, 0, 3] = 0.7
    result = _normalise_shap_output(array, 84, 5, class_index=2)
    assert result[3] == pytest.approx(0.7)


def test_normalise_handles_list_of_per_class_arrays() -> None:
    """The shape older SHAP versions return."""
    import numpy as np

    raw = [np.zeros((1, 84)) for _ in range(5)]
    raw[1][0, 10] = 0.5
    result = _normalise_shap_output(raw, 84, 5, class_index=1)
    assert result[10] == pytest.approx(0.5)


def test_normalise_handles_two_dimensional_output() -> None:
    import numpy as np

    array = np.zeros((1, 84))
    array[0, 5] = 0.4
    result = _normalise_shap_output(array, 84, 5, class_index=0)
    assert result[5] == pytest.approx(0.4)


def test_normalise_handles_explanation_objects() -> None:
    import numpy as np

    class FakeExplanation:
        def __init__(self, values):
            self.values = values

    array = np.zeros((1, 84, 5))
    array[0, 7, 4] = 0.6
    result = _normalise_shap_output(FakeExplanation(array), 84, 5, class_index=4)
    assert result[7] == pytest.approx(0.6)


def test_normalise_rejects_ambiguous_shapes() -> None:
    """Guessing an axis would produce a plausible explanation of the wrong class."""
    import numpy as np

    with pytest.raises(ExplainerUnavailableError):
        _normalise_shap_output(np.zeros((2, 3, 4)), 84, 5, class_index=0)
    with pytest.raises(ExplainerUnavailableError):
        _normalise_shap_output(np.zeros((1, 9)), 84, 5, class_index=0)


def test_normalise_rejects_short_class_list() -> None:
    import numpy as np

    with pytest.raises(ExplainerUnavailableError):
        _normalise_shap_output([np.zeros((1, 84))], 84, 5, class_index=4)


# ---------------------------------------------------------------------------
# Deterministic labelling and summary
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "feature,expected",
    [
        ("heat_index_max", "peak heat index"),
        ("cat_today", "today's heat category"),
        ("hot_streak", "consecutive hot days"),
        ("temperature_max_lag_1", "maximum temperature 1 day(s) earlier"),
        ("heat_index_max_rmean_7", "7-day average peak heat index"),
        ("utci_max_rmax_14", "14-day highest peak UTCI"),
        ("humidity_mean_rstd_3", "3-day variability in mean humidity"),
    ],
)
def test_feature_labels_are_readable(feature: str, expected: str) -> None:
    assert feature_label(feature) == expected


@pytest.mark.parametrize(
    "feature,theme",
    [
        ("heat_index_max_rmean_7", "heat index"),
        ("hot_streak", "recent heat persistence"),
        ("utci_max", "UTCI thermal stress"),
        ("humidity_mean", "humidity"),
        ("temperature_max_lag_2", "temperature"),
        ("season_PRE_MONSOON", "time of year"),
    ],
)
def test_feature_themes(feature: str, theme: str) -> None:
    assert feature_theme(feature) == theme


def test_summary_is_deterministic() -> None:
    """No LLM, no randomness: same input, same sentence."""
    factors = [
        {"feature": "heat_index_max", "direction": "increases_risk"},
        {"feature": "temperature_max_lag_1", "direction": "increases_risk"},
        {"feature": "humidity_mean", "direction": "increases_risk"},
        {"feature": "wind_speed_mean", "direction": "decreases_risk"},
    ]
    first = build_summary("EXTREME", factors)
    second = build_summary("EXTREME", factors)
    assert first == second
    assert "EXTREME" in first
    assert "heat index" in first
    assert "Moderating" in first


def test_summary_handles_no_factors() -> None:
    assert "No feature contributions" in build_summary("LOW", [])


# ---------------------------------------------------------------------------
# API surface
# ---------------------------------------------------------------------------


def test_model_status_reports_explainer_availability(
    client: TestClient, with_model
) -> None:
    body = client.get(MODEL_URL).json()
    assert body["available"] is True
    assert body["explainer_available"] is True
    assert "SHAP" in body["detail"]


def test_explain_flag_is_in_the_openapi_schema(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    params = {
        p["name"]
        for p in schema["paths"]["/api/v1/risk/forecast"]["get"]["parameters"]
    }
    assert {"latitude", "longitude", "explain", "top_factors"} <= params


def test_no_duplicate_prediction_endpoint_was_added(client: TestClient) -> None:
    """Requirement: explanation must not fork the prediction path."""
    paths = client.get("/openapi.json").json()["paths"]
    risk_paths = {p for p in paths if p.startswith("/api/v1/risk")}
    assert risk_paths == {
        "/api/v1/risk/predict",
        "/api/v1/risk/forecast",
        "/api/v1/risk/model",
    }


def test_explainability_service_never_predicts() -> None:
    """SHAP explains the model; it must not compute a second score."""
    import ast

    module = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "explainability_service.py"
    )
    source = module.read_text(encoding="utf-8")
    tree = ast.parse(source)

    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert "predict" not in calls
    assert "predict_proba" not in calls
    assert "engineer_features" not in calls


# ---------------------------------------------------------------------------
# Missing-class regression: the model has fewer classes than risk_levels
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def four_class_artifact(tmp_path_factory) -> Path:
    """An artifact whose model never saw EXTREME -- the production case.

    No EXTREME day exists in the training record, so the estimator carries
    four classes while `risk_levels` lists five. SHAP's class axis is then
    length 4, and the predicted label is not the same as its position.
    """
    import joblib
    import numpy as np
    import pandas as pd
    from xgboost import XGBClassifier

    pipeline = ml_service.load_pipeline_module()
    stamps = pd.date_range("2022-01-01", "2024-12-31", freq="h")
    hour, doy = stamps.hour.values, stamps.dayofyear.values
    rng = np.random.default_rng(3)
    frame = pd.DataFrame(
        {
            "city": "T",
            "timestamp": stamps,
            "temperature": (
                26
                + 8 * np.sin(2 * np.pi * (doy - 100) / 365.25)
                + 6 * np.sin(2 * np.pi * (hour - 9) / 24)
                + rng.normal(0, 1.2, len(stamps))
            ),
            "humidity": np.clip(
                58 + 16 * np.sin(2 * np.pi * (doy - 190) / 365.25), 5, 99
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
    keep = engineered[engineered["target"] != 4]  # drop EXTREME

    model = XGBClassifier(
        n_estimators=25,
        max_depth=4,
        objective="multi:softprob",
        verbosity=0,
        random_state=0,
    ).fit(keep[features], keep["target"])

    path = tmp_path_factory.mktemp("fourclass") / "heat_model.joblib"
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
def with_four_class_model(four_class_artifact, monkeypatch):
    monkeypatch.setattr(
        settings, "ML_MODEL_PATH", str(four_class_artifact), raising=False
    )
    ml_service.reset_caches()
    explainability_service.reset_caches()
    yield
    ml_service.reset_caches()
    explainability_service.reset_caches()


def test_model_with_missing_class_still_explains(with_four_class_model) -> None:
    """Regression: a 4-class model against 5 risk_levels must not 503."""
    artifact = ml_service.load_artifact()
    model = artifact["model"]
    assert len(model.classes_) == 4
    assert len(artifact["risk_levels"]) == 5

    import pandas as pd

    design = pd.DataFrame(
        [dict.fromkeys(artifact["features"], 30.0)],
        columns=artifact["features"],
    )
    label = int(model.predict(design)[0])
    result = explainability_service.explain_prediction(
        design, label, artifact["risk_levels"][label], top_n=5
    )

    assert len(result["top_factors"]) == 5
    assert result["explained_class_index"] == label
    assert result["summary"]


def test_forecast_explains_with_a_missing_class_model(
    client: TestClient, with_four_class_model
) -> None:
    with mock_provider(history_payload()):
        response = client.get(FORECAST_URL, params={**DELHI, "explain": "true"})
    assert response.status_code == 200
    assert response.json()["explanation"]["top_factors"]


def test_unknown_predicted_class_fails_clearly(with_four_class_model) -> None:
    """A label the model never learned cannot be attributed."""
    import pandas as pd

    artifact = ml_service.load_artifact()
    design = pd.DataFrame(
        [dict.fromkeys(artifact["features"], 30.0)],
        columns=artifact["features"],
    )
    with pytest.raises(ExplainerUnavailableError) as excinfo:
        explainability_service.explain_prediction(design, 4, "EXTREME")
    assert "not among the classes" in str(excinfo.value)


def test_normalise_uses_the_models_class_count_not_the_label_count() -> None:
    """(1, 84, 4) with five labels defined must still resolve."""
    import numpy as np

    array = np.zeros((1, 84, 4))
    array[0, 12, 3] = 0.8
    result = _normalise_shap_output(array, 84, 4, class_index=3)
    assert result[12] == pytest.approx(0.8)


def test_normalise_rejects_class_index_beyond_the_axis() -> None:
    import numpy as np

    with pytest.raises(ExplainerUnavailableError):
        _normalise_shap_output(np.zeros((1, 84, 4)), 84, 4, class_index=4)
