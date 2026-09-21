"""Health risk schemas.

PROTOTYPE DECISION-SUPPORT SCORE. Not a medically validated prediction
model. Weights and thresholds are uncalibrated starting values, held in
app/core/config.py so they can be replaced without touching code.

This layer CONSUMES thermal indices computed by the thermal engine. It never
recalculates Heat Index, WBGT or UTCI -- that separation is deliberate and
enforced by a test.

`allow_inf_nan=False` appears on every float field on purpose: a field with
only a lower bound (`ge=0`) accepts `Infinity` in Pydantic v2, which would
propagate silently through the whole score.
"""

from typing import Literal

from pydantic import BaseModel, Field

DISCLAIMER = (
    "PROTOTYPE HEALTH-RISK SCORE - NOT A MEDICALLY VALIDATED PREDICTION "
    "MODEL. Weights, normalisation anchors and thresholds are uncalibrated "
    "prototype values. This describes a population, never an individual."
)


class RiskPredictionRequest(BaseModel):
    """Input for POST /api/v1/risk/predict.

    Thermal indices are expected to come from
    `POST /api/v1/thermal/calculate`, and `vulnerability_score` from
    `POST /api/v1/vulnerability/calculate`.
    """

    temperature_c: float = Field(
        ...,
        ge=-90.0,
        le=60.0,
        allow_inf_nan=False,
        description="Air temperature, deg C. Context only; not scored directly.",
        examples=[42.0],
    )
    relative_humidity: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        allow_inf_nan=False,
        description="Relative humidity, percent. Context only.",
        examples=[65.0],
    )
    wind_speed: float = Field(
        0.0,
        ge=0.0,
        le=150.0,
        allow_inf_nan=False,
        description="Wind speed, m/s. Context only.",
        examples=[2.5],
    )
    solar_radiation: float | None = Field(
        None,
        ge=0.0,
        le=2000.0,
        allow_inf_nan=False,
        description="Shortwave solar radiation, W/m^2. Context only.",
        examples=[700.0],
    )

    heat_index: float = Field(
        ...,
        ge=-100.0,
        le=150.0,
        allow_inf_nan=False,
        description=(
            "Heat Index in deg C, as returned by the thermal engine. "
            "Not recalculated here."
        ),
        examples=[49.2],
    )
    wbgt: float = Field(
        ...,
        ge=-50.0,
        le=100.0,
        allow_inf_nan=False,
        description=(
            "Shade WBGT approximation in deg C, from the thermal engine."
        ),
        examples=[31.5],
    )
    utci: float | None = Field(
        None,
        ge=-100.0,
        le=100.0,
        allow_inf_nan=False,
        description=(
            "UTCI in deg C, from the thermal engine. OPTIONAL because the "
            "UTCI model returns no value above 50 C air temperature -- which "
            "occurs in India. When null, its weight is redistributed "
            "proportionally across the remaining thermal indices."
        ),
        examples=[43.1],
    )

    vulnerability_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        allow_inf_nan=False,
        description=(
            "Population vulnerability, 0 to 1, from the vulnerability engine."
        ),
        examples=[0.78],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "temperature_c": 42.0,
                "relative_humidity": 65.0,
                "wind_speed": 2.5,
                "solar_radiation": 700.0,
                "heat_index": 49.2,
                "wbgt": 31.5,
                "utci": 43.1,
                "vulnerability_score": 0.78,
            }
        }
    }


class RiskContributor(BaseModel):
    """One factor's share of the final score.

    PROTOTYPE CONTRIBUTION, deliberately NOT a SHAP value. It is simply
    `weight x normalised factor`, and the contributors sum to `risk_score`.
    Real SHAP values arrive with the XGBoost model in a later phase.
    """

    factor: str
    impact: float = Field(..., description="weight x normalised value.")
    direction: Literal["increases", "neutral"] = Field(
        ...,
        description=(
            "Every factor in this prototype is non-negative, so nothing "
            "reduces risk. 'neutral' means a contribution of exactly zero."
        ),
    )
    normalised_value: float = Field(..., ge=0.0, le=1.0)
    weight: float = Field(..., ge=0.0, le=1.0)


class RiskComponents(BaseModel):
    """The two top-level blocks that make up the score."""

    thermal_stress: float = Field(..., ge=0.0, le=1.0)
    vulnerability: float = Field(..., ge=0.0, le=1.0)


class RiskPredictionResponse(BaseModel):
    """Result of a prototype risk calculation."""

    risk_score: float = Field(..., ge=0.0, le=1.0)
    risk_probability: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description=(
            "Currently identical to `risk_score`. This is NOT a calibrated "
            "probability -- no model has been fitted to outcome data. The "
            "field exists so the contract does not change when a trained "
            "model later supplies a real probability."
        ),
    )
    risk_level: Literal["LOW", "MODERATE", "HIGH", "EXTREME"]
    confidence: float | None = Field(
        None,
        description=(
            "Always null until a trained model exists. A confidence value "
            "from a hand-weighted formula would be meaningless."
        ),
    )
    components: RiskComponents
    contributors: list[RiskContributor]
    normalised_indices: dict[str, float | None] = Field(
        ..., description="Each thermal index after normalisation to 0-1."
    )
    weights: dict[str, float] = Field(
        ..., description="Weights actually applied, after any redistribution."
    )
    normalisation_anchors: dict[str, str] = Field(
        ..., description="Range each index was scaled against, and its source."
    )
    thresholds: dict[str, float]
    method: str
    limitations: list[str] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    disclaimer: str = Field(default=DISCLAIMER)
