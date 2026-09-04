"""Heat hazard forecast schemas (trained-model output).

Distinct from the risk schemas on purpose. This describes a HAZARD -- how
hot it will be -- not a health risk. The model was trained on meteorological
variables only; no mortality, demographic or health data was involved.
"""

from datetime import date as date_type

from pydantic import BaseModel, Field


class ModelPerformance(BaseModel):
    """Held-out test metrics, published with every prediction."""

    accuracy: float | None = None
    f1: float | None = None
    POD: float | None = Field(
        None, description="Probability of detection: share of events caught."
    )
    FAR: float | None = Field(
        None, description="False alarm ratio: share of alerts that were wrong."
    )
    CSI: float | None = Field(
        None, description="Critical success index, the selection metric."
    )
    hits: int | None = None
    misses: int | None = None
    false_alarms: int | None = None


class ModelInfo(BaseModel):
    """What produced this prediction."""

    type: str
    feature_count: int
    horizon_days: int
    risk_levels: list[str]
    heat_index_edges: list[float] | None = None
    trained_on: str
    test_metrics: ModelPerformance


class HazardForecastResponse(BaseModel):
    """Envelope for GET /api/v1/risk/forecast."""

    location: dict
    based_on: date_type = Field(
        ..., description="Last day of observations used to build features."
    )
    issued_for: date_type = Field(
        ..., description="Day the forecast applies to (based_on + horizon)."
    )
    horizon_days: int

    predicted_category: str = Field(
        ..., description="Forecast heat hazard band."
    )
    predicted_class_index: int
    confidence: float | None = Field(
        None,
        description=(
            "The model's probability for the predicted class. NOT a "
            "calibrated forecast probability."
        ),
    )
    class_probabilities: dict[str, float] = Field(default_factory=dict)

    current_category: str = Field(
        ..., description="Observed band on `based_on`, the persistence baseline."
    )
    current_heat_index_max: float
    days_of_history_used: int

    model_info: ModelInfo
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str

    model_config = {"protected_namespaces": ()}


class ModelStatusResponse(BaseModel):
    """Envelope for GET /api/v1/risk/model."""

    available: bool
    detail: str
    model_info: ModelInfo | None = None

    model_config = {"protected_namespaces": ()}
