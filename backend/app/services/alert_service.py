"""Early warning & alert engine (Phase 11).

Converts a zone's Phase 7 risk trajectory into an actionable early warning:
should authorities act, how urgently, and on what basis.

    Forecast (Phase 7)
        v
    Risk escalation detection
        v
    Alert severity + priority
        v
    Alert payload

REUSE, NOT REIMPLEMENTATION
This module forecasts nothing itself. It reads the trajectory already
produced by `forecast_service.get_trajectory` (Phase 7) and the
vulnerability level already produced by `vulnerability_service` /
`geospatial_service` (Phase 4/8), then applies a small set of deterministic
rules on top. No new hazard or vulnerability computation happens here.

RULES (thresholds live in app/core/config.py, not scattered in this file)
    1. Alert required once the forecast PEAK reaches ALERT_MIN_LEVEL or
       above.
    2. Escalation -- the peak strictly worse than today's observed level,
       e.g. MODERATE -> HIGH -- is always detected and reported
       (`escalation`, `escalation_label`), and is called out in `reason`
       whenever it is what pushed the plan across the alert threshold. An
       escalation that stays under the threshold (e.g. LOW -> MODERATE) is
       still surfaced, so a rising trend is visible before it becomes
       alert-worthy, but does not by itself force `alert_required`.
    3. Priority (separate from the alert level) is raised when the zone's
       vulnerability is high.
    4. Priority reaches CRITICAL only when high heat (an EXTREME peak) and
       high vulnerability combine.

DELIVERY
This module only builds a structured alert payload; it never sends
anything. `NotificationAdapter` is a placeholder seam for a future
SMS/WhatsApp/Email/FCM integration -- deliberately unimplemented here (see
the project brief's ALERT DELIVERY section). The default
`NoopNotificationAdapter` just logs. No adapter in this repository requires
an API key, and none is wired into the /alerts/evaluate endpoint.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

from app.core.config import settings
from app.core.exceptions import ValidationError

logger = logging.getLogger(__name__)

ALERT_DISCLAIMER = (
    "DECISION-SUPPORT ALERT. Derived from HeatSentinal's own forecast "
    "trajectory and vulnerability estimate. It does NOT predict deaths or "
    "medical outcomes. Recommended actions are decision-support text, not "
    "medical instructions, for a human to review -- this module does not "
    "send anything and does not execute any action automatically."
)


@runtime_checkable
class NotificationAdapter(Protocol):
    """Seam for a future SMS/WhatsApp/Email/FCM integration.

    Deliberately unimplemented in this phase. No implementation of this
    protocol is required (or present) for /alerts/evaluate to work, and none
    requires external API keys.
    """

    def send(self, alert: dict[str, Any]) -> None: ...


class NoopNotificationAdapter:
    """Default adapter: logs the alert and dispatches nothing."""

    def send(self, alert: dict[str, Any]) -> None:
        logger.info(
            "ALERT built (not dispatched -- no notification provider "
            "configured): zone=%s level=%s required=%s priority=%s",
            alert.get("zone_id"),
            alert.get("alert_level"),
            alert.get("alert_required"),
            alert.get("priority"),
        )


def _level_index(level: str) -> int:
    """Position of a category on the configured 5-band alert scale.

    Unknown labels default to index 0 (least severe) rather than raising,
    so a future relabelled category degrades safely instead of crashing an
    alert evaluation.
    """
    levels = settings.alert_levels_list
    try:
        return levels.index(level)
    except ValueError:
        return 0


def priority_for(
    alert_level: str, vulnerability_level: str, alert_required: bool
) -> str:
    """PROTOTYPE priority matrix. Not a published prioritisation standard.

    Kept as an explicit ladder (like geospatial_service's priority matrix)
    rather than a formula, so each rule from the project brief is visible
    as one line.
    """
    high_vulnerability = (
        vulnerability_level in settings.alert_high_vulnerability_levels_list
    )
    if alert_level == "EXTREME" and high_vulnerability:
        return "CRITICAL"
    if alert_level in ("VERY_HIGH", "EXTREME"):
        return "HIGH"
    if alert_level == "HIGH" and high_vulnerability:
        return "HIGH"
    if alert_required:
        return "MODERATE"
    return "LOW"


def evaluate_alert(
    *,
    zone_id: str,
    trajectory: dict[str, Any],
    vulnerability_level: str,
) -> dict[str, Any]:
    """Build an alert payload from an existing trajectory + vulnerability.

    Pure and deterministic: the same trajectory and vulnerability level
    always produce the same alert. Never mutates `trajectory`.
    """
    entries = trajectory.get("forecast") or []
    if not entries:
        raise ValidationError(
            "The trajectory carries no forecast days to evaluate.",
            details={"zone_id": zone_id},
        )

    current_risk = entries[0]["risk_level"]
    forecast_peak = trajectory["peak_risk"]
    peak_date = trajectory["peak_date"]
    trend = trajectory["trend"]

    current_idx = _level_index(current_risk)
    peak_idx = _level_index(forecast_peak)
    # peak is computed as the max category index over the whole trajectory
    # (including today) by forecast_service.build_trajectory, so peak_idx
    # >= current_idx always holds; escalation is never spuriously negative.
    escalation = peak_idx > current_idx

    min_idx = _level_index(settings.ALERT_MIN_LEVEL)
    alert_required = peak_idx >= min_idx
    alert_level = forecast_peak

    if not alert_required:
        if escalation:
            reason = (
                f"Forecast trends upward toward {alert_level} by "
                f"{peak_date}, but stays below the "
                f"{settings.ALERT_MIN_LEVEL} alert threshold."
            )
        else:
            reason = (
                f"Forecast risk stays below the {settings.ALERT_MIN_LEVEL} "
                f"alert threshold through {peak_date}."
            )
    elif escalation:
        reason = (
            f"Forecast risk is expected to escalate from {current_risk} to "
            f"{alert_level} by {peak_date}."
        )
    else:
        reason = f"Forecast risk remains at {alert_level} through {peak_date}."

    priority = priority_for(alert_level, vulnerability_level, alert_required)
    actions = list(settings.alert_recommended_actions.get(alert_level, []))

    return {
        "zone_id": zone_id,
        "alert_required": alert_required,
        "alert_level": alert_level,
        "priority": priority,
        "reason": reason,
        "current_risk": current_risk,
        "forecast_peak": forecast_peak,
        "peak_date": peak_date,
        "trend": trend,
        "escalation": escalation,
        "escalation_label": (
            f"{current_risk} -> {forecast_peak}" if escalation else None
        ),
        "vulnerability_level": vulnerability_level,
        "based_on": trajectory["based_on"],
        "recommended_actions": actions,
        "assumptions": [
            "Alert level is the worst forecast category within the "
            "evaluated window, taken from the existing Phase 7 trajectory "
            "-- no new hazard forecast is computed here.",
            f"Alert required once the forecast peak reaches "
            f"{settings.ALERT_MIN_LEVEL} or above. Escalation above "
            "today's observed level is always detected and reported "
            "separately, even when it does not itself cross the "
            "threshold.",
            "Priority reflects vulnerability as well as hazard: it is "
            "raised when a high-vulnerability zone faces elevated heat, "
            "and reaches CRITICAL only when an EXTREME peak and high "
            "vulnerability combine. Prototype matrix, not a published "
            "prioritisation standard.",
            "Recommended actions are decision-support text, not medical "
            "instructions, and are never dispatched automatically.",
        ],
        "disclaimer": ALERT_DISCLAIMER,
    }
