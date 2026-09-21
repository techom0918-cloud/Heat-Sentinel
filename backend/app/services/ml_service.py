"""Trained-model integration for heat hazard forecasting.

Loads the artifact produced by `ml/heat_pipeline.py` and serves 3-day-ahead
heat hazard category forecasts.

TRAIN / SERVE PARITY
Feature engineering is NOT reimplemented here. This module imports
`heat_pipeline.py` itself and calls its `engineer_features`, so the 84
features served are produced by exactly the code that produced the 84
features trained on. Reimplementing them would drift silently: a renamed
column or a changed rolling window would not raise an error, it would just
make every prediction quietly wrong.

That also means the pipeline's own quirks are preserved deliberately --
notably `utci(..., limit_inputs=False)`, which extrapolates UTCI above
50 C where the Phase 3 thermal engine returns null. The two differ on
purpose: the model must see what it was trained on.

WHAT THIS PREDICTS
The label is `_categorise(heat_index_max)` -- a heat HAZARD band, not a
health outcome. No mortality, demographic or health data was used in
training. It answers "how hot will it be in 3 days", not "who will be
harmed". Combining hazard with vulnerability is the risk engine's job.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from datetime import date as date_type
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.core.config import settings
from app.core.exceptions import ExternalServiceError, HeatSentinalError

logger = logging.getLogger(__name__)

# Documented from the trained artifact, surfaced in every response so a
# consumer never sees a prediction without its caveats.
MODEL_LIMITATIONS = [
    "Predicts a heat HAZARD category, not a health outcome. No mortality, "
    "demographic or health data was used in training.",
    "The EXTREME band was never observed. Across six cities, 578,592 hourly "
    "records and eleven years (2015-2025), no day reached a Heat Index above "
    "54 C, so zero EXTREME days appear in the training, validation or test "
    "splits. The model therefore cannot predict that band and its skill "
    "there is unmeasured.",
    "Trained on six Indian cities only (Delhi, Bengaluru, Kochi, Ahmedabad, "
    "Nagpur, Kolkata) from Open-Meteo ERA5 reanalysis, 2015-2025. Skill "
    "elsewhere is unverified.",
    "VERY_HIGH recall on held-out test is 0.57: roughly two in five "
    "VERY_HIGH days are called HIGH instead. Errors skew toward "
    "under-warning, which is the more dangerous direction.",
    "The improvement over persistence comes with slightly more false alarms: "
    "74 fewer missed events in exchange for 12 additional false alarms on "
    "the test set.",
    "`confidence` is the model's class probability, not a calibrated "
    "forecast probability.",
    "Describes conditions at a location, never an individual.",
]

MODEL_DISCLAIMER = (
    "PROTOTYPE HEAT HAZARD FORECAST. Benchmarked against persistence and "
    "climatology baselines. Not a medically validated health prediction."
)


class ModelUnavailableError(HeatSentinalError):
    """The trained artifact or the pipeline module could not be loaded."""

    status_code = 503
    error_type = "model_unavailable"


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _resolve(path_value: str) -> Path:
    """Resolve a configured path relative to the backend directory."""
    path = Path(path_value)
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / path).resolve()


@lru_cache(maxsize=1)
def load_pipeline_module() -> Any:
    """Import heat_pipeline.py from disk, once.

    Imported rather than vendored so feature engineering cannot drift away
    from what the model was trained on.
    """
    path = _resolve(settings.ML_PIPELINE_PATH)
    if not path.exists():
        raise ModelUnavailableError(
            "The ML pipeline module was not found, so features cannot be "
            "built. Forecasting is unavailable.",
            details={"expected_path": str(path)},
        )

    spec = importlib.util.spec_from_file_location("heat_pipeline", path)
    if spec is None or spec.loader is None:
        raise ModelUnavailableError(
            "The ML pipeline module could not be loaded.",
            details={"path": str(path)},
        )

    module = importlib.util.module_from_spec(spec)
    sys.modules["heat_pipeline"] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:  # noqa: BLE001 - any import error is fatal here
        logger.exception("Failed to import heat_pipeline")
        raise ModelUnavailableError(
            "The ML pipeline module failed to import.",
            details={"path": str(path), "error": str(exc)},
        ) from exc

    return module


@lru_cache(maxsize=1)
def load_artifact() -> dict[str, Any]:
    """Load heat_model.joblib once and validate its shape."""
    path = _resolve(settings.ML_MODEL_PATH)
    if not path.exists():
        raise ModelUnavailableError(
            "No trained model artifact is present. Run ml/heat_pipeline.py "
            "to train one, then restart the API.",
            details={"expected_path": str(path)},
        )

    try:
        import joblib

        artifact = joblib.load(path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to load model artifact")
        raise ModelUnavailableError(
            "The trained model artifact could not be loaded.",
            details={"path": str(path), "error": str(exc)},
        ) from exc

    required = {"model", "features", "risk_levels", "horizon_days"}
    missing = required - set(artifact or {})
    if missing:
        raise ModelUnavailableError(
            "The model artifact is missing required keys.",
            details={"missing": sorted(missing), "path": str(path)},
        )

    logger.info(
        "Loaded %s: %d features, horizon %sd",
        type(artifact["model"]).__name__,
        len(artifact["features"]),
        artifact["horizon_days"],
    )
    return artifact


def model_is_available() -> bool:
    """True when both the artifact and the pipeline module can be loaded."""
    try:
        load_artifact()
        load_pipeline_module()
        return True
    except HeatSentinalError:
        return False


def model_info() -> dict[str, Any]:
    """Metadata about the loaded model, for health checks and responses."""
    artifact = load_artifact()
    metrics = artifact.get("test_metrics") or {}
    return {
        "type": type(artifact["model"]).__name__,
        "feature_count": len(artifact["features"]),
        "horizon_days": int(artifact["horizon_days"]),
        "risk_levels": list(artifact["risk_levels"]),
        "heat_index_edges": artifact.get("heat_index_edges"),
        "test_metrics": {
            key: (round(value, 4) if isinstance(value, float) else value)
            for key, value in metrics.items()
        },
        "trained_on": (
            "Open-Meteo ERA5 reanalysis, 2015-2025, six Indian cities "
            "(Delhi, Bengaluru, Kochi, Ahmedabad, Nagpur, Kolkata). "
            "578,592 hourly records, 24,012 labelled days. Meteorological "
            "variables only -- no mortality, demographic or health data."
        ),
    }


# ---------------------------------------------------------------------------
# Prediction
# ---------------------------------------------------------------------------


def forecast_from_history(history: dict[str, Any]) -> dict[str, Any]:
    """Build features from hourly history and predict the hazard category.

    `history` comes from weather_service.get_hourly_history and carries the
    same four variables the pipeline trained on.
    """
    import pandas as pd

    pipeline = load_pipeline_module()
    artifact = load_artifact()

    frame = _to_dataframe(history, pd)
    frame = _add_thermal_indices(frame, pipeline)

    features = pipeline.engineer_features(frame, for_prediction=True)
    if features.empty:
        raise ExternalServiceError(
            "Not enough complete daily history to build model features. The "
            "model needs at least 14 consecutive days with 20+ hourly "
            "observations each.",
            status_code=422,
            details={"hourly_rows": int(len(frame))},
        )

    latest = features.sort_values("date").tail(1)

    # Reindex to the artifact's feature list. Order is positional for the
    # model, so a mismatch produces confident, silently wrong predictions
    # rather than an error.
    feature_names = list(artifact["features"])
    design = latest.reindex(columns=feature_names, fill_value=0.0)

    model = artifact["model"]
    predicted_index = int(model.predict(design)[0])
    levels = list(artifact["risk_levels"])

    probabilities: dict[str, float] = {}
    confidence = None
    if hasattr(model, "predict_proba"):
        raw = model.predict_proba(design)[0]
        classes = getattr(model, "classes_", range(len(raw)))
        for class_index, probability in zip(classes, raw):
            probabilities[levels[int(class_index)]] = round(
                float(probability), 4
            )
        confidence = probabilities.get(levels[predicted_index])

    row = latest.iloc[0]
    based_on: date_type = row["date"].date()
    horizon = int(artifact["horizon_days"])

    return {
        "based_on": based_on,
        "issued_for": based_on + pd.Timedelta(days=horizon).to_pytimedelta(),
        "horizon_days": horizon,
        "predicted_category": levels[predicted_index],
        "predicted_class_index": predicted_index,
        "confidence": confidence,
        "class_probabilities": probabilities,
        "current_category": levels[int(row["cat_today"])],
        "current_heat_index_max": round(float(row["heat_index_max"]), 1),
        "days_of_history_used": int(len(features)),
        # Private. The caller pops this before building the response. Exposed
        # so the explainability service can attribute SHAP values to the exact
        # vector the model scored, rather than rebuilding it and risking drift.
        "_design": design,
    }


def _to_dataframe(history: dict[str, Any], pd: Any) -> Any:
    """Convert the provider's hourly arrays into the pipeline's frame shape."""
    times = history.get("time") or []
    if not times:
        raise ExternalServiceError(
            "The weather provider returned no hourly history.",
            status_code=422,
        )

    frame = pd.DataFrame(
        {
            # The pipeline groups by city; a single location is one group.
            "city": "query",
            "timestamp": pd.to_datetime(times),
            "temperature": history.get("temperature") or [None] * len(times),
            "humidity": history.get("humidity") or [None] * len(times),
            "wind_speed": history.get("wind_speed") or [None] * len(times),
            "solar_radiation": (
                history.get("solar_radiation") or [None] * len(times)
            ),
        }
    )

    # Same cleaning the pipeline applied before training.
    frame["temperature"] = frame["temperature"].clip(-10, 55)
    frame["humidity"] = frame["humidity"].clip(1, 100)
    frame[["temperature", "humidity", "wind_speed", "solar_radiation"]] = frame[
        ["temperature", "humidity", "wind_speed", "solar_radiation"]
    ].interpolate(limit_direction="both")
    frame["wind_speed"] = frame["wind_speed"].fillna(1.0)
    frame["solar_radiation"] = frame["solar_radiation"].fillna(0.0)

    return frame.dropna(subset=["temperature", "humidity"])


def _add_thermal_indices(frame: Any, pipeline: Any) -> Any:
    """Compute indices with the pipeline's own functions, not Phase 3's.

    Deliberate: the pipeline uses `limit_inputs=False` for UTCI while the
    thermal engine returns null above 50 C. The model must be fed what it
    was trained on.
    """
    frame["heat_index"] = pipeline.calculate_heat_index(
        frame["temperature"], frame["humidity"]
    )
    frame["wbgt"] = pipeline.calculate_wbgt(
        frame["temperature"], frame["humidity"]
    )
    frame["utci"] = pipeline.calculate_utci(
        frame["temperature"], frame["humidity"], frame["wind_speed"]
    )
    return frame


def reset_caches() -> None:
    """Clear cached module and artifact. Used by tests and after retraining."""
    load_artifact.cache_clear()
    load_pipeline_module.cache_clear()
