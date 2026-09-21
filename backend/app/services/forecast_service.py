"""Risk trajectory over the supported forecast horizon.

THE HONEST CONSTRAINT
The trained artifact stores `horizon_days: 3`. It was fitted on a single
target -- the heat category exactly three days after the feature date. It
does not predict day 1, 2, 4 or 5. Asking it to would mean feeding it a
question it was never trained to answer.

So a trajectory cannot come from the model alone. Each day is labelled with
the method that actually produced it:

    OBSERVED      derived from observed weather (today)
    NWP_DERIVED   heat category computed from the provider's numerical
                  weather forecast, using the same Heat Index bands the
                  model was trained against. A forecast, but not an ML one.
    ML_MODEL      the trained model's t+3 prediction, with its own
                  class probability

At t+3 both an ML and an NWP-derived value exist. Both are reported. Where
they disagree, that disagreement is information, not a bug to hide.

No day is ever produced by extrapolating the model beyond its horizon.
"""

from __future__ import annotations

import logging
from datetime import date as date_type
from datetime import timedelta
from typing import Any

from app.core.config import settings
from app.core.exceptions import ExternalServiceError
from app.services import ml_service

logger = logging.getLogger(__name__)

METHOD_OBSERVED = "OBSERVED"
METHOD_NWP = "NWP_DERIVED"
METHOD_ML = "ML_MODEL"

TREND_IMPROVING = "IMPROVING"
TREND_STABLE = "STABLE"
TREND_WORSENING = "WORSENING"

METHOD_NOTES = {
    METHOD_OBSERVED: (
        "Heat Index category computed from observed weather for this date."
    ),
    METHOD_NWP: (
        "Heat Index category computed from the provider's numerical weather "
        "forecast, using the same category edges the model was trained "
        "against. This is a weather forecast, not a machine-learning "
        "prediction."
    ),
    METHOD_ML: (
        "Predicted by the trained model at its supported 3-day horizon, with "
        "the model's own class probability as confidence."
    ),
}


def _daily_from_hourly(history: dict[str, Any]) -> Any:
    """Aggregate the hourly series to daily peak Heat Index, per the pipeline.

    Uses the pipeline's own `calculate_heat_index` and `_categorise`, so the
    bands here are identical to the ones the model was trained on.
    """
    import pandas as pd

    pipeline = ml_service.load_pipeline_module()

    times = history.get("time") or []
    if not times:
        raise ExternalServiceError(
            "The weather provider returned no hourly series.",
            status_code=422,
        )

    temperature = history.get("temperature") or []
    humidity = history.get("humidity") or []
    # A provider that returns series of differing lengths would otherwise
    # surface as a raw pandas ValueError (a 500 with a traceback) instead of
    # the project's error envelope. Same treatment as the empty-series case.
    if not len(temperature) == len(humidity) == len(times):
        raise ExternalServiceError(
            "The weather provider returned hourly series of differing "
            "lengths.",
            status_code=422,
            details={
                "time": len(times),
                "temperature": len(temperature),
                "humidity": len(humidity),
            },
        )

    frame = pd.DataFrame(
        {
            "timestamp": pd.to_datetime(times),
            "temperature": temperature,
            "humidity": humidity,
        }
    )
    frame = frame.dropna(subset=["temperature", "humidity"])
    frame["heat_index"] = pipeline.calculate_heat_index(
        frame["temperature"], frame["humidity"]
    )
    frame["date"] = frame["timestamp"].dt.floor("D")

    daily = (
        frame.groupby("date")
        .agg(heat_index_max=("heat_index", "max"), hours=("temperature", "size"))
        .reset_index()
    )
    # Partial days would understate the peak.
    daily = daily[daily["hours"] >= 20]
    daily["category_index"] = pipeline._categorise(daily["heat_index_max"])
    return daily


def compute_trend(levels: list[int]) -> str:
    """Deterministic trend from the ordered category indices.

    Compares the mean level of the later half of the trajectory against the
    earlier half. A single threshold, configurable, decides whether the
    difference is worth calling a trend at all.
    """
    if len(levels) < 2:
        return TREND_STABLE

    midpoint = len(levels) // 2
    earlier = levels[:midpoint] or levels[:1]
    later = levels[midpoint:]

    delta = (sum(later) / len(later)) - (sum(earlier) / len(earlier))
    threshold = settings.FORECAST_TREND_THRESHOLD

    if delta >= threshold:
        return TREND_WORSENING
    if delta <= -threshold:
        return TREND_IMPROVING
    return TREND_STABLE


def build_trajectory(
    history: dict[str, Any], days: int
) -> dict[str, Any]:
    """Assemble the trajectory from observed, NWP-derived and ML sources."""
    import pandas as pd

    artifact = ml_service.load_artifact()
    levels = list(artifact["risk_levels"])
    horizon = int(artifact["horizon_days"])

    daily = _daily_from_hourly(history)
    if daily.empty:
        raise ExternalServiceError(
            "Not enough complete daily data to build a trajectory.",
            status_code=422,
        )

    # The provider returns past days then forecast days in one series. The
    # last day with a full 24 hours of observations is "today"; anything
    # after it comes from the numerical forecast.
    today = pd.Timestamp(date_type.today())
    observed = daily[daily["date"] <= today]
    based_on: date_type = (
        observed["date"].max().date()
        if not observed.empty
        else daily["date"].max().date()
    )

    # The model's single supported horizon.
    ml_prediction = ml_service.forecast_from_history(history)
    ml_design = ml_prediction.pop("_design")
    ml_target = based_on + timedelta(days=horizon)

    entries: list[dict[str, Any]] = []
    for _, row in daily.iterrows():
        target: date_type = row["date"].date()
        offset = (target - based_on).days
        if offset < 0 or offset >= days:
            continue

        index = int(row["category_index"])
        method = METHOD_OBSERVED if offset == 0 else METHOD_NWP

        entry: dict[str, Any] = {
            "target_date": target,
            "days_ahead": offset,
            "risk_level": levels[index],
            "risk_level_index": index,
            "heat_index_max": round(float(row["heat_index_max"]), 1),
            "method": method,
            "confidence": None,
            "method_note": METHOD_NOTES[method],
            "model_risk_level": None,
            "model_confidence": None,
        }

        if target == ml_target:
            # Both sources exist here. Report both rather than picking one.
            entry["model_risk_level"] = ml_prediction["predicted_category"]
            entry["model_confidence"] = ml_prediction["confidence"]
            entry["method"] = METHOD_ML
            entry["confidence"] = ml_prediction["confidence"]
            entry["risk_level"] = ml_prediction["predicted_category"]
            entry["risk_level_index"] = ml_prediction["predicted_class_index"]
            entry["method_note"] = (
                METHOD_NOTES[METHOD_ML]
                + " The numerical forecast for this date implies "
                + f"{levels[index]}."
            )

        entries.append(entry)

    entries.sort(key=lambda item: item["target_date"])
    if not entries:
        raise ExternalServiceError(
            "No forecast days could be assembled from the provider series.",
            status_code=422,
        )

    indices = [entry["risk_level_index"] for entry in entries]
    peak = max(entries, key=lambda entry: entry["risk_level_index"])

    return {
        "based_on": based_on,
        "days_requested": days,
        "days_returned": len(entries),
        "model_horizon_days": horizon,
        "forecast": entries,
        "peak_risk": peak["risk_level"],
        "peak_date": peak["target_date"],
        "trend": compute_trend(indices),
        "method_summary": {
            METHOD_OBSERVED: sum(
                1 for e in entries if e["method"] == METHOD_OBSERVED
            ),
            METHOD_NWP: sum(1 for e in entries if e["method"] == METHOD_NWP),
            METHOD_ML: sum(1 for e in entries if e["method"] == METHOD_ML),
        },
        "limitations": [
            f"The trained model supports a single {horizon}-day horizon. Only "
            "the day at that horizon carries a machine-learning prediction; "
            "every other day is derived from the provider's numerical weather "
            "forecast using the same Heat Index bands.",
            "NWP-derived days carry no confidence value, because a weather "
            "forecast converted to a category has no model probability "
            "attached.",
            "Categories describe heat HAZARD, not health outcomes.",
        ],
    }


async def get_trajectory(
    latitude: float, longitude: float, days: int
) -> dict[str, Any]:
    """Fetch weather once and build the trajectory from it."""
    from app.services import weather_service

    history = await weather_service.get_hourly_history(
        latitude,
        longitude,
        past_days=settings.ML_HISTORY_DAYS,
        # +1 so the requested horizon is fully covered after "today".
        forecast_days=min(days + 1, 16),
    )
    trajectory = build_trajectory(history, days)
    trajectory["location"] = history["location"].model_dump()
    return trajectory
