"""Health / mortality data integration schemas (Phase 12)."""

from typing import Literal

from pydantic import BaseModel, Field

DataStatus = Literal["GOVERNMENT_REPORTED", "DEMO_SAMPLE"]


class HealthObservation(BaseModel):
    """One year x state/UT heat-wave mortality observation.

    Extensible on purpose: `population` and `exposure_period` are optional
    because the bundled dataset does not carry them, not because the schema
    forbids them. A future dataset that does supply them needs no schema
    change.
    """

    year: int = Field(..., ge=1900, le=2100)
    state: str = Field(..., min_length=1)
    category: str | None = Field(
        None, description="'State' or 'Union Territory', where known."
    )
    heat_wave_deaths: int = Field(..., ge=0)
    source: str = Field(..., min_length=1)
    data_status: DataStatus = Field(
        "GOVERNMENT_REPORTED",
        description=(
            "GOVERNMENT_REPORTED for real reported figures (this dataset); "
            "DEMO_SAMPLE must be used for any invented/illustrative row."
        ),
    )
    population: int | None = Field(None, ge=0)
    exposure_period: str | None = None


class HealthDataResponse(BaseModel):
    """Envelope for GET /api/v1/health-data."""

    data_status: DataStatus
    source_file: str
    records_returned: int
    records_loaded_total: int
    rejected_rows: int = Field(
        ..., description="Rows dropped during loading (malformed/duplicate)."
    )
    missing_value_rows: int = Field(
        ...,
        description=(
            "Well-formed rows kept out of `observations` because a required "
            "value (e.g. deaths) was not reported. Never coerced to zero."
        ),
    )
    observations: list[HealthObservation]
    notes: list[str]


class YearlyTotal(BaseModel):
    year: int
    total_deaths: int
    states_reporting: int


class RegionTotal(BaseModel):
    state: str
    total_deaths: int
    years_reporting: int
    high_risk_years: int


class ValidationResponse(BaseModel):
    """Envelope for GET /api/v1/health-data/validation.

    Deliberately descriptive rather than predictive by default: this
    repository does not contain a historical, year/state-matched model
    prediction series to compare the observed data against, so no
    confusion matrix, POD, precision/recall or correlation is fabricated.
    `notes` says so explicitly. `optimizer_service`-style predictive skill
    metrics can be computed by
    `health_data_service.compare_predictions_to_observations` whenever a
    real matched prediction series becomes available.
    """

    period: str
    regions_evaluated: int
    observations: int
    high_risk_threshold: int
    high_risk_events: int
    yearly_totals: list[YearlyTotal]
    top_regions: list[RegionTotal]
    notes: list[str]
