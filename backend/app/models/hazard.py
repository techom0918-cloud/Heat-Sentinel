"""Heat hazard forecast schemas (trained-model output).

Distinct from the risk schemas on purpose. This describes a HAZARD -- how
hot it will be -- not a health risk. The model was trained on meteorological
variables only; no mortality, demographic or health data was involved.
"""

from datetime import date as date_type
from typing import Literal

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


class ExplanationFactor(BaseModel):
    """One feature's SHAP contribution to the predicted class."""

    feature: str = Field(..., description="Model feature name.")
    feature_label: str = Field(
        ..., description="Readable version of the feature name."
    )
    value: float = Field(..., description="The feature's value for this input.")
    shap_value: float = Field(
        ...,
        description=(
            "Signed SHAP contribution toward the predicted class. Positive "
            "pushed the model toward that class, negative away from it."
        ),
    )
    impact: float = Field(
        ..., ge=0.0, description="Absolute SHAP value. The ranking key."
    )
    direction: Literal["increases_risk", "decreases_risk"]


class Explanation(BaseModel):
    """SHAP explanation of one prediction.

    Describes model behaviour, not causation.
    """

    summary: str = Field(
        ..., description="Deterministic sentence built from the top factors."
    )
    explained_class: str = Field(
        ..., description="The class these contributions are attributed to."
    )
    explained_class_index: int
    base_value: float | None = Field(
        None, description="Expected model output before feature contributions."
    )
    top_factors: list[ExplanationFactor] = Field(
        ..., description="Ranked by absolute SHAP magnitude, descending."
    )
    features_considered: int
    method: str
    caveat: str


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
    explanation: Explanation | None = Field(
        None,
        description=(
            "Present only when `explain=true`. SHAP is skipped otherwise "
            "because it is the expensive part of the request."
        ),
    )
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str

    model_config = {"protected_namespaces": ()}


class ModelStatusResponse(BaseModel):
    """Envelope for GET /api/v1/risk/model."""

    available: bool
    detail: str
    explainer_available: bool = False
    model_info: ModelInfo | None = None

    model_config = {"protected_namespaces": ()}
