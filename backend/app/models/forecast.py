"""Risk trajectory schemas (Phase 7)."""

from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, Field

ForecastMethod = Literal["OBSERVED", "NWP_DERIVED", "ML_MODEL"]
Trend = Literal["IMPROVING", "STABLE", "WORSENING"]


class ForecastDay(BaseModel):
    """One day of the trajectory, labelled with the method that produced it."""

    target_date: date_type
    days_ahead: int = Field(..., ge=0)
    risk_level: str
    risk_level_index: int
    heat_index_max: float = Field(..., description="Daily peak Heat Index, C.")
    method: ForecastMethod = Field(
        ...,
        description=(
            "OBSERVED: from observed weather. NWP_DERIVED: category computed "
            "from the provider's numerical forecast, not an ML prediction. "
            "ML_MODEL: the trained model at its supported horizon."
        ),
    )
    confidence: float | None = Field(
        None,
        ge=0.0,
        le=1.0,
        description=(
            "Present only for ML_MODEL days. A weather forecast converted to "
            "a category carries no model probability."
        ),
    )
    method_note: str
    model_risk_level: str | None = Field(
        None, description="Model's category, where a model day exists."
    )
    model_confidence: float | None = None

    model_config = {"protected_namespaces": ()}


class TrajectoryResponse(BaseModel):
    """Envelope for GET /api/v1/forecast/risk."""

    location: dict
    based_on: date_type = Field(..., description="Last fully observed day.")
    days_requested: int
    days_returned: int
    model_horizon_days: int = Field(
        ..., description="The single horizon the trained model supports."
    )
    forecast: list[ForecastDay]
    peak_risk: str
    peak_date: date_type
    trend: Trend
    method_summary: dict[str, int]
    limitations: list[str] = Field(default_factory=list)

    model_config = {"protected_namespaces": ()}
