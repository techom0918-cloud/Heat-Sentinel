"""Phase 11 tests: early warning & alerts."""

from datetime import date

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core.config import settings
from app.main import app
from app.services import alert_service
from tests.conftest import hourly_payload, mock_provider

URL = f"{settings.API_V1_PREFIX}/alerts/evaluate"


@pytest.fixture(scope="module")
def client() -> TestClient:
    with TestClient(app) as test_client:
        yield test_client


def _trajectory(levels: list[str], trend: str = "STABLE") -> dict:
    """A minimal synthetic trajectory dict, shaped like forecast_service's."""
    base = date(2026, 9, 4)
    entries = [
        {
            "target_date": date(2026, 9, 4 + offset),
            "days_ahead": offset,
            "risk_level": level,
        }
        for offset, level in enumerate(levels)
    ]
    order = settings.alert_levels_list
    peak_entry = max(entries, key=lambda e: order.index(e["risk_level"]))
    return {
        "based_on": base,
        "forecast": entries,
        "peak_risk": peak_entry["risk_level"],
        "peak_date": peak_entry["target_date"],
        "trend": trend,
    }


# --- Alert level thresholds --------------------------------------------


def test_no_alert_for_low_risk() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["LOW", "LOW", "MODERATE"]),
        vulnerability_level="LOW",
    )
    assert result["alert_required"] is False
    assert result["alert_level"] == "MODERATE"


def test_no_alert_when_forecast_never_reaches_threshold() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["MODERATE", "MODERATE", "MODERATE"]),
        vulnerability_level="LOW",
    )
    assert result["alert_required"] is False


def test_alert_for_high_risk() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["MODERATE", "HIGH", "HIGH"]),
        vulnerability_level="LOW",
    )
    assert result["alert_required"] is True
    assert result["alert_level"] == "HIGH"


def test_alert_for_very_high_risk() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["HIGH", "VERY_HIGH"]),
        vulnerability_level="LOW",
    )
    assert result["alert_required"] is True
    assert result["alert_level"] == "VERY_HIGH"


def test_alert_for_extreme_risk() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["HIGH", "VERY_HIGH", "EXTREME"]),
        vulnerability_level="LOW",
    )
    assert result["alert_required"] is True
    assert result["alert_level"] == "EXTREME"


def test_alert_min_level_is_configurable(monkeypatch) -> None:
    monkeypatch.setattr(settings, "ALERT_MIN_LEVEL", "EXTREME", raising=False)
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["MODERATE", "HIGH", "VERY_HIGH"]),
        vulnerability_level="LOW",
    )
    assert result["alert_required"] is False


# --- Escalation detection ------------------------------------------------


def test_escalation_detected_from_moderate_to_high() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["MODERATE", "HIGH"]),
        vulnerability_level="LOW",
    )
    assert result["escalation"] is True
    assert result["escalation_label"] == "MODERATE -> HIGH"
    assert result["alert_required"] is True


def test_no_escalation_when_risk_is_flat() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["HIGH", "HIGH", "HIGH"]),
        vulnerability_level="LOW",
    )
    assert result["escalation"] is False
    assert result["escalation_label"] is None


def test_escalation_below_threshold_is_reported_but_does_not_alert() -> None:
    """LOW -> MODERATE is a real escalation, but MODERATE is under HIGH."""
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["LOW", "MODERATE"]),
        vulnerability_level="LOW",
    )
    assert result["alert_level"] == "MODERATE"
    assert result["escalation"] is True
    assert result["escalation_label"] == "LOW -> MODERATE"
    assert result["alert_required"] is False
    assert "below" in result["reason"].lower()


def test_escalation_across_threshold_does_alert() -> None:
    """MODERATE -> HIGH crosses the default HIGH threshold."""
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["MODERATE", "HIGH"]),
        vulnerability_level="LOW",
    )
    assert result["alert_level"] == "HIGH"
    assert result["escalation"] is True
    assert result["alert_required"] is True
    assert "escalate" in result["reason"].lower()


# --- Vulnerable zone priority ---------------------------------------------


def test_priority_escalates_with_high_vulnerability() -> None:
    trajectory = _trajectory(["HIGH", "EXTREME"])
    low_vuln = alert_service.evaluate_alert(
        zone_id="ZONE_01", trajectory=trajectory, vulnerability_level="LOW"
    )
    high_vuln = alert_service.evaluate_alert(
        zone_id="ZONE_01", trajectory=trajectory, vulnerability_level="EXTREME"
    )
    order = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
    assert order[high_vuln["priority"]] >= order[low_vuln["priority"]]


def test_critical_priority_requires_extreme_heat_and_high_vulnerability() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["HIGH", "EXTREME"]),
        vulnerability_level="EXTREME",
    )
    assert result["priority"] == "CRITICAL"


def test_extreme_heat_alone_is_not_critical_without_vulnerability() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["HIGH", "EXTREME"]),
        vulnerability_level="LOW",
    )
    assert result["priority"] != "CRITICAL"


# --- Peak date & determinism -----------------------------------------------


def test_correct_peak_date_is_reported() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["LOW", "HIGH", "MODERATE", "EXTREME", "LOW"]),
        vulnerability_level="LOW",
    )
    assert result["peak_date"] == date(2026, 9, 7)  # index 3 -> EXTREME
    assert result["forecast_peak"] == "EXTREME"


def test_alert_reason_is_deterministic() -> None:
    trajectory = _trajectory(["MODERATE", "HIGH", "EXTREME"])
    first = alert_service.evaluate_alert(
        zone_id="ZONE_01", trajectory=trajectory, vulnerability_level="HIGH"
    )
    second = alert_service.evaluate_alert(
        zone_id="ZONE_01", trajectory=trajectory, vulnerability_level="HIGH"
    )
    assert first == second
    assert "escalate" in first["reason"].lower()


def test_no_alert_reason_mentions_threshold() -> None:
    # LOW -> MODERATE would still count as escalation, so use a flat,
    # entirely-LOW trajectory to get a genuine no-alert case.
    flat = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["LOW", "LOW"], trend="STABLE"),
        vulnerability_level="LOW",
    )
    assert flat["alert_required"] is False
    assert "below" in flat["reason"].lower()


# --- Malformed input ---------------------------------------------------


def test_malformed_zone_rejected_by_api(client: TestClient) -> None:
    response = client.post(URL, json={"zone_id": "ZONE_999"})
    assert response.status_code == 404


def test_empty_trajectory_rejected() -> None:
    from app.core.exceptions import ValidationError

    empty = {
        "based_on": date(2026, 9, 4),
        "forecast": [],
        "peak_risk": "LOW",
        "peak_date": date(2026, 9, 4),
        "trend": "STABLE",
    }
    with pytest.raises(ValidationError):
        alert_service.evaluate_alert(
            zone_id="ZONE_01", trajectory=empty, vulnerability_level="LOW"
        )


# --- No notification API required ------------------------------------------


def test_no_external_notification_api_required() -> None:
    """Building an alert never touches a notification provider."""
    from app.services.alert_service import NoopNotificationAdapter

    adapter = NoopNotificationAdapter()
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["HIGH", "EXTREME"]),
        vulnerability_level="HIGH",
    )
    adapter.send(result)  # must not raise, must not need any API key/network


def test_recommended_actions_are_not_medical_instructions() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["HIGH", "EXTREME"]),
        vulnerability_level="HIGH",
    )
    joined = " ".join(result["recommended_actions"]).lower()
    for banned in ("prescribe", "diagnos", "medication", "dosage"):
        assert banned not in joined


def test_no_mortality_claims() -> None:
    result = alert_service.evaluate_alert(
        zone_id="ZONE_01",
        trajectory=_trajectory(["HIGH", "EXTREME"]),
        vulnerability_level="HIGH",
    )
    disclaimer = result["disclaimer"].lower()
    assert "does not predict deaths" in disclaimer


# --- API ---------------------------------------------------------------


def test_evaluate_endpoint(client: TestClient, with_model) -> None:
    with mock_provider(hourly_payload()):
        response = client.post(URL, json={"zone_id": "ZONE_01"})
    assert response.status_code == 200
    body = response.json()
    assert body["zone_id"] == "ZONE_01"
    assert body["alert_level"] in {"LOW", "MODERATE", "HIGH", "VERY_HIGH", "EXTREME"}
    assert isinstance(body["recommended_actions"], list)


def test_evaluate_endpoint_in_schema(client: TestClient) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert "/api/v1/alerts/evaluate" in paths


def test_evaluate_provider_timeout_returns_502(client: TestClient, with_model) -> None:
    with mock_provider(exc=httpx.TimeoutException("timed out")):
        response = client.post(URL, json={"zone_id": "ZONE_01"})
    assert response.status_code == 502


@pytest.mark.parametrize(
    "payload",
    [
        {"zone_id": "ZONE_01", "days": 0},
        {"zone_id": "ZONE_01", "days": 999},
        {},
    ],
)
def test_malformed_requests_rejected(client: TestClient, payload) -> None:
    assert client.post(URL, json=payload).status_code == 422
