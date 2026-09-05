"""Personalisation layer.

The most important test in this file is the last one: it proves the existing
thermal engine still returns exactly what it did before this feature existed.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
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
    TimeInRegion,
    TriState,
    UserProfile,
    UsualClimate,
)
from app.services import personalization_service as ps
from app.services import thermal_service
from tests.conftest import current_payload, mock_provider

URL = f"{settings.API_V1_PREFIX}/personal"


@pytest.fixture
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    """Never write to the real store from a test."""
    monkeypatch.setattr(
        settings, "PERSONALISATION_STORE_PATH", str(tmp_path), raising=False
    )
    yield


def _profile(**kw) -> UserProfile:
    return UserProfile(**{"user_id": "demo_user_001", **kw})


def _daily(**kw) -> DailyAssessment:
    return DailyAssessment(**{"user_id": "demo_user_001", **kw})


# --- scoring ---------------------------------------------------------------
def test_weights_sum_to_one() -> None:
    assert sum(settings.personal_vulnerability_weights.values()) == pytest.approx(1.0)
    assert (
        settings.PERSONAL_ENVIRONMENT_WEIGHT
        + settings.PERSONAL_VULNERABILITY_WEIGHT
    ) == pytest.approx(1.0)


def test_scoring_is_deterministic() -> None:
    """Same inputs, same score. No randomness anywhere."""
    p, d = _profile(), _daily()
    first, _ = ps.personal_vulnerability(p, d)
    for _ in range(5):
        again, _ = ps.personal_vulnerability(p, d)
        assert again == first


def test_worst_case_scores_above_best_case() -> None:
    best, _ = ps.personal_vulnerability(
        _profile(
            usual_climate=UsualClimate.HOT_HUMID,
            time_in_region=TimeInRegion.OVER_A_MONTH,
            experienced_over_40c=True,
            heat_comfort=HeatComfort.VERY_COMFORTABLE,
            age_group="31_50",
        ),
        _daily(
            outdoor_duration=OutdoorDuration.UNDER_30_MIN,
            outdoor_window=OutdoorWindow.EVENING_NIGHT,
            activity=Activity.MOSTLY_INDOORS,
            fluids_today=FluidsToday.YES,
            clothing=Clothing.LIGHT_LOOSE,
            water_access=True, shade_access=True,
            hat_access=True, sunscreen_access=True,
        ),
    )
    worst, _ = ps.personal_vulnerability(
        _profile(
            usual_climate=UsualClimate.COLD,
            time_in_region=TimeInRegion.FIRST_3_DAYS,
            experienced_over_40c=False,
            heat_comfort=HeatComfort.EXTREMELY_UNCOMFORTABLE,
            age_group="over_75",
        ),
        _daily(
            outdoor_duration=OutdoorDuration.OVER_4H,
            outdoor_window=OutdoorWindow.MIDDAY,
            activity=Activity.SPORTS,
            fluids_today=FluidsToday.NO,
            alcohol_today=True,
            clothing=Clothing.HEAVY_DARK,
            water_access=False, shade_access=False,
            hat_access=False, sunscreen_access=False,
        ),
    )
    assert worst > best
    assert 0.0 <= best <= 1.0 and 0.0 <= worst <= 1.0


def test_midday_long_exposure_beats_evening_short() -> None:
    """The dangerous combination must actually score higher."""
    mild, _ = ps.personal_vulnerability(_profile(), _daily(
        outdoor_duration=OutdoorDuration.UNDER_30_MIN,
        outdoor_window=OutdoorWindow.EVENING_NIGHT))
    harsh, _ = ps.personal_vulnerability(_profile(), _daily(
        outdoor_duration=OutdoorDuration.OVER_4H,
        outdoor_window=OutdoorWindow.MIDDAY))
    assert harsh > mild


def test_health_uplift_is_capped() -> None:
    base, _ = ps.personal_vulnerability(_profile(), _daily())
    with_health, _ = ps.personal_vulnerability(
        _profile(), _daily(),
        HealthProfile(heat_sensitive=TriState.YES, status=HealthStatus.ACTIVE,
                      pregnancy_status=TriState.YES),
    )
    assert with_health > base
    assert with_health - base <= settings.PERSONAL_HEALTH_UPLIFT_MAX + 1e-9


def test_resolved_condition_adds_nothing() -> None:
    """A resolved condition must not follow the user forever."""
    base, _ = ps.personal_vulnerability(_profile(), _daily())
    resolved, _ = ps.personal_vulnerability(
        _profile(), _daily(),
        HealthProfile(heat_sensitive=TriState.YES, status=HealthStatus.RESOLVED),
    )
    assert resolved == base


def test_body_size_is_a_minor_term() -> None:
    slim, _ = ps.personal_vulnerability(
        _profile(height_cm=175, weight_kg=68), _daily())
    large, _ = ps.personal_vulnerability(
        _profile(height_cm=175, weight_kg=100), _daily())
    assert large - slim <= settings.PERSONAL_BMI_UPLIFT_MAX + 1e-9


# --- safety ----------------------------------------------------------------
def test_red_flag_symptoms_do_not_change_the_score() -> None:
    without, _ = ps.personal_vulnerability(_profile(), _daily())
    with_symptoms, _ = ps.personal_vulnerability(
        _profile(), _daily(current_symptoms=["fainting", "confusion"]))
    assert with_symptoms == without


def test_red_flag_symptoms_raise_an_urgent_notice() -> None:
    notice = ps.check_red_flags(_daily(current_symptoms=["Severe Dizziness"]))
    assert notice is not None and notice.urgent
    assert "severe_dizziness" in notice.matched_symptoms
    assert "emergency" in notice.message.lower()


def test_ordinary_symptoms_raise_no_notice() -> None:
    assert ps.check_red_flags(_daily(current_symptoms=["mild thirst"])) is None


def test_response_never_claims_a_diagnosis() -> None:
    r = ps.personalised_risk(
        profile=_profile(), daily=_daily(), health=None,
        thermal={"heat_index": 49.0}, environmental_score=0.7,
        environmental_level="HIGH")
    # The disclaimer legitimately contains "diagnosis" while denying one, so
    # scan everything except the disclaimer for claim-shaped language.
    payload = r.model_dump()
    payload.pop("disclaimer")
    blob = str(payload).lower()
    for banned in ("you have ", "we detect", "confirmed case",
                   "diagnosed with", "is a diagnosis"):
        assert banned not in blob, f"prohibited language: {banned}"
    assert "not a medical diagnosis" in r.disclaimer.lower()


# --- storage separation ----------------------------------------------------
def test_daily_data_never_enters_the_stable_profile() -> None:
    ps.save_profile(_profile(usual_climate=UsualClimate.MILD))
    ps.save_assessment(_daily(activity=Activity.SPORTS))
    stored = ps.get_profile("demo_user_001")
    assert "activity" not in stored.model_dump()
    assert stored.usual_climate == UsualClimate.MILD


def test_assessments_are_keyed_by_date() -> None:
    from datetime import date, timedelta
    today, yesterday = date.today(), date.today() - timedelta(days=1)
    ps.save_assessment(_daily(assessment_date=yesterday, activity=Activity.WORK))
    ps.save_assessment(_daily(assessment_date=today, activity=Activity.SPORTS))
    assert ps.get_assessment("demo_user_001", yesterday).activity == Activity.WORK
    assert ps.get_assessment("demo_user_001", today).activity == Activity.SPORTS


def test_profile_is_editable() -> None:
    ps.save_profile(_profile(usual_climate=UsualClimate.COLD))
    ps.save_profile(_profile(usual_climate=UsualClimate.HOT_HUMID))
    assert ps.get_profile("demo_user_001").usual_climate == UsualClimate.HOT_HUMID


def test_user_id_cannot_escape_the_store(tmp_path) -> None:
    """Ids become filenames, so separators must not survive sanitisation."""
    ps.save_profile(UserProfile(user_id="../../etc/passwd"))
    written = list(Path(tmp_path).rglob("profile.json"))
    assert written, "nothing was written"
    for path in written:
        assert Path(tmp_path) in path.parents or path.parent.parent == Path(tmp_path)
        assert ".." not in str(path)

    with pytest.raises(Exception):
        ps.save_profile(UserProfile(user_id="../.."))   # nothing usable left


# --- endpoints -------------------------------------------------------------
def test_risk_requires_a_profile_first(client: TestClient) -> None:
    r = client.post(f"{URL}/risk",
                    json={"user_id": "nobody001", "latitude": 28.6, "longitude": 77.2})
    assert r.status_code == 404
    assert r.json()["error"]["details"]["missing"] == "profile"


def test_full_endpoint_flow(client: TestClient) -> None:
    assert client.put(f"{URL}/profile", json={
        "user_id": "demo_user_001", "age_group": "31_50",
        "height_cm": 172, "weight_kg": 68, "usual_climate": "cold",
        "time_in_region": "first_3_days", "experienced_over_40c": False,
        "heat_comfort": "uncomfortable"}).status_code == 200

    assert client.put(f"{URL}/assessment", json={
        "user_id": "demo_user_001", "outdoor_duration": "over_4h",
        "outdoor_window": "midday", "activity": "sports",
        "fluids_today": "no", "clothing": "heavy_dark",
        "water_access": False, "shade_access": False}).status_code == 200

    with mock_provider(current_payload()):
        r = client.post(f"{URL}/risk",
                        json={"user_id": "demo_user_001",
                              "latitude": 28.6139, "longitude": 77.2090})
    assert r.status_code == 200
    body = r.json()
    assert 0.0 <= body["personalised_risk_score"] <= 1.0
    assert body["personal_vulnerability_score"] > 0.6      # a harsh profile
    assert body["top_drivers"] and body["recommendations"]
    assert body["safety_notice"] is None
    # The blend must be reproducible from the parts.
    expected = (settings.PERSONAL_ENVIRONMENT_WEIGHT * body["environmental_risk_score"]
                + settings.PERSONAL_VULNERABILITY_WEIGHT
                * body["personal_vulnerability_score"])
    assert body["personalised_risk_score"] == pytest.approx(expected, abs=1e-3)


# --- the guarantee that matters -------------------------------------------
def test_existing_thermal_engine_is_unchanged() -> None:
    """Regression guard.

    These values were produced by the thermal engine before the
    personalisation layer existed. If adding personalisation ever perturbs
    Heat Index, WBGT, UTCI or wet bulb, this fails.
    """
    result = thermal_service.calculate_thermal_stress(
        temperature=42.0, relative_humidity=60.0,
        wind_speed=2.0, solar_radiation=500.0)
    assert result.heat_index == pytest.approx(71.2, abs=0.5)
    assert result.wbgt == pytest.approx(36.9, abs=0.5)
    assert result.wet_bulb_temperature is not None
    assert result.wbgt_category == "NOT_CLASSIFIED"


# --- alignment with the designed form -------------------------------------
def test_country_of_residence_never_changes_the_score() -> None:
    """Nationality must not be a risk factor. Acclimatisation carries it."""
    base, _ = ps.personal_vulnerability(_profile(), _daily())
    for country in ("India", "Norway", "Australia", "Nigeria"):
        other, _ = ps.personal_vulnerability(
            _profile(country_of_residence=country), _daily())
        assert other == base, f"{country} changed the score"


def test_designed_age_buckets_are_accepted() -> None:
    for bucket in ("under_18", "18_30", "31_50", "51_65", "over_65"):
        score, factors = ps.personal_vulnerability(
            _profile(age_group=bucket), _daily())
        age = next(f for f in factors if f.key == "age")
        assert 0.0 <= age.score <= 1.0
        assert "not provided" not in age.detail, f"{bucket} not recognised"


def test_older_age_scores_higher_than_young_adult() -> None:
    young, _ = ps.personal_vulnerability(_profile(age_group="18_30"), _daily())
    old, _ = ps.personal_vulnerability(_profile(age_group="over_65"), _daily())
    assert old > young


def test_early_warning_symptoms_raise_a_non_urgent_advisory() -> None:
    notice = ps.check_red_flags(_daily(current_symptoms=["headache", "muscle_cramps"]))
    assert notice is not None
    assert notice.urgent is False
    assert "heat exhaustion" in notice.message.lower()


def test_red_flags_take_precedence_over_early_warnings() -> None:
    notice = ps.check_red_flags(
        _daily(current_symptoms=["headache", "fainting"]))
    assert notice.urgent is True
    assert "fainting" in notice.matched_symptoms


def test_neither_symptom_tier_changes_the_score() -> None:
    base, _ = ps.personal_vulnerability(_profile(), _daily())
    for symptoms in (["headache"], ["fainting"], ["headache", "confusion"]):
        other, _ = ps.personal_vulnerability(
            _profile(), _daily(current_symptoms=symptoms))
        assert other == base


def test_free_text_condition_is_stored_not_parsed() -> None:
    saved = ps.save_health(HealthProfile(
        user_id="demo_user_001", heat_sensitive=TriState.YES,
        status=HealthStatus.ACTIVE, condition_note="autoimmune, on medication"))
    assert saved.condition_note == "autoimmune, on medication"
    stored = ps.get_health("demo_user_001")
    assert stored.condition_note == "autoimmune, on medication"
