"""Phase 9 tests: heat action simulator."""

import copy

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.main import app
from app.services import intervention_service
from tests.conftest import current_payload, mock_provider

URL = f"{settings.API_V1_PREFIX}/interventions/simulate"
TYPES_URL = f"{settings.API_V1_PREFIX}/interventions/types"

BASELINE_INPUT = dict(
    temperature_c=42.0,
    relative_humidity=60.0,
    heat_index=49.2,
    wbgt=31.5,
    utci=43.1,
    vulnerability_score=0.78,
    wind_speed=2.0,
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# --- Baseline and simulation ------------------------------------------------


def test_baseline_and_simulation_are_both_returned() -> None:
    result = intervention_service.simulate(
        **BASELINE_INPUT,
        interventions=[{"type": "COOLING_CENTER", "coverage": 0.6}],
    )
    assert result["baseline"]["risk_score"] > 0
    assert result["simulation"]["risk_score"] > 0
    assert result["simulation"]["risk_score"] <= result["baseline"]["risk_score"]


def test_reduction_is_computed_consistently() -> None:
    result = intervention_service.simulate(
        **BASELINE_INPUT,
        interventions=[{"type": "COOLING_CENTER", "coverage": 0.6}],
    )
    expected = (
        result["baseline"]["risk_score"] - result["simulation"]["risk_score"]
    )
    assert result["estimated_risk_reduction"] == pytest.approx(expected, abs=1e-3)

    expected_pct = expected / result["baseline"]["risk_score"] * 100
    assert result["estimated_risk_reduction_percent"] == pytest.approx(
        expected_pct, abs=0.1
    )


def test_zero_coverage_changes_nothing() -> None:
    result = intervention_service.simulate(
        **BASELINE_INPUT,
        interventions=[{"type": "COOLING_CENTER", "coverage": 0.0}],
    )
    assert result["estimated_risk_reduction"] == pytest.approx(0.0, abs=1e-6)
    assert result["baseline"]["risk_score"] == result["simulation"]["risk_score"]


def test_more_coverage_reduces_risk_further() -> None:
    scores = [
        intervention_service.simulate(
            **BASELINE_INPUT,
            interventions=[{"type": "COOLING_CENTER", "coverage": c}],
        )["simulation"]["risk_score"]
        for c in (0.0, 0.25, 0.5, 0.75, 1.0)
    ]
    assert scores == sorted(scores, reverse=True)


def test_risk_level_transition_is_reported() -> None:
    result = intervention_service.simulate(
        **BASELINE_INPUT,
        interventions=[
            {"type": t, "coverage": 1.0}
            for t in intervention_service.supported_types()
        ],
    )
    assert isinstance(result["risk_level_changed"], bool)
    if result["baseline"]["risk_level"] != result["simulation"]["risk_level"]:
        assert result["risk_level_changed"] is True


def test_channels_are_applied_separately() -> None:
    """Vulnerability and exposure interventions act on different channels."""
    vulnerability_only = intervention_service.simulate(
        **BASELINE_INPUT,
        interventions=[{"type": "COOLING_CENTER", "coverage": 1.0}],
    )
    exposure_only = intervention_service.simulate(
        **BASELINE_INPUT,
        interventions=[{"type": "WORK_HOUR_SHIFT", "coverage": 1.0}],
    )
    assert vulnerability_only["channel_reductions"]["exposure"] == 0.0
    assert vulnerability_only["channel_reductions"]["vulnerability"] > 0
    assert exposure_only["channel_reductions"]["vulnerability"] == 0.0
    assert exposure_only["channel_reductions"]["exposure"] > 0


def test_stacked_interventions_never_exceed_full_reduction() -> None:
    """Additive combination would let four measures sum past 100%."""
    result = intervention_service.simulate(
        **BASELINE_INPUT,
        interventions=[
            {"type": t, "coverage": 1.0}
            for t in intervention_service.supported_types()
        ],
    )
    for value in result["channel_reductions"].values():
        assert 0.0 <= value < 1.0


def test_stacking_has_diminishing_returns() -> None:
    one = intervention_service.compute_channel_reductions(
        [{"type": "COOLING_CENTER", "coverage": 1.0}]
    )[0]
    two = intervention_service.compute_channel_reductions(
        [
            {"type": "COOLING_CENTER", "coverage": 1.0},
            {"type": "WATER_DISTRIBUTION", "coverage": 1.0},
        ]
    )[0]
    additive = (
        settings.INTERVENTION_COOLING_CENTER_EFFECT
        + settings.INTERVENTION_WATER_DISTRIBUTION_EFFECT
    )
    assert one < two < additive


def test_simulation_does_not_mutate_its_input() -> None:
    interventions = [{"type": "COOLING_CENTER", "coverage": 0.6}]
    snapshot = copy.deepcopy(interventions)
    baseline_input = copy.deepcopy(BASELINE_INPUT)

    intervention_service.simulate(**BASELINE_INPUT, interventions=interventions)

    assert interventions == snapshot
    assert BASELINE_INPUT == baseline_input


def test_repeated_simulation_is_deterministic() -> None:
    args = dict(
        **BASELINE_INPUT,
        interventions=[{"type": "SHADE_REST_AREA", "coverage": 0.5}],
    )
    assert intervention_service.simulate(**args) == intervention_service.simulate(
        **args
    )


# --- Validation -------------------------------------------------------------


@pytest.mark.parametrize("coverage", [-0.1, 1.1, 2.0, -5.0])
def test_invalid_coverage_rejected(coverage) -> None:
    with pytest.raises(ValidationError):
        intervention_service.simulate(
            **BASELINE_INPUT,
            interventions=[{"type": "COOLING_CENTER", "coverage": coverage}],
        )


def test_unknown_intervention_rejected() -> None:
    with pytest.raises(ValidationError) as excinfo:
        intervention_service.simulate(
            **BASELINE_INPUT,
            interventions=[{"type": "CLOUD_SEEDING", "coverage": 0.5}],
        )
    assert "supported" in excinfo.value.details


def test_empty_intervention_list_rejected() -> None:
    with pytest.raises(ValidationError):
        intervention_service.simulate(**BASELINE_INPUT, interventions=[])


def test_duplicate_intervention_rejected() -> None:
    with pytest.raises(ValidationError):
        intervention_service.simulate(
            **BASELINE_INPUT,
            interventions=[
                {"type": "COOLING_CENTER", "coverage": 0.4},
                {"type": "COOLING_CENTER", "coverage": 0.5},
            ],
        )


# --- Assumptions and terminology -------------------------------------------


def test_assumptions_are_returned() -> None:
    result = intervention_service.simulate(
        **BASELINE_INPUT,
        interventions=[
            {"type": "COOLING_CENTER", "coverage": 0.6},
            {"type": "WATER_DISTRIBUTION", "coverage": 0.4},
        ],
    )
    assert len(result["assumptions"]) >= 4
    joined = " ".join(result["assumptions"]).lower()
    assert "cooling" in joined
    assert "uncalibrated" in joined


def test_no_mortality_or_medical_claims() -> None:
    """Terminology guard.

    The banned phrases must not appear as CLAIMS. The disclaimer is allowed
    to name them in order to deny them, which is the point of a disclaimer,
    so it is checked separately.
    """
    result = intervention_service.simulate(
        **BASELINE_INPUT,
        interventions=[{"type": "COOLING_CENTER", "coverage": 0.6}],
    )
    claims = " ".join(result["assumptions"]).lower()
    for banned in ("deaths prevented", "mortality reduction", "lives saved"):
        assert banned not in claims
    assert "modelled" in claims or "modeled" in claims

    # The disclaimer must explicitly rule those outcomes out.
    disclaimer = result["disclaimer"].lower()
    assert "does not" in disclaimer
    assert "deaths prevented" in disclaimer
    assert "mortality reduction" in disclaimer


def test_disclaimer_states_it_is_a_modelled_scenario() -> None:
    result = intervention_service.simulate(
        **BASELINE_INPUT,
        interventions=[{"type": "PUBLIC_ALERT", "coverage": 1.0}],
    )
    disclaimer = result["disclaimer"].upper()
    assert "MODELLED SCENARIO" in disclaimer
    assert "NOT" in disclaimer


def test_effects_are_configurable(monkeypatch) -> None:
    before = intervention_service.max_effect("COOLING_CENTER")
    monkeypatch.setattr(
        settings, "INTERVENTION_COOLING_CENTER_EFFECT", 0.9, raising=False
    )
    assert intervention_service.max_effect("COOLING_CENTER") == 0.9
    assert before != 0.9


# --- API --------------------------------------------------------------------


def test_simulate_endpoint(client: TestClient) -> None:
    with mock_provider(current_payload()):
        response = client.post(
            URL,
            json={
                "zone_id": "ZONE_01",
                "interventions": [{"type": "COOLING_CENTER", "coverage": 0.6}],
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["zone_id"] == "ZONE_01"
    assert body["baseline"]["risk_score"] >= body["simulation"]["risk_score"]
    assert body["applied_interventions"][0]["channel"] == "VULNERABILITY"


def test_unknown_zone_returns_404(client: TestClient) -> None:
    with mock_provider(current_payload()):
        response = client.post(
            URL,
            json={
                "zone_id": "ZONE_999",
                "interventions": [{"type": "COOLING_CENTER", "coverage": 0.5}],
            },
        )
    assert response.status_code == 404
    assert "available_zones" in str(response.json()["error"]["details"])


@pytest.mark.parametrize(
    "payload",
    [
        {"zone_id": "ZONE_01", "interventions": []},
        {"zone_id": "ZONE_01", "interventions": [{"type": "NOPE", "coverage": 0.5}]},
        {
            "zone_id": "ZONE_01",
            "interventions": [{"type": "COOLING_CENTER", "coverage": 1.5}],
        },
        {
            "zone_id": "ZONE_01",
            "interventions": [{"type": "COOLING_CENTER", "coverage": -0.2}],
        },
        {"interventions": [{"type": "COOLING_CENTER", "coverage": 0.5}]},
    ],
)
def test_malformed_requests_rejected(client: TestClient, payload) -> None:
    assert client.post(URL, json=payload).status_code == 422


def test_provider_timeout_returns_502(client: TestClient) -> None:
    with mock_provider(exc=httpx.TimeoutException("timed out")):
        response = client.post(
            URL,
            json={
                "zone_id": "ZONE_01",
                "interventions": [{"type": "COOLING_CENTER", "coverage": 0.5}],
            },
        )
    assert response.status_code == 502


def test_types_endpoint_lists_all_interventions(client: TestClient) -> None:
    body = client.get(TYPES_URL).json()
    types = {entry["type"] for entry in body["interventions"]}
    assert types == set(intervention_service.supported_types())
    for entry in body["interventions"]:
        assert entry["channel"] in {"VULNERABILITY", "EXPOSURE"}
        assert 0.0 < entry["max_effect"] <= 1.0
        assert entry["assumption"]
    assert "MODELLED SCENARIO" in body["disclaimer"].upper()


def test_intervention_endpoints_in_schema(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/interventions/simulate" in paths
    assert "/api/v1/interventions/types" in paths


def test_simulator_does_not_touch_the_ml_model() -> None:
    """The simulator operates on the downstream risk layer only."""
    import ast
    from pathlib import Path

    module = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "intervention_service.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("ml_service" in name for name in imported)
    assert not any("heat_pipeline" in name for name in imported)
