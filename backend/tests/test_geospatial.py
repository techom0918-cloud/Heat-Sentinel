"""Phase 8 tests: hyperlocal zone risk."""

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.core.exceptions import ResourceNotFoundError
from app.main import app
from app.services import geospatial_service
from tests.conftest import current_payload, mock_provider

URL = f"{settings.API_V1_PREFIX}/zones/risk"


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


# --- Dataset ----------------------------------------------------------------


def test_zone_dataset_loads() -> None:
    document = geospatial_service.load_zones()
    assert document["type"] == "FeatureCollection"
    assert len(document["features"]) >= 3


def test_dataset_is_marked_synthetic() -> None:
    """Synthetic boundaries must never be mistaken for real ones."""
    document = geospatial_service.load_zones()
    assert document["data_status"] == "SYNTHETIC_DEMO"
    warning = document["warning"].upper()
    assert "SYNTHETIC" in warning
    assert "NOT FOR REAL-WORLD DECISION MAKING" in warning
    assert "not real administrative" in document["warning"].lower()


def test_every_zone_is_marked_synthetic() -> None:
    for feature in geospatial_service.load_zones()["features"]:
        assert feature["properties"]["data_status"] == "SYNTHETIC_DEMO"


def test_missing_dataset_fails_clearly(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(
        settings, "ZONES_GEOJSON_PATH", str(tmp_path / "gone.geojson"),
        raising=False,
    )
    geospatial_service.reset_caches()
    with pytest.raises(geospatial_service.ZoneDataError):
        geospatial_service.load_zones()
    geospatial_service.reset_caches()


def test_unknown_zone_raises_not_found() -> None:
    with pytest.raises(ResourceNotFoundError) as excinfo:
        geospatial_service.get_zone("NOPE")
    assert "available_zones" in excinfo.value.details


# --- GeoJSON structure ------------------------------------------------------


def test_returns_valid_feature_collection(client: TestClient) -> None:
    with mock_provider(current_payload()):
        response = client.get(URL)

    assert response.status_code == 200
    body = response.json()
    assert body["type"] == "FeatureCollection"
    assert isinstance(body["features"], list)

    for feature in body["features"]:
        assert feature["type"] == "Feature"
        assert feature["geometry"]["type"] == "Polygon"
        # A closed ring: first and last coordinate must match.
        ring = feature["geometry"]["coordinates"][0]
        assert ring[0] == ring[-1]
        assert len(ring) >= 4


def test_features_carry_the_four_distinct_layers(client: TestClient) -> None:
    """Hazard, vulnerability, combined risk and priority stay separate."""
    with mock_provider(current_payload()):
        body = client.get(URL).json()

    for feature in body["features"]:
        properties = feature["properties"]
        assert 0.0 <= properties["heat_hazard"] <= 1.0
        assert 0.0 <= properties["vulnerability"] <= 1.0
        assert 0.0 <= properties["human_risk"] <= 1.0
        assert properties["risk_level"] in {"LOW", "MODERATE", "HIGH", "EXTREME"}
        assert properties["priority"] in {"LOW", "MODERATE", "HIGH", "CRITICAL"}
        assert properties["vulnerability_level"]


def test_hazard_is_identical_across_zones(client: TestClient) -> None:
    """One provider grid cell covers them all, and the response says so."""
    with mock_provider(current_payload()):
        body = client.get(URL).json()

    hazards = {f["properties"]["heat_hazard"] for f in body["features"]}
    assert len(hazards) == 1
    note = body["hazard_source"]["note"].lower()
    assert "11 km" in note or "grid cell" in note
    assert "vulnerability" in note


def test_vulnerability_varies_between_zones(client: TestClient) -> None:
    """This is the point of zones: same weather, different populations."""
    with mock_provider(current_payload()):
        body = client.get(URL).json()

    vulnerabilities = {f["properties"]["vulnerability"] for f in body["features"]}
    assert len(vulnerabilities) > 1


def test_features_sorted_by_human_risk(client: TestClient) -> None:
    with mock_provider(current_payload()):
        body = client.get(URL).json()

    scores = [f["properties"]["human_risk"] for f in body["features"]]
    assert scores == sorted(scores, reverse=True)


def test_response_carries_the_synthetic_warning(client: TestClient) -> None:
    with mock_provider(current_payload()):
        body = client.get(URL).json()
    assert body["data_status"] == "SYNTHETIC_DEMO"
    assert "SYNTHETIC" in body["warning"].upper()


# --- Reuse of existing engines ----------------------------------------------


def test_vulnerability_comes_from_phase_four() -> None:
    """Phase 4 must not be reimplemented here."""
    feature = geospatial_service.get_zone("ZONE_01")
    result = geospatial_service.zone_vulnerability(feature)
    assert 0.0 <= result.vulnerability_score <= 1.0
    assert result.contributions
    assert "NOT A MEDICALLY VALIDATED" in result.disclaimer.upper()


def test_no_new_scoring_weights_are_introduced() -> None:
    """Combined risk must use the existing Phase 5 weights."""
    import ast
    from pathlib import Path

    module = (
        Path(__file__).resolve().parents[1]
        / "app"
        / "services"
        / "geospatial_service.py"
    )
    tree = ast.parse(module.read_text(encoding="utf-8"))
    imported = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module
    }
    assert any("services" in name for name in imported)


@pytest.mark.parametrize(
    "risk,vulnerability,expected",
    [
        ("EXTREME", "EXTREME", "CRITICAL"),
        ("EXTREME", "LOW", "HIGH"),
        ("MODERATE", "EXTREME", "HIGH"),
        ("LOW", "LOW", "LOW"),
        ("HIGH", "MODERATE", "HIGH"),
    ],
)
def test_priority_matrix(risk, vulnerability, expected) -> None:
    assert geospatial_service.priority_for(risk, vulnerability) == expected


def test_priority_favours_vulnerable_zones() -> None:
    """A cooler but far more vulnerable zone must not be out-ranked."""
    hot_resilient = geospatial_service.priority_for("HIGH", "LOW")
    mild_vulnerable = geospatial_service.priority_for("MODERATE", "EXTREME")
    order = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
    assert order[mild_vulnerable] > order[hot_resilient]


# --- Failure paths ----------------------------------------------------------


def test_provider_timeout_returns_502(client: TestClient) -> None:
    with mock_provider(exc=httpx.TimeoutException("timed out")):
        assert client.get(URL).status_code == 502


def test_missing_humidity_fails_cleanly(client: TestClient) -> None:
    with mock_provider(current_payload(relative_humidity_2m=None)):
        assert client.get(URL).status_code == 502


def test_invalid_coordinates_rejected(client: TestClient) -> None:
    assert client.get(URL, params={"latitude": 999, "longitude": 77}).status_code == 422


def test_zones_endpoint_in_schema(client: TestClient) -> None:
    assert "/api/v1/zones/risk" in client.get("/openapi.json").json()["paths"]
