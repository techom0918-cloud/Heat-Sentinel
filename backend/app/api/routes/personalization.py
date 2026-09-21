"""Personalised heat risk endpoints.

Thin by design: parse, validate, delegate, return. All scoring lives in
personalization_service.py.

This module adds a layer on top of the existing engines. It does not modify
weather ingestion, thermal calculations, vulnerability scoring or the risk
engine — it consumes their output.

Authentication is out of scope and is being built separately. Every endpoint
takes a ``user_id`` which defaults to ``demo_user_001``, so the feature works
standalone. Wiring real auth later means supplying the authenticated id
instead of the default; no other change is required.
"""

from datetime import date

from fastapi import APIRouter, Query

from app.core.config import settings
from app.core.exceptions import ExternalServiceError, HeatSentinalError
from app.models.common import ErrorResponse
from app.models.personalization import (
    DailyAssessment,
    HealthProfile,
    PersonalRiskRequest,
    PersonalRiskResponse,
    UserProfile,
)
from app.services import (
    personalization_service,
    risk_service,
    thermal_service,
    weather_service,
)

router = APIRouter(prefix="/personal", tags=["Personalisation"])

_DEMO_USER = "demo_user_001"

_RISK_DESCRIPTION = """
Combines the existing environmental risk score with a personal vulnerability
score built from the user's stored profile and today's assessment.

> **Not a medical diagnosis.** This estimates heat risk from conditions the
> user reported. It does not assess health and is not clinical advice.

**Method**

    personalised = 0.65 × environmental + 0.35 × personal

The environmental term is produced by the existing risk engine and is passed
through unchanged. The personal term is a weighted sum of seven factors —
acclimatisation, outdoor exposure, activity, hydration, protection, age and
usual climate — each a documented lookup table, plus small capped uplifts for
self-reported health context and body size.

Nationality is never an input. Acclimatisation and usual climate are used
instead, since exposure history is what the evidence supports.

Reported symptoms never change the score. Red-flag symptoms raise a separate
urgent safety notice.
"""


# --- stable profile --------------------------------------------------------
@router.put(
    "/profile",
    response_model=UserProfile,
    responses={422: {"model": ErrorResponse}},
    summary="Create or update the stable profile",
)
async def put_profile(payload: UserProfile) -> UserProfile:
    return personalization_service.save_profile(payload)


@router.get(
    "/profile",
    response_model=UserProfile,
    responses={404: {"model": ErrorResponse}},
    summary="Fetch the stable profile",
)
async def read_profile(user_id: str = Query(_DEMO_USER)) -> UserProfile:
    profile = personalization_service.get_profile(user_id)
    if profile is None:
        raise HeatSentinalError(
            "No stable profile stored for this user.",
            status_code=404,
            details={"user_id": user_id},
        )
    return profile


# --- long-term health ------------------------------------------------------
@router.put(
    "/health-profile",
    response_model=HealthProfile,
    responses={422: {"model": ErrorResponse}},
    summary="Create or update self-reported health context",
)
async def put_health(payload: HealthProfile) -> HealthProfile:
    return personalization_service.save_health(payload)


@router.get(
    "/health-profile",
    response_model=HealthProfile,
    responses={404: {"model": ErrorResponse}},
    summary="Fetch self-reported health context",
)
async def read_health(user_id: str = Query(_DEMO_USER)) -> HealthProfile:
    health = personalization_service.get_health(user_id)
    if health is None:
        raise HeatSentinalError(
            "No health context stored for this user.",
            status_code=404,
            details={"user_id": user_id},
        )
    return health


# --- today only ------------------------------------------------------------
@router.put(
    "/assessment",
    response_model=DailyAssessment,
    responses={422: {"model": ErrorResponse}},
    summary="Record today's exposure assessment",
)
async def put_assessment(payload: DailyAssessment) -> DailyAssessment:
    return personalization_service.save_assessment(payload)


@router.get(
    "/assessment",
    response_model=DailyAssessment,
    responses={404: {"model": ErrorResponse}},
    summary="Fetch an assessment for a given date",
)
async def read_assessment(
    user_id: str = Query(_DEMO_USER),
    on: date | None = Query(None, description="Defaults to today."),
) -> DailyAssessment:
    daily = personalization_service.get_assessment(user_id, on)
    if daily is None:
        raise HeatSentinalError(
            "No assessment stored for this user on that date.",
            status_code=404,
            details={"user_id": user_id, "date": str(on or date.today())},
        )
    return daily


# --- the combined score ----------------------------------------------------
@router.post(
    "/risk",
    response_model=PersonalRiskResponse,
    responses={
        404: {"model": ErrorResponse},
        422: {"model": ErrorResponse},
        502: {"model": ErrorResponse},
    },
    summary="Personalised heat risk for the stored profile",
    description=_RISK_DESCRIPTION,
)
async def personal_risk(payload: PersonalRiskRequest) -> PersonalRiskResponse:
    profile = personalization_service.get_profile(payload.user_id)
    if profile is None:
        raise HeatSentinalError(
            "Save a stable profile before requesting a personalised score.",
            status_code=404,
            details={"user_id": payload.user_id, "missing": "profile"},
        )
    daily = personalization_service.get_assessment(payload.user_id)
    if daily is None:
        raise HeatSentinalError(
            "Save today's assessment before requesting a personalised score.",
            status_code=404,
            details={"user_id": payload.user_id, "missing": "assessment"},
        )
    health = personalization_service.get_health(payload.user_id)

    # Existing pipeline, untouched: provider -> thermal engine -> risk engine.
    weather = await weather_service.get_current_weather(
        payload.latitude, payload.longitude
    )
    current = weather.current

    if current.relative_humidity is None:
        raise ExternalServiceError(
            "The weather provider supplied no relative humidity for this "
            "location, so a personalised score cannot be produced.",
            details={
                "provider": weather.provider,
                "latitude": payload.latitude,
                "longitude": payload.longitude,
            },
        )

    # Same call the thermal route makes. Formulas untouched.
    thermal = thermal_service.calculate_thermal_stress(
        temperature=current.temperature_c,
        relative_humidity=current.relative_humidity,
        wind_speed=current.wind_speed_ms or 0.0,
        solar_radiation=current.solar_radiation_wm2,
    )
    if thermal.heat_index is None or thermal.wbgt is None:
        raise ExternalServiceError(
            "The thermal engine could not produce the indices this score needs.",
            status_code=502,
            details={"heat_index": thermal.heat_index, "wbgt": thermal.wbgt},
        )

    # A neutral population vulnerability is passed in, because the personal
    # layer supplies the person-specific half. Using a zone score here would
    # double-count vulnerability.
    environmental = risk_service.predict_risk(
        temperature_c=thermal.temperature,
        relative_humidity=thermal.relative_humidity,
        heat_index=thermal.heat_index,
        wbgt=thermal.wbgt,
        utci=thermal.utci,
        wind_speed=thermal.wind_speed,
        solar_radiation=thermal.solar_radiation,
        vulnerability_score=settings.PERSONAL_NEUTRAL_VULNERABILITY,
    )

    return personalization_service.personalised_risk(
        profile=profile,
        daily=daily,
        health=health,
        thermal={
            "temperature": thermal.temperature,
            "relative_humidity": thermal.relative_humidity,
            "wind_speed": thermal.wind_speed,
            "solar_radiation": thermal.solar_radiation,
            "heat_index": thermal.heat_index,
            "wbgt": thermal.wbgt,
            "utci": thermal.utci,
            "wet_bulb": thermal.wet_bulb_temperature,
        },
        environmental_score=environmental.risk_score,
        environmental_level=environmental.risk_level,
    )
