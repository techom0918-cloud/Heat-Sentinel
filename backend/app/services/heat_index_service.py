"""Phase 8/9/11 -- the current-condition Heat Index Category classifier.

DELIBERATELY SEPARATE FROM `ml_service.py`.

This repository has TWO trained models that answer different questions and
must not be conflated:

  * `ml_service.py` loads `ml/heat_model.joblib` (via `heat_pipeline.py`,
    84 engineered features from a rolling 14-day window). It forecasts a
    heat HAZARD band 3 DAYS AHEAD from trailing weather history, for the
    existing `/forecast/risk` trajectory endpoint. UNTOUCHED by this module.

  * This module loads `backend/models/heat_index_model.joblib` (28 features,
    no rolling window). It classifies the Heat Index category for a
    SINGLE, INSTANTANEOUS set of weather + 300m-environmental conditions --
    "what category is this?", not "what will it be in 3 days?". It is the
    model used for Phase 9's per-cell 300m prediction pipeline.

They were trained on different periods, different feature sets and answer
different questions. Routing both through one loader/interface would silently
imply they are interchangeable, which they are not.

SCIENTIFIC CAVEATS (surfaced with every response, not just in a docstring)
  * The target (`heat_index_category`) is a deterministic band of
    `heat_index_c`, itself a formula of temperature + humidity. High
    accuracy on this model reflects re-deriving that formula, not
    independent forecasting or causal skill from the environmental features.
  * EXTREME has zero training samples (2022-2025) and cannot be predicted.
  * The weather inputs this model was trained on come from ~10-25 km
    reanalysis/point sources, not true 300m observations. The 300m grid is
    an environmental *spatial* resolution, not a weather resolution.
"""

from __future__ import annotations

import logging

# NOTE: previously this set KMP_DUPLICATE_LIB_OK=TRUE / OMP_NUM_THREADS=1
# here, on the theory that an OpenMP runtime conflict needed silencing.
# Removed: KMP_DUPLICATE_LIB_OK=TRUE does not fix a duplicate-OpenMP-
# runtime conflict, it suppresses the safety check that would otherwise
# make it fail loudly and cleanly -- which can turn a clean abort into
# silent memory corruption that surfaces later as an unrelated-looking
# crash. That is a live suspect for the `access violation reading
# 0x0...0` seen even on np.zeros((1,28)) once pyarrow/pandas are also
# imported in the same process (see ml/diagnose_minimal.py). Left
# deliberately unset so any real OpenMP conflict shows its own clear
# error instead of being masked.

from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.core.config import settings
from app.core.exceptions import HeatSentinalError

logger = logging.getLogger(__name__)

WEATHER_RESOLUTION_NOTE = (
    "Weather inputs are associated from ~10-25 km point/reanalysis sources, "
    "not true 300m observations. The 300m grid describes environmental "
    "spatial resolution (LST/NDVI/land cover/elevation), not weather "
    "resolution."
)

MODEL_LIMITATIONS = [
    "heat_index_category is a deterministic band of heat_index_c, which is "
    "itself a formula of temperature and humidity. High accuracy reflects "
    "re-deriving that formula, not independently forecasting heat risk.",
    "EXTREME has zero training samples in the 2022-2025 period used to fit "
    "this model and cannot be predicted.",
    WEATHER_RESOLUTION_NOTE,
    "This is a classifier of the CURRENT/given conditions, not a temporal "
    "forecaster. Feeding it forecast weather values classifies that "
    "forecast's category -- it does not itself generate a weather forecast.",
]


class HeatIndexModelUnavailableError(HeatSentinalError):
    """The heat_index_model.joblib bundle could not be loaded."""

    status_code = 503
    error_type = "heat_index_model_unavailable"


class HeatIndexFeatureError(HeatSentinalError):
    """Input features could not be assembled into a valid model input."""

    status_code = 422
    error_type = "heat_index_feature_error"


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / path).resolve()


@lru_cache(maxsize=1)
def load_bundle() -> dict[str, Any]:
    """Load heat_index_model.joblib once. Never raises on import; missing
    model is a normal, handled state (service starts, endpoint returns 503)."""
    path = _resolve(settings.HEAT_INDEX_MODEL_PATH)
    if not path.exists():
        raise HeatIndexModelUnavailableError(
            "No trained heat_index model artifact is present. Run "
            "ml/train_heat_model.py, then restart the API.",
            details={"expected_path": str(path)},
        )

    try:
        import joblib

        bundle = joblib.load(path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to load heat_index_model.joblib")
        raise HeatIndexModelUnavailableError(
            "The heat_index model artifact could not be loaded.",
            details={"path": str(path), "error": str(exc)},
        ) from exc

    required = {"model", "imputer", "feature_names", "class_names"}
    missing = required - set(bundle or {})
    if missing:
        raise HeatIndexModelUnavailableError(
            "The heat_index model artifact is missing required keys.",
            details={"missing": sorted(missing), "path": str(path)},
        )

    # Do NOT rebuild the native LightGBM booster.
    # The original joblib booster works correctly in this environment.
    # _rebuild_lightgbm_booster_fresh(bundle["model"])

    # Force single-threaded prediction HERE, once, so every caller
    # (predict_one, predict_batch, predict_row_by_row, explain_prediction)
    # gets it -- not just whichever function remembered to call
    # _force_single_threaded itself. Confirmed on the machine that hit the
    # native crash: manually forcing n_jobs=1 before predict_proba worked;
    # the default n_jobs=-1 this model was trained with did not.
    model = _force_single_threaded(bundle["model"])

    logger.info(
        "Loaded heat_index model: %s, %d features, classes=%s",
        type(model).__name__,
        len(bundle["feature_names"]),
        bundle["class_names"],
    )
    return bundle


def _rebuild_lightgbm_booster_fresh(model: Any) -> None:
    """Rebuild a LightGBM model's native booster from its own text
    representation, in place.

    A pickled LGBMClassifier carries a ctypes handle to a native C
    booster. Reconstructing that handle across processes/environments
    (different LightGBM build, different machine) is exactly the kind of
    thing that can leave it pointing at invalid memory -- consistent with
    a crash that a tiny prediction can dodge by luck but a real batch
    reliably hits (`access violation reading 0x0...0` is a null/dangling
    pointer read). `model_to_string()` / `Booster(model_str=...)` forces a
    brand new, guaranteed-valid handle built by the CURRENTLY installed
    LightGBM in THIS process, instead of trusting whatever pickle handed
    back. No-op, quietly, for any model that isn't a LightGBM booster."""
    booster = getattr(model, "booster_", None)
    if booster is None:
        return
    try:
        import lightgbm as lgb

        model_str = booster.model_to_string()
        model._Booster = lgb.Booster(model_str=model_str)
        logger.info("Rebuilt LightGBM booster from its text representation.")
    except Exception as exc:  # noqa: BLE001 -- best-effort; original booster still usable
        logger.warning("Could not rebuild LightGBM booster fresh: %s", exc)


def bundle_is_available() -> bool:
    try:
        load_bundle()
        return True
    except HeatSentinalError:
        return False


def model_info() -> dict[str, Any]:
    """Metadata for health checks and API responses. Reads the metadata
    file written at training time rather than hardcoding metrics here, so
    this can never silently drift from what was actually measured."""
    bundle = load_bundle()
    metadata_path = _resolve(settings.HEAT_INDEX_METADATA_PATH)
    metadata: dict[str, Any] = {}
    if metadata_path.exists():
        import json

        metadata = json.loads(metadata_path.read_text())

    return {
        "model_type": type(bundle["model"]).__name__,
        "feature_count": len(bundle["feature_names"]),
        "features": list(bundle["feature_names"]),
        "target_classes_learned": list(bundle["class_names"]),
        "target_classes_all": metadata.get(
            "target_classes_all",
            ["LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"],
        ),
        "classes_with_no_training_data": metadata.get(
            "classes_with_no_training_data", []
        ),
        "training_period": metadata.get("training_period"),
        "validation_period": metadata.get("validation_period"),
        "test_period": metadata.get("test_period"),
        "metrics": metadata.get("metrics", {}),
        "weather_resolution": WEATHER_RESOLUTION_NOTE,
        "limitations": MODEL_LIMITATIONS,
    }


# ---------------------------------------------------------------------------
# Feature assembly + prediction
# ---------------------------------------------------------------------------


def validate_features(input_features: dict[str, Any]) -> dict[str, list[str]]:
    """Which of the model's required features are present/missing in the
    given input, without silently guessing. Callers decide what to do with
    a missing feature -- this never fills one with an arbitrary zero."""
    bundle = load_bundle()
    expected = list(bundle["feature_names"])
    present = [f for f in expected if f in input_features and input_features[f] is not None]
    missing = [f for f in expected if f not in present]
    extra = [k for k in input_features if k not in expected]
    return {"expected": expected, "present": present, "missing": missing, "extra": extra}


def predict_one(input_features: dict[str, Any]) -> dict[str, Any]:
    """Predict the category for ONE set of features (dict of feature_name
    -> value). Missing features are imputed with the SAME training-year
    medians used at fit time (never an arbitrary zero); this is reported
    back in the response so a caller can see exactly what was filled in.
    """
    bundle = load_bundle()
    features = list(bundle["feature_names"])

    check = validate_features(input_features)
    row = pd.DataFrame([{f: input_features.get(f) for f in features}])
    X = bundle["imputer"].transform(row)
    design_row = pd.DataFrame(X, columns=features)  # imputed, correct dtypes -- what the model actually sees

    proba = _model_predict_proba(bundle["model"], X)[0]
    classes = list(bundle["class_names"])
    predicted_index = int(np.argmax(proba))

    return {
        "predicted_category": classes[predicted_index],
        "probabilities": {c: round(float(p), 4) for c, p in zip(classes, proba)},
        "features_used": features,
        "features_missing_and_imputed": check["missing"],
        "features_ignored": check["extra"],
        "design_row": design_row,  # private: consumed by explain_prediction, not serialized
    }


def _force_single_threaded(model: Any) -> Any:
    """Best-effort: make the model predict single-threaded. LightGBM's
    n_jobs maps to its native num_threads; harmless no-op for estimators
    without this param (RandomForest/XGBoost aren't implicated in the
    Windows crash this addresses, so they're left alone if set_params fails)."""
    try:
        model.set_params(n_jobs=1)
        logger.info("Forced LightGBM to single-threaded prediction (n_jobs=1).")
    except Exception:  # noqa: BLE001 -- best-effort only
        pass
    return model


def _model_predict_proba(model: Any, X: np.ndarray) -> np.ndarray:
    """Class probabilities via the model's raw Booster directly, bypassing
    LGBMClassifier.predict_proba().

    Confirmed by direct isolation on the machine that hit the native
    crash: `model.booster_.predict(X)` works reliably where
    `model.predict_proba(X)` crashes with `access violation reading
    0x0...0`. The sklearn wrapper does extra validation/conversion before
    handing data to the native call; that layer is implicated, not the
    native predictor itself, which is why chunking/threading fixes aimed
    at the native call never helped.

    Falls back to plain predict_proba for estimators with no `booster_`
    (RandomForest/XGBoost), which were never implicated in this crash.
    """
    booster = getattr(model, "booster_", None)
    if booster is None:
        return model.predict_proba(X)

    raw = np.asarray(booster.predict(X))
    if raw.ndim == 1:
        # Binary objective: booster.predict returns P(class=1) only.
        raw = np.column_stack([1.0 - raw, raw])
    return raw


def _predict_proba_safely(model: Any, chunk: np.ndarray) -> np.ndarray:
    """Class probabilities for a chunk, via the raw-Booster path -- see
    `_model_predict_proba`'s docstring for why."""
    return _model_predict_proba(model, chunk)


def predict_batch(rows: pd.DataFrame, chunk_size: int = 20_000) -> pd.DataFrame:
    """Batch inference for many rows at once (Phase 9). `rows` must already
    contain columns named exactly like the model's feature_names -- this
    function does not rename or reshape, it only imputes + predicts, so a
    caller building 300m-cell features stays in control of that mapping.

    Predicts in plain chunks of `chunk_size` rows via the raw Booster
    (`_model_predict_proba`). No recursive shrink-on-failure fallback here
    on purpose: that masked the actual crash instead of surfacing it, and
    root-causing it (see ml/diagnose_predict_crash.py) is more valuable
    than papering over it with smaller and smaller retries. If a chunk
    fails, this reports exactly which row range and re-raises -- it does
    not silently degrade to a slower path.

    Returns a DataFrame with predicted_category and one probability column
    per class, indexed the same as `rows`.
    """
    bundle = load_bundle()
    features = list(bundle["feature_names"])
    missing_cols = [f for f in features if f not in rows.columns]
    if missing_cols:
        raise HeatIndexFeatureError(
            "Input rows are missing required model columns.",
            details={"missing_columns": missing_cols},
        )

    selected = rows[features]
    if selected.shape[1] != len(features):
        # A duplicate column NAME in `rows` under one of the expected
        # feature names silently produces a wider-than-expected frame
        # here (rows[["x"]] returns 2 columns if "x" appears twice) --
        # exactly the kind of column-count mismatch that crashes
        # LightGBM's native predictor (`access violation reading
        # 0x0...0`) instead of raising a clean, catchable error. This
        # check turns that into one.
        counts = selected.columns.value_counts()
        dupes = counts[counts > 1].index.tolist()
        raise HeatIndexFeatureError(
            f"Selecting the model's feature columns produced shape "
            f"{selected.shape}, expected (*, {len(features)}). This means "
            "a duplicate column name in the input DataFrame.",
            details={"duplicate_columns": dupes, "shape": list(selected.shape)},
        )

    logger.info(
        "predict_batch: input shape %s, model expects %d features",
        selected.shape, len(features),
    )

    X = bundle["imputer"].transform(selected)
    X = np.ascontiguousarray(X, dtype=np.float64)

    n_nan, n_inf = int(np.isnan(X).sum()), int(np.isinf(X).sum())
    if n_nan or n_inf:
        logger.warning(
            "Post-imputation input still has %d NaN and %d Inf values -- "
            "clipping to finite range before prediction.", n_nan, n_inf
        )
        X = np.nan_to_num(X, nan=0.0, posinf=np.finfo(np.float64).max,
                           neginf=np.finfo(np.float64).min)

    model = bundle["model"]  # already forced single-threaded in load_bundle()
    n_expected = getattr(model, "n_features_in_", None)
    if n_expected is not None and X.shape[1] != n_expected:
        raise HeatIndexFeatureError(
            f"Assembled input has {X.shape[1]} columns but the fitted "
            f"model expects {n_expected}. Refusing to call predict with "
            "a mismatched shape -- that mismatch is what crashes "
            "LightGBM's native predictor rather than raising an error.",
            details={"input_columns": X.shape[1], "model_expects": n_expected},
        )
    classes = list(bundle["class_names"])

    proba_chunks = []
    for start in range(0, len(X), chunk_size):
        chunk = np.ascontiguousarray(X[start:start + chunk_size])
        try:
            proba_chunks.append(_predict_proba_safely(model, chunk))
        except OSError:
            logger.error(
                "predict_batch crashed on rows [%d:%d) of %d.",
                start, start + len(chunk), len(X)
            )
            raise
    proba = np.vstack(proba_chunks) if proba_chunks else np.empty((0, len(classes)))
    predicted_index = np.argmax(proba, axis=1)

    out = pd.DataFrame(index=rows.index)
    out["predicted_category"] = [classes[i] for i in predicted_index]
    for i, c in enumerate(classes):
        out[f"probability_{c}"] = np.round(proba[:, i], 4)
    return out


def reset_caches() -> None:
    """Clear cached bundle. Used by tests and after retraining."""
    load_bundle.cache_clear()
    get_explainer.cache_clear()


def predict_row_by_row(rows: pd.DataFrame, progress_every: int = 50_000) -> pd.DataFrame:
    """Same result as predict_batch, computed one row at a time using the
    EXACT call shape as predict_one (imputer.transform on a single-row
    frame, then predict_proba on that single row) -- i.e. the code path
    already confirmed working via predict_heat_model.py's demo.

    Exists because predict_batch's vectorized path has been observed to
    crash with a native `access violation reading 0x0...0` on at least
    one Windows machine, at every batch size tried down to and including
    1-row chunks produced by slicing a larger array -- but a genuinely
    separately-constructed single-row DataFrame predicts fine. The
    difference triggering that is unresolved; this sidesteps it entirely
    by reusing the known-good path, at the cost of being much slower on
    very large inputs (some tens of minutes for ~600k rows, vs seconds
    for predict_batch when predict_batch works).
    """
    bundle = load_bundle()
    features = list(bundle["feature_names"])
    missing_cols = [f for f in features if f not in rows.columns]
    if missing_cols:
        raise HeatIndexFeatureError(
            "Input rows are missing required model columns.",
            details={"missing_columns": missing_cols},
        )

    imputer = bundle["imputer"]
    model = bundle["model"]
    classes = list(bundle["class_names"])
    total = len(rows)

    categories = []
    proba_rows = []
    selected = rows[features]
    for i in range(total):
        one_row = selected.iloc[[i]]  # a genuine single-row DataFrame, like predict_one builds
        X = imputer.transform(one_row)
        proba = _model_predict_proba(model, X)[0]
        categories.append(classes[int(np.argmax(proba))])
        proba_rows.append(proba)
        if progress_every and (i + 1) % progress_every == 0:
            logger.info("predict_row_by_row: %d / %d done", i + 1, total)

    out = pd.DataFrame(index=rows.index)
    out["predicted_category"] = categories
    proba_arr = np.asarray(proba_rows)
    for j, c in enumerate(classes):
        out[f"probability_{c}"] = np.round(proba_arr[:, j], 4)
    return out


# ---------------------------------------------------------------------------
# Phase 11: SHAP explainability for THIS model
# ---------------------------------------------------------------------------


class HeatIndexExplainerUnavailableError(HeatSentinalError):
    """SHAP is not installed, or an explainer could not be built."""

    status_code = 503
    error_type = "heat_index_explainer_unavailable"


@lru_cache(maxsize=1)
def get_explainer() -> Any:
    try:
        import shap
    except ImportError as exc:
        raise HeatIndexExplainerUnavailableError(
            "SHAP is not installed, so explanations are unavailable. "
            "Prediction is unaffected. Install with: pip install shap",
            details={"missing_dependency": "shap"},
        ) from exc

    model = load_bundle()["model"]
    try:
        explainer = shap.TreeExplainer(model)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Could not build a SHAP explainer for heat_index_model")
        raise HeatIndexExplainerUnavailableError(
            "A SHAP explainer could not be built for this estimator.",
            details={"estimator": type(model).__name__, "error": str(exc)},
        ) from exc
    return explainer


def explain_prediction(input_features: dict[str, Any]) -> dict[str, Any]:
    """SHAP contributions for ONE prediction, attributed to the predicted
    class. Reuses predict_one's exact design row -- never rebuilds it --
    so the explanation matches the prediction it explains, not a
    re-derived approximation of it.

    Returns 'model contribution' language only. Never a causal claim.
    """
    bundle = load_bundle()
    prediction = predict_one(input_features)
    design_row = prediction.pop("design_row")
    features = list(bundle["feature_names"])
    classes = list(bundle["class_names"])
    predicted_index = classes.index(prediction["predicted_category"])

    explainer = get_explainer()
    raw = np.asarray(explainer.shap_values(design_row))

    # LightGBM/XGBoost/RandomForest with shap>=0.45 return
    # (n_samples, n_features, n_classes); normalise defensively.
    if raw.ndim == 3 and raw.shape[0] == len(classes) and raw.shape[1] == 1:
        raw = np.transpose(raw, (1, 2, 0))  # (classes, 1, features) -> (1, features, classes)
    if raw.ndim != 3:
        raise HeatIndexExplainerUnavailableError(
            "Unexpected SHAP output shape for this estimator.",
            details={"shap_output_shape": list(raw.shape)},
        )

    class_shap = raw[0, :, predicted_index]
    base_values = getattr(explainer, "expected_value", None)
    base_value = None
    if base_values is not None:
        base_arr = np.asarray(base_values)
        base_value = float(base_arr[predicted_index]) if base_arr.ndim else float(base_arr)

    top_idx = np.argsort(-np.abs(class_shap))[:10]
    top_factors = []
    for i in top_idx:
        value = float(design_row.iloc[0, i])
        contribution = float(class_shap[i])
        top_factors.append({
            "feature": features[i],
            "value": value,
            "shap_value": round(contribution, 5),
            "impact": round(abs(contribution), 5),
            "direction": "increases_risk" if contribution > 0 else "decreases_risk",
        })

    return {
        "predicted_category": prediction["predicted_category"],
        "probabilities": prediction["probabilities"],
        "base_value": base_value,
        "top_factors": top_factors,
        "method": "shap.TreeExplainer",
        "caveat": (
            "SHAP values describe how this fitted model weighted its inputs "
            "for this one prediction (model contribution). They are not a "
            "causal claim and not a medical assessment."
        ),
    }
