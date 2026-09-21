"""Phase 10 tests: AI action optimizer."""

import copy

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import ValidationError
from app.main import app
from app.services import intervention_service, optimizer_service
from tests.conftest import current_payload, mock_provider

URL = f"{settings.API_V1_PREFIX}/interventions/optimize"

BASELINE_INPUT = dict(
    temperature_c=42.0,
    relative_humidity=60.0,
    heat_index=49.2,
    wbgt=31.5,
    utci=43.1,
    vulnerability_score=0.78,
    wind_speed=2.0,
)

RESOURCES = {"cooling_centers": 2, "water_tankers": 10, "field_workers": 50}


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _optimize(**overrides):
    kwargs = dict(
        zone_id="ZONE_01",
        budget=500000,
        available_resources=RESOURCES,
        **BASELINE_INPUT,
    )
    kwargs.update(overrides)
    return optimizer_service.optimize(**kwargs)


# --- Valid optimization -------------------------------------------------


def test_valid_optimization_returns_a_plan() -> None:
    result = _optimize()
    assert result["zone_id"] == "ZONE_01"
    assert result["baseline_risk"] > 0
    assert len(result["recommended_actions"]) > 0


def test_optimized_risk_never_exceeds_baseline() -> None:
    result = _optimize()
    assert result["optimized_risk"] <= result["baseline_risk"]


def test_optimized_risk_strictly_improves_when_resources_allow() -> None:
    result = _optimize()
    assert result["optimized_risk"] < result["baseline_risk"]
    assert result["estimated_risk_reduction"] > 0


def test_recommended_plan_uses_only_allowed_interventions() -> None:
    result = _optimize(allowed_interventions=["COOLING_CENTER", "WATER_DISTRIBUTION"])
    used = {action["type"] for action in result["recommended_actions"]}
    assert used <= {"COOLING_CENTER", "WATER_DISTRIBUTION"}


# --- Budget constraint ----------------------------------------------------


def test_zero_budget_recommends_nothing() -> None:
    result = _optimize(budget=0)
    assert result["recommended_actions"] == []
    assert result["budget_used"] == 0
    assert result["optimized_risk"] == pytest.approx(result["baseline_risk"])


def test_budget_used_never_exceeds_budget() -> None:
    result = _optimize(budget=15000)
    assert result["budget_used"] <= 15000
    assert result["budget_remaining"] == pytest.approx(
        15000 - result["budget_used"], abs=1e-6
    )


def test_more_budget_never_reduces_recommended_reduction() -> None:
    small = _optimize(budget=10000)["estimated_risk_reduction"]
    large = _optimize(budget=500000)["estimated_risk_reduction"]
    assert large >= small


def test_negative_budget_rejected() -> None:
    with pytest.raises(ValidationError):
        _optimize(budget=-1)


# --- Resource constraints ---------------------------------------------------


def test_insufficient_resources_recommends_nothing() -> None:
    result = _optimize(
        available_resources={"cooling_centers": 0, "water_tankers": 0, "field_workers": 0}
    )
    assert result["recommended_actions"] == []
    assert result["optimized_risk"] == pytest.approx(result["baseline_risk"])


def test_negative_resource_count_rejected() -> None:
    with pytest.raises(ValidationError):
        _optimize(available_resources={"cooling_centers": -1})


def test_plan_never_uses_more_resource_units_than_available() -> None:
    result = _optimize(
        available_resources={"cooling_centers": 1, "water_tankers": 2, "field_workers": 3}
    )
    for resource, used in result["resources_used"].items():
        assert used <= {"cooling_centers": 1, "water_tankers": 2, "field_workers": 3}.get(
            resource, 0
        )


def test_resources_used_plus_remaining_equals_available() -> None:
    result = _optimize(available_resources=RESOURCES)
    for resource, available in RESOURCES.items():
        assert (
            result["resources_used"][resource]
            + result["resources_remaining"][resource]
            == available
        )


# --- Validation -------------------------------------------------------------


def test_invalid_zone_returns_404(client: TestClient) -> None:
    with mock_provider(current_payload()):
        response = client.post(
            URL,
            json={
                "zone_id": "ZONE_999",
                "budget": 100000,
                "available_resources": RESOURCES,
            },
        )
    assert response.status_code == 404


def test_invalid_intervention_rejected() -> None:
    with pytest.raises(ValidationError):
        _optimize(allowed_interventions=["CLOUD_SEEDING"])


@pytest.mark.parametrize(
    "payload",
    [
        {"zone_id": "ZONE_01", "budget": -1, "available_resources": RESOURCES},
        {
            "zone_id": "ZONE_01",
            "budget": 1000,
            "available_resources": {"cooling_centers": -1},
        },
        {
            "zone_id": "ZONE_01",
            "budget": 1000,
            "available_resources": RESOURCES,
            "allowed_interventions": ["NOPE"],
        },
        {"budget": 1000, "available_resources": RESOURCES},
    ],
)
def test_malformed_requests_rejected(client: TestClient, payload) -> None:
    assert client.post(URL, json=payload).status_code == 422


# --- Feasibility, determinism, reuse -----------------------------------


def test_recommended_plan_is_feasible() -> None:
    """No recommended action costs more, or uses more resource, than exists."""
    result = _optimize(budget=50000, available_resources=RESOURCES)
    economics = settings.optimizer_unit_economics
    for action in result["recommended_actions"]:
        assert action["quantity"] >= 1
        assert action["cost"] == pytest.approx(
            action["quantity"] * economics[action["type"]]["unit_cost"], abs=1e-6
        )
    assert result["budget_used"] <= result["budget"]


def test_optimizer_does_not_mutate_its_inputs() -> None:
    resources = copy.deepcopy(RESOURCES)
    resources_snapshot = copy.deepcopy(resources)
    baseline_snapshot = copy.deepcopy(BASELINE_INPUT)

    _optimize(available_resources=resources)

    assert resources == resources_snapshot
    assert BASELINE_INPUT == baseline_snapshot


def test_optimizer_is_deterministic() -> None:
    first = _optimize()
    second = _optimize()
    assert first == second


def test_optimizer_reuses_the_phase9_simulator() -> None:
    """The final plan's risk score must match calling the simulator directly."""
    result = _optimize(budget=50000, available_resources=RESOURCES)
    interventions = [
        {
            "type": action["type"],
            "coverage": action["coverage"],
        }
        for action in result["recommended_actions"]
    ]
    direct = intervention_service.simulate(
        **BASELINE_INPUT, interventions=interventions, zone_id="ZONE_01"
    )
    assert direct["simulation"]["risk_score"] == pytest.approx(
        result["optimized_risk"], abs=1e-6
    )


def test_assumptions_are_returned() -> None:
    result = _optimize()
    assert len(result["assumptions"]) >= 2
    joined = " ".join(result["assumptions"]).lower()
    assert "uncalibrated" in joined or "prototype" in joined


def test_no_mortality_or_medical_claims() -> None:
    result = _optimize()
    claims = " ".join(result["assumptions"]).lower()
    for banned in ("deaths prevented", "mortality reduction", "lives saved"):
        assert banned not in claims

    disclaimer = result["disclaimer"].lower()
    assert "does not" in disclaimer
    assert "deaths prevented" in disclaimer
    assert "mortality reduction" in disclaimer


def test_disclaimer_states_it_is_a_modelled_recommendation() -> None:
    result = _optimize()
    disclaimer = result["disclaimer"].upper()
    assert "MODELLED RECOMMENDATION" in disclaimer
    assert "NOT" in disclaimer


# --- API ---------------------------------------------------------------


def test_optimize_endpoint(client: TestClient) -> None:
    with mock_provider(current_payload()):
        response = client.post(
            URL,
            json={
                "zone_id": "ZONE_01",
                "budget": 500000,
                "available_resources": RESOURCES,
            },
        )
    assert response.status_code == 200
    body = response.json()
    assert body["zone_id"] == "ZONE_01"
    assert body["optimized_risk"] <= body["baseline_risk"]
    assert isinstance(body["recommended_actions"], list)


def test_optimize_endpoint_with_restricted_interventions(client: TestClient) -> None:
    with mock_provider(current_payload()):
        response = client.post(
            URL,
            json={
                "zone_id": "ZONE_01",
                "budget": 500000,
                "available_resources": RESOURCES,
                "allowed_interventions": ["COOLING_CENTER"],
            },
        )
    assert response.status_code == 200
    body = response.json()
    used = {a["type"] for a in body["recommended_actions"]}
    assert used <= {"COOLING_CENTER"}


def test_optimize_provider_timeout_returns_502(client: TestClient) -> None:
    with mock_provider(exc=httpx.TimeoutException("timed out")):
        response = client.post(
            URL,
            json={
                "zone_id": "ZONE_01",
                "budget": 100000,
                "available_resources": RESOURCES,
            },
        )
    assert response.status_code == 502


def test_optimize_endpoint_in_schema(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/interventions/optimize" in paths


def test_optimizer_does_not_touch_the_ml_model() -> None:
    """The optimizer operates on the downstream risk/intervention layer only."""
    import ast
    from pathlib import Path

    module = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "optimizer_service.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert not any("ml_service" in name for name in imported)
    assert not any("heat_pipeline" in name for name in imported)
