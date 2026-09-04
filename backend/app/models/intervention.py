"""Heat action simulator schemas (Phase 9)."""

from typing import Literal

from pydantic import BaseModel, Field

InterventionType = Literal[
    "COOLING_CENTER",
    "WATER_DISTRIBUTION",
    "WORK_HOUR_SHIFT",
    "PUBLIC_ALERT",
    "SHADE_REST_AREA",
]


class InterventionInput(BaseModel):
    """One intervention and the share of the population it reaches."""

    type: InterventionType
    coverage: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Share of the affected population reached, 0 to 1.",
        examples=[0.6],
    )


class SimulationRequest(BaseModel):
    """Input for POST /api/v1/interventions/simulate."""

    zone_id: str = Field(
        ...,
        description="Zone to simulate. Must exist in the zone dataset.",
        examples=["ZONE_01"],
    )
    interventions: list[InterventionInput] = Field(
        ..., min_length=1, max_length=5
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "zone_id": "ZONE_01",
                "interventions": [
                    {"type": "COOLING_CENTER", "coverage": 0.6},
                    {"type": "WATER_DISTRIBUTION", "coverage": 0.4},
                ],
            }
        }
    }


class RiskSnapshot(BaseModel):
    risk_score: float = Field(..., ge=0.0, le=1.0)
    risk_level: str
    thermal_stress: float = Field(..., ge=0.0, le=1.0)
    vulnerability: float = Field(..., ge=0.0, le=1.0)


class AppliedIntervention(BaseModel):
    type: str
    label: str
    channel: Literal["VULNERABILITY", "EXPOSURE"]
    coverage: float
    max_effect: float = Field(
        ..., description="Configured maximum effect at full coverage."
    )
    applied_effect: float = Field(..., description="max_effect x coverage.")
    assumption: str


class SimulationResponse(BaseModel):
    """Baseline versus simulated risk under the supplied interventions."""

    zone_id: str | None = None
    baseline: RiskSnapshot
    simulation: RiskSnapshot
    estimated_risk_reduction: float = Field(
        ..., ge=0.0, description="Absolute change in modelled risk score."
    )
    estimated_risk_reduction_percent: float = Field(..., ge=0.0)
    risk_level_changed: bool
    applied_interventions: list[AppliedIntervention]
    channel_reductions: dict[str, float]
    assumptions: list[str]
    disclaimer: str


class InterventionCatalogueEntry(BaseModel):
    type: str
    label: str
    channel: str
    max_effect: float
    assumption: str


class InterventionCatalogue(BaseModel):
    """Envelope for GET /api/v1/interventions/types."""

    interventions: list[InterventionCatalogueEntry]
    disclaimer: str
