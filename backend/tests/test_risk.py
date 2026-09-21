"""Phase 5 tests: prototype health risk engine.

Pure computation -- no mocking, no network.
"""

import json

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import HeatSentinalError, ValidationError
from app.main import app
from app.services.risk_service import (
    normalise_index,
    predict_risk,
    risk_level,
    validate_weights,
)

URL = f"{settings.API_V1_PREFIX}/risk/predict"

BASELINE = {
    "temperature_c": 42.0,
    "relative_humidity": 65.0,
    "wind_speed": 2.5,
    "solar_radiation": 700.0,
    "heat_index": 49.2,
    "wbgt": 31.5,
    "utci": 43.1,
    "vulnerability_score": 0.78,
}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# ---------------------------------------------------------------------------
# 1-4. Risk scenarios across the range
# ---------------------------------------------------------------------------


def test_low_risk_scenario(client: TestClient) -> None:
    """Mild conditions, low vulnerability."""
    response = client.post(
        URL,
        json={
            "temperature_c": 24.0,
            "relative_humidity": 40.0,
            "wind_speed": 3.0,
            "heat_index": 23.0,
            "wbgt": 18.0,
            "utci": 22.0,
            "vulnerability_score": 0.05,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] == "LOW"
    assert body["risk_score"] < 0.25


def test_moderate_risk_scenario(client: TestClient) -> None:
    response = client.post(
        URL,
        json={
            "temperature_c": 35.0,
            "relative_humidity": 45.0,
            "heat_index": 37.0,
            "wbgt": 26.0,
            "utci": 32.0,
            "vulnerability_score": 0.35,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] == "MODERATE"
    assert 0.25 <= body["risk_score"] < 0.50


def test_high_risk_scenario(client: TestClient) -> None:
    response = client.post(
        URL,
        json={
            "temperature_c": 40.0,
            "relative_humidity": 55.0,
            "heat_index": 44.0,
            "wbgt": 30.0,
            "utci": 38.0,
            "vulnerability_score": 0.55,
        },
    )
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] == "HIGH"
    assert 0.50 <= body["risk_score"] < 0.75


def test_extreme_risk_scenario(client: TestClient) -> None:
    response = client.post(URL, json=BASELINE)
    assert response.status_code == 200
    body = response.json()
    assert body["risk_level"] == "EXTREME"
    assert body["risk_score"] >= 0.75


def test_scenarios_are_ordered_by_severity() -> None:
    """Worse conditions must never score lower."""
    mild = predict_risk(24.0, 40.0, 23.0, 18.0, 0.05, utci=22.0)
    middling = predict_risk(35.0, 45.0, 37.0, 26.0, 0.35, utci=32.0)
    severe = predict_risk(42.0, 65.0, 49.2, 31.5, 0.78, utci=43.1)
    scores = [mild.risk_score, middling.risk_score, severe.risk_score]
    assert scores == sorted(scores)


# ---------------------------------------------------------------------------
# 5. Vulnerability raises risk
# ---------------------------------------------------------------------------


def test_higher_vulnerability_increases_risk() -> None:
    low = predict_risk(38.0, 50.0, 40.0, 28.0, 0.10, utci=34.0)
    high = predict_risk(38.0, 50.0, 40.0, 28.0, 0.90, utci=34.0)
    assert high.risk_score > low.risk_score


def test_vulnerability_is_monotonic() -> None:
    scores = [
        predict_risk(38.0, 50.0, 40.0, 28.0, v, utci=34.0).risk_score
        for v in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    assert scores == sorted(scores)


def test_vulnerability_contributes_its_configured_share() -> None:
    """Identical thermal input, vulnerability 0 -> 1, shifts by its weight."""
    zero = predict_risk(38.0, 50.0, 40.0, 28.0, 0.0, utci=34.0)
    full = predict_risk(38.0, 50.0, 40.0, 28.0, 1.0, utci=34.0)
    assert full.risk_score - zero.risk_score == pytest.approx(
        settings.RISK_WEIGHT_VULNERABILITY, abs=1e-3
    )


def test_hotter_conditions_increase_risk() -> None:
    cool = predict_risk(30.0, 50.0, 30.0, 22.0, 0.5, utci=26.0)
    hot = predict_risk(45.0, 50.0, 52.0, 34.0, 0.5, utci=45.0)
    assert hot.risk_score > cool.risk_score


# ---------------------------------------------------------------------------
# 6-8. Validation
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("value", [-0.1, 1.1, 2.0, -5.0])
def test_invalid_vulnerability_returns_422(
    client: TestClient, value: float
) -> None:
    response = client.post(URL, json={**BASELINE, "vulnerability_score": value})
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "request_validation_error"


@pytest.mark.parametrize("value", [-200.0, 200.0, 61.0, -91.0])
def test_invalid_temperature_returns_422(
    client: TestClient, value: float
) -> None:
    response = client.post(URL, json={**BASELINE, "temperature_c": value})
    assert response.status_code == 422


@pytest.mark.parametrize(
    "field",
    [
        "temperature_c",
        "relative_humidity",
        "heat_index",
        "wbgt",
        "vulnerability_score",
    ],
)
def test_missing_required_field_returns_422(
    client: TestClient, field: str
) -> None:
    payload = {key: value for key, value in BASELINE.items() if key != field}
    assert client.post(URL, json=payload).status_code == 422


@pytest.mark.parametrize(
    "field,value",
    [
        ("relative_humidity", 101.0),
        ("relative_humidity", -1.0),
        ("wind_speed", -3.0),
        ("solar_radiation", -50.0),
        ("heat_index", 500.0),
        ("wbgt", -80.0),
        ("utci", 300.0),
    ],
)
def test_out_of_range_values_return_422(
    client: TestClient, field: str, value: float
) -> None:
    assert client.post(URL, json={**BASELINE, field: value}).status_code == 422


@pytest.mark.parametrize(
    "field", ["temperature_c", "heat_index", "wbgt", "vulnerability_score"]
)
@pytest.mark.parametrize("bad", ["NaN", "Infinity", "-Infinity"])
def test_nan_and_infinity_are_rejected(
    client: TestClient, field: str, bad: str
) -> None:
    """A field with only a lower bound accepts Infinity unless blocked."""
    raw = json.dumps({**BASELINE, field: 0}).replace(f'"{field}": 0', f'"{field}": {bad}')
    response = client.post(
        URL, content=raw, headers={"Content-Type": "application/json"}
    )
    assert response.status_code == 422


def test_non_numeric_input_returns_422(client: TestClient) -> None:
    assert client.post(URL, json={**BASELINE, "wbgt": "hot"}).status_code == 422


def test_service_validates_independently_of_fastapi() -> None:
    """Later phases call this directly with no HTTP layer to guard it."""
    with pytest.raises(ValidationError):
        predict_risk(42.0, 65.0, 49.2, 31.5, 1.5, utci=43.1)
    with pytest.raises(ValidationError):
        predict_risk(200.0, 65.0, 49.2, 31.5, 0.78, utci=43.1)
    with pytest.raises(ValidationError):
        predict_risk(42.0, 65.0, float("nan"), 31.5, 0.78)
    with pytest.raises(ValidationError):
        predict_risk(42.0, 65.0, 49.2, float("inf"), 0.78)


# ---------------------------------------------------------------------------
# 9-10. Bounds and level agreement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "temp,rh,hi,wbgt,vuln,utci",
    [
        (-50.0, 0.0, -90.0, -40.0, 0.0, -90.0),
        (60.0, 100.0, 150.0, 100.0, 1.0, 100.0),
        (42.0, 65.0, 49.2, 31.5, 0.78, None),
        (20.0, 90.0, 20.0, 10.0, 1.0, 5.0),
        (55.0, 5.0, 120.0, 60.0, 0.0, None),
    ],
)
def test_score_always_between_zero_and_one(
    temp, rh, hi, wbgt, vuln, utci
) -> None:
    result = predict_risk(temp, rh, hi, wbgt, vuln, utci=utci)
    assert 0.0 <= result.risk_score <= 1.0
    assert 0.0 <= result.components.thermal_stress <= 1.0
    assert 0.0 <= result.components.vulnerability <= 1.0


def test_extremes_reach_the_full_range() -> None:
    assert predict_risk(20.0, 30.0, 20.0, 15.0, 0.0, utci=10.0).risk_score == 0.0
    assert predict_risk(50.0, 90.0, 90.0, 45.0, 1.0, utci=60.0).risk_score == 1.0


@pytest.mark.parametrize(
    "score,expected",
    [
        (0.0, "LOW"),
        (0.24, "LOW"),
        (0.25, "MODERATE"),
        (0.49, "MODERATE"),
        (0.50, "HIGH"),
        (0.74, "HIGH"),
        (0.75, "EXTREME"),
        (1.0, "EXTREME"),
    ],
)
def test_risk_level_thresholds(score: float, expected: str) -> None:
    assert risk_level(score) == expected


def test_returned_level_matches_returned_score(client: TestClient) -> None:
    """The level must always agree with the score it was derived from."""
    cases = [
        {**BASELINE, "vulnerability_score": v} for v in (0.0, 0.2, 0.5, 0.8, 1.0)
    ]
    for payload in cases:
        body = client.post(URL, json=payload).json()
        assert body["risk_level"] == risk_level(body["risk_score"])


# ---------------------------------------------------------------------------
# UTCI optionality -- the >50 C integration case
# ---------------------------------------------------------------------------


def test_missing_utci_is_accepted(client: TestClient) -> None:
    """Above 50 C the thermal engine returns no UTCI. Risk must still work."""
    payload = {**BASELINE, "utci": None}
    response = client.post(URL, json=payload)
    assert response.status_code == 200

    body = response.json()
    assert body["normalised_indices"]["utci"] is None
    assert any("UTCI" in note for note in body["notes"])


def test_missing_utci_redistributes_weight() -> None:
    """Dropping the weight instead would understate risk during the worst events."""
    result = predict_risk(52.0, 30.0, 73.8, 40.1, 0.78, utci=None)
    thermal_weights = [
        weight
        for name, weight in result.weights.items()
        if name.startswith("thermal.")
    ]
    assert sum(thermal_weights) == pytest.approx(
        settings.RISK_WEIGHT_THERMAL, abs=1e-6
    )
    assert "thermal.utci" not in result.weights


def test_contributors_omit_missing_utci() -> None:
    result = predict_risk(52.0, 30.0, 73.8, 40.1, 0.78, utci=None)
    factors = {contributor.factor for contributor in result.contributors}
    assert "UTCI" not in factors
    assert {"Heat Index", "WBGT", "vulnerability"} <= factors


# ---------------------------------------------------------------------------
# Honesty of the contract
# ---------------------------------------------------------------------------


def test_confidence_is_always_null(client: TestClient) -> None:
    """No model has been fitted, so no confidence can be claimed."""
    assert client.post(URL, json=BASELINE).json()["confidence"] is None


def test_risk_probability_equals_score(client: TestClient) -> None:
    body = client.post(URL, json=BASELINE).json()
    assert body["risk_probability"] == body["risk_score"]


def test_response_states_it_is_not_validated(client: TestClient) -> None:
    body = client.post(URL, json=BASELINE).json()
    assert "NOT A MEDICALLY VALIDATED" in body["disclaimer"].upper()
    joined = " ".join(body["limitations"]).upper()
    assert "SHAP" in joined
    assert "PROBABILITY" in joined


def test_contributors_are_not_called_shap(client: TestClient) -> None:
    body = client.post(URL, json=BASELINE).json()
    assert "contributors" in body
    assert "shap" not in json.dumps(body["contributors"]).lower()


def test_contributors_sum_to_the_score() -> None:
    result = predict_risk(41.0, 58.0, 47.5, 30.2, 0.61, utci=41.0)
    total = sum(contributor.impact for contributor in result.contributors)
    assert total == pytest.approx(result.risk_score, abs=1e-3)


def test_contributors_are_sorted_by_impact() -> None:
    result = predict_risk(42.0, 65.0, 49.2, 31.5, 0.78, utci=43.1)
    impacts = [contributor.impact for contributor in result.contributors]
    assert impacts == sorted(impacts, reverse=True)


def test_response_exposes_normalisation_anchors(client: TestClient) -> None:
    anchors = client.post(URL, json=BASELINE).json()["normalisation_anchors"]
    assert "UNCALIBRATED" in anchors["wbgt"].upper()
    assert "Brode" in anchors["utci"]


# ---------------------------------------------------------------------------
# Weights, normalisation, architecture
# ---------------------------------------------------------------------------


def test_weights_sum_to_one() -> None:
    thermal, vulnerability, sub_weights = validate_weights()
    assert thermal + vulnerability == pytest.approx(1.0)
    assert sum(sub_weights.values()) == pytest.approx(1.0)


def test_misconfigured_weights_fail_loudly(monkeypatch) -> None:
    monkeypatch.setattr(settings, "RISK_WEIGHT_THERMAL", 0.9, raising=False)
    with pytest.raises(HeatSentinalError):
        validate_weights()


def test_misconfigured_thermal_sub_weights_fail_loudly(monkeypatch) -> None:
    monkeypatch.setattr(
        settings, "RISK_THERMAL_WEIGHT_WBGT", 0.9, raising=False
    )
    with pytest.raises(HeatSentinalError):
        validate_weights()


def test_normalisation_is_linear_and_clamped() -> None:
    assert normalise_index(27.0, 27.0, 54.0) == 0.0
    assert normalise_index(54.0, 27.0, 54.0) == pytest.approx(1.0)
    assert normalise_index(40.5, 27.0, 54.0) == pytest.approx(0.5)
    assert normalise_index(10.0, 27.0, 54.0) == 0.0
    assert normalise_index(99.0, 27.0, 54.0) == pytest.approx(1.0)


def test_degenerate_anchors_fail_loudly() -> None:
    with pytest.raises(HeatSentinalError):
        normalise_index(30.0, 50.0, 50.0)


def test_thresholds_come_from_configuration() -> None:
    assert settings.risk_bounds_list == [0.25, 0.50, 0.75]
    assert settings.risk_categories_list == [
        "LOW",
        "MODERATE",
        "HIGH",
        "EXTREME",
    ]


def test_calculation_is_deterministic() -> None:
    first = predict_risk(39.4, 62.1, 45.8, 29.7, 0.53, utci=39.2)
    second = predict_risk(39.4, 62.1, 45.8, 29.7, 0.53, utci=39.2)
    assert first.model_dump() == second.model_dump()


def test_risk_service_does_not_recalculate_thermal_indices() -> None:
    """Separation of concerns: scoring must not import the thermal engine."""
    import ast
    from pathlib import Path

    module = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "risk_service.py"
    )
    source = module.read_text(encoding="utf-8")
    tree = ast.parse(source)

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)

    assert not any("thermal_service" in name for name in imported)
    assert not any(
        name.split(".")[0] in {"httpx", "requests", "fastapi"}
        for name in imported
    )
    # No index formula should appear here.
    assert "rothfusz" not in source.lower()
    assert "0.7 *" not in source


# ---------------------------------------------------------------------------
# Earlier phases still work
# ---------------------------------------------------------------------------


def test_risk_endpoint_is_in_the_openapi_schema(client: TestClient) -> None:
    schema = client.get("/openapi.json").json()
    assert "/api/v1/risk/predict" in schema["paths"]
    assert "post" in schema["paths"]["/api/v1/risk/predict"]

    for path in (
        "/api/v1/health",
        "/api/v1/weather/current",
        "/api/v1/weather/forecast",
        "/api/v1/thermal/calculate",
        "/api/v1/thermal/current",
        "/api/v1/vulnerability/calculate",
    ):
        assert path in schema["paths"]
