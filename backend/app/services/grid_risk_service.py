"""Phase 10 -- 300m spatial risk, served from Phase 9's precomputed batch file.

Never runs model inference per request and never loads all 618,373 cells
into a response. `ml/predict_grid_300m.py` does the (offline) inference;
this module only reads that parquet, filters by bbox, and caps the count.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path
from typing import Any

import pandas as pd

from app.core.config import settings
from app.core.exceptions import HeatSentinalError

logger = logging.getLogger(__name__)


class GridPredictionsUnavailableError(HeatSentinalError):
    """Phase 9's batch output has not been generated yet."""

    status_code = 503
    error_type = "grid_predictions_unavailable"


class InvalidBboxError(HeatSentinalError):
    """Bbox query params were partially supplied."""

    status_code = 422
    error_type = "invalid_bbox"


def _resolve(path_value: str) -> Path:
    path = Path(path_value)
    if path.is_absolute():
        return path
    backend_root = Path(__file__).resolve().parents[2]
    return (backend_root / path).resolve()


@lru_cache(maxsize=1)
def _load_predictions() -> pd.DataFrame:
    """Loaded once per process and cached -- this file changes only when
    ml/predict_grid_300m.py is re-run, which also happens outside a
    request. Call reset_cache() after regenerating it."""
    path = _resolve(settings.HEAT_INDEX_GRID_PREDICTIONS_PATH)
    if not path.exists():
        raise GridPredictionsUnavailableError(
            "No precomputed 300m grid predictions found. Run "
            "ml/predict_grid_300m.py first.",
            details={"expected_path": str(path)},
        )
    df = pd.read_parquet(path)
    logger.info("Loaded %d precomputed grid predictions from %s", len(df), path)
    return df


def reset_cache() -> None:
    _load_predictions.cache_clear()


def get_grid_risk(
    min_lat: float | None, max_lat: float | None,
    min_lon: float | None, max_lon: float | None,
) -> dict[str, Any]:
    df = _load_predictions()

    if any(v is not None for v in (min_lat, max_lat, min_lon, max_lon)):
        if None in (min_lat, max_lat, min_lon, max_lon):
            raise InvalidBboxError(
                "Provide all four of min_lat/max_lat/min_lon/max_lon, or none."
            )
        mask = (
            (df["latitude"] >= min_lat) & (df["latitude"] <= max_lat)
            & (df["longitude"] >= min_lon) & (df["longitude"] <= max_lon)
        )
        subset = df[mask]
    else:
        subset = df

    total = len(subset)
    cap = settings.GRID_RISK_MAX_CELLS
    truncated = total > cap
    subset = subset.head(cap)

    prob_cols = [c for c in subset.columns if c.startswith("probability_")]
    cells = []
    for _, row in subset.iterrows():
        cells.append({
            "cell_id": row["cell_id"],
            "latitude": float(row["latitude"]),
            "longitude": float(row["longitude"]),
            "predicted_category": row["predicted_category"],
            "probabilities": {
                c.removeprefix("probability_"): float(row[c]) for c in prob_cols
            },
            "heat_index_source_weather_point": row["heat_index_source_weather_point"],
            "nearest_weather_distance_km": float(row["nearest_weather_distance_km"]),
            "weather_timestamp": row["weather_timestamp"],
        })

    return {
        "count": len(cells),
        "total_cells_in_bbox": total,
        "truncated": truncated,
        "geometry_available": False,
        "weather_resolution": (
            "Weather associated from ~10-25 km nearest point/reanalysis "
            "source -- see heat_index_source_weather_point and "
            "nearest_weather_distance_km per cell. Not 300m weather."
        ),
        "batch_generated_at": (
            subset["batch_generated_at"].iloc[0] if len(subset) else None
        ),
        "cells": cells,
    }
