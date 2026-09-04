"""SHAP explanations for the trained heat hazard model.

EXPLANATION ONLY. This module never predicts, never scores, and never
alters a prediction. It takes the design matrix and predicted class that
`ml_service` already produced and reports which features drove that
specific class.

WHAT A SHAP VALUE IS HERE
A signed contribution, in the model's output space, of one feature toward
the predicted class for this one input, relative to the explainer's base
value. Positive means the feature pushed the model toward the predicted
category; negative means it pushed away.

WHAT IT IS NOT
Not a causal claim. SHAP describes the behaviour of this fitted model on
this input. It does not establish that a feature causes heat, harm, or any
health outcome. The model was trained on meteorological variables only.

MULTICLASS OUTPUT SHAPES
SHAP returns different shapes depending on library and estimator version.
Observed with shap 0.52, all four estimators the pipeline can select
(XGBoost, RandomForest, HistGradientBoosting, LightGBM) return
(n_samples, n_features, n_classes). Older versions return a list of
per-class arrays. `_normalise_shap_output` handles both plus the
Explanation-object form, and refuses anything it cannot map unambiguously
rather than guessing.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Any

from app.core.exceptions import HeatSentinalError
from app.services import ml_service

logger = logging.getLogger(__name__)

EXPLANATION_CAVEAT = (
    "SHAP values describe how this fitted model weighted its inputs for "
    "this single prediction. They are not causal claims and not a medical "
    "assessment. The model was trained on meteorological variables only."
)


class ExplainerUnavailableError(HeatSentinalError):
    """SHAP is not installed, or an explainer could not be built."""

    status_code = 503
    error_type = "explainer_unavailable"


# ---------------------------------------------------------------------------
# Explainer construction (cached - building one per request is expensive)
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_explainer() -> Any:
    """Build a TreeExplainer once for the already-loaded estimator.

    Reuses `ml_service.load_artifact()`, so the model is never loaded twice
    and the explainer is never rebuilt per request.
    """
    try:
        import shap
    except ImportError as exc:  # pragma: no cover - dependency is pinned
        raise ExplainerUnavailableError(
            "SHAP is not installed, so explanations are unavailable. The "
            "prediction endpoint is unaffected.",
            details={"missing_dependency": "shap"},
        ) from exc

    model = ml_service.load_artifact()["model"]

    try:
        explainer = shap.TreeExplainer(model)
    except Exception as exc:  # noqa: BLE001 - any failure is fatal here
        logger.exception("Could not build a SHAP explainer")
        raise ExplainerUnavailableError(
            "A SHAP explainer could not be built for this estimator.",
            details={"estimator": type(model).__name__, "error": str(exc)},
        ) from exc

    logger.info("SHAP TreeExplainer ready for %s", type(model).__name__)
    return explainer


def reset_caches() -> None:
    """Clear the cached explainer. Used by tests and after retraining."""
    get_explainer.cache_clear()


def explainer_is_available() -> bool:
    try:
        get_explainer()
        return True
    except HeatSentinalError:
        return False


# ---------------------------------------------------------------------------
# Multiclass normalisation
# ---------------------------------------------------------------------------


def _normalise_shap_output(
    raw: Any, n_features: int, n_classes: int, class_index: int
) -> list[float]:
    """Reduce any SHAP output form to one row of per-feature contributions.

    `n_classes` must be the number of classes the MODEL has
    (`len(model.classes_)`), not the number of labels defined in the
    artifact. They differ whenever a class never occurred in training --
    which is the case here: no EXTREME day exists in the record, so the
    estimator carries four classes while `risk_levels` lists five.

    `class_index` is likewise a POSITION in `model.classes_`, not a label.

    Handles, in order:
      - Explanation objects (unwrap `.values`, then recurse)
      - list of per-class arrays, each (n_samples, n_features)
      - 3D arrays, either (samples, features, classes)
        or (classes, samples, features)
      - 2D arrays (binary or single-output), returned as-is

    Axis detection anchors on the feature count, which is unambiguous.
    Genuine ambiguity is an error, not a guess: silently taking the wrong
    axis would produce a plausible-looking explanation of the wrong class.
    """
    import numpy as np

    if hasattr(raw, "values") and not isinstance(raw, (list, tuple)):
        return _normalise_shap_output(
            raw.values, n_features, n_classes, class_index
        )

    if isinstance(raw, (list, tuple)):
        if not 0 <= class_index < len(raw):
            raise ExplainerUnavailableError(
                "SHAP returned fewer class arrays than the model has classes.",
                details={"returned": len(raw), "class_index": class_index},
            )
        row = np.asarray(raw[class_index])
        if row.ndim == 2:
            row = row[0]
        return [float(value) for value in np.asarray(row).ravel()]

    array = np.asarray(raw)

    if array.ndim == 3:
        # (samples, features, classes) -- the common modern form.
        if array.shape[1] == n_features:
            if not 0 <= class_index < array.shape[2]:
                raise ExplainerUnavailableError(
                    "SHAP class axis is smaller than the predicted class "
                    "position.",
                    details={
                        "class_axis": array.shape[2],
                        "class_index": class_index,
                    },
                )
            return [float(v) for v in array[0, :, class_index]]
        # (classes, samples, features) -- older layouts.
        if array.shape[2] == n_features:
            if not 0 <= class_index < array.shape[0]:
                raise ExplainerUnavailableError(
                    "SHAP class axis is smaller than the predicted class "
                    "position.",
                    details={
                        "class_axis": array.shape[0],
                        "class_index": class_index,
                    },
                )
            return [float(v) for v in array[class_index, 0, :]]
        raise ExplainerUnavailableError(
            "SHAP returned a 3D array with no axis matching the feature "
            "count, so it could not be mapped unambiguously.",
            details={
                "shape": list(array.shape),
                "n_features": n_features,
                "n_model_classes": n_classes,
            },
        )

    if array.ndim == 2:
        if array.shape[1] == n_features:
            return [float(v) for v in array[0]]
        if array.shape[0] == n_features:
            return [float(v) for v in array[:, 0]]
        raise ExplainerUnavailableError(
            "SHAP returned a 2D array that does not match the feature count.",
            details={"shape": list(array.shape), "n_features": n_features},
        )

    if array.ndim == 1 and array.shape[0] == n_features:
        return [float(v) for v in array]

    raise ExplainerUnavailableError(
        "SHAP returned an unrecognised output shape.",
        details={"shape": list(array.shape), "n_features": n_features},
    )


def _base_value(explainer: Any, class_index: int) -> float | None:
    """Expected model output before any feature contribution."""
    import numpy as np

    expected = getattr(explainer, "expected_value", None)
    if expected is None:
        return None
    array = np.asarray(expected)
    if array.ndim == 0:
        return float(array)
    if 0 <= class_index < array.shape[0]:
        return float(array.ravel()[class_index])
    return float(array.ravel()[0])


# ---------------------------------------------------------------------------
# Human-readable feature labels (deterministic, no LLM)
# ---------------------------------------------------------------------------

_BASE_LABELS = {
    "temperature_mean": "mean temperature",
    "temperature_max": "maximum temperature",
    "temperature_min": "overnight minimum temperature",
    "humidity_mean": "mean humidity",
    "humidity_min": "minimum humidity",
    "heat_index_mean": "mean heat index",
    "heat_index_max": "peak heat index",
    "wbgt_max": "peak WBGT",
    "utci_max": "peak UTCI",
    "wind_speed_mean": "mean wind speed",
    "solar_radiation_mean": "mean solar radiation",
    "solar_radiation_max": "peak solar radiation",
    "cat_today": "today's heat category",
    "hot_streak": "consecutive hot days",
    "diurnal_range": "day-night temperature range",
    "temp_humidity": "combined temperature and humidity",
    "temp_change_1d": "1-day temperature change",
    "temp_change_3d": "3-day temperature change",
    "heat_index_change": "1-day heat index change",
    "tmin_anomaly_7": "overnight minimum vs 7-day average",
    "day_sin": "day of year",
    "day_cos": "day of year",
    "month_sin": "month of year",
    "month_cos": "month of year",
    "season_PRE_MONSOON": "pre-monsoon season",
    "season_MONSOON": "monsoon season",
    "season_POST_MONSOON": "post-monsoon season",
    "season_WINTER": "winter season",
}

_SUFFIX = re.compile(r"^(?P<base>.+?)_(?P<kind>lag|rmean|rmax|rstd)_(?P<n>\d+)$")

_KIND_TEMPLATES = {
    "lag": "{label} {n} day(s) earlier",
    "rmean": "{n}-day average {label}",
    "rmax": "{n}-day highest {label}",
    "rstd": "{n}-day variability in {label}",
}

_THEMES = [
    ("heat index", ("heat_index",)),
    ("recent heat persistence", ("cat_today", "hot_streak")),
    ("UTCI thermal stress", ("utci",)),
    ("wet-bulb globe temperature", ("wbgt",)),
    ("humidity", ("humidity", "temp_humidity")),
    ("temperature", ("temperature", "temp_change", "diurnal_range", "tmin_")),
    ("solar radiation", ("solar_radiation",)),
    ("wind", ("wind_speed",)),
    ("time of year", ("season_", "day_", "month_")),
]


def feature_label(feature: str) -> str:
    """Turn a feature name into readable text. Deterministic and testable."""
    if feature in _BASE_LABELS:
        return _BASE_LABELS[feature]

    match = _SUFFIX.match(feature)
    if match:
        base = match.group("base")
        label = _BASE_LABELS.get(base, base.replace("_", " "))
        return _KIND_TEMPLATES[match.group("kind")].format(
            label=label, n=match.group("n")
        )

    return feature.replace("_", " ")


def feature_theme(feature: str) -> str:
    """Group a feature into a coarse theme for summary generation."""
    for theme, prefixes in _THEMES:
        if any(token in feature for token in prefixes):
            return theme
    return "other conditions"


def _join(items: list[str]) -> str:
    if len(items) == 1:
        return items[0]
    if len(items) == 2:
        return f"{items[0]} and {items[1]}"
    return ", ".join(items[:-1]) + f" and {items[-1]}"


def build_summary(
    predicted_category: str, factors: list[dict[str, Any]], top_n: int = 4
) -> str:
    """Deterministic sentence built from the ranked factors.

    No LLM, no randomness: the same factors always yield the same text.
    """
    if not factors:
        return (
            f"No feature contributions were available for the predicted "
            f"{predicted_category} category."
        )

    increasing: list[str] = []
    decreasing: list[str] = []
    for factor in factors[: top_n * 3]:
        theme = feature_theme(factor["feature"])
        bucket = (
            increasing if factor["direction"] == "increases_risk" else decreasing
        )
        if theme not in bucket:
            bucket.append(theme)

    parts: list[str] = []
    if increasing:
        parts.append(
            f"The model's {predicted_category} forecast is driven mainly by "
            f"{_join(increasing[:top_n])}."
        )
    else:
        parts.append(
            f"No feature pushed the model toward {predicted_category}."
        )
    if decreasing:
        parts.append(
            f"Moderating the forecast: {_join(decreasing[:2])}."
        )
    return " ".join(parts)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def explain_prediction(
    design: Any,
    class_index: int,
    predicted_category: str,
    top_n: int = 10,
) -> dict[str, Any]:
    """Explain one already-made prediction.

    `design` is the exact single-row DataFrame ml_service built and fed to
    the model, with the artifact's 84 feature names in the artifact's order.
    `class_index` is the class the model actually chose. Nothing here
    re-runs or second-guesses the prediction.
    """
    artifact = ml_service.load_artifact()
    feature_names = list(artifact["features"])
    model = artifact["model"]

    if list(design.columns) != feature_names:
        raise ExplainerUnavailableError(
            "The design matrix does not match the artifact's feature list, "
            "so SHAP values could not be attributed reliably.",
            details={
                "expected_features": len(feature_names),
                "received_features": len(design.columns),
            },
        )

    # SHAP's class axis is positional over the classes the MODEL actually
    # has, which is not the same as the label vocabulary. No EXTREME day
    # exists in the training record, so the estimator carries four classes
    # while `risk_levels` lists five. Indexing SHAP with the label would
    # read the wrong class, or fall off the end of the axis.
    model_classes = list(getattr(model, "classes_", []))
    if model_classes:
        try:
            class_position = model_classes.index(class_index)
        except ValueError:
            raise ExplainerUnavailableError(
                "The predicted class is not among the classes the model was "
                "trained on, so its contributions cannot be attributed.",
                details={
                    "predicted_class": class_index,
                    "model_classes": [int(c) for c in model_classes],
                },
            ) from None
        n_model_classes = len(model_classes)
    else:
        class_position = class_index
        n_model_classes = len(artifact["risk_levels"])

    explainer = get_explainer()

    try:
        raw = explainer.shap_values(design, check_additivity=False)
    except TypeError:
        # Older SHAP signatures do not accept check_additivity.
        raw = explainer.shap_values(design)
    except Exception as exc:  # noqa: BLE001
        logger.exception("SHAP computation failed")
        raise ExplainerUnavailableError(
            "SHAP values could not be computed for this input.",
            details={"error": str(exc)},
        ) from exc

    contributions = _normalise_shap_output(
        raw, len(feature_names), n_model_classes, class_position
    )

    if len(contributions) != len(feature_names):
        raise ExplainerUnavailableError(
            "SHAP returned a different number of contributions than there "
            "are features.",
            details={
                "contributions": len(contributions),
                "features": len(feature_names),
            },
        )

    values = design.iloc[0]
    factors = [
        {
            "feature": name,
            "feature_label": feature_label(name),
            "value": round(float(values[name]), 4),
            "shap_value": round(contribution, 6),
            "impact": round(abs(contribution), 6),
            "direction": (
                "increases_risk" if contribution > 0 else "decreases_risk"
            ),
        }
        for name, contribution in zip(feature_names, contributions)
    ]
    factors.sort(key=lambda item: item["impact"], reverse=True)

    return {
        "summary": build_summary(predicted_category, factors),
        "explained_class": predicted_category,
        "explained_class_index": class_index,
        "base_value": _base_value(explainer, class_position),
        "top_factors": factors[:top_n],
        "features_considered": len(feature_names),
        "method": (
            f"SHAP TreeExplainer over {type(artifact['model']).__name__}, "
            "attributed to the predicted class only."
        ),
        "caveat": EXPLANATION_CAVEAT,
    }
