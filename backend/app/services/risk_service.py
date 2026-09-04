"""Prototype health risk engine.

Combines thermal stress with population vulnerability into a single 0-1
score:

    normalise each thermal index  ->  weighted mean  ->  thermal_stress
    risk = W_thermal * thermal_stress + W_vulnerability * vulnerability

PROTOTYPE DECISION-SUPPORT SCORE. Not a medically validated prediction
model. Nothing here has been fitted to outcome data.

SEPARATION OF CONCERNS
This module CONSUMES thermal indices; it never computes them. There is no
Heat Index, WBGT or UTCI formula anywhere in this file, and a test asserts
that thermal_service is not imported. Index calculation belongs to Phase 3;
this is scoring only.

FUTURE ML
`predict_risk` is the seam. When XGBoost arrives it replaces the body of
this function behind the same signature and response model, and
`confidence` starts returning a real value instead of null. Callers do not
change.
"""

from __future__ import annotations

import logging
import math

from app.core.config import settings
from app.core.exceptions import HeatSentinalError, ValidationError
from app.models.risk import (
    RiskComponents,
    RiskContributor,
    RiskPredictionResponse,
)

logger = logging.getLogger(__name__)

_WEIGHT_SUM_TOLERANCE = 1e-6

METHOD = (
    "Prototype weighted composite: thermal indices normalised linearly "
    "against documented anchors, combined by configurable weights, then "
    "blended with population vulnerability. No model has been fitted."
)

LIMITATIONS = [
    "Not a medically validated prediction model. No model has been fitted "
    "to heat-mortality outcomes.",
    "Weights (thermal 0.65 / vulnerability 0.35) are uncalibrated prototype "
    "values chosen for plausibility, not derived from data.",
    "WBGT normalisation anchors are placeholders. Phase 3 deliberately "
    "returns NOT_CLASSIFIED for WBGT because ISO 7243 and ACGIH limits "
    "apply to full outdoor WBGT, not the shade approximation used here, so "
    "those limits are not used as anchors.",
    "Heat Index and WBGT are strongly correlated with each other, so the "
    "weighted mean double-counts temperature and humidity to some degree.",
    "The model is linear and additive: it cannot represent interactions, "
    "such as extreme heat arriving in an already vulnerable district.",
    "`risk_probability` is the score echoed, NOT a calibrated probability.",
    "`confidence` is null and will stay null until a trained model exists.",
    "Contributors are arithmetic shares, NOT SHAP values.",
    "Describes a population, never an individual.",
]


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def normalise_index(value: float, minimum: float, maximum: float) -> float:
    """Linear scaling from `minimum` (0.0) to `maximum` (1.0), clamped."""
    if maximum <= minimum:
        raise HeatSentinalError(
            "Risk normalisation anchors are misconfigured: max <= min.",
            status_code=500,
            details={"min": minimum, "max": maximum},
        )
    return _clamp((value - minimum) / (maximum - minimum))


def normalisation_anchors() -> dict[str, str]:
    """What each index was scaled against, and where the range came from."""
    return {
        "heat_index": (
            f"{settings.RISK_HEAT_INDEX_MIN_C}-"
            f"{settings.RISK_HEAT_INDEX_MAX_C} C "
            "(Phase 3 Heat Index category edges; prototype bands)"
        ),
        "wbgt": (
            f"{settings.RISK_WBGT_MIN_C}-{settings.RISK_WBGT_MAX_C} C "
            "(PROTOTYPE ANCHORS, UNCALIBRATED: ISO 7243 / ACGIH limits are "
            "defined on outdoor WBGT and are deliberately not used here)"
        ),
        "utci": (
            f"{settings.RISK_UTCI_MIN_C}-{settings.RISK_UTCI_MAX_C} C "
            "(published UTCI thermal stress assessment scale, Brode et al. "
            "2012: moderate heat stress from +26 C, extreme from +46 C)"
        ),
    }


# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------


def validate_weights() -> tuple[float, float, dict[str, float]]:
    """Return (thermal weight, vulnerability weight, thermal sub-weights).

    Weight sets that do not sum to 1.0 silently rescale every score and
    destroy comparability between locations, so this fails loudly.
    """
    thermal = settings.RISK_WEIGHT_THERMAL
    vulnerability = settings.RISK_WEIGHT_VULNERABILITY
    total = thermal + vulnerability

    if abs(total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise HeatSentinalError(
            "Risk weights (thermal + vulnerability) must sum to 1.0 but sum "
            f"to {total:.6f}.",
            status_code=500,
            details={"thermal": thermal, "vulnerability": vulnerability},
        )

    sub_weights = settings.risk_thermal_weights
    sub_total = sum(sub_weights.values())
    if abs(sub_total - 1.0) > _WEIGHT_SUM_TOLERANCE:
        raise HeatSentinalError(
            f"Thermal sub-weights must sum to 1.0 but sum to {sub_total:.6f}.",
            status_code=500,
            details={"thermal_weights": sub_weights},
        )

    negative = {
        name: value
        for name, value in {
            "thermal": thermal,
            "vulnerability": vulnerability,
            **sub_weights,
        }.items()
        if value < 0
    }
    if negative:
        raise HeatSentinalError(
            "Risk weights must not be negative.",
            status_code=500,
            details={"negative_weights": negative},
        )

    return thermal, vulnerability, sub_weights


def _redistribute(
    sub_weights: dict[str, float], available: list[str]
) -> dict[str, float]:
    """Rescale sub-weights over the indices actually present.

    UTCI is absent whenever air temperature exceeds 50 C, which happens in
    India during exactly the events this system exists for. Dropping its
    weight without redistributing would shrink thermal_stress and understate
    risk at the worst possible moment.
    """
    subset = {name: sub_weights[name] for name in available}
    total = sum(subset.values())
    if total <= 0:
        raise HeatSentinalError(
            "No thermal index available to score.",
            status_code=422,
            details={"available": available},
        )
    return {name: weight / total for name, weight in subset.items()}


def risk_level(score: float) -> str:
    """Band a score using configurable PROTOTYPE thresholds.

    Defaults: <0.25 LOW, <0.50 MODERATE, <0.75 HIGH, else EXTREME.
    """
    edges = settings.risk_bounds_list
    labels = settings.risk_categories_list

    if len(labels) != len(edges) + 1:
        raise HeatSentinalError(
            "Risk categories must be exactly one more than bounds.",
            status_code=500,
            details={"bounds": edges, "categories": labels},
        )

    for index, edge in enumerate(edges):
        if score < edge:
            return labels[index]
    return labels[-1]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def predict_risk(
    temperature_c: float,
    relative_humidity: float,
    heat_index: float,
    wbgt: float,
    vulnerability_score: float,
    utci: float | None = None,
    wind_speed: float = 0.0,
    solar_radiation: float | None = None,
) -> RiskPredictionResponse:
    """Compute a prototype heat-health risk score.

    Deterministic and side-effect free. This is the seam a trained XGBoost
    model will later replace, keeping the same signature and response.
    """
    _validate(
        temperature_c,
        relative_humidity,
        heat_index,
        wbgt,
        vulnerability_score,
        utci,
        wind_speed,
        solar_radiation,
    )

    thermal_weight, vulnerability_weight, sub_weights = validate_weights()
    notes: list[str] = []

    normalised: dict[str, float | None] = {
        "heat_index": normalise_index(
            heat_index,
            settings.RISK_HEAT_INDEX_MIN_C,
            settings.RISK_HEAT_INDEX_MAX_C,
        ),
        "wbgt": normalise_index(
            wbgt, settings.RISK_WBGT_MIN_C, settings.RISK_WBGT_MAX_C
        ),
        "utci": None,
    }

    available = ["heat_index", "wbgt"]
    if utci is not None:
        normalised["utci"] = normalise_index(
            utci, settings.RISK_UTCI_MIN_C, settings.RISK_UTCI_MAX_C
        )
        available.append("utci")
    else:
        notes.append(
            "UTCI was not supplied, so its weight was redistributed "
            "proportionally across the Heat Index and WBGT. The thermal "
            "engine returns no UTCI above 50 C air temperature."
        )

    effective = _redistribute(sub_weights, available)

    thermal_stress = _clamp(
        sum(effective[name] * float(normalised[name]) for name in available)
    )
    vulnerability = _clamp(vulnerability_score)

    score = _clamp(
        thermal_weight * thermal_stress + vulnerability_weight * vulnerability
    )

    contributors = _build_contributors(
        normalised, effective, available, thermal_weight,
        vulnerability, vulnerability_weight,
    )

    applied_weights = {
        f"thermal.{name}": round(thermal_weight * weight, 6)
        for name, weight in effective.items()
    }
    applied_weights["vulnerability"] = vulnerability_weight

    return RiskPredictionResponse(
        risk_score=round(score, 4),
        # Echoed, not calibrated. See the field description and limitations.
        risk_probability=round(score, 4),
        risk_level=risk_level(score),
        confidence=None,
        components=RiskComponents(
            thermal_stress=round(thermal_stress, 4),
            vulnerability=round(vulnerability, 4),
        ),
        contributors=contributors,
        normalised_indices={
            name: (round(value, 4) if value is not None else None)
            for name, value in normalised.items()
        },
        weights=applied_weights,
        normalisation_anchors=normalisation_anchors(),
        thresholds=_threshold_map(),
        method=METHOD,
        limitations=LIMITATIONS,
        notes=notes,
    )


def _build_contributors(
    normalised: dict[str, float | None],
    effective: dict[str, float],
    available: list[str],
    thermal_weight: float,
    vulnerability: float,
    vulnerability_weight: float,
) -> list[RiskContributor]:
    """Per-factor shares that sum to the risk score.

    PROTOTYPE CONTRIBUTIONS, not SHAP values.
    """
    labels = {"heat_index": "Heat Index", "wbgt": "WBGT", "utci": "UTCI"}
    contributors: list[RiskContributor] = []

    for name in available:
        value = float(normalised[name])
        weight = thermal_weight * effective[name]
        impact = weight * value
        contributors.append(
            RiskContributor(
                factor=labels[name],
                impact=round(impact, 6),
                direction="increases" if impact > 0 else "neutral",
                normalised_value=round(value, 4),
                weight=round(weight, 6),
            )
        )

    vulnerability_impact = vulnerability_weight * vulnerability
    contributors.append(
        RiskContributor(
            factor="vulnerability",
            impact=round(vulnerability_impact, 6),
            direction="increases" if vulnerability_impact > 0 else "neutral",
            normalised_value=round(vulnerability, 4),
            weight=vulnerability_weight,
        )
    )

    return sorted(contributors, key=lambda item: item.impact, reverse=True)


def _threshold_map() -> dict[str, float]:
    edges = settings.risk_bounds_list
    labels = settings.risk_categories_list
    mapping = {label: edge for label, edge in zip(labels, edges)}
    mapping[labels[-1]] = 1.0
    return mapping


def _validate(
    temperature_c: float,
    relative_humidity: float,
    heat_index: float,
    wbgt: float,
    vulnerability_score: float,
    utci: float | None,
    wind_speed: float,
    solar_radiation: float | None,
) -> None:
    """Domain validation, independent of FastAPI.

    Later phases call this service directly with no HTTP layer to guard it,
    so non-finite values are rejected here too.
    """
    checks = [
        ("temperature_c", temperature_c, -90.0, 60.0),
        ("relative_humidity", relative_humidity, 0.0, 100.0),
        ("heat_index", heat_index, -100.0, 150.0),
        ("wbgt", wbgt, -50.0, 100.0),
        ("vulnerability_score", vulnerability_score, 0.0, 1.0),
        ("wind_speed", wind_speed, 0.0, 150.0),
    ]
    if utci is not None:
        checks.append(("utci", utci, -100.0, 100.0))
    if solar_radiation is not None:
        checks.append(("solar_radiation", solar_radiation, 0.0, 2000.0))

    for field, value, low, high in checks:
        if not math.isfinite(value):
            raise ValidationError(
                f"{field} must be a finite number.",
                details={"field": field, "received": str(value)},
            )
        if not low <= value <= high:
            raise ValidationError(
                f"{field} must be between {low} and {high}.",
                details={"field": field, "received": value},
            )
