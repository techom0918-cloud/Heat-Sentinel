"""AI Action Optimizer schemas (Phase 10)."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from app.models.intervention import InterventionType


class ResourceInventory(BaseModel):
    """Physical resources available to an intervention plan.

    Field names match the resource each intervention type is configured to
    consume (see `settings.optimizer_unit_economics`). Extending the roster
    of interventions later means adding a field here and a matching config
    entry -- nothing structural changes.
    """

    cooling_centers: int = Field(0, ge=0, examples=[2])
    water_tankers: int = Field(0, ge=0, examples=[10])
    field_workers: int = Field(0, ge=0, examples=[50])


class OptimizerRequest(BaseModel):
    """Input for POST /api/v1/interventions/optimize."""

    zone_id: str = Field(..., examples=["ZONE_01"])
    budget: float = Field(..., ge=0.0, examples=[500000])
    available_resources: ResourceInventory
    allowed_interventions: list[InterventionType] | None = Field(
        None,
        min_length=1,
        max_length=5,
        description=(
            "Interventions the optimizer may choose from. Defaults to every "
            "supported intervention type when omitted."
        ),
    )

    @model_validator(mode="after")
    def _no_duplicate_interventions(self) -> "OptimizerRequest":
        if self.allowed_interventions is not None:
            if len(set(self.allowed_interventions)) != len(
                self.allowed_interventions
            ):
                raise ValueError(
                    "allowed_interventions must not contain duplicates."
                )
        return self

    model_config = {
        "json_schema_extra": {
            "example": {
                "zone_id": "ZONE_01",
                "budget": 500000,
                "available_resources": {
                    "cooling_centers": 2,
                    "water_tankers": 10,
                    "field_workers": 50,
                },
                "allowed_interventions": [
                    "COOLING_CENTER",
                    "WATER_DISTRIBUTION",
                    "WORK_HOUR_SHIFT",
                    "PUBLIC_ALERT",
                    "SHADE_REST_AREA",
                ],
            }
        }
    }


class RecommendedAction(BaseModel):
    """One intervention type and how much of it the plan recommends."""

    type: InterventionType
    quantity: int = Field(..., ge=1, description="Resource units recommended.")
    resource_type: str
    coverage: float = Field(
        ..., ge=0.0, le=1.0, description="quantity x coverage_per_unit, capped."
    )
    unit_cost: float = Field(..., ge=0.0)
    cost: float = Field(..., ge=0.0, description="quantity x unit_cost.")
    channel: Literal["VULNERABILITY", "EXPOSURE"]
    assumption: str


class OptimizerResponse(BaseModel):
    """Envelope for POST /api/v1/interventions/optimize."""

    zone_id: str
    baseline_risk: float = Field(..., ge=0.0, le=1.0)
    baseline_risk_level: str
    optimized_risk: float = Field(..., ge=0.0, le=1.0)
    optimized_risk_level: str
    estimated_risk_reduction: float = Field(..., ge=0.0)
    estimated_risk_reduction_percent: float = Field(..., ge=0.0)
    risk_level_changed: bool
    recommended_actions: list[RecommendedAction]
    resources_used: dict[str, int]
    resources_remaining: dict[str, int]
    budget: float
    budget_used: float
    budget_remaining: float
    method: str
    assumptions: list[str]
    disclaimer: str
