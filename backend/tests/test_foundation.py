"""Phase 1 tests: application foundation, health, errors, CORS."""

import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def test_root_returns_service_identity(client: TestClient) -> None:
    response = client.get("/")
    assert response.status_code == 200
    assert response.json() == {
        "name": "HeatSentinal",
        "status": "running",
        "message": "Heat Health Intelligence API",
    }


def test_health_returns_healthy(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_PREFIX}/health")
    assert response.status_code == 200
    assert response.json() == {"status": "healthy"}


def test_health_details_reports_metadata(client: TestClient) -> None:
    response = client.get(f"{settings.API_V1_PREFIX}/health/details")
    assert response.status_code == 200

    payload = response.json()
    assert payload["status"] == "healthy"
    assert payload["service"] == settings.APP_NAME
    assert payload["version"] == settings.APP_VERSION
    assert payload["uptime_seconds"] >= 0


def test_unknown_route_uses_error_envelope(client: TestClient) -> None:
    response = client.get("/api/v1/does-not-exist")
    assert response.status_code == 404

    error = response.json()["error"]
    assert error["type"] == "http_error"
    assert isinstance(error["details"], dict)


def test_openapi_schema_is_available(client: TestClient) -> None:
    response = client.get("/openapi.json")
    assert response.status_code == 200

    schema = response.json()
    assert schema["info"]["title"] == "HeatSentinal API"
    assert schema["info"]["version"] == "1.0.0"
    assert "/api/v1/health" in schema["paths"]


def test_cors_allows_local_react_dev_server(client: TestClient) -> None:
    origin = "http://localhost:5173"
    response = client.get("/", headers={"Origin": origin})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == origin


def test_cors_origins_are_parsed_into_a_list() -> None:
    origins = settings.cors_origins_list
    assert "http://localhost:5173" in origins
    assert "http://127.0.0.1:5173" in origins
