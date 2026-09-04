"""Hyperlocal zone schemas (Phase 8).

GeoJSON-shaped so any mapping library can consume the response directly.
"""

from typing import Any, Literal

from pydantic import BaseModel, Field


class ZoneProperties(BaseModel):
    """Per-zone properties.

    Deliberately separates the four things a decision-maker needs to keep
    apart: hazard, vulnerability, their combination, and what to do first.
    """

    zone_id: str
    name: str | None = None
    data_status: str = Field(
        ..., description="SYNTHETIC_DEMO for the bundled development dataset."
    )

    # 1. hazard
    heat_hazard: float = Field(
        ..., ge=0.0, le=1.0, description="Normalised thermal stress."
    )
    heat_index: float | None = None
    wbgt: float | None = None
    utci: float | None = None

    # 2. vulnerability
    vulnerability: float = Field(..., ge=0.0, le=1.0)
    vulnerability_level: str

    # 3. combined
    human_risk: float = Field(..., ge=0.0, le=1.0)
    risk_level: str

    # 4. priority
    priority: Literal["LOW", "MODERATE", "HIGH", "CRITICAL"]

    vulnerability_contributions: dict[str, float] = Field(default_factory=dict)


class ZoneFeature(BaseModel):
    type: Literal["Feature"] = "Feature"
    geometry: dict[str, Any] | None
    properties: ZoneProperties


class ZoneRiskCollection(BaseModel):
    """GeoJSON FeatureCollection returned by GET /api/v1/zones/risk."""

    type: Literal["FeatureCollection"] = "FeatureCollection"
    data_status: str
    warning: str
    hazard_source: dict[str, Any]
    features: list[ZoneFeature]
