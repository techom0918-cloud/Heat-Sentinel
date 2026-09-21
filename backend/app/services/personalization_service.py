"""Personalised heat risk: storage plus a transparent vulnerability score.

Design rules this file follows:

* The environmental half comes from ``risk_service.predict_risk`` unchanged.
  No thermal formula is reimplemented or adjusted here.
* Every factor is a lookup table, not a fitted coefficient. The score is
  fully deterministic and reproducible from the tables below.
* Nationality is never an input. Acclimatisation and usual climate are used
  instead, because exposure history is what the physiology literature
  actually supports.
* Self-reported health is a small capped uplift, so it cannot dominate.
* Red-flag symptoms never change the number. They raise a safety notice.

Framework-free by project convention, so the ML pipeline and tests can call
it directly.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone
from pathlib import Path

from app.core.config import settings
from app.core.exceptions import HeatSentinalError
from app.models.personalization import (
    Activity,
    Clothing,
    DailyAssessment,
    FluidsToday,
    HealthProfile,
    HealthStatus,
    HeatComfort,
    OutdoorDuration,
    OutdoorWindow,
    PersonalRiskResponse,
    SafetyNotice,
    TimeInRegion,
    TriState,
    UserProfile,
    UsualClimate,
    VulnerabilityFactor,
)
from app.services import risk_service

DISCLAIMER = (
    "This is a heat-risk estimate built from conditions you reported. It is "
    "not a medical diagnosis, not a clinical assessment, and not a substitute "
    "for advice from a health professional. Weights are prototype values."
)


# ---------------------------------------------------------------------------
# Scoring tables. Each maps an answer to a 0-1 vulnerability contribution.
# ---------------------------------------------------------------------------

_ACCLIM_TIME = {
    TimeInRegion.FIRST_3_DAYS: 1.00,   # acclimatisation takes ~7-14 days
    TimeInRegion.DAYS_4_7: 0.70,
    TimeInRegion.WEEKS_1_4: 0.35,
    TimeInRegion.OVER_A_MONTH: 0.10,
}

_COMFORT = {
    HeatComfort.VERY_COMFORTABLE: 0.00,
    HeatComfort.SOMEWHAT_COMFORTABLE: 0.30,
    HeatComfort.UNCOMFORTABLE: 0.70,
    HeatComfort.EXTREMELY_UNCOMFORTABLE: 1.00,
}

_CLIMATE = {
    UsualClimate.COLD: 1.00,
    UsualClimate.MILD: 0.65,
    UsualClimate.WARM: 0.30,
    UsualClimate.HOT_HUMID: 0.05,
}

_DURATION = {
    OutdoorDuration.UNDER_30_MIN: 0.10,
    OutdoorDuration.MIN_30_TO_2H: 0.40,
    OutdoorDuration.H2_TO_4: 0.75,
    OutdoorDuration.OVER_4H: 1.00,
}

_WINDOW = {
    OutdoorWindow.MORNING: 0.25,
    OutdoorWindow.MIDDAY: 1.00,        # peak solar and peak air temperature
    OutdoorWindow.AFTERNOON: 0.70,
    OutdoorWindow.EVENING_NIGHT: 0.10,
}

_ACTIVITY = {
    Activity.MOSTLY_INDOORS: 0.05,
    Activity.SHOPPING: 0.30,
    Activity.TRAVELLING: 0.40,
    Activity.SIGHTSEEING: 0.55,
    Activity.WORK: 0.80,
    Activity.SPORTS: 1.00,             # highest metabolic heat production
}

_FLUIDS = {
    FluidsToday.YES: 0.10,
    FluidsToday.NOT_SURE: 0.55,
    FluidsToday.NO: 1.00,
}

_CLOTHING = {
    Clothing.LIGHT_LOOSE: 0.10,
    Clothing.NORMAL: 0.45,
    Clothing.HEAVY_DARK: 1.00,
}

# Age: the very young and the old are less able to thermoregulate.
_AGE_GROUP = {
    "under_18": 0.65,
    "18_30": 0.15,
    "31_50": 0.25,
    "51_65": 0.55,
    "over_65": 0.95,
}


def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))


def _age_score(profile: UserProfile) -> tuple[float, str]:
    if profile.date_of_birth:
        years = (date.today() - profile.date_of_birth).days / 365.25
        if years < 18:
            return 0.65, f"about {years:.0f} years old"
        if years < 31:
            return 0.15, f"about {years:.0f} years old"
        if years < 51:
            return 0.25, f"about {years:.0f} years old"
        if years < 66:
            return 0.55, f"about {years:.0f} years old"
        return 0.95, f"about {years:.0f} years old"
    if profile.age_group and profile.age_group in _AGE_GROUP:
        return _AGE_GROUP[profile.age_group], profile.age_group.replace("_", "-")
    return 0.30, "age not provided, mid-range assumed"


def _acclimatisation(profile: UserProfile) -> tuple[float, str]:
    """Time in region dominates; prior >40 C exposure and comfort adjust it."""
    base = _ACCLIM_TIME[profile.time_in_region]
    comfort = _COMFORT[profile.heat_comfort]
    score = 0.6 * base + 0.4 * comfort
    if profile.experienced_over_40c is True:
        score *= 0.85
    elif profile.experienced_over_40c is False:
        score = min(1.0, score * 1.10)
    bits = [profile.time_in_region.value.replace("_", " ")]
    if profile.experienced_over_40c is not None:
        bits.append(
            "has experienced above 40 C" if profile.experienced_over_40c
            else "no experience above 40 C"
        )
    return _clamp(score), ", ".join(bits)


def _exposure(daily: DailyAssessment) -> tuple[float, str]:
    """Duration and time of day compound rather than average.

    Four hours at midday is materially worse than four hours at dawn, so the
    two are multiplied and then softened, not averaged.
    """
    d = _DURATION[daily.outdoor_duration]
    w = _WINDOW[daily.outdoor_window]
    score = (d * w) ** 0.5 if d and w else max(d, w) * 0.5
    return _clamp(score), (
        f"{daily.outdoor_duration.value.replace('_', ' ')} during "
        f"{daily.outdoor_window.value.replace('_', ' ')}"
    )


def _hydration(daily: DailyAssessment) -> tuple[float, str]:
    score = _FLUIDS[daily.fluids_today]
    notes = [f"fluids today: {daily.fluids_today.value.replace('_', ' ')}"]
    if daily.daily_water_litres is not None:
        if daily.daily_water_litres < 1.5:
            score = min(1.0, score + 0.25)
            notes.append("low usual intake")
        elif daily.daily_water_litres >= 3.0:
            score = max(0.0, score - 0.15)
            notes.append("good usual intake")
    if daily.alcohol_today:
        score = min(1.0, score + 0.20)
        notes.append("alcohol today")
    if daily.caffeine_today:
        score = min(1.0, score + 0.05)
        notes.append("high caffeine today")
    return _clamp(score), ", ".join(notes)


def _protection(daily: DailyAssessment) -> tuple[float, str]:
    score = _CLOTHING[daily.clothing]
    missing: list[str] = []
    if not daily.shade_access:
        score += 0.30
        missing.append("no shade or AC")
    if not daily.water_access:
        score += 0.30
        missing.append("no drinking water")
    if not daily.hat_access:
        score += 0.08
        missing.append("no hat or umbrella")
    if not daily.sunscreen_access:
        score += 0.05
        missing.append("no sunscreen")
    detail = daily.clothing.value.replace("_", " ") + " clothing"
    if missing:
        detail += "; " + ", ".join(missing)
    return _clamp(score), detail


def _health_uplift(health: HealthProfile | None) -> tuple[float, str]:
    """Small, capped, and only for what the user chose to disclose."""
    if health is None or health.heat_sensitive != TriState.YES:
        return 0.0, ""
    if health.status == HealthStatus.RESOLVED:
        return 0.0, "reported condition marked resolved"
    cap = settings.PERSONAL_HEALTH_UPLIFT_MAX
    uplift = cap * 0.6
    detail = "self-reported heat-sensitive condition or medication"
    if health.pregnancy_status == TriState.YES:
        uplift = cap
        detail += "; pregnancy reported"
    return uplift, detail


def _bmi_uplift(profile: UserProfile) -> tuple[float, str]:
    """Deliberately minor. Body size is a weak predictor next to exposure."""
    if not profile.height_cm or not profile.weight_kg:
        return 0.0, ""
    bmi = profile.weight_kg / ((profile.height_cm / 100.0) ** 2)
    cap = settings.PERSONAL_BMI_UPLIFT_MAX
    if bmi >= 30 or bmi < 16:
        return cap, f"BMI {bmi:.1f}"
    if bmi >= 27:
        return cap * 0.5, f"BMI {bmi:.1f}"
    return 0.0, f"BMI {bmi:.1f}"


def _validate_weights() -> dict[str, float]:
    w = settings.personal_vulnerability_weights
    total = sum(w.values())
    if abs(total - 1.0) > 1e-6:
        raise HeatSentinalError(
            "Personal vulnerability weights must sum to 1.0.",
            status_code=500,
            details={"weights": w, "total": round(total, 6)},
        )
    blend = (
        settings.PERSONAL_ENVIRONMENT_WEIGHT
        + settings.PERSONAL_VULNERABILITY_WEIGHT
    )
    if abs(blend - 1.0) > 1e-6:
        raise HeatSentinalError(
            "Environmental and personal weights must sum to 1.0.",
            status_code=500,
            details={"blend_total": round(blend, 6)},
        )
    return w


# ---------------------------------------------------------------------------
# Public: vulnerability
# ---------------------------------------------------------------------------
def personal_vulnerability(
    profile: UserProfile,
    daily: DailyAssessment,
    health: HealthProfile | None = None,
) -> tuple[float, list[VulnerabilityFactor]]:
    """Weighted sum of seven factors plus two small capped uplifts."""
    weights = _validate_weights()

    acclim, acclim_note = _acclimatisation(profile)
    expo, expo_note = _exposure(daily)
    act = _ACTIVITY[daily.activity]
    hydr, hydr_note = _hydration(daily)
    prot, prot_note = _protection(daily)
    age, age_note = _age_score(profile)
    clim = _CLIMATE[profile.usual_climate]

    raw = {
        "acclimatisation": (acclim, "Heat acclimatisation", acclim_note),
        "exposure": (expo, "Outdoor exposure today", expo_note),
        "activity": (act, "Physical activity", daily.activity.value.replace("_", " ")),
        "hydration": (hydr, "Hydration", hydr_note),
        "protection": (prot, "Clothing and protection", prot_note),
        "age": (age, "Age", age_note),
        "usual_climate": (clim, "Usual climate", profile.usual_climate.value.replace("_", " ")),
    }

    factors: list[VulnerabilityFactor] = []
    score = 0.0
    for key, (value, label, detail) in raw.items():
        weight = weights[key]
        contribution = value * weight
        score += contribution
        factors.append(VulnerabilityFactor(
            key=key, label=label, score=round(value, 4),
            weight=round(weight, 4), contribution=round(contribution, 4),
            detail=detail,
        ))

    health_up, health_note = _health_uplift(health)
    if health_up:
        score += health_up
        factors.append(VulnerabilityFactor(
            key="health_context", label="Self-reported health context",
            score=1.0, weight=round(health_up, 4),
            contribution=round(health_up, 4), detail=health_note,
        ))

    bmi_up, bmi_note = _bmi_uplift(profile)
    if bmi_up:
        score += bmi_up
        factors.append(VulnerabilityFactor(
            key="body_size", label="Body size (minor factor)",
            score=1.0, weight=round(bmi_up, 4),
            contribution=round(bmi_up, 4), detail=bmi_note,
        ))

    return _clamp(score), factors


def check_red_flags(daily: DailyAssessment) -> SafetyNotice | None:
    """Symptoms never change the score. They raise a message instead.

    Two tiers. Red flags point at possible heat stroke and get an emergency
    message. Early-warning signs point at heat exhaustion, which is the stage
    where acting early actually prevents the emergency, so they get a firm
    advisory rather than nothing.
    """
    reported = {
        s.strip().lower().replace(" ", "_").replace("/", "_")
        for s in daily.current_symptoms
    }
    flags = set(settings.personal_red_flag_list)
    early = set(settings.personal_early_warning_list)

    matched = sorted(reported & flags)
    if not matched:
        warned = sorted(reported & early)
        if not warned:
            return None
        return SafetyNotice(
            urgent=False,
            matched_symptoms=warned,
            message=(
                "The symptoms you reported can be early signs of heat "
                "exhaustion. Stop what you are doing, get into shade or air "
                "conditioning, sip water, and loosen tight clothing. If they "
                "do not ease within about 30 minutes, or if you start feeling "
                "confused, faint or stop sweating, treat it as an emergency "
                "and get medical help. This tool cannot assess you."
            ),
        )
    return SafetyNotice(
        urgent=True,
        matched_symptoms=matched,
        message=(
            "The symptoms you reported can be signs of heat stroke, which is a "
            "medical emergency. Please stop what you are doing, move somewhere "
            "cool, and seek medical help now — call 108 for an ambulance in "
            "India, or your local emergency number. Do not wait to see if it "
            "passes. This tool cannot assess you and this is not a diagnosis."
        ),
    )


# ---------------------------------------------------------------------------
# Storage
#
# The project has no database (DATABASE_URL is empty and there is no ORM), so
# the three record types are kept as separate JSON documents under a single
# store root. The separation from the spec is preserved: stable profile,
# health profile and daily assessments never share a file, and daily records
# are keyed by date so they cannot silently become permanent.
# ---------------------------------------------------------------------------
def _store_root() -> Path:
    configured = Path(settings.PERSONALISATION_STORE_PATH)
    root = (
        configured if configured.is_absolute()
        else Path(__file__).resolve().parents[2] / configured
    )
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_user(user_id: str) -> str:
    """Filenames come from user ids, so keep them to a known-safe alphabet."""
    cleaned = "".join(c for c in user_id if c.isalnum() or c in "-_")[:64]
    if not cleaned:
        raise HeatSentinalError(
            "user_id must contain at least one alphanumeric character.",
            status_code=422,
            details={"user_id": user_id},
        )
    return cleaned


def _path(user_id: str, kind: str) -> Path:
    folder = _store_root() / _safe_user(user_id)
    folder.mkdir(parents=True, exist_ok=True)
    return folder / f"{kind}.json"


def _write(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")


def _read(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise HeatSentinalError(
            "Stored personalisation record is not valid JSON.",
            status_code=500,
            details={"path": path.name, "error": str(exc)},
        ) from exc


def save_profile(profile: UserProfile) -> UserProfile:
    now = datetime.now(timezone.utc)
    existing = _read(_path(profile.user_id, "profile"))
    profile.created_at = (
        datetime.fromisoformat(existing["created_at"])
        if existing and existing.get("created_at") else now
    )
    profile.updated_at = now
    _write(_path(profile.user_id, "profile"), profile.model_dump(mode="json"))
    return profile


def get_profile(user_id: str) -> UserProfile | None:
    data = _read(_path(user_id, "profile"))
    return UserProfile(**data) if data else None


def save_health(health: HealthProfile) -> HealthProfile:
    health.updated_at = datetime.now(timezone.utc)
    _write(_path(health.user_id, "health"), health.model_dump(mode="json"))
    return health


def get_health(user_id: str) -> HealthProfile | None:
    data = _read(_path(user_id, "health"))
    return HealthProfile(**data) if data else None


def save_assessment(daily: DailyAssessment) -> DailyAssessment:
    daily.assessment_date = daily.assessment_date or date.today()
    daily.created_at = datetime.now(timezone.utc)
    # Keyed by date: today's answers never overwrite the stable profile, and
    # yesterday's answers never leak into today's score.
    store = _read(_path(daily.user_id, "daily")) or {}
    store[str(daily.assessment_date)] = daily.model_dump(mode="json")
    _write(_path(daily.user_id, "daily"), store)
    return daily


def get_assessment(user_id: str, on: date | None = None) -> DailyAssessment | None:
    store = _read(_path(user_id, "daily"))
    if not store:
        return None
    key = str(on or date.today())
    data = store.get(key)
    return DailyAssessment(**data) if data else None


# ---------------------------------------------------------------------------
# Recommendations -- derived from the same answers that drove the score, so
# advice and explanation can never disagree.
# ---------------------------------------------------------------------------
def build_recommendations(
    profile: UserProfile, daily: DailyAssessment, level: str
) -> list[str]:
    out: list[str] = []

    if daily.outdoor_window == OutdoorWindow.MIDDAY:
        out.append(
            "Shift outdoor plans before 11am or after 4pm if you can — the "
            "11am-3pm window carries the highest solar and air-temperature load."
        )
    if daily.outdoor_duration in (OutdoorDuration.H2_TO_4, OutdoorDuration.OVER_4H):
        out.append(
            "Break long stretches outdoors into shorter blocks with time in "
            "shade or air conditioning between them."
        )
    if daily.activity == Activity.SPORTS:
        out.append(
            "Hard exercise generates a lot of internal heat. Reduce intensity, "
            "or move the session to early morning or evening."
        )
    elif daily.activity == Activity.WORK:
        out.append(
            "For outdoor work, plan regular rest breaks in shade and share "
            "water between the group rather than relying on individual bottles."
        )
    if daily.fluids_today in (FluidsToday.NO, FluidsToday.NOT_SURE):
        out.append(
            "Start drinking water now rather than waiting until you feel "
            "thirsty — thirst lags behind actual fluid loss."
        )
    if daily.alcohol_today:
        out.append("Alcohol increases fluid loss. Match each drink with water.")
    if not daily.water_access:
        out.append("Carry water with you; you reported no reliable access today.")
    if not daily.shade_access:
        out.append(
            "Identify somewhere cool you can reach quickly — a mall, metro "
            "station, library or clinic all work as cooling points."
        )
    if daily.clothing == Clothing.HEAVY_DARK:
        out.append(
            "Switch to light-coloured, loose, breathable clothing if you can."
        )
    if not daily.hat_access:
        out.append("A hat or umbrella cuts direct solar load on your head and neck.")
    if profile.time_in_region in (TimeInRegion.FIRST_3_DAYS, TimeInRegion.DAYS_4_7):
        out.append(
            "You are still adjusting to this climate. Acclimatisation takes "
            "roughly one to two weeks, so treat your usual limits as lower for now."
        )
    if profile.usual_climate == UsualClimate.COLD:
        out.append(
            "Coming from a cooler climate, plan for shorter exposure than "
            "locals doing the same activity."
        )

    out.append(
        "Know the warning signs: dizziness, nausea, headache, a fast pulse, or "
        "stopping sweating in the heat. If they appear, get somewhere cool and "
        "seek help."
    )
    if level in ("HIGH", "VERY_HIGH", "EXTREME"):
        out.insert(0, (
            "Your combined risk is elevated today. Consider postponing "
            "non-essential outdoor plans."
        ))
    return out


# ---------------------------------------------------------------------------
# Public: combine environmental and personal
# ---------------------------------------------------------------------------
def personalised_risk(
    *,
    profile: UserProfile,
    daily: DailyAssessment,
    health: HealthProfile | None,
    thermal: dict[str, float | None],
    environmental_score: float,
    environmental_level: str,
) -> PersonalRiskResponse:
    """Blend the existing environmental score with personal vulnerability.

    ``environmental_score`` must come from ``risk_service.predict_risk``. This
    function never recomputes Heat Index, WBGT, UTCI or wet bulb.
    """
    _validate_weights()
    vulnerability, factors = personal_vulnerability(profile, daily, health)

    env_w = settings.PERSONAL_ENVIRONMENT_WEIGHT
    per_w = settings.PERSONAL_VULNERABILITY_WEIGHT
    combined = _clamp(env_w * environmental_score + per_w * vulnerability)
    level = risk_service.risk_level(combined)

    ranked = sorted(factors, key=lambda f: f.contribution, reverse=True)
    drivers = [f"{f.label}: {f.detail}" for f in ranked[:5] if f.contribution > 0.02]

    return PersonalRiskResponse(
        user_id=profile.user_id,
        generated_at=datetime.now(timezone.utc),
        environmental_risk_score=round(environmental_score, 4),
        environmental_risk_level=environmental_level,
        personal_vulnerability_score=round(vulnerability, 4),
        personalised_risk_score=round(combined, 4),
        risk_level=level,
        thermal=thermal,
        factors=ranked,
        top_drivers=drivers,
        recommendations=build_recommendations(profile, daily, level),
        safety_notice=check_red_flags(daily),
        weights={
            "environmental": env_w,
            "personal_vulnerability": per_w,
            **settings.personal_vulnerability_weights,
        },
        method=(
            f"personalised = {env_w:g} x environmental + {per_w:g} x personal. "
            "The environmental term is the existing risk engine output, "
            "unmodified. The personal term is a weighted sum of seven "
            "lookup-table factors plus capped uplifts for self-reported health "
            "context and body size. Fully deterministic."
        ),
        assumptions=[
            "Factor weights are prototype values, not fitted to outcome data.",
            "Acclimatisation is modelled from time in region, prior exposure "
            "above 40 C and self-reported comfort. Nationality is never used.",
            "Body size is deliberately a minor term, capped at "
            f"{settings.PERSONAL_BMI_UPLIFT_MAX:g}, because it is a weak "
            "predictor next to exposure and acclimatisation.",
            "Self-reported health context is capped at "
            f"{settings.PERSONAL_HEALTH_UPLIFT_MAX:g} so it cannot dominate.",
            "Today's answers apply to today only and are stored separately "
            "from the stable profile.",
        ],
        limitations=[
            "No clinical validation. Weights are not derived from health outcomes.",
            "Self-reported inputs are taken at face value and are not verified.",
            "The environmental half inherits the limits of the underlying "
            "engine, including city-scale hazard resolution.",
            "Symptoms are not scored and cannot be assessed by this system.",
        ],
        disclaimer=DISCLAIMER,
    )
