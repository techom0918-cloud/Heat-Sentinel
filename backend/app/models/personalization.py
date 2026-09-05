"""Schemas for the personalisation layer.

Three record types are kept deliberately separate, because they have
different lifetimes:

* ``UserProfile``      -- stable, rarely changes, editable
* ``HealthProfile``    -- long-term but *status-bearing* and editable
* ``DailyAssessment``  -- today only, never merged into the profile

Nothing here alters the thermal or risk models; the personalisation layer
consumes their output.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


# --- enumerations ----------------------------------------------------------
class UsualClimate(str, Enum):
    COLD = "cold"
    MILD = "mild"
    WARM = "warm"
    HOT_HUMID = "hot_humid"


class TimeInRegion(str, Enum):
    FIRST_3_DAYS = "first_3_days"
    DAYS_4_7 = "days_4_7"
    WEEKS_1_4 = "weeks_1_4"
    OVER_A_MONTH = "over_a_month"


class HeatComfort(str, Enum):
    VERY_COMFORTABLE = "very_comfortable"
    SOMEWHAT_COMFORTABLE = "somewhat_comfortable"
    UNCOMFORTABLE = "uncomfortable"
    EXTREMELY_UNCOMFORTABLE = "extremely_uncomfortable"


class OutdoorDuration(str, Enum):
    UNDER_30_MIN = "under_30_min"
    MIN_30_TO_2H = "min_30_to_2h"
    H2_TO_4 = "h2_to_4"
    OVER_4H = "over_4h"


class OutdoorWindow(str, Enum):
    MORNING = "morning"
    MIDDAY = "midday"          # 11:00-15:00, peak solar load
    AFTERNOON = "afternoon"    # 15:00-18:00
    EVENING_NIGHT = "evening_night"


class Activity(str, Enum):
    SIGHTSEEING = "sightseeing"
    SPORTS = "sports"
    WORK = "work"
    SHOPPING = "shopping"
    TRAVELLING = "travelling"
    MOSTLY_INDOORS = "mostly_indoors"


class FluidsToday(str, Enum):
    YES = "yes"
    NOT_SURE = "not_sure"
    NO = "no"


class Clothing(str, Enum):
    LIGHT_LOOSE = "light_loose"
    NORMAL = "normal"
    HEAVY_DARK = "heavy_dark"


class TriState(str, Enum):
    YES = "yes"
    NO = "no"
    PREFER_NOT_TO_SAY = "prefer_not_to_say"


class HealthStatus(str, Enum):
    ACTIVE = "active"
    RESOLVED = "resolved"
    UNKNOWN = "unknown"


# --- stable profile --------------------------------------------------------
class UserProfile(BaseModel):
    """Stable but editable. Age is stored as a group or a date of birth."""

    model_config = ConfigDict(json_schema_extra={"examples": [{
        "age_group": "26_40", "height_cm": 172.0, "weight_kg": 68.0,
        "usual_climate": "mild",
    }]})

    user_id: str = Field("demo_user_001", max_length=64)
    date_of_birth: date | None = None
    age_group: str | None = Field(
        None, description="One of under_18, 18_30, 31_50, 51_65, over_65."
    )
    height_cm: float | None = Field(None, gt=0, le=260, allow_inf_nan=False)
    weight_kg: float | None = Field(None, gt=0, le=400, allow_inf_nan=False)
    # Stored for context only. Nationality and country of residence are NEVER
    # inputs to the vulnerability score -- acclimatisation and usual climate
    # carry that signal, because exposure history is what the evidence
    # supports. A test asserts the score is invariant to this field.
    country_of_residence: str | None = Field(None, max_length=80)
    usual_climate: UsualClimate = UsualClimate.MILD
    time_in_region: TimeInRegion = TimeInRegion.OVER_A_MONTH
    experienced_over_40c: bool | None = None
    heat_comfort: HeatComfort = HeatComfort.SOMEWHAT_COMFORTABLE
    created_at: datetime | None = None
    updated_at: datetime | None = None


# --- long-term health ------------------------------------------------------
class HealthProfile(BaseModel):
    """Self-reported only.

    Nothing here is diagnosed by the system, and `status` exists so that a
    condition can be marked resolved rather than following a user forever.
    Pregnancy is a status, never a permanent boolean.
    """

    user_id: str = Field("demo_user_001", max_length=64)
    heat_sensitive: TriState = TriState.PREFER_NOT_TO_SAY
    conditions: list[str] = Field(default_factory=list, max_length=20)
    condition_note: str | None = Field(
        None, max_length=300,
        description="Free text, as typed by the user. Never parsed or diagnosed.",
    )
    status: HealthStatus = HealthStatus.UNKNOWN
    pregnancy_status: TriState = TriState.PREFER_NOT_TO_SAY
    start_date: date | None = None
    end_date: date | None = None
    updated_at: datetime | None = None


# --- today only ------------------------------------------------------------
class DailyAssessment(BaseModel):
    """Temporary. Keyed by date and never folded into the stable profile."""

    user_id: str = Field("demo_user_001", max_length=64)
    assessment_date: date | None = None
    outdoor_duration: OutdoorDuration = OutdoorDuration.MIN_30_TO_2H
    outdoor_window: OutdoorWindow = OutdoorWindow.MORNING
    activity: Activity = Activity.SIGHTSEEING
    daily_water_litres: float | None = Field(
        None, ge=0, le=20, allow_inf_nan=False
    )
    fluids_today: FluidsToday = FluidsToday.NOT_SURE
    alcohol_today: bool = False
    caffeine_today: bool = False
    clothing: Clothing = Clothing.NORMAL
    water_access: bool = True
    shade_access: bool = True
    hat_access: bool = False
    sunscreen_access: bool = False
    # Current symptoms are transient. They never enter the score; they are
    # matched against the red-flag list and can only raise a safety message.
    current_symptoms: list[str] = Field(default_factory=list, max_length=20)
    created_at: datetime | None = None


# --- request / response ----------------------------------------------------
class PersonalRiskRequest(BaseModel):
    """Location is used only to fetch existing environmental values."""

    user_id: str = Field("demo_user_001", max_length=64)
    latitude: float = Field(..., ge=-90, le=90, allow_inf_nan=False)
    longitude: float = Field(..., ge=-180, le=180, allow_inf_nan=False)


class VulnerabilityFactor(BaseModel):
    key: str
    label: str
    score: float = Field(..., ge=0.0, le=1.0)
    weight: float
    contribution: float
    detail: str


class SafetyNotice(BaseModel):
    """Raised by red-flag symptoms. Not a diagnosis and not a score input."""

    urgent: bool
    matched_symptoms: list[str]
    message: str


class PersonalRiskResponse(BaseModel):
    user_id: str
    generated_at: datetime

    environmental_risk_score: float
    environmental_risk_level: str
    personal_vulnerability_score: float
    personalised_risk_score: float
    risk_level: str

    thermal: dict[str, float | None]
    factors: list[VulnerabilityFactor]
    top_drivers: list[str]
    recommendations: list[str]
    safety_notice: SafetyNotice | None = None

    weights: dict[str, float]
    method: str
    assumptions: list[str]
    limitations: list[str]
    disclaimer: str
