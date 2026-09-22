"""Schemas for the Phase 8/9/10/11 heat_index classifier endpoints.

Distinct from `models/hazard.py`, which describes the SEPARATE 3-day-ahead
hazard forecast model. See `heat_index_service.py` for why these are two
different models with two different response shapes.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class HeatIndexModelInfo(BaseModel):
    model_type: str
    feature_count: int
    features: list[str]
    target_classes_learned: list[str]
    target_classes_all: list[str]
    classes_with_no_training_data: list[str]
    training_period: list[int] | None = None
    validation_period: list[int] | None = None
    test_period: list[int] | None = None
    metrics: dict = Field(default_factory=dict)
    weather_resolution: str
    limitations: list[str]

    model_config = {"protected_namespaces": ()}


class HeatIndexModelStatusResponse(BaseModel):
    available: bool
    detail: str
    explainer_available: bool = False
    model_info: HeatIndexModelInfo | None = None

    model_config = {"protected_namespaces": ()}


class HeatIndexPredictionRequest(BaseModel):
    """Feature values by name. Any subset of the model's features may be
    given; missing ones are imputed with training medians and reported
    back in `features_missing_and_imputed` -- never silently zero-filled.
    """

    features: dict[str, float] = Field(
        ...,
        description="feature_name -> value. See GET /heat-index/model for the full feature list.",
        examples=[{
            "temperature_2m_c": 41.0, "relative_humidity_pct": 45.0,
            "wind_speed_10m_ms": 2.5, "shortwave_radiation_wm2": 700.0,
            "month": 6, "hour": 14, "latitude": 28.61, "longitude": 77.21,
        }],
    )


class HeatIndexPredictionResponse(BaseModel):
    predicted_category: str
    probabilities: dict[str, float]
    features_used: list[str]
    features_missing_and_imputed: list[str] = Field(
        default_factory=list,
        description="Model features not supplied; filled with training-year medians.",
    )
    features_ignored: list[str] = Field(
        default_factory=list, description="Supplied keys the model does not use."
    )
    weather_resolution: str
    disclaimer: str


class HeatIndexExplanationFactor(BaseModel):
    feature: str
    value: float
    shap_value: float
    impact: float = Field(..., ge=0.0)
    direction: Literal["increases_risk", "decreases_risk"]


class HeatIndexExplanationResponse(BaseModel):
    predicted_category: str
    probabilities: dict[str, float]
    base_value: float | None = None
    top_factors: list[HeatIndexExplanationFactor]
    method: str
    caveat: str


class GridCellRisk(BaseModel):
    cell_id: str
    latitude: float
    longitude: float
    predicted_category: str
    probabilities: dict[str, float]
    heat_index_source_weather_point: str
    nearest_weather_distance_km: float
    weather_timestamp: datetime
    data_source: Literal["batch_prediction"] = "batch_prediction"


class GridRiskResponse(BaseModel):
    """Deliberately a plain list, not a GeoJSON FeatureCollection, because
    the precomputed batch output carries point coordinates (cell centroid),
    not polygon geometry -- attaching real cell polygons means joining the
    618k-cell GPKG at request time, which this endpoint does not do by
    default for latency reasons. geometry_available=false says so.
    """

    count: int
    total_cells_in_bbox: int
    truncated: bool = Field(
        ..., description="True if total_cells_in_bbox exceeded the response cap."
    )
    geometry_available: bool = False
    weather_resolution: str
    batch_generated_at: datetime | None = None
    cells: list[GridCellRisk]
