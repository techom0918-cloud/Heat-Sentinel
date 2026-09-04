"""Thermal stress schemas.

Units, fixed for the whole engine:

    temperature       degrees Celsius
    relative humidity percent (0-100)
    wind speed        metres per second
    solar radiation   watts per square metre

Every index carries an explicit `classification` so a reader can tell at a
glance whether a number is a recognised calculation, an approximation, or a
reference implementation. None of these values is a medical diagnosis.
"""

from typing import Literal

from pydantic import BaseModel, Field

MethodClassification = Literal[
    "RECOGNISED_CALCULATION",
    "APPROXIMATION",
    "REFERENCE_IMPLEMENTATION",
]


class ThermalCalculationRequest(BaseModel):
    """Input for POST /api/v1/thermal/calculate."""

    temperature: float = Field(
        ...,
        ge=-90.0,
        le=60.0,
        description=(
            "Air temperature in degrees Celsius. Bounds are the observed "
            "terrestrial record range (-89.2 to 56.7 C), deliberately wide "
            "so genuine extreme-heat scenarios are not rejected."
        ),
        examples=[42.0],
    )
    relative_humidity: float = Field(
        ...,
        ge=0.0,
        le=100.0,
        description="Relative humidity in percent.",
        examples=[60.0],
    )
    wind_speed: float = Field(
        0.0,
        ge=0.0,
        description=(
            "Wind speed in metres per second. Used by UTCI only; the Heat "
            "Index and the shade WBGT approximation do not take wind."
        ),
        examples=[2.0],
    )
    solar_radiation: float | None = Field(
        None,
        ge=0.0,
        description=(
            "Shortwave solar radiation in W/m^2. Accepted and echoed back, "
            "but NOT used by any current calculation -- see the WBGT "
            "limitations. Reserved for a future outdoor WBGT formulation."
        ),
        examples=[500.0],
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "temperature": 42.0,
                "relative_humidity": 60.0,
                "wind_speed": 2.0,
                "solar_radiation": 500.0,
            }
        }
    }


class ThermalMethod(BaseModel):
    """Provenance record for one index."""

    index: str = Field(..., description="Index name.")
    method: str = Field(..., description="Calculation method and citation.")
    classification: MethodClassification = Field(
        ...,
        description=(
            "RECOGNISED_CALCULATION: published, standard algorithm. "
            "APPROXIMATION: simplified estimate, not the full formulation. "
            "REFERENCE_IMPLEMENTATION: computed by a maintained library "
            "implementing the published model."
        ),
    )
    assumptions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class ThermalStressResult(BaseModel):
    """Computed thermal stress for one set of conditions."""

    temperature: float = Field(..., description="Echoed input, deg C.")
    relative_humidity: float = Field(..., description="Echoed input, percent.")
    wind_speed: float = Field(..., description="Echoed input, m/s.")
    solar_radiation: float | None = Field(
        None, description="Echoed input, W/m^2. Not used in any calculation."
    )

    heat_index: float | None = Field(
        None, description="NWS Heat Index, deg C. Null if not computable."
    )
    heat_index_category: str = Field(
        ...,
        description=(
            "Prototype band from configurable Celsius edges. NOT a medical "
            "classification."
        ),
    )

    wet_bulb_temperature: float | None = Field(
        None, description="Stull (2011) estimated wet-bulb temperature, deg C."
    )
    wbgt: float | None = Field(
        None, description="Shade WBGT approximation, deg C."
    )
    wbgt_category: str = Field(
        ...,
        description=(
            "Always NOT_CLASSIFIED. Published WBGT limits (ISO 7243, ACGIH) "
            "apply to full outdoor WBGT and depend on metabolic rate and "
            "acclimatisation, so they cannot be applied to a shade "
            "approximation without misrepresenting them."
        ),
    )

    utci: float | None = Field(
        None,
        description=(
            "Universal Thermal Climate Index, deg C. Null when inputs fall "
            "outside the model's applicability limits."
        ),
    )
    utci_category: str = Field(
        ...,
        description=(
            "Official UTCI thermal stress category (Brode et al. 2012), or "
            "NOT_AVAILABLE when UTCI could not be computed."
        ),
    )

    assumptions: list[str] = Field(
        default_factory=list,
        description="Flat list of every assumption applied to this result.",
    )
    methods: list[ThermalMethod] = Field(
        default_factory=list,
        description="Per-index method, classification, and limitations.",
    )
    notes: list[str] = Field(
        default_factory=list,
        description="Condition-specific warnings raised for these inputs.",
    )


class ThermalCurrentResponse(BaseModel):
    """Envelope for GET /api/v1/thermal/current."""

    location: dict = Field(..., description="Resolved provider grid cell.")
    observed_at: str = Field(..., description="Local observation time.")
    weather: dict = Field(..., description="Current weather as retrieved.")
    thermal: ThermalStressResult
    provider: str
