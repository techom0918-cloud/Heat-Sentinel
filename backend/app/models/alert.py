"""Early warning & alert schemas (Phase 11)."""

from datetime import date as date_type
from typing import Literal

from pydantic import BaseModel, Field

from app.core.config import settings

AlertLevel = Literal["LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"]
AlertPriority = Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]
Trend = Literal["IMPROVING", "STABLE", "WORSENING"]


class AlertRequest(BaseModel):
    """Input for POST /api/v1/alerts/evaluate."""

    zone_id: str = Field(..., examples=["ZONE_01"])
    days: int = Field(
        settings.FORECAST_MAX_DAYS,
        ge=1,
        le=settings.FORECAST_MAX_DAYS,
        description="Forecast window to evaluate, in days.",
    )

    model_config = {
        "json_schema_extra": {"example": {"zone_id": "ZONE_01"}}
    }


class AlertResponse(BaseModel):
    """Envelope for POST /api/v1/alerts/evaluate."""

    zone_id: str
    alert_required: bool
    alert_level: AlertLevel
    priority: AlertPriority
    reason: str
    current_risk: AlertLevel
    forecast_peak: AlertLevel
    peak_date: date_type
    trend: Trend
    escalation: bool = Field(
        ..., description="True when forecast_peak is worse than current_risk."
    )
    escalation_label: str | None = Field(
        None, description="'X -> Y' when escalation is true, else null."
    )
    vulnerability_level: str
    based_on: date_type = Field(..., description="Last fully observed day.")
    recommended_actions: list[str]
    assumptions: list[str]
    disclaimer: str
